#Requires -Version 5.1
<#
.SYNOPSIS
    Windows acceptance checks for install.ps1 and start-demo.ps1.

.DESCRIPTION
    The packaging gate from contract section 40.5, minus the parts that need a
    real release: this checks the two scripts as source, which is what a
    Windows runner can check on every push.

    It asserts, for each script:

    - it parses under the Windows PowerShell 5.1 parser with no errors
    - it declares the parameters contract section 40 needs
    - it carries the required markers (loopback addresses, the pinned ports,
      the tracked-child cleanup, the exact next command)
    - it does not carry the prohibited ones (execution policy changes, admin
      elevation, `compose down`, remote fetch or execute, a URL with inline
      credentials, a hard-coded secret)

    Then it runs both scripts with -DryRun and asserts the plan they print. The
    prohibited-pattern scan reads the code with comments stripped, so a doc
    comment that has to mention `docker compose down` to say it never runs it
    does not read as running it.

    Section 6 is the contract 40.4 supply-chain check: it copies the installer
    into a throwaway stub bundle, writes a SHA256SUMS.txt next to it, and
    proves the installer refuses a wrong, unreadable and absent checksum, and
    that it verifies a right one. The stub bundle is deleted afterwards.

    Section 8 calls start-demo.ps1's own Test-LoopbackHost - lifted out of the
    file as written - on a table of hosts, so the loopback rule is proved by what
    it does and not by what its text looks like. Section 9 runs the launcher
    against a table of database URLs, so the DSN guard is proved end to end: a
    URL whose query string or fragment redirects the connection is refused, and
    the three loopback forms are not. Section 10 proves the installer refuses a
    source root and an install root that differ, before any install work, and
    accepts one directory named twice.

    Section 11 runs start-demo.ps1 against a stub bundle three times: as a
    source checkout it passes -SkipChecksum and says so, as a release bundle it
    passes nothing at all, and as a directory that is neither it fails closed
    before the plan.

    Nothing here starts a server, a container, or a database: every check is a
    parse, a text scan, a dry run, or a run that is expected to fail closed
    before it can install anything.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tests\windows\verify_scripts.ps1

.NOTES
    Exits 0 when every check passes, 1 otherwise. The message says which.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Passed = 0
$script:Failed = 0
$script:Failures = New-Object System.Collections.ArrayList

function Assert-True {
    param(
        [Parameter(Mandatory)][bool]$Condition,
        [Parameter(Mandatory)][string]$Message
    )
    if ($Condition) {
        $script:Passed++
        Write-Host "  [pass] $Message" -ForegroundColor DarkGray
    } else {
        $script:Failed++
        $null = $script:Failures.Add($Message)
        Write-Host "  [FAIL] $Message" -ForegroundColor Red
    }
}

function Assert-Contains {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory)][string]$Needle,
        [Parameter(Mandatory)][string]$Message
    )
    Assert-True -Condition $Text.Contains($Needle) -Message $Message
}

function Assert-Matches {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory)][string]$Pattern,
        [Parameter(Mandatory)][string]$Message
    )
    Assert-True -Condition ([regex]::IsMatch($Text, $Pattern)) -Message $Message
}

function Assert-NotMatches {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory)][string]$Pattern,
        [Parameter(Mandatory)][string]$Message
    )
    Assert-True -Condition (-not [regex]::IsMatch($Text, $Pattern)) -Message $Message
}

function Get-ScriptCode {
    <# The executable source: comment-based help and `#` comments removed. A
       sentence that explains why a forbidden thing is forbidden is not the
       forbidden thing. #>
    param([Parameter(Mandatory)][string]$Path)
    $raw = Get-Content -LiteralPath $Path -Raw
    $withoutHelp = [regex]::Replace($raw, '(?s)<#.*?#>', '')
    # `#Requires` is a directive, not a comment, and it is exactly what the
    # PowerShell floor check reads.
    return (($withoutHelp -split "`r?`n") |
        Where-Object { $_ -notmatch '^\s*#(?!Requires)' }) -join "`n"
}

function Get-ScriptParameterNames {
    param([Parameter(Mandatory)][string]$Path)
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($null -eq $ast.ParamBlock) { return @() }
    return @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
}

function Get-ListeningPorts {
    <# Which of the demo's ports have a listener, as "port" strings. Proves
       the dry runs left nothing behind. #>
    param([Parameter(Mandatory)][int[]]$Ports)
    $listening = @()
    foreach ($port in $Ports) {
        try {
            if (@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
                $listening += $port
            }
        } catch {
            continue
        }
    }
    return $listening
}

# --- locate the scripts ------------------------------------------------------

$repositoryRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$installPath = Join-Path $repositoryRoot 'install.ps1'
$demoPath = Join-Path $repositoryRoot 'start-demo.ps1'

Write-Host "verifying the Windows scripts in '$repositoryRoot'" -ForegroundColor Cyan

foreach ($path in @($installPath, $demoPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "  [FAIL] missing script: $path" -ForegroundColor Red
        exit 1
    }
}

$installCode = Get-ScriptCode -Path $installPath
$demoCode = Get-ScriptCode -Path $demoPath
$installRaw = Get-Content -LiteralPath $installPath -Raw

# --- 1. the parser -----------------------------------------------------------

Write-Host '==> 1. both scripts parse under Windows PowerShell 5.1' -ForegroundColor Cyan
foreach ($pair in @(
        @{ Label = 'install.ps1'; Path = $installPath },
        @{ Label = 'start-demo.ps1'; Path = $demoPath })) {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($pair.Path, [ref]$tokens, [ref]$errors)
    $message = ($errors | ForEach-Object { "line $($_.Extent.StartLineNumber): $($_.Message)" }) -join '; '
    Assert-True -Condition ($errors.Count -eq 0) -Message "$($pair.Label) parses with no errors$message"
}

# --- 2. required parameters --------------------------------------------------

Write-Host '==> 2. required parameters' -ForegroundColor Cyan
$installParameters = Get-ScriptParameterNames -Path $installPath
$demoParameters = Get-ScriptParameterNames -Path $demoPath
foreach ($name in @('SourceRoot', 'InstallRoot', 'SkipWeb', 'SkipChecksum', 'DryRun', 'Force')) {
    Assert-True -Condition ($installParameters -contains $name) -Message "install.ps1 declares -$name"
}
foreach ($name in @('InitializeOperator', 'OpenBrowser', 'DryRun', 'SkipInstall', 'LogRoot', 'DatabaseUrl')) {
    Assert-True -Condition ($demoParameters -contains $name) -Message "start-demo.ps1 declares -$name"
}

# --- 3. prohibited patterns --------------------------------------------------

