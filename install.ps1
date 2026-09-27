#Requires -Version 5.1
<#
.SYNOPSIS
    Installs Atlas-HQ on Windows from a release bundle or a repository clone.

.DESCRIPTION
    Creates a local virtual environment, installs this project with its dev
    extras into it, and installs the web console's node modules from the
    lockfile.

    Before it does any of that, it verifies itself: this script hashes its own
    bytes with SHA-256 and compares them with the digest the SHA256SUMS.txt
    beside it records for install.ps1. A missing, unreadable or mismatched
    checksum stops the run. That check reads two local files and nothing else.

    The installer is deliberately unable to make a machine-wide change. It does
    not request Administrator elevation, it does not read or change the
    PowerShell execution policy, it does not download or execute a remote
    script, it does not create, alter or migrate a database schema, and it
    never handles a credential. It writes only inside its install directory
    plus the user-local npm cache that npm already owns. See contract.md
    section 40.

    The console is installed with every dependency's install scripts switched
    off (`npm ci --ignore-scripts`), and the two build binaries named in
    web/package.json#allowScripts are then rebuilt by name and run to prove they
    were built. Nothing else in the tree gets to run code during the install,
    and the same three commands mean the same thing under npm 10, 11 and 12.

.PARAMETER SourceRoot
    Directory holding pyproject.toml, src/ and web/. Defaults to the directory
    this script lives in.

.PARAMETER InstallRoot
    Directory that receives .venv, the install stamp and the console's
    node_modules. It must be the same directory as SourceRoot, which is also its
    default: a different one is refused, because contract section 40.2 only lets
    this installer write inside its own install directory, and the console's
    dependencies are installed into that directory's web\ by name.

.PARAMETER SkipWeb
    Skip the web console. Then Node.js, npm and web/ are not required.

.PARAMETER SkipChecksum
    Do not verify this script against SHA256SUMS.txt. This is for a
    repository clone, where there is no release asset and no checksum beside
    it. It is not a valid way to run a released installer: it is the switch
    that removes the proof, so nothing downloaded should ever be run with it.

.PARAMETER DryRun
    Print every command and every file this script would write, and change
    nothing at all.

.PARAMETER Force
    Reinstall even when the stamp says this bundle is already installed.

.EXAMPLE
    .\install.ps1 -DryRun
    Shows the whole plan, including on a machine that is missing a prerequisite.

.EXAMPLE
    .\install.ps1
    Installs into .venv next to this script, then prints the next command.

.NOTES
    Contract section 40.2. The installer never migrates a schema: a schema
    change is delivered by a versioned migration, not by an installer.
    Contract section 40.4. The installer verifies its own SHA-256 against the
    checksum file that ships beside it, before it installs anything, and it
    never updates itself.

    A dry run runs nothing, so it verifies nothing. Where a check would have
    run it prints the command it would run and says the check was not made in a
    dry run; it never prints a green result it did not earn.
#>
[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$InstallRoot,
    [switch]$SkipWeb,
    [switch]$SkipChecksum,
    [switch]$DryRun,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- output ------------------------------------------------------------------

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Detail {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Write-Ok {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "    [ok] $Message" -ForegroundColor Green
}

function Write-Note {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "    [note] $Message" -ForegroundColor Yellow
}

function Stop-Install {
    param(
        [Parameter(Mandatory)][string]$Message,
        [string[]]$Details = @()
    )
    Write-Host ""
    Write-Host "install.ps1 cannot continue: $Message" -ForegroundColor Red
    foreach ($detail in $Details) { Write-Host "    $detail" -ForegroundColor Red }
    Write-Host "" -ForegroundColor Red
    throw $Message
}

# --- process plumbing --------------------------------------------------------

function Format-NativeCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $parts = @("'$FilePath'")
    foreach ($argument in $Arguments) {
        if ($argument -match '[\s\[]') { $parts += "'$argument'" } else { $parts += $argument }
    }
    return ($parts -join ' ')
}

function Resolve-Tool {
    <#
        Resolve an executable, preferring a real binary over a same-named
        .ps1 shim. Returns $null rather than throwing so a DryRun can still
        print the plan on a machine that does not have the tool.
    #>
    param(
        [Parameter(Mandatory)][string[]]$Names,
        [switch]$Required
    )
    foreach ($name in $Names) {
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command) { return $command.Source }
    }
    if ($Required) {
        Stop-Install "a required tool is missing: $($Names -join ' or ')"
    }
    return $null
}