Write-Host '==> 3. prohibited patterns are absent' -ForegroundColor Cyan
$prohibited = @(
    @{ Pattern = '(?i)set-executionpolicy'; Why = 'changes the execution policy' },
    @{ Pattern = '(?i)executionpolicy\s*='; Why = 'sets the execution policy' },
    @{ Pattern = '(?i)-verb\s+runas'; Why = 'elevates to Administrator' },
    @{ Pattern = '(?i)requires\s+-runasadministrator'; Why = 'requires Administrator' },
    @{ Pattern = '(?i)net\s+user|start-process\s+-credential'; Why = 'changes machine or user accounts' },
    @{ Pattern = '(?i)invoke-webrequest|invoke-restmethod|start-bitstransfer|net\.webclient|downloadstring|downloadfile|downloadtofile'; Why = 'fetches something remote' },
    @{ Pattern = '(?i)\biex\b|invoke-expression'; Why = 'evaluates code as text' },
    @{ Pattern = '(?i)\bcurl(\.exe)?\b|\bwget(\.exe)?\b'; Why = 'downloads over the network' },
    @{ Pattern = '(?i)down\s+(-v|--volumes)'; Why = 'removes volumes' },
    @{ Pattern = "(?i)'\s*,\s*'-v'"; Why = 'removes volumes' },
    @{ Pattern = '(?i)\s--rm\b'; Why = 'removes a container and its anonymous volumes' },
    @{ Pattern = '(?i)create_all|alembic\s+upgrade|apply_migrations'; Why = 'migrates or creates a schema' },
    @{ Pattern = "(?i)(password|secret|token|api[_-]?key)\s*=\s*'[^']{2,}'"; Why = 'hard-codes a secret literal' },
    @{ Pattern = '(?i)npm_config_yes|npm_config_ignore_scripts\s*='; Why = 'sets an npm config for a prompt or for script suppression' }

)
foreach ($rule in $prohibited) {
    foreach ($pair in @(
            @{ Label = 'install.ps1'; Code = $installCode },
            @{ Label = 'start-demo.ps1'; Code = $demoCode })) {
        Assert-NotMatches -Text $pair.Code -Pattern $rule.Pattern `
            -Message "$($pair.Label) does not $($rule.Why)"
    }
}

# A URL is only a problem where something would fetch it. A URL inside a
# sentence that tells the operator where to go get a tool is documentation.
foreach ($pair in @(
        @{ Label = 'install.ps1'; Code = $installCode },
        @{ Label = 'start-demo.ps1'; Code = $demoCode })) {
    foreach ($line in ($pair.Code -split "`n")) {
        if ($line -notmatch 'https?://') { continue }
        $invoking = $line -match '(?i)(&\s*\$|start-process|-argument|invoke-|\biex\b|download|fetch|curl|wget)'
        Assert-True -Condition (-not $invoking) `
            -Message "$($pair.Label) has no URL on an executing line: $($line.Trim())"
    }
}

# --- 4. required markers -----------------------------------------------------

Write-Host '==> 4. required markers' -ForegroundColor Cyan
$installMarkers = @(
    @{ Needle = '#Requires -Version 5.1'; Why = 'declares its PowerShell floor' },
    @{ Needle = 'Set-StrictMode'; Why = 'runs under strict mode' },
    @{ Needle = "ErrorActionPreference = 'Stop'"; Why = 'stops on the first error' },
    @{ Needle = "'uv'"; Why = 'prefers uv' },
    @{ Needle = "'py'"; Why = 'falls back to the py launcher' },
    @{ Needle = "'3.12'"; Why = 'pins Python 3.12' },
    @{ Needle = "'20.19.0'"; Why = 'pins the Node floor' },
    @{ Needle = "@('ci', '--ignore-scripts')"; Why = 'installs the console from the lockfile with every install script off' },
    @{ Needle = '$approvedBuildPackages = @(''esbuild'', ''@tailwindcss/oxide'')'; Why = 'names the only two packages allowed to build' },
    @{ Needle = "@('rebuild') + `$approvedBuildPackages"; Why = 'rebuilds those two by name and nothing else' },
    @{ Needle = 'proving the esbuild build'; Why = 'runs esbuild instead of assuming the build worked' },
    @{ Needle = "require('@tailwindcss/oxide')"; Why = 'loads the Tailwind native binding to prove it was built' },
    @{ Needle = '5433'; Why = 'reports the PostgreSQL port' },
    @{ Needle = 'SHA256SUMS.txt'; Why = 'looks for the checksum file beside itself' },
    @{ Needle = 'Get-FileHash -LiteralPath $installerPath -Algorithm SHA256'; Why = 'hashes its own bytes with SHA-256' },
    @{ Needle = '-ine $expectedDigest'; Why = 'compares the digests case-insensitively' },
    @{ Needle = 'SkipChecksum'; Why = 'offers a way out of the check for a source checkout' },
    @{ Needle = '.\start-demo.ps1 -InitializeOperator -OpenBrowser'; Why = 'prints the exact next command' }
)
foreach ($marker in $installMarkers) {
    Assert-True -Condition $installCode.Contains($marker.Needle) `
        -Message "install.ps1 $($marker.Why) ($($marker.Needle))"
}

$demoMarkers = @(
    @{ Needle = '#Requires -Version 5.1'; Why = 'declares its PowerShell floor' },
    @{ Needle = 'Set-StrictMode'; Why = 'runs under strict mode' },
    @{ Needle = "ErrorActionPreference = 'Stop'"; Why = 'stops on the first error' },
    @{ Needle = "ApiHost = '127.0.0.1'"; Why = 'binds the API to loopback' },
    @{ Needle = "WebHost = '127.0.0.1'"; Why = 'binds the console to loopback' },
    @{ Needle = 'DatabasePort = 5433'; Why = 'pins the PostgreSQL port' },
    @{ Needle = 'ApiPort = 8000'; Why = 'pins the API port' },
    @{ Needle = 'WebPort = 5175'; Why = 'pins the console port' },
    @{ Needle = "'up', '--detach', 'postgres'"; Why = 'starts only the postgres service' },
    @{ Needle = "'-m', 'atlas_web', '--host', `$script:ApiHost, '--port'"; Why = 'starts the API on loopback' },
    @{ Needle = "'run', 'dev', '--', '--host', `$script:WebHost"; Why = 'starts the console on loopback' },
    @{ Needle = "'ATLAS_DATABASE_URL'"; Why = 'passes the database URL to its children' },
    @{ Needle = "'ATLAS_DATABASE_SCHEMA'"; Why = 'passes the schema to its children' },
    @{ Needle = "'ATLAS_WEB_DEV_LOGIN'"; Why = 'enables the development login for its children' },
    @{ Needle = "'ATLAS_WEB_OPERATOR_PRINCIPAL'"; Why = 'names the local operator' },
    @{ Needle = 'operator-init'; Why = 'prints the operator-init command' },
    @{ Needle = "'authorization.manage'"; Why = 'names every grant' },
    @{ Needle = "'report.render'"; Why = 'names every grant' },
    @{ Needle = "'self.monthly.report.view'"; Why = 'names every grant' },
    @{ Needle = 'InitializeOperator'; Why = 'requires the operator-init flag' },
    @{ Needle = 'Test-LoopbackHost'; Why = 'refuses a non-loopback database' },
    @{ Needle = 'Start-TrackedChild'; Why = 'tracks only what it starts' },
    @{ Needle = 'Stop-TrackedChildren'; Why = 'stops the tracked set' },
    @{ Needle = 'taskkill'; Why = 'stops a tracked process tree and nothing else' }
)
foreach ($marker in $demoMarkers) {
    Assert-True -Condition $demoCode.Contains($marker.Needle) `
        -Message "start-demo.ps1 $($marker.Why) ($($marker.Needle))"
}

# The four child variables are set into the child's own environment, never into
# this script's: no `$env:` assignment appears outside the install's npm one.
Assert-NotMatches -Text $demoCode -Pattern '(?m)^\s*\$env:ATLAS' `
    -Message 'start-demo.ps1 never assigns an ATLAS_* variable to its own environment'

# The two packages install.ps1 rebuilds are the two web/package.json approves,
# and the only two non-optional packages in the lockfile that carry an install
# script at all. Both sides are read from the files rather than restated here,
# so a third one fails this instead of being silently skipped by the installer.
$webManifest = Get-Content -LiteralPath (Join-Path $repositoryRoot 'web\package.json') -Raw | ConvertFrom-Json
$approvedNames = @(
    # `@tailwindcss/oxide@4.1.14` -> `@tailwindcss/oxide`: the name is everything
    # before the *last* `@` that is not the leading scope marker.
    $webManifest.allowScripts.PSObject.Properties.Name |
        ForEach-Object { $_ -replace '@(?=[^@]*$).*$', '' } | Sort-Object
)
$rebuiltNames = @(
    [regex]::Match($installCode, '(?m)^\s*\$approvedBuildPackages = @\((?<names>[^)]*)\)').Groups['names'].Value -split ',' |
        ForEach-Object { $_.Trim().Trim("'") } | Sort-Object
)
Assert-True -Condition (($rebuiltNames -join ',') -eq ($approvedNames -join ',')) `
    -Message "install.ps1 rebuilds exactly what web/package.json#allowScripts approves ($($approvedNames -join ', '))"

$webLockText = Get-Content -LiteralPath (Join-Path $repositoryRoot 'web\package-lock.json') -Raw
# Windows PowerShell 5.1's ConvertFrom-Json rejects an empty property name, and
# a lockfile has one: "" is the project itself, not a package. It is renamed
# before parsing, and it carries no install script, so nothing else changes.
$webLock = ($webLockText -replace '(?m)^(\s*)"":\s*\{', '$1"__project__": {') | ConvertFrom-Json
$lockInstallers = @(
    $webLock.packages.PSObject.Properties | Where-Object {
        # StrictMode treats a missing property as an error, and most entries have
        # neither field, so both are read through the property collection first.
        # `-and` short-circuits, so an entry without them is never dereferenced.
        $null -ne $_.Value.PSObject.Properties['hasInstallScript'] -and
        $_.Value.hasInstallScript -eq $true -and
        $null -eq $_.Value.PSObject.Properties['optional']
    } | ForEach-Object { $_.Name -replace '^node_modules/', '' } | Sort-Object
)
Assert-True -Condition (($lockInstallers -join ',') -eq ($approvedNames -join ',')) `
    -Message "every non-optional package with an install script in the lockfile is one of them ($($lockInstallers -join ', '))"

# --- 5. the dry runs ---------------------------------------------------------

Write-Host '==> 5. both scripts run clean in -DryRun' -ForegroundColor Cyan
$demoPorts = @(5433, 8000, 5175)
$listeningBefore = Get-ListeningPorts -Ports $demoPorts

function Invoke-Script {
    <# Run one checked script in a child Windows PowerShell and hand back its
       exit code and its whole output. The arguments are passed straight
       through, so a dry run and a run that has to fail closed are the same
       code path with different switches. #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [string[]]$Arguments = @()
    )
    $childArguments = @('-NoProfile', '-File', $Path) + $Arguments
    # A run that is expected to fail closed writes its reason to stderr, and
    # under $ErrorActionPreference = 'Stop' the 2>&1 that merges stderr into
    # the output would turn that reason into a terminating error of this
    # script's own. The preference is relaxed for the call and restored after,
    # so a refusal is text to assert on rather than a crash.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & powershell.exe @childArguments 2>&1
        $exit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $text = (($output | ForEach-Object { [string]$_ }) -join "`n") -replace '\x1b\[[0-9;]*m', ''
    return [pscustomobject]@{ Exit = $exit; Text = $text }
}

function Invoke-DryRun {
    param(
        [Parameter(Mandatory)][string]$Path,
        [string[]]$Arguments = @()
    )
    return Invoke-Script -Path $Path -Arguments (@('-DryRun') + $Arguments)
}

# -Force because the assertions below are about the *plan*, and on a machine
# that has already run the installer its own plan is `already installed` - the
# console steps it is meant to be checking would not be printed at all. It is a
# dry run either way, so nothing is installed by passing it.
$installDryRun = Invoke-DryRun -Path $installPath -Arguments @('-Force')
Assert-True -Condition ($installDryRun.Exit -eq 0) `
    -Message "install.ps1 -DryRun exits 0 (got $($installDryRun.Exit))"
Assert-Contains -Text $installDryRun.Text -Needle '.\start-demo.ps1 -InitializeOperator -OpenBrowser' `
    -Message 'install.ps1 -DryRun prints the exact next command'
Assert-Contains -Text $installDryRun.Text -Needle 'npm' -Message 'install.ps1 -DryRun plans the console install'
Assert-Contains -Text $installDryRun.Text -Needle 'ci --ignore-scripts' `
    -Message 'install.ps1 -DryRun plans the console install with every install script off'
Assert-Contains -Text $installDryRun.Text -Needle 'rebuild esbuild @tailwindcss/oxide' `
    -Message 'install.ps1 -DryRun plans the named rebuild of the two approved build binaries'
Assert-NotMatches -Text $installDryRun.Text -Pattern 'NPM_CONFIG_YES' `
    -Message 'install.ps1 -DryRun sets no npm prompt answer'
Assert-NotMatches -Text $installDryRun.Text -Pattern '(?i)creating the virtual environment' `
    -Message 'install.ps1 -DryRun does not create a virtual environment'

# A plan is only worth reading if it is true. Nothing in a dry run ran, so a
# green "checked" line in one is a claim the script did not earn, and the
# assertions below are the reason it cannot print one.
Assert-NotMatches -Text $installDryRun.Text -Pattern '(?i)\[ok\]\s*docker' `
    -Message 'install.ps1 -DryRun claims no Docker check it did not run'
Assert-Contains -Text $installDryRun.Text -Needle 'not checked in dry run' `
    -Message 'install.ps1 -DryRun says the Docker check was not made'
Assert-NotMatches -Text $installDryRun.Text -Pattern '(?i)\[ok\]\s*(project )?installed' `
    -Message 'install.ps1 -DryRun claims nothing was installed'
Assert-Contains -Text $installDryRun.Text -Needle 'nothing was created' `
    -Message 'install.ps1 -DryRun says what it did not create'

$demoDryRun = Invoke-DryRun -Path $demoPath
Assert-True -Condition ($demoDryRun.Exit -eq 0) `
    -Message "start-demo.ps1 -DryRun exits 0 (got $($demoDryRun.Exit))"
Assert-Contains -Text $demoDryRun.Text -Needle 'dry run complete: nothing was started, nothing was written' `
    -Message 'start-demo.ps1 -DryRun says it changed nothing'
Assert-Contains -Text $demoDryRun.Text -Needle 'up --detach postgres' `
    -Message 'start-demo.ps1 -DryRun plans only the postgres service'
Assert-Contains -Text $demoDryRun.Text -Needle '-m atlas_web --host 127.0.0.1 --port 8000' `
    -Message 'start-demo.ps1 -DryRun plans the API on loopback 8000'
Assert-Contains -Text $demoDryRun.Text -Needle 'run dev -- --host 127.0.0.1' `
    -Message 'start-demo.ps1 -DryRun plans the console on loopback 5175'
Assert-Contains -Text $demoDryRun.Text -Needle 'operator-init' `
    -Message 'start-demo.ps1 -DryRun prints operator-init'
Assert-Contains -Text $demoDryRun.Text -Needle 'ATLAS_WEB_DEV_LOGIN' `
    -Message 'start-demo.ps1 -DryRun names the child environment'
Assert-NotMatches -Text $demoDryRun.Text -Pattern 'the demo is up' `
    -Message 'start-demo.ps1 -DryRun does not claim the demo is running'
Assert-NotMatches -Text $demoDryRun.Text -Pattern 'opened http' `
    -Message 'start-demo.ps1 -DryRun opens no browser'

# Which install command the launcher picks is a property of the directory it is
# sitting in, so this checkout is itself the case: a clone has no
# SHA256SUMS.txt, and the launcher has to answer that rather than the operator.
# (The release bundle is proved in section 11, against a stub that has one.)
$repositorySums = Join-Path $repositoryRoot 'SHA256SUMS.txt'
if (Test-Path -LiteralPath $repositorySums) {
    Assert-NotMatches -Text $demoDryRun.Text -Pattern 'SkipChecksum' `
        -Message 'start-demo.ps1 -DryRun adds no switch where a checksum file is present'
} else {
    Assert-Contains -Text $demoDryRun.Text -Needle 'source checkout: checksum verification skipped' `
        -Message 'start-demo.ps1 -DryRun says why it skipped the checksum in this clone'
    Assert-Contains -Text $demoDryRun.Text -Needle 'install.ps1 -SkipChecksum -DryRun' `
        -Message 'start-demo.ps1 -DryRun plans the install the installer will accept from a clone'
}

$listeningAfter = Get-ListeningPorts -Ports $demoPorts
Assert-True -Condition (($listeningBefore -join ',') -eq ($listeningAfter -join ',')) `
    -Message "no new listener appeared on 5433/8000/5175 (before: $($listeningBefore -join ','); after: $($listeningAfter -join ','))"

# --- 6. the installer proves its own bytes (contract 40.4) -------------------

Write-Host '==> 6. install.ps1 verifies itself against SHA256SUMS.txt before it installs' -ForegroundColor Cyan

# The way out has to say what it is, in the help an operator actually reads.
Assert-Contains -Text $installRaw -Needle 'not a valid way to run a released installer' `
    -Message 'install.ps1 marks -SkipChecksum as invalid for a released asset'

# A throwaway copy of the installer over a stub source bundle, so a checksum
# can be proved without a release. Every run below is given an install root
# that is deliberately not there, so a run that somehow got past the checksum
# fails at the install-directory check instead of creating a virtual
# environment on a machine that happens to have every tool installed.
$sandbox = Join-Path ([System.IO.Path]::GetTempPath()) `
    ("atlas-hq-verify-scripts-{0}-{1}" -f $PID, ([guid]::NewGuid().ToString('n').Substring(0, 8)))
$bundle = Join-Path $sandbox 'bundle'
$absentInstallRoot = Join-Path $bundle 'install-root-not-created'

function New-StubBundle {
    <# The minimum a directory needs to look like an Atlas-HQ source bundle.
       It carries what start-demo.ps1's own layout check asks for as well as
       what install.ps1 asks for, so either script can be run against it. #>
    param([Parameter(Mandatory)][string]$Path)
    $null = New-Item -ItemType Directory -Path $Path -Force
    foreach ($relative in @('src\atlas_hq', 'src\atlas_core', 'src\atlas_web', 'web')) {
        $null = New-Item -ItemType Directory -Path (Join-Path $Path $relative) -Force
    }
    Set-Content -LiteralPath (Join-Path $Path 'pyproject.toml') -Value '<project />'
    Set-Content -LiteralPath (Join-Path $Path 'web\package.json') -Value '{}'
    # A dry run reads neither this file nor its contents; only its presence is
    # part of the launcher's layout check.
    Set-Content -LiteralPath (Join-Path $Path 'docker-compose.yml') -Value '# stub'
    # Both release scripts, because the release writes a checksum line for
    # each of them and a reader that took the wrong line would be a bug.
    Copy-Item -LiteralPath $installPath -Destination (Join-Path $Path 'install.ps1')
    Copy-Item -LiteralPath $demoPath -Destination (Join-Path $Path 'start-demo.ps1')
    return $Path
}

function Get-ChecksumLine {
    <# One `sha256sum` line for a file. $Marker is the separator: two spaces
       for a text-mode line, ' *' for the binary-mode one. #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [string]$Marker = '  '
    )
    $digest = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    return "$digest$Marker$(Split-Path -Leaf $Path)"
}

try {
    $null = New-StubBundle -Path $bundle
    $bundleInstall = Join-Path $bundle 'install.ps1'
    $bundleSums = Join-Path $bundle 'SHA256SUMS.txt'
    $dryRunArguments = @('-SourceRoot', $bundle, '-DryRun')
    $realArguments = @('-SourceRoot', $bundle, '-InstallRoot', $absentInstallRoot)
    # `sha256sum` writes lower-case hex and Get-FileHash reports upper-case, so
    # a real checksum file is itself the case-insensitivity check.
    $realDigest = (Get-FileHash -LiteralPath $bundleInstall -Algorithm SHA256).Hash
    $releaseLine = "$($realDigest.ToLower())  install.ps1"
    $upperLine = "$realDigest  install.ps1"
    $goodDemoLine = Get-ChecksumLine -Path (Join-Path $bundle 'start-demo.ps1')
    $wrongDigest = '0' * 64

    # A dry run must show the plan without a checksum file to check against.
    $noSumsRun = Invoke-Script -Path $bundleInstall -Arguments $dryRunArguments
    Assert-True -Condition ($noSumsRun.Exit -eq 0) `
        -Message "install.ps1 -DryRun exits 0 with no SHA256SUMS.txt (got $($noSumsRun.Exit))"
    Assert-Contains -Text $noSumsRun.Text -Needle 'Get-FileHash -Algorithm SHA256' `
        -Message 'the dry run prints the verification plan'
    Assert-Contains -Text $noSumsRun.Text -Needle 'does not require the checksum file' `
        -Message 'the dry run says it needs no checksum file'

    # The right digest, in each shape a sha256sum line can take.
    Set-Content -LiteralPath $bundleSums -Value @($releaseLine, $goodDemoLine) -Encoding ASCII
    $matchRun = Invoke-Script -Path $bundleInstall -Arguments $dryRunArguments
    Assert-True -Condition ($matchRun.Exit -eq 0) `
        -Message "install.ps1 verifies a lower-case sha256sum digest (got $($matchRun.Exit))"
    Assert-Contains -Text $matchRun.Text -Needle 'SHA-256 verified' `
        -Message 'install.ps1 reports the verified digest'

    # The same digest in upper case, which is what Get-FileHash itself gives.
    Set-Content -LiteralPath $bundleSums -Value @($upperLine, $goodDemoLine) -Encoding ASCII
    $upperRun = Invoke-Script -Path $bundleInstall -Arguments $dryRunArguments
    Assert-True -Condition ($upperRun.Exit -eq 0) `
        -Message "an upper-case digest still verifies (got $($upperRun.Exit))"
    Assert-Contains -Text $upperRun.Text -Needle 'SHA-256 verified' `
        -Message 'the digest comparison ignores case in both directions'

    # A binary-mode line, where the second space is a *.
    Set-Content -LiteralPath $bundleSums `
        -Value @((Get-ChecksumLine -Path $bundleInstall -Marker ' *'), $goodDemoLine) -Encoding ASCII
    $binaryRun = Invoke-Script -Path $bundleInstall -Arguments $dryRunArguments
    Assert-True -Condition ($binaryRun.Exit -eq 0) `
        -Message "a binary-mode sha256sum line parses (got $($binaryRun.Exit))"
    Assert-Contains -Text $binaryRun.Text -Needle 'SHA-256 verified' `
        -Message 'the * marker is read as part of the line format'

    # A digest for another file is not this file's digest.
    Set-Content -LiteralPath $bundleSums -Value @($goodDemoLine) -Encoding ASCII
    $noLineRun = Invoke-Script -Path $bundleInstall -Arguments $realArguments
    Assert-True -Condition ($noLineRun.Exit -ne 0) `
        -Message "a checksum file with no install.ps1 line stops the install (got $($noLineRun.Exit))"
    Assert-Contains -Text $noLineRun.Text -Needle "has no readable 'install.ps1' line" `
        -Message 'the refusal names the missing line'
    Assert-NotMatches -Text $noLineRun.Text -Pattern 'SHA-256 verified' `
        -Message 'nothing is claimed to be verified when there is no line to verify against'

    # A line that is not a digest is not parsed into one.
    Set-Content -LiteralPath $bundleSums -Value @('# the release checksums', 'deadbeef  install.ps1') -Encoding ASCII
    $garbageRun = Invoke-Script -Path $bundleInstall -Arguments $realArguments
    Assert-True -Condition ($garbageRun.Exit -ne 0) `
        -Message "a malformed digest stops the install (got $($garbageRun.Exit))"
    Assert-Contains -Text $garbageRun.Text -Needle "has no readable 'install.ps1' line" `
        -Message 'a short digest is a malformed line, not a digest'

    # The mismatch, and the order it happens in: before any install work.
    Set-Content -LiteralPath $bundleSums -Value @("$wrongDigest  install.ps1", $goodDemoLine) -Encoding ASCII
    $mismatchRun = Invoke-Script -Path $bundleInstall -Arguments $realArguments
    Assert-True -Condition ($mismatchRun.Exit -ne 0) `
        -Message "a wrong digest stops the install (got $($mismatchRun.Exit))"
    Assert-Contains -Text $mismatchRun.Text -Needle 'does not match the SHA256SUMS.txt beside it' `
        -Message 'the mismatch says so in one line'
    Assert-Contains -Text $mismatchRun.Text -Needle $wrongDigest `
        -Message 'the mismatch names the digest it expected'
    Assert-Contains -Text $mismatchRun.Text -Needle $realDigest `
        -Message 'the mismatch names the digest it found'
    Assert-NotMatches -Text $mismatchRun.Text -Pattern 'the install directory does not exist' `
        -Message 'the checksum is read before any install work is done'

    # No checksum file at all is a refusal too, and it names the way out.
    Remove-Item -LiteralPath $bundleSums
    $absentRun = Invoke-Script -Path $bundleInstall -Arguments $realArguments
    Assert-True -Condition ($absentRun.Exit -ne 0) `
        -Message "no SHA256SUMS.txt stops the install (got $($absentRun.Exit))"
    Assert-Contains -Text $absentRun.Text -Needle 'there is no SHA256SUMS.txt beside this installer' `
        -Message 'the missing checksum file is named'
    Assert-Contains -Text $absentRun.Text -Needle '.\install.ps1 -SkipChecksum' `
        -Message 'the refusal names the clone-only way out'

    # And the way out is a real switch, not a comment.
    Set-Content -LiteralPath $bundleSums -Value @("$wrongDigest  install.ps1") -Encoding ASCII
    $skipRun = Invoke-Script -Path $bundleInstall `
        -Arguments @('-SourceRoot', $bundle, '-DryRun', '-SkipChecksum')
    Assert-True -Condition ($skipRun.Exit -eq 0) `
        -Message "install.ps1 accepts -SkipChecksum (got $($skipRun.Exit))"
    Assert-Contains -Text $skipRun.Text -Needle 'skipped (-SkipChecksum)' `
        -Message '-SkipChecksum says it skipped the check'
    Assert-NotMatches -Text $skipRun.Text -Pattern 'SHA-256 verified' `
        -Message '-SkipChecksum claims no verification'

    # None of the nine runs above installed anything.
    $checksumText = ($noSumsRun.Text + $matchRun.Text + $upperRun.Text + $binaryRun.Text +
        $noLineRun.Text + $garbageRun.Text + $mismatchRun.Text + $absentRun.Text + $skipRun.Text)
    Assert-NotMatches -Text $checksumText `
        -Pattern '(?i)creating the virtual environment|install stamp written|console dependencies installed' `
        -Message 'no checksum run created an environment, a stamp or a node_modules'
    Assert-True -Condition (-not (Test-Path -LiteralPath (Join-Path $bundle '.venv'))) `
        -Message 'the stub bundle has no .venv afterwards'
    Assert-True -Condition (-not (Test-Path -LiteralPath $absentInstallRoot)) `
        -Message 'the install root that was never there was never created'
    $listeningAfterChecksums = Get-ListeningPorts -Ports $demoPorts
    Assert-True -Condition (($listeningAfterChecksums -join ',') -eq ($listeningBefore -join ',')) `
        -Message "no checksum run started a listener (before: $($listeningBefore -join ','); after: $($listeningAfterChecksums -join ','))"
} finally {
    if (Test-Path -LiteralPath $sandbox) { Remove-Item -LiteralPath $sandbox -Recurse -Force }
}

# --- 7. the tracked set is always stopped (contract 40.3) --------------------

Write-Host '==> 7. start-demo.ps1 cannot leave a tracked child running' -ForegroundColor Cyan

# Structural, not textual: the guarantee is that the first tracked child is
# started inside a `try` whose `finally` reaps the set. Asserting on the shape
# of the AST is what makes it hold - a text scan cannot tell whether a
# `finally` belongs to the statement that starts the API or to an unrelated one
# further up, and it cannot tell an empty `finally` from a real one.
$demoTokens = $null
$demoErrors = $null
$demoAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $demoPath, [ref]$demoTokens, [ref]$demoErrors)

$startCalls = @($demoAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
            $node.GetCommandName() -eq 'Start-TrackedChild'
        }, $true))
Assert-True -Condition ($startCalls.Count -gt 0) `
    -Message "start-demo.ps1 starts tracked children (found $($startCalls.Count))"