function Invoke-Native {
    <#
        Run one external command. DryRun prints the exact command line and
        returns success without running anything, so the printed plan is the
        real plan.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory)][string]$Description,
        [string]$WorkingDirectory
    )
    Write-Detail (Format-NativeCommand $FilePath $Arguments)
    if ($DryRun) { return }
    $exitCode = 1
    $pushed = $false
    if ($WorkingDirectory) { Push-Location -LiteralPath $WorkingDirectory; $pushed = $true }
    try {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        if ($pushed) { Pop-Location }
    }
    if ($exitCode -ne 0) {
        Stop-Install "'$Description' failed with exit code $exitCode." @(
            (Format-NativeCommand $FilePath $Arguments),
            'Re-run with -DryRun to see the plan, and see docs/INSTALL.md for the matching fix.'
        )
    }
}

function Test-LoopbackPortListening {
    param([Parameter(Mandatory)][int]$Port)
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) { return $null }
    return ($listeners | Select-Object -First 1).LocalAddress
}

function Get-ExpectedDigest {
    <#
        The SHA-256 that a `sha256sum -c` checksum file records for one file
        name, or $null when that file has no readable line for it. The line is
        "<64 hex>  <name>", and a binary-mode line puts a * where the second
        space is, so both are read. A line in any other shape proves nothing
        and is skipped rather than guessed at: a checksum that cannot be read
        is a checksum that cannot be checked.
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$FileName
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in @(Get-Content -LiteralPath $Path)) {
        if ($line -notmatch '^[ \t]*(?<digest>[0-9A-Fa-f]{64})[ \t]+[*]?[ \t]*(?<name>\S+)') { continue }
        if ($Matches['name'] -ieq $FileName) { return $Matches['digest'] }
    }
    return $null
}

# --- identity ----------------------------------------------------------------

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($DryRun) { Write-Step "dry run: nothing below this line changes anything" }

# --- supply chain ------------------------------------------------------------

# contract.md 40.4: the installer proves its own bytes against the checksum
# file that ships beside it, before it installs anything. Two local files are
# read here and nothing is fetched, executed or updated.
Write-Step 'verifying this installer against its checksum'

$installerPath = Join-Path $scriptDirectory 'install.ps1'
$checksumPath = Join-Path $scriptDirectory 'SHA256SUMS.txt'
Write-Detail "Get-FileHash -Algorithm SHA256 '$installerPath'"
Write-Detail "compared case-insensitively with the 'install.ps1' line in '$checksumPath'"

if ($SkipChecksum) {
    Write-Note 'skipped (-SkipChecksum): valid from a source checkout only, never for a released asset'
} else {
    $expectedDigest = Get-ExpectedDigest -Path $checksumPath -FileName 'install.ps1'
    if ($null -eq $expectedDigest) {
        if ($DryRun) {
            Write-Note 'a dry run does not require the checksum file, so nothing was compared'
        } elseif (-not (Test-Path -LiteralPath $checksumPath)) {
            Stop-Install 'there is no SHA256SUMS.txt beside this installer.' @(
                "'$checksumPath' was not found next to install.ps1.",
                'Download install.ps1 and SHA256SUMS.txt from the same release, and keep them in the same directory.',
                'From a repository clone, run .\install.ps1 -SkipChecksum.'
            )
        } else {
            Stop-Install "SHA256SUMS.txt has no readable 'install.ps1' line." @(
                "'$checksumPath' is not in sha256sum format: 64 hex characters, a space, then the file name.",
                'Download SHA256SUMS.txt from the same release again. If it still fails, this asset is not the one the release was tested against.'
            )
        }
    } else {
        $actualDigest = $null
        try {
            $actualDigest = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
        } catch {
            Stop-Install 'this installer could not be read, so it cannot be verified.' @(
                $_.Exception.Message,
                'This is a file permission problem, not a bad checksum. Fix the file, then re-run.'
            )
        }
        if ($actualDigest -ine $expectedDigest) {
            Stop-Install 'install.ps1 does not match the SHA256SUMS.txt beside it.' @(
                "expected  $expectedDigest",
                "actual    $actualDigest",
                'This file is not the one the release was tested against. Do not run it.',
                'Re-download install.ps1 and SHA256SUMS.txt from the same release into the same directory, and check them again.'
            )
        }
        Write-Ok 'SHA-256 verified against SHA256SUMS.txt'
    }
}