function Get-EnclosingTry {
    param([Parameter(Mandatory)]$Node)
    $current = $Node.Parent
    while ($null -ne $current) {
        if ($current -is [System.Management.Automation.Language.TryStatementAst]) { return $current }
        $current = $current.Parent
    }
    return $null
}

$guarded = 0
$guardedTry = $null
foreach ($call in $startCalls) {
    $try = Get-EnclosingTry -Node $call
    if ($null -eq $try) { continue }
    if ($null -eq $guardedTry) { $guardedTry = $try }
    if ($try -eq $guardedTry) { $guarded++ }
}
Assert-True -Condition ($guarded -eq $startCalls.Count) `
    -Message "every tracked child is started inside the one try ($guarded of $($startCalls.Count))"

$finallyCommands = @()
if ($null -ne $guardedTry -and $null -ne $guardedTry.Finally) {
    $finallyCommands = @($guardedTry.Finally.FindAll({
                param($node) $node -is [System.Management.Automation.Language.CommandAst]
            }, $true) | ForEach-Object { $_.GetCommandName() })
}
Assert-True -Condition ($finallyCommands -contains 'Stop-TrackedChildren') `
    -Message "that try has a finally that calls Stop-TrackedChildren ($($finallyCommands -join ', '))"

# The finally is where an error is least welcome, so cleanup may not add one:
# idempotent, and every step guarded.
$stopFunctions = @($demoAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Stop-TrackedChildren'
        }, $true))
Assert-True -Condition ($stopFunctions.Count -eq 1) `
    -Message 'Stop-TrackedChildren is defined exactly once'
if ($stopFunctions.Count -eq 1) {
    $stopBody = $stopFunctions[0].Body.Extent.Text
    Assert-True -Condition ($stopBody -match '\$script:Stopped') `
        -Message 'Stop-TrackedChildren is idempotent (it remembers that it has run)'
    # Asked of the AST, not of the text: the help says in words what the code
    # must not do, and a text scan would fail on the sentence that says it.
    $stopCatches = @($stopFunctions[0].FindAll({
                param($node)
                $node -is [System.Management.Automation.Language.TryStatementAst] -and
                $node.CatchClauses.Count -gt 0
            }, $true))
    Assert-True -Condition ($stopCatches.Count -gt 0) `
        -Message 'Stop-TrackedChildren guards every step, so it cannot throw'
    $stopThrows = @($stopFunctions[0].FindAll({
                param($node) $node -is [System.Management.Automation.Language.ThrowStatementAst]
            }, $true))
    Assert-True -Condition ($stopThrows.Count -eq 0) `
        -Message 'Stop-TrackedChildren reports a failure instead of raising one'
}

# --- 8. loopback is parsed, not matched (contract 40.3) ----------------------