# --- layout ------------------------------------------------------------------

if ([string]::IsNullOrWhiteSpace($SourceRoot)) { $SourceRoot = $scriptDirectory }
if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $InstallRoot = $SourceRoot }
$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).ProviderPath
if (Test-Path -LiteralPath $InstallRoot) {
    $InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).ProviderPath
} elseif ($DryRun) {
    Write-Step "create the install directory"
    Write-Detail "'$InstallRoot'"
    $InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
} else {
    Stop-Install "the install directory does not exist: $InstallRoot" @(
        'Pass -InstallRoot <path> to a directory you already own.'
    )
}

# contract.md 40.2: this installer writes only inside its own install directory.
# Three things go there: .venv, the install stamp and the console's
# node_modules. A source bundle in one directory and an install in another would
# put the virtual environment and the stamp in the install directory and the
# console's dependencies beside the bundle - a write outside the directory the
# operator named, and not where start-demo.ps1 looks for them, so the demo would
# come up without a console. There is nothing to reconcile, so a split pair is
# refused rather than half-honoured. Both parameters default to this script's
# own directory, which is the only relationship the happy path has.
if ($InstallRoot -ne $SourceRoot) {
    Stop-Install 'the install directory and the source directory are different directories.' @(
        "source   $SourceRoot",
        "install  $InstallRoot",
        'Everything this installer writes - .venv, the install stamp and the console''s',
        'node_modules - goes into the install directory, and it is not the one you named.',
        'Drop -InstallRoot, or point -SourceRoot at the directory you want installed into.'
    )
}
$venvPath = Join-Path $InstallRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$stampPath = Join-Path $InstallRoot '.atlas-install-stamp.json'
$webPath = Join-Path $InstallRoot 'web'

# --- preflight ---------------------------------------------------------------

Write-Step 'checking prerequisites'

$problems = @()

# Windows PowerShell 5.1 is the supported host. $IsWindows only exists on
# PowerShell 6+, and under Set-StrictMode reading it on 5.1 would be an error,
# so the edition decides how the question is asked.
$isWindowsCore = $PSVersionTable.PSEdition -eq 'Core'
if ($isWindowsCore -and -not $IsWindows) { $problems += 'this script runs on Windows only.' }
Write-Ok "Windows PowerShell $($PSVersionTable.PSVersion)"

$gitPath = Resolve-Tool -Names @('git') -Required:(-not $DryRun)
if ($null -eq $gitPath) {
    Write-Note 'git not found on PATH (needed to build a bundle from a clone)'
} else {
    Write-Ok 'git'
}

$dockerPath = Resolve-Tool -Names @('docker')
$composeAvailable = $false
    if ($null -eq $dockerPath) {
        if ($DryRun) {
            Write-Note 'docker not found on PATH (Docker Desktop with Compose v2 is required)'
        } else {
            $problems += 'Docker Desktop is not on PATH. Install Docker Desktop (Compose v2 ships with it).'
        }
    } else {
        if ($DryRun) {
            # A dry run runs nothing, so it checks nothing. It prints the two
            # commands it would run and says so; it never prints a green check
            # it did not earn, because the one thing a plan is for is being
            # accurate about what has been verified.
            Write-Detail (Format-NativeCommand $dockerPath @('version', '--format', '{{.Server.Version}}'))
            Write-Detail (Format-NativeCommand $dockerPath @('compose', 'version', '--short'))
            Write-Note 'docker engine and Compose v2 not checked in dry run'
        } else {
            & $dockerPath version --format '{{.Server.Version}}' 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $problems += 'Docker Desktop is not running. Start it, wait for the whale to settle, then re-run.'
            } else {
                Write-Ok 'docker engine'
            }
            & $dockerPath compose version --short 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $problems += '`docker compose` (Compose v2) is not available. Update Docker Desktop; the v1 `docker-compose` shim is not supported.'
            } else {
                $composeAvailable = $true
                Write-Ok 'docker compose v2'
            }
        }
    }


# Python 3.12: uv provisions it, otherwise the py launcher must already have it.
$uvPath = Resolve-Tool -Names @('uv')
$pyPath = Resolve-Tool -Names @('py')
$pythonProvisioner = ''
if ($null -ne $uvPath) {
    $pythonProvisioner = 'uv'
    Write-Ok 'uv (will provision Python 3.12 into the virtual environment)'
} elseif ($null -ne $pyPath) {
    $pyExit = 0
    if ($DryRun) {
        Write-Detail (Format-NativeCommand $pyPath @('-3.12', '--version'))
    } else {
        & $pyPath -3.12 --version 2>$null | Out-Null
        $pyExit = $LASTEXITCODE
    }
    if ($pyExit -ne 0) {
        if ($DryRun) {
            Write-Note 'py launcher found; `py -3.12` is not installed'
        } else {
            $problems += 'Python 3.12 is not installed. Install it from python.org, or install uv and re-run.'
        }
    } else {
        $pythonProvisioner = 'py'
        Write-Ok 'py -3.12'
    }
} else {
    if ($DryRun) {
        Write-Note 'neither uv nor the py launcher was found'
    } else {
        $problems += 'Neither uv nor the py launcher was found. Install uv (https://docs.astral.sh/uv/) or Python 3.12 from python.org.'
    }
}

$npmPath = $null
$nodePath = $null
if ($SkipWeb) {
    Write-Note 'web console skipped (-SkipWeb): Node.js and npm are not needed'
} else {
    $nodePath = Resolve-Tool -Names @('node')
    if ($null -eq $nodePath) {
        if ($DryRun) {
            Write-Note 'node not found on PATH'
        } else {
            $problems += 'Node.js was not found. Install Node.js 20.19 or newer, or re-run with -SkipWeb.'
        }
    } else {
        $nodeVersionText = ''
        if ($DryRun) {
            Write-Detail (Format-NativeCommand $nodePath @('--version'))
        } else {
            $nodeVersionText = (& $nodePath --version 2>$null | Select-Object -First 1)
        }
        $nodeVersion = $null
        if ($nodeVersionText) {
            $bare = ($nodeVersionText.Trim() -replace '^v', '') -replace '[^0-9.].*$', ''
            if ($bare) { $nodeVersion = [version]$bare }
        }
        if ($DryRun) {
            Write-Note 'node version not checked in a dry run'
        } elseif ($null -eq $nodeVersion) {
            $problems += "Could not read a version from `node --version` ($nodeVersionText)."
        } elseif ($nodeVersion -lt [version]'20.19.0') {
            $problems += "Node.js $nodeVersionText is too old. The console needs 20.19 or newer (web/package.json#engines)."
        } else {
            Write-Ok "node $nodeVersionText"
        }
    }
    $npmPath = Resolve-Tool -Names @('npm.cmd', 'npm.exe', 'npm')
    if ($null -eq $npmPath) {
        if ($DryRun) {
            Write-Note 'npm not found on PATH'
        } else {
            $problems += 'npm was not found. It ships with Node.js; re-run with -SkipWeb to skip the console.'
        }
    } else {
        Write-Ok 'npm'
    }
}

if ($problems.Count -gt 0) {
    Stop-Install 'one or more prerequisites are not met.' $problems
}

# Informational only. The installer never starts Docker and never opens a
# database connection, so an answer here changes nothing.
$postgresListener = Test-LoopbackPortListening -Port 5433
if ($null -eq $postgresListener) {
    Write-Note 'port 5433 is free. start-demo.ps1 starts PostgreSQL for you.'
} else {
    Write-Note "port 5433 is already listening on $postgresListener. start-demo.ps1 will reuse it."
}

# --- bundle layout -----------------------------------------------------------

Write-Step 'checking the source bundle'

$requiredFiles = @('pyproject.toml', (Join-Path 'src' 'atlas_hq'), (Join-Path 'src' 'atlas_core'))
if (-not $SkipWeb) { $requiredFiles += (Join-Path 'web' 'package.json') }
$missing = @()
foreach ($relative in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot $relative))) { $missing += $relative }
}
if ($missing.Count -gt 0) {
    Stop-Install "this does not look like an Atlas-HQ source bundle." @(
        ("missing under '$SourceRoot': " + ($missing -join ', ')),
        'Run install.ps1 from the bundle root, or pass -SourceRoot <path>.'
    )
}
Write-Ok "source bundle at '$SourceRoot'"