Write-Host '==> 8. start-demo.ps1 decides loopback by parsing an address' -ForegroundColor Cyan

# The defect this replaces: `^127\.` matched text, so `127.0.0.1.example.com`
# passed as this machine. The name of an address is not an address, and .NET's
# parser is also happy with the shorthands a URL's resolver hands to DNS
# (`127.1`), so the code has to ask for a real address and then ask .NET whether
# that address is a loopback one.
Assert-NotMatches -Text $demoCode -Pattern '\^127' `
    -Message 'start-demo.ps1 does not decide loopback from the text of a host'
Assert-Contains -Text $demoCode -Needle '[System.Net.IPAddress]::TryParse' `
    -Message 'start-demo.ps1 parses the host as an IP address'
Assert-Contains -Text $demoCode -Needle 'IsLoopback' `
    -Message 'start-demo.ps1 asks whether the parsed address is loopback'

# Behavioural, because a text scan cannot tell a real parse from a regex shaped
# like one. The function is lifted out of the file exactly as written and called:
# it is self-contained on purpose, so nothing else from the launcher is in scope
# and what answers each host below is the launcher's own code.
$loopbackFunctions = @($demoAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Test-LoopbackHost'
        }, $true))
Assert-True -Condition ($loopbackFunctions.Count -eq 1) `
    -Message "Test-LoopbackHost is defined exactly once (found $($loopbackFunctions.Count))"
if ($loopbackFunctions.Count -eq 1) {
    . ([scriptblock]::Create(('function Test-LoopbackHost {0}' -f $loopbackFunctions[0].Body.Extent.Text)))
    # The accept list is the one tests/test_web_bind_guard.py pins for the API's
    # own guard, so the launcher and the API cannot disagree about loopback.
    foreach ($candidate in @('127.0.0.1', '127.0.0.53', '::1', '[::1]', 'localhost', 'LOCALHOST')) {
        Assert-True -Condition (Test-LoopbackHost $candidate) `
            -Message "Test-LoopbackHost accepts $candidate"
    }
    foreach ($candidate in @(
            '0.0.0.0', '10.0.0.5', '192.168.1.10', '::',
            # The reported case, and the shape a prefix test gets wrong: a name
            # that begins with an address is somebody else's host.
            '127.0.0.1.example.com',
            # A shorthand .NET parses as 127.0.0.1 and a resolver does not.
            '127.1',
            '10.0.0.5:5432', 'example.internal', '')) {
        Assert-True -Condition (-not (Test-LoopbackHost $candidate)) `
            -Message "Test-LoopbackHost refuses '$candidate'"
    }
}

# --- 9. the DSN cannot be redirected out of loopback (contract 40.3) ----------

Write-Host '==> 9. start-demo.ps1 refuses a database URL that redirects the connection' -ForegroundColor Cyan

# The defect this closes: the guard read `$parsedDatabaseUrl.Host`, and everything
# after a `?` is a connect-arg to SQLAlchemy and psycopg that wins over the
# authority. So `...@127.0.0.1:5433/atlas_hq?host=evil.example.com` passed the
# loopback check and connected to evil.example.com - and a `#` in front of the `?`
# did the same, because .NET calls that a fragment while the driver's own parse
# reads the `?` after it as a query. A text scan cannot catch either: the launcher
# has no idea what a DSN means - so the launcher itself is run against a table of
# URLs and has to refuse or accept each one.
Assert-Contains -Text $demoCode -Needle '$parsedDatabaseUrl.Query' `
    -Message 'start-demo.ps1 looks at the query string, not only the authority'
Assert-Contains -Text $demoCode -Needle '$parsedDatabaseUrl.Fragment' `
    -Message 'start-demo.ps1 looks at the fragment, so a # cannot hide a connect-arg'