# --- already installed? ------------------------------------------------------

$stampExists = Test-Path -LiteralPath $stampPath
$installStale = $Force -or -not (Test-Path -LiteralPath $venvPython)
if ($stampExists -and -not $installStale) {
    Write-Step 'already installed'
    if ($DryRun) {
        Write-Note "an install stamp exists; -Force would reinstall over it"
    } else {
        Write-Note "install stamp found at '$stampPath'."
        Write-Note 'Nothing to do. Pass -Force to reinstall over the existing .venv.'
    }
} else {
    # --- virtual environment -------------------------------------------------

    Write-Step 'preparing the virtual environment'

    if (Test-Path -LiteralPath $venvPath) {
        if ($DryRun) { Write-Note "'.venv' exists; it is left alone" }
        else { Write-Note "reusing the existing '.venv' (an installer never deletes a directory)" }
    } elseif ($DryRun) {
        if ($pythonProvisioner -eq 'uv') {
            Write-Detail (Format-NativeCommand $uvPath @('venv', '--python', '3.12', $venvPath))
        } elseif ($pythonProvisioner -eq 'py') {
            Write-Detail (Format-NativeCommand $pyPath @('-3.12', '-m', 'venv', $venvPath))
        } else {
            Write-Note 'no Python provisioner available, so .venv cannot be created'
        }
    } elseif ($pythonProvisioner -eq 'uv') {
        Invoke-Native -FilePath $uvPath -Arguments @('venv', '--python', '3.12', $venvPath) `
            -Description 'creating the virtual environment'
        Write-Ok "'.venv' created"
    } else {
        Invoke-Native -FilePath $pyPath -Arguments @('-3.12', '-m', 'venv', $venvPath) `
            -Description 'creating the virtual environment'
        Write-Ok "'.venv' created"
    }

    # --- the project itself --------------------------------------------------

    Write-Step 'installing Atlas-HQ'

    $editableTarget = "$SourceRoot[dev]"
    if ($null -ne $uvPath) {
        Invoke-Native -FilePath $uvPath `
            -Arguments @('pip', 'install', '--python', $venvPython, '-e', $editableTarget) `
            -Description 'installing the project with its dev extras'
    } elseif ($DryRun) {
        Write-Detail (Format-NativeCommand $venvPython @('-m', 'pip', 'install', '-e', $editableTarget))
    } else {
        Invoke-Native -FilePath $venvPython -Arguments @('-m', 'pip', 'install', '-e', $editableTarget) `
            -Description 'installing the project with its dev extras'
    }
    if ($DryRun) {
        Write-Note 'dry run: nothing was installed into the virtual environment'
    } else {
        Write-Ok 'project installed (editable, with the dev extras: pytest, ruff, pyright)'
    }

    # --- web console ---------------------------------------------------------

    if (-not $SkipWeb) {
        Write-Step 'installing the web console'

        # Exactly the two packages web/package.json#allowScripts names, and the
        # only two non-optional packages in web/package-lock.json that carry an
        # install script at all. Every other dependency is installed with its
        # scripts switched off, so no third-party code runs during an install.
        # tests/windows/verify_scripts.ps1 fails if this list and that
        # allowScripts block ever disagree, so the list cannot drift away from
        # the approval.
        $approvedBuildPackages = @('esbuild', '@tailwindcss/oxide')

        if ($null -eq $npmPath) {
            Write-Note 'npm is unavailable, so the console cannot be installed'
        } elseif ($DryRun) {
            Write-Detail ((Format-NativeCommand $npmPath (@('ci', '--ignore-scripts'))) + "   # working directory: $webPath")
            Write-Detail ((Format-NativeCommand $npmPath (@('rebuild') + $approvedBuildPackages)) + "   # working directory: $webPath")
            Write-Detail 'then run the two approved products to prove they were built'
            Write-Detail ((Format-NativeCommand $nodePath @('-e', "require('@tailwindcss/oxide')")) + "   # working directory: $webPath")
            Write-Detail 'dry run: no package was installed and no build was run'
        } else {
            # `--ignore-scripts` is the whole safety property, and it is the one
            # flag whose meaning has not moved: npm 10, 11 and 12 all install
            # the tree from the lockfile and run nothing. Nothing here answers a
            # prompt, and NPM_CONFIG_YES is deliberately not set - a yes-answer
            # to a prompt that only some versions ask for is a behaviour to
            # depend on nowhere.
            Invoke-Native -FilePath $npmPath -Arguments @('ci', '--ignore-scripts') `
                -Description 'installing the console dependencies from the lockfile' `
                -WorkingDirectory $webPath
            # Then, and only then, the approved install scripts, by name.
            Invoke-Native -FilePath $npmPath -Arguments (@('rebuild') + $approvedBuildPackages) `
                -Description 'building the approved console build binaries' `
                -WorkingDirectory $webPath
            # A rebuild that quietly built nothing leaves esbuild without its
            # binary and Tailwind without its native binding, and the console
            # then fails on the operator's first `npm run dev` instead of here.
            # So both products are run: esbuild reports its version, and the
            # oxide addon throws "Cannot find native binding" if it is absent.
            # Invoke-Native stops the install with the failing command if either
            # one is not what it must be.
            $esbuildPath = Join-Path $webPath 'node_modules\.bin\esbuild.cmd'
            if (-not (Test-Path -LiteralPath $esbuildPath)) {
                Stop-Install "the approved console build did not produce '$esbuildPath'." @(
                    'npm ci --ignore-scripts ran, and the rebuild of esbuild and @tailwindcss/oxide did not.',
                    "Delete '$webPath\node_modules' and run this again: a partial node_modules is not repairable in place.",
                    'Re-run with -SkipWeb to install the backend only, and see docs/INSTALL.md for the console.'
                )
            }
            Invoke-Native -FilePath $esbuildPath -Arguments @('--version') `
                -Description 'proving the esbuild build' -WorkingDirectory $webPath
            Invoke-Native -FilePath $nodePath -Arguments @('-e', "require('@tailwindcss/oxide')") `
                -Description 'proving the Tailwind oxide build' -WorkingDirectory $webPath
            Write-Ok 'console dependencies installed from web/package-lock.json (scripts off)'
            Write-Ok "the approved build binaries were rebuilt and run: $($approvedBuildPackages -join ', ')"
        }
    }

    # --- stamp ---------------------------------------------------------------

    if ($DryRun) {
        Write-Step 'recording the install'
        Write-Detail "'$stampPath'"
    } else {
        Write-Step 'recording the install'
        $stamp = [ordered]@{
            schemaVersion  = 1
            installedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
            sourceRoot     = $SourceRoot
            installRoot    = $InstallRoot
            pythonVersion  = $pythonProvisioner
            web            = (-not $SkipWeb)
        }
        Set-Content -LiteralPath $stampPath -Value ($stamp | ConvertTo-Json) -Encoding UTF8
        Write-Ok "install stamp written to '$stampPath'"
    }
}

# --- next --------------------------------------------------------------------

Write-Host ""
if ($DryRun) {
    # The plan ends where a real run would end, and says plainly that it is a
    # plan. A dry run that printed "installed" would be claiming a result it
    # did not produce, which is the one thing a plan must never do.
    Write-Step 'dry run complete: the plan above is what a real run does'
    Write-Note 'nothing was created: no virtual environment, no install, no node_modules, no stamp'
    if (-not $SkipWeb) { Write-Detail "a real run would install the console into $webPath\node_modules" }
} else {
    Write-Step 'installed'
    Write-Ok "virtual environment: $venvPath"
    if (-not $SkipWeb) { Write-Ok "console dependencies: $webPath\node_modules" }
}
Write-Host ""
Write-Host 'Start the local demo with exactly this command:' -ForegroundColor Cyan
Write-Host ''
Write-Host '    .\start-demo.ps1 -InitializeOperator -OpenBrowser' -ForegroundColor White
Write-Host ''
Write-Detail 'That starts PostgreSQL on 5433, the API on 127.0.0.1:8000 and the console on 127.0.0.1:5175.'
Write-Detail 'Ctrl-C stops the processes it started and nothing else.'
Write-Host ''