# `-SkipInstall` keeps the run off the install, and -DryRun keeps it off Docker,
# the database and both servers: the guard sits in the database step, which is
# reached either way and starts nothing.
$dsnArguments = @('-SkipInstall', '-DryRun')
$validUrls = @(
    @{ Url = 'postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq'; Host = '127.0.0.1:5433' },
    @{ Url = 'postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq'; Host = 'localhost:5433' },
    @{ Url = 'postgresql+psycopg://atlas:atlas@[::1]:5433/atlas_hq'; Host = $null }
)
foreach ($case in $validUrls) {
    $run = Invoke-Script -Path $demoPath -Arguments ($dsnArguments + @('-DatabaseUrl', $case.Url))
    Assert-True -Condition ($run.Exit -eq 0) `
        -Message "$($case.Url) is accepted (got $($run.Exit))"
    Assert-Contains -Text $run.Text -Needle '(from -DatabaseUrl)' `
        -Message "$($case.Url) is the database the run would use"
    Assert-Contains -Text $run.Text -Needle 'dry run complete: nothing was started, nothing was written' `
        -Message "$($case.Url) reaches the plan instead of being refused"
    Assert-NotMatches -Text $run.Text -Pattern 'must not carry a query string or a fragment' `
        -Message "$($case.Url) is not refused for a query string it does not have"
    if ($null -ne $case.Host) {
        Assert-Contains -Text $run.Text -Needle "database $($case.Host) " `
            -Message "$($case.Url) is reported as $($case.Host)"
    }
}

# Every connect-arg a driver honours, not just the reported one: a guard that
# refused only `?host=` would still let `?port=`, `?dbname=`, `?user=`,
# `?password=`, `?service=` and `?options=` through. The launcher refuses the
# whole query, so the table below is a property of the decision, not a list it
# has to be taught. The `#` rows are the same bypass with a fragment in front of
# it, which is what a `.Query`-only guard would wave through.
foreach ($tail in @(
        '?host=evil.example.com',
        '?port=6543',
        '?dbname=other&user=other&password=other',
        '?service=pg_service',
        '?options=-c%20statement_timeout=0',
        # A key with nothing after it is still a key, and still refused.
        '?host=',
        '#f?host=evil.example.com',
        '#?port=6543',
        '#fragment')) {
    $run = Invoke-Script -Path $demoPath `
        -Arguments ($dsnArguments + @('-DatabaseUrl', "postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq$tail"))
    Assert-True -Condition ($run.Exit -ne 0) `
        -Message "a database URL carrying $tail is refused (got $($run.Exit))"
    Assert-Contains -Text $run.Text -Needle 'must not carry a query string or a fragment' `
        -Message "the refusal for $tail names the query string or fragment"
    Assert-Contains -Text $run.Text -Needle '?host=, ?port=, ?dbname=, ?user=, ?password=, ?service= and' `
        -Message "the refusal for $tail names the connect-args it refuses to reason about"
    # Refused where the guard is, which is before the plan and before anything
    # is started, rather than by a later check that happens to fail.
    Assert-NotMatches -Text $run.Text -Pattern 'dry run complete|the demo is up' `
        -Message "the run carrying $tail is refused before the plan"
}

# The other half: a name that merely begins with an address is still somebody
# else's host, through the real URL path rather than through the lifted function.
$nameRun = Invoke-Script -Path $demoPath -Arguments ($dsnArguments + @(
        '-DatabaseUrl', 'postgresql+psycopg://atlas:atlas@127.0.0.1.example.com:5433/atlas_hq'))
Assert-True -Condition ($nameRun.Exit -ne 0) `
    -Message "a database host of 127.0.0.1.example.com is refused (got $($nameRun.Exit))"
Assert-Contains -Text $nameRun.Text -Needle 'which is not loopback' `
    -Message 'the refusal names the host it refused'

# Nothing above touched the machine, and the loopback ports are still the ones
# the dry runs found free.
$listeningAfterDsns = Get-ListeningPorts -Ports $demoPorts
Assert-True -Condition (($listeningAfterDsns -join ',') -eq ($listeningBefore -join ',')) `
    -Message "no database-URL run started a listener (before: $($listeningBefore -join ','); after: $($listeningAfterDsns -join ','))"

# --- 10. one install root (contract 40.2) -------------------------------------

Write-Host '==> 10. install.ps1 installs into one directory, or refuses' -ForegroundColor Cyan

# The other half of section 40.2: a source bundle in one directory and an install
# in another is the case the rule is about. The virtual environment and the
# stamp would land in the install directory while npm wrote the console's
# node_modules beside the bundle - a write outside the directory the operator
# named, and not where start-demo.ps1 looks, so the demo would come up with no
# console. A stub bundle is enough to prove the refusal, and a run that somehow
# got past it could not have installed anything real.
$rootSandbox = Join-Path ([System.IO.Path]::GetTempPath()) `
    ("atlas-hq-verify-roots-{0}-{1}" -f $PID, ([guid]::NewGuid().ToString('n').Substring(0, 8)))
$rootBundle = Join-Path $rootSandbox 'bundle'
$otherRoot = Join-Path $rootSandbox 'somewhere-else'
try {
    $null = New-StubBundle -Path $rootBundle
    $null = New-Item -ItemType Directory -Path $otherRoot -Force
    $rootInstaller = Join-Path $rootBundle 'install.ps1'

    $splitRun = Invoke-Script -Path $rootInstaller `
        -Arguments @('-SourceRoot', $rootBundle, '-InstallRoot', $otherRoot, '-SkipChecksum')
    Assert-True -Condition ($splitRun.Exit -ne 0) `
        -Message "a source root and a different install root stop the install (got $($splitRun.Exit))"
    Assert-Contains -Text $splitRun.Text -Needle 'different directories' `
        -Message 'the refusal says the two roots differ'
    Assert-Contains -Text $splitRun.Text -Needle $rootBundle `
        -Message 'the refusal names the source root it was given'
    Assert-Contains -Text $splitRun.Text -Needle $otherRoot `
        -Message 'the refusal names the install root it was given'
    Assert-Contains -Text $splitRun.Text -Needle 'Drop -InstallRoot' `
        -Message 'the refusal names the way out'
    # The refusal lands before any of the work it protects, so the run below
    # never got as far as a checksum, a prerequisite, an environment or npm.
    Assert-NotMatches -Text $splitRun.Text `
        -Pattern '(?i)preparing the virtual environment|installing the console|SHA-256 verified|docker' `
        -Message 'the split root is refused before any install work is examined'

    # A dry run refuses it too: the split is a property of the two arguments, not
    # of how far the run got, and a plan for a refused run is not a plan.
    $splitDryRun = Invoke-Script -Path $rootInstaller `
        -Arguments @('-SourceRoot', $rootBundle, '-InstallRoot', $otherRoot, '-SkipChecksum', '-DryRun')
    Assert-True -Condition ($splitDryRun.Exit -ne 0) `
        -Message "install.ps1 -DryRun refuses a split root as well (got $($splitDryRun.Exit))"
    Assert-NotMatches -Text $splitDryRun.Text -Pattern '(?i)dry run complete' `
        -Message 'a dry run prints no plan for a run it refuses'

    # The pair that is allowed: one directory named twice, which is exactly what
    # the defaults resolve to.
    $sameRootRun = Invoke-Script -Path $rootInstaller `
        -Arguments @('-SourceRoot', $rootBundle, '-InstallRoot', $rootBundle, '-SkipChecksum', '-DryRun')
    Assert-True -Condition ($sameRootRun.Exit -eq 0) `
        -Message "one directory named for both roots is accepted (got $($sameRootRun.Exit))"
    Assert-Contains -Text $sameRootRun.Text -Needle 'dry run complete' `
        -Message 'the accepted pair prints the plan'

    foreach ($root in @($rootBundle, $otherRoot)) {
        Assert-True -Condition (-not (Test-Path -LiteralPath (Join-Path $root '.venv'))) `
            -Message "'$root' has no .venv afterwards"
        Assert-True -Condition (-not (Test-Path -LiteralPath (Join-Path $root '.atlas-install-stamp.json'))) `
            -Message "'$root' has no install stamp afterwards"
    }
    Assert-True -Condition (-not (Test-Path -LiteralPath (Join-Path $rootBundle 'web\node_modules'))) `
        -Message 'no console dependencies were installed into either root'
} finally {
    if (Test-Path -LiteralPath $rootSandbox) { Remove-Item -LiteralPath $rootSandbox -Recurse -Force }
}

# --- 11. the launcher picks the installer's checksum mode (contract 40.4) -----

Write-Host '==> 11. start-demo.ps1 runs install.ps1 the way its directory is built' -ForegroundColor Cyan

# The defect this closes: the launcher always ran `install.ps1` with no
# arguments, so a repository clone - which has no release asset, and so no
# SHA256SUMS.txt beside it - was refused by the installer's own checksum rule
# and the demo could not start. The fix has to be narrow in both directions: a
# release bundle still verifies itself, and a directory that is neither a
# bundle nor a checkout still fails closed. Only a text scan cannot tell those
# apart, so the launcher is run against all three.
Assert-Contains -Text $demoCode -Needle 'Test-SourceCheckout' `
    -Message 'start-demo.ps1 decides from the directory it is running in'

$launchSandbox = Join-Path ([System.IO.Path]::GetTempPath()) `
    ("atlas-hq-verify-launch-{0}-{1}" -f $PID, ([guid]::NewGuid().ToString('n').Substring(0, 8)))
$launchBundle = Join-Path $launchSandbox 'bundle'
$launchDemo = Join-Path $launchBundle 'start-demo.ps1'
$launchSums = Join-Path $launchBundle 'SHA256SUMS.txt'
try {
    $null = New-StubBundle -Path $launchBundle

    # 1. A source checkout: no checksum file, and the markers that make it one.
    # The bundle runs, the install is planned with -SkipChecksum, and the reason
    # is printed. -DryRun so the plan is proved and nothing is installed.
    $checkoutRun = Invoke-Script -Path $launchDemo -Arguments @('-DryRun')
    Assert-True -Condition ($checkoutRun.Exit -eq 0) `
        -Message "a source checkout plans its install (got $($checkoutRun.Exit))"
    Assert-Contains -Text $checkoutRun.Text -Needle 'source checkout: checksum verification skipped' `
        -Message 'the clone path says the check was skipped'
    Assert-Contains -Text $checkoutRun.Text -Needle 'install.ps1 -SkipChecksum -DryRun' `
        -Message 'the clone path plans install.ps1 -SkipChecksum'
    Assert-NotMatches -Text $checkoutRun.Text -Pattern 'there is no SHA256SUMS.txt beside this script' `
        -Message 'a checkout is not refused for the absent checksum file'
    Assert-Contains -Text $checkoutRun.Text -Needle 'dry run complete: nothing was started, nothing was written' `
        -Message 'the clone path reaches the plan'

    # 2. A release bundle: the checksum file is there, so it is installed with
    # no switch at all and the proof is left to the installer. The content is
    # never read - this is the launcher's decision, not a second verification -
    # so a stub file is enough to prove it.
    Set-Content -LiteralPath $launchSums -Value '# stub' -Encoding ASCII
    $bundleRun = Invoke-Script -Path $launchDemo -Arguments @('-DryRun')
    Assert-True -Condition ($bundleRun.Exit -eq 0) `
        -Message "a bundle with a checksum file plans its install (got $($bundleRun.Exit))"
    Assert-NotMatches -Text $bundleRun.Text -Pattern 'SkipChecksum' `
        -Message 'a release bundle is installed with the checksum check intact'
    Assert-NotMatches -Text $bundleRun.Text -Pattern 'source checkout' `
        -Message 'a release bundle is not called a source checkout'
    Assert-Contains -Text $bundleRun.Text -Needle 'install.ps1 -DryRun' `
        -Message 'the bundle path plans the plain install.ps1 -DryRun'

    # 3. Neither: a directory that is not a bundle and not a checkout fails
    # closed, at the install step and before anything is started. `src\atlas_core`
    # is the marker that makes this one stop being a checkout.
    Remove-Item -LiteralPath $launchSums
    Remove-Item -LiteralPath (Join-Path $launchBundle 'src\atlas_core') -Recurse -Force
    $neitherRun = Invoke-Script -Path $launchDemo -Arguments @('-DryRun')
    Assert-True -Condition ($neitherRun.Exit -ne 0) `
        -Message "a directory that is neither a bundle nor a checkout is refused (got $($neitherRun.Exit))"
    Assert-Contains -Text $neitherRun.Text -Needle 'there is no SHA256SUMS.txt beside this script.' `
        -Message 'the refusal names the missing checksum file'
    Assert-Contains -Text $neitherRun.Text -Needle 'Download install.ps1 and SHA256SUMS.txt from the same release' `
        -Message 'the refusal says where a bundle comes from'
    Assert-Contains -Text $neitherRun.Text -Needle 'run .\start-demo.ps1 from the repository root' `
        -Message 'the refusal names the clone way out'
    Assert-NotMatches -Text $neitherRun.Text -Pattern 'SkipChecksum' `
        -Message 'the refused run never passes -SkipChecksum'
    Assert-NotMatches -Text $neitherRun.Text -Pattern 'dry run complete|the demo is up' `
        -Message 'the refused run is refused before the plan'
} finally {
    if (Test-Path -LiteralPath $launchSandbox) { Remove-Item -LiteralPath $launchSandbox -Recurse -Force }
}

# The installer's own rule is untouched: it is what makes the branch above
# narrow. A bundle whose bytes do not match is still refused by the installer,
# and the launcher only ever adds the switch where the file is absent entirely.
Assert-Contains -Text $installRaw -Needle 'there is no SHA256SUMS.txt beside this installer.' `
    -Message 'install.ps1 still refuses an absent checksum file of its own accord'
Assert-Contains -Text $installRaw -Needle 'install.ps1 does not match the SHA256SUMS.txt beside it.' `
    -Message 'install.ps1 still refuses a digest that does not match'
$listeningAfterLaunch = Get-ListeningPorts -Ports $demoPorts
Assert-True -Condition (($listeningAfterLaunch -join ',') -eq ($listeningBefore -join ',')) `
    -Message "no checksum-branch run started a listener (before: $($listeningBefore -join ','); after: $($listeningAfterLaunch -join ','))"

# --- summary -----------------------------------------------------------------

Write-Host ''
if ($script:Failed -gt 0) {
    Write-Host "$($script:Failed) check(s) failed, $($script:Passed) passed:" -ForegroundColor Red
    foreach ($failure in $script:Failures) { Write-Host "    $failure" -ForegroundColor Red }
    exit 1
}
Write-Host "all $($script:Passed) checks passed" -ForegroundColor Green
exit 0
