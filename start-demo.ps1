#Requires -Version 5.1
<#
.SYNOPSIS
    Starts the Atlas-HQ local demo: PostgreSQL, the web API, and the console.

.DESCRIPTION
    Everything this script binds is bound to 127.0.0.1. It starts only
    `docker compose up -d postgres`, the API on port 8000 and the Vite dev
    server on port 5175, and it stops exactly the processes it started however
    the run ends: normally, on Ctrl-C, or through a failure while a child is
    starting or while readiness is being waited for. It never runs
    `docker compose down`, never removes a volume, never runs operator-init
    unless you ask for it by name, and never stops a process it did not start.

    The development login and the database URL go into the child processes'
    environment only. This script never touches its own environment, so none of
    it reaches your PowerShell session or a shell you open later (contract
    section 40.3).

    It is a local development convenience, not a deployment path, and there is
    no flag that points it at a remote database.

    It runs install.ps1 the way the directory it is sitting in is built. A
    release bundle ships SHA256SUMS.txt beside the two scripts, so the install
    verifies itself there. A repository checkout has no release asset to check
    against, so the launcher passes -SkipChecksum itself and says so. A
    directory that is neither is refused rather than installed.

.PARAMETER InitializeOperator
    Run `atlas-hq operator-init` for the fixed local organization and principal
    before the servers start. Without this flag the command is printed and
    nothing is written: the console's development login answers 503 until an
    operator principal exists, so the first run needs it.

.PARAMETER OpenBrowser
    Open http://127.0.0.1:5175 once both servers are accepting connections.

.PARAMETER DryRun
    Print every command, every log file, and every environment variable name
    this script would use, and change nothing at all.

.PARAMETER SkipInstall
    Do not run install.ps1 first. Use it when the install is already done and
    you do not want to pay for the check.

.PARAMETER LogRoot
    Directory for the captured output of each child process. Defaults to
    `logs` under this script's directory.

.PARAMETER DatabaseUrl
    Use this PostgreSQL URL instead of deriving one. It still has to point at
    loopback: this script has no remote-database flag, by design. It also has to
    carry no query string or fragment, because the driver's connect-args live
    there and they override the authority - see the refusal below.

.EXAMPLE
    .\start-demo.ps1 -DryRun
    Prints the whole plan without starting anything.

.EXAMPLE
    .\start-demo.ps1 -InitializeOperator -OpenBrowser
    The documented first run.

.EXAMPLE
    .\start-demo.ps1 -SkipInstall
    Restart the demo against an existing install and an already-initialized
    operator.

.NOTES
    Contract section 40.3. A child process's output is captured and written to
    LogRoot when it exits, and straight to this console when it dies, which is
    the case that matters.

    Contract section 40.3 again, for the guarantee. Everything from the first
    child to the last line of the script sits inside one `try`, so
    Stop-TrackedChildren runs on every exit path. It is idempotent and it never
    throws: a process it cannot reap is reported rather than raised, because a
    throw from a `finally` would hide the real error and skip the processes
    after it.

    Contract section 40.4. The -SkipChecksum this script passes from a source
    checkout is the installer's own switch and the installer's own rule: the
    check still runs and still fails a released bundle whose bytes do not
    match, because this script only ever adds the switch where no
    SHA256SUMS.txt exists at all.
#>
[CmdletBinding()]
param(
    [switch]$InitializeOperator,
    [switch]$OpenBrowser,
    [switch]$DryRun,
    [switch]$SkipInstall,
    [string]$LogRoot = 'logs',
    [string]$DatabaseUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- pinned local topology ---------------------------------------------------

$script:ApiHost = '127.0.0.1'
$script:ApiPort = 8000
$script:WebHost = '127.0.0.1'
$script:WebPort = 5175
$script:DatabasePort = 5433
$script:ConsoleUrl = "http://$($script:WebHost):$($script:WebPort)"

# The organization and principal the console's development login acts as. They
# are constants, not parameters: a demo run that can be pointed at another
# organization is a demo run that can write into somebody else's data.
$script:OperatorPrincipal = 'atlas.local.operator'
$script:OperatorOrganization = 'atlas.local.demo'
$script:OperatorOrganizationName = 'Atlas local demo'

# Named one by one. Nothing is granted implicitly, and this is exactly what
# the console needs: manage authorization, render a report, read a self report.
$script:OperatorGrants = @('authorization.manage', 'report.render', 'self.monthly.report.view')

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

function Stop-Demo {
    param(
        [Parameter(Mandatory)][string]$Message,
        [string[]]$Details = @()
    )
    Write-Host ''
    Write-Host "start-demo.ps1 cannot continue: $Message" -ForegroundColor Red
    foreach ($detail in $Details) { Write-Host "    $detail" -ForegroundColor Red }
    Write-Host ''
    throw $Message
}

# --- small helpers -----------------------------------------------------------

function Format-Command {
    <# One printable command line, used for every plan line, so the printed
       plan is the real plan. #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $parts = @("'$FilePath'")
    foreach ($argument in $Arguments) {
        if ($argument -match '[\s\[\]]') { $parts += "'$argument'" } else { $parts += $argument }
    }
    return ($parts -join ' ')
}

function Get-PropertyOrNull {
    <# StrictMode treats a missing property on an object as an error, and
       ConvertFrom-Json output is full of properties that are sometimes absent.
       This is the one accessor everything JSON goes through. #>
    param(
        [Parameter(Mandatory)][AllowNull()]$Object,
        [Parameter(Mandatory)][string]$Name
    )
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Resolve-Tool {
    param([Parameter(Mandatory)][string[]]$Names)
    foreach ($name in $Names) {
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command) { return $command.Source }
    }
    return $null
}

function Get-PortOwner {
    <# The process listening on a port, or $null. Never stopped: it is only
       named, so the operator can free it themselves. #>
    param([Parameter(Mandatory)][int]$Port)
    try {
        $connection = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) |
            Select-Object -First 1
        if ($null -eq $connection) { return $null }
        return (Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue)
    } catch {
        return $null
    }
}

function Test-TcpReachable {
    <# A real connect attempt: works on every Windows edition and needs no
       NetTCPIP module. #>
    param(
        [Parameter(Mandatory)][string]$TargetHost,
        [Parameter(Mandatory)][int]$Port,
        [int]$TimeoutMilliseconds = 500
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-ForPort {
    param(
        [Parameter(Mandatory)][string]$TargetHost,
        [Parameter(Mandatory)][int]$Port,
        [int]$TimeoutSeconds = 60,
        [scriptblock]$Abort
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpReachable -TargetHost $TargetHost -Port $Port) { return $true }
        if ($Abort -and -not (& $Abort)) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-LoopbackHost {
    <#
        Whether a database host is this machine, decided by parsing the host as
        an address rather than by matching its text.

        The rule is the one `atlas_web.http.is_loopback_host` applies to a bind
        address, and the list `tests/test_web_bind_guard.py` pins down: an IPv4
        or IPv6 address literal that parses and reports itself a loopback
        address, plus `localhost`, the one name that always means this machine.
        Everything else is refused.

        Text matching cannot do this. `^127\.` also accepted
        `127.0.0.1.example.com`, which is somebody else's host, and the shape is
        checked before the parse because .NET parses shorthands too - `127.1` is
        a name, and a name is not proof of anything.
    #>
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Candidate)
    $candidate = $Candidate.Trim()
    # `[::1]` is how a bracketed IPv6 literal appears in a URL's authority.
    if ($candidate.StartsWith('[') -and $candidate.EndsWith(']')) {
        $candidate = $candidate.Substring(1, $candidate.Length - 2)
    }
    if ($candidate -eq 'localhost') { return $true }
    $isAddressShape = ($candidate -match '^\d{1,3}(\.\d{1,3}){3}$') -or $candidate.Contains(':')
    if (-not $isAddressShape) { return $false }
    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($candidate, [ref]$address)) { return $false }
    return [System.Net.IPAddress]::IsLoopback($address)
}

function Test-SourceCheckout {
    <#
        Whether these scripts are running from a repository checkout rather
        than a release bundle. `pyproject.toml` and `web\package.json` are the
        layout the check above already proved; `src\atlas_core` is the package
        every installable part of Atlas-HQ comes from, and a directory without
        it is not a tree this installer was written for.

        One missing marker means "not a checkout", so the answer fails closed:
        this is only ever asked to widen something, never to narrow it.
    #>
    param([Parameter(Mandatory)][string]$Path)
    foreach ($relative in @('pyproject.toml', 'src\atlas_core', 'web\package.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $relative))) { return $false }
    }
    return $true
}

function Read-ComposeEnvironment {
    <# `docker compose config` normalises `environment` to a map; a `KEY=VALUE`
       list is accepted too, so a hand-edited compose file cannot break the
       demo. #>
    param([AllowNull()]$Environment)
    $values = @{}
    if ($null -eq $Environment) { return $values }
    if ($Environment -is [string]) { $Environment = @($Environment -split "`r?`n") }
    foreach ($entry in @($Environment)) {
        if ($entry -is [string]) {
            $separator = $entry.IndexOf('=')
            if ($separator -gt 0) { $values[$entry.Substring(0, $separator)] = $entry.Substring($separator + 1) }
        } else {
            foreach ($property in $entry.PSObject.Properties) { $values[$property.Name] = [string]$property.Value }
        }
    }
    return $values
}

# --- child process plumbing --------------------------------------------------

$script:Tracked = New-Object System.Collections.ArrayList
# Cleanup bookkeeping. `Stop-TrackedChildren` is called from a `finally`, so it
# has to be safe to call once or twice: these two say whether it has run.
$script:Stopped = $false
$script:StoppedResult = @()

function New-ChildStartInfo {
    <#
        Build a ProcessStartInfo whose environment is the parent environment
        minus every ATLAS_* variable, plus exactly the ones passed in. That is
        what "the development login exists only for the child process" means in
        practice: the four variables reach the API, the console and
        operator-init, and nothing else does, this script included.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [Parameter(Mandatory)][hashtable]$Environment
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = if ($WorkingDirectory) { $WorkingDirectory } else { $script:RepositoryRoot }
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $quoted = @()
    foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') { $quoted += '"' + ($argument -replace '"', '\"') + '"' } else { $quoted += $argument }
    }
    $startInfo.Arguments = $quoted -join ' '
    foreach ($key in @($startInfo.EnvironmentVariables.Keys)) {
        if ($key -like 'ATLAS_*') { $startInfo.EnvironmentVariables.Remove($key) }
    }
    foreach ($key in $Environment.Keys) { $startInfo.EnvironmentVariables[$key] = [string]$Environment[$key] }
    return $startInfo
}

function Start-TrackedChild {
    <#
        Start one long-running child, remember it by name, and begin draining
        both of its pipes. Draining through ReadToEndAsync is what keeps a
        chatty Vite process from filling a pipe buffer and blocking forever.
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [Parameter(Mandatory)][hashtable]$Environment
    )
    $startInfo = New-ChildStartInfo -FilePath $FilePath -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory -Environment $Environment
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $null = $process.Start()
    $entry = [pscustomobject]@{
        Name    = $Name
        Process = $process
        OutTask = $process.StandardOutput.ReadToEndAsync()
        ErrTask = $process.StandardError.ReadToEndAsync()
        OutPath = (Join-Path $script:LogRootPath "$Name.out.log")
        ErrPath = (Join-Path $script:LogRootPath "$Name.err.log")
    }
    $null = $script:Tracked.Add($entry)
    return $entry
}

function Save-ContentToFile {
    <# One place that writes a log file, so every log is UTF-8 and inside
       LogRoot and nothing else is. #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Text
    )
    Set-Content -LiteralPath $Path -Value $Text -Encoding UTF8
}

function Get-TrackedText {
    param(
        [Parameter(Mandatory)]$Entry,
        [switch]$PreferError
    )
    $text = ''
    try { $text = [string]$Entry.OutTask.Result } catch { $text = '' }
    if ($PreferError -or -not $text.Trim()) {
        $errorText = ''
        try { $errorText = [string]$Entry.ErrTask.Result } catch { $errorText = '' }
        if ($PreferError -and $errorText.Trim()) { return $errorText }
        if (-not $text.Trim()) { $text = $errorText }
    }
    return $text
}

function Save-TrackedOutput {
    <# Flush one child's captured output to its log files. #>
    param([Parameter(Mandatory)]$Entry)
    if ($null -ne $Entry.Process) { $null = $Entry.Process.WaitForExit(2000) }
    Save-ContentToFile -Path $Entry.OutPath -Text (Get-TrackedText -Entry $Entry)
    Save-ContentToFile -Path $Entry.ErrPath -Text (Get-TrackedText -Entry $Entry -PreferError)
}

function Show-TrackedTail {
    param(
        [Parameter(Mandatory)]$Entry,
        [int]$Lines = 20
    )
    $text = Get-TrackedText -Entry $Entry
    if (-not $text.Trim()) { return }
    Write-Host "$($Entry.Name) captured output:" -ForegroundColor Red
    foreach ($line in @($text -split "`r?`n" | Select-Object -Last $Lines)) {
        if ($line.Trim()) { Write-Host "    $line" -ForegroundColor Red }
    }
}

function Stop-TrackedChildren {
    <#
        Stop only the processes this script started, and their own children
        (Vite spawns esbuild). taskkill /T is scoped to the PIDs recorded above,
        so an unrelated process holding 8000 is never a target.

        This runs from a `finally`, which means it must never throw: an error
        here would replace whatever the script was already reporting, and an
        unhandled entry would abandon the entries after it and leave real
        processes running. So every step is guarded, one unreadable process
        cannot stop the rest being reaped, and the whole function is idempotent
        - a second call reports the first call's result and touches nothing.
    #>
    if ($script:Stopped) { return @($script:StoppedResult) }
    $script:Stopped = $true

    $stopped = @()
    try {
        $taskkill = Resolve-Tool -Names @('taskkill.exe', 'taskkill')
        foreach ($entry in @($script:Tracked)) {
            $label = $entry.Name
            try {
                $process = $entry.Process
                if ($null -eq $process) { continue }
                if ($process.HasExited) {
                    $stopped += "$label (pid $($process.Id), already exited)"
                } else {
                    if ($null -ne $taskkill) {
                        & $taskkill /PID $process.Id /T /F 2>&1 | Out-Null
                    } else {
                        $process.Kill()
                    }
                    $null = $process.WaitForExit(5000)
                    $stopped += "$label (pid $($process.Id))"
                }
            } catch {
                # Reported, never raised: the remaining children still get reaped.
                $stopped += "$label (not stopped: $($_.Exception.Message))"
            }
            try { Save-TrackedOutput -Entry $entry } catch { continue }
        }
    } catch {
        # The last backstop. This function is called from a `finally`, and a
        # throw from there replaces the error the operator actually needs to
        # read with a cleanup error.
        $stopped += "cleanup could not finish: $($_.Exception.Message)"
    }
    $script:StoppedResult = $stopped
    return $stopped
}

# --- layout ------------------------------------------------------------------

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:RepositoryRoot = $scriptDirectory
$script:LogRootPath = if ([System.IO.Path]::IsPathRooted($LogRoot)) { $LogRoot } else { Join-Path $scriptDirectory $LogRoot }

$venvPython = Join-Path $scriptDirectory '.venv\Scripts\python.exe'
$webPath = Join-Path $scriptDirectory 'web'
$composeFile = Join-Path $scriptDirectory 'docker-compose.yml'
$installScript = Join-Path $scriptDirectory 'install.ps1'

if ($DryRun) { Write-Step 'dry run: nothing below this line changes anything' }

Write-Step 'checking the repository layout'
$missing = @()
foreach ($relative in @('pyproject.toml', 'src\atlas_web', 'web\package.json', 'docker-compose.yml')) {
    if (-not (Test-Path -LiteralPath (Join-Path $scriptDirectory $relative))) { $missing += $relative }
}
if ($missing.Count -gt 0) {
    Stop-Demo 'this does not look like an Atlas-HQ checkout.' @(
        ("missing under '$scriptDirectory': " + ($missing -join ', ')),
        'Run start-demo.ps1 from the repository root.'
    )
}
Write-Ok "repository at '$scriptDirectory'"

# --- install -----------------------------------------------------------------

if ($SkipInstall) {
    Write-Step 'skipping the install (-SkipInstall)'
} else {
    Write-Step 'installing'
    if (-not (Test-Path -LiteralPath $installScript)) {
        Stop-Demo 'install.ps1 is missing next to this script.' @(
            'Re-run without -SkipInstall from a complete bundle.'
        )
    }
    # install.ps1 runs in a child PowerShell rather than being dot-sourced, so
    # the install cannot change this script's variables, and so its output is
    # the install's own output. The child inherits the same execution policy
    # the operator already used to launch this script; neither script ever
    # changes that policy (contract 40.2).
    #
    # contract.md 40.4, decided here rather than left to the install: the release
    # bundle ships SHA256SUMS.txt beside the two scripts, so a bundle installs
    # with the check and nothing added; a checkout has no release asset to check
    # against, so -SkipChecksum is passed, out loud. Neither is guessed at from
    # the file names alone - install.ps1 still refuses a wrong digest either way,
    # so what this decides is only ever whether the proof is offered, never
    # whether it is believed.
    $checksumFile = Join-Path $scriptDirectory 'SHA256SUMS.txt'
    $installArguments = @('-NoProfile', '-File', $installScript)
    if (Test-Path -LiteralPath $checksumFile) {
        Write-Ok "checksum file: $checksumFile"
    } elseif (Test-SourceCheckout -Path $scriptDirectory) {
        $installArguments += '-SkipChecksum'
        Write-Note 'source checkout: checksum verification skipped (-SkipChecksum)'
    } else {
        Stop-Demo 'there is no SHA256SUMS.txt beside this script.' @(
            "'$checksumFile' was not found next to install.ps1.",
            'Download install.ps1 and SHA256SUMS.txt from the same release, and keep them in the same directory.',
            'From a repository clone, run .\start-demo.ps1 from the repository root.'
        )
    }
    if ($DryRun) { $installArguments += '-DryRun' }
    Write-Detail (Format-Command 'powershell.exe' $installArguments)
    if (-not $DryRun) {
        & powershell.exe @installArguments
        $installExit = $LASTEXITCODE
        if ($installExit -ne 0) {
            Stop-Demo "install.ps1 failed with exit code $installExit." @(
                'Fix what it reported and run it on its own:  .\install.ps1'
            )
        }
    }
}

if (-not $DryRun -and -not (Test-Path -LiteralPath $venvPython)) {
    Stop-Demo "no virtual environment at '$venvPython'." @(
        'Run .\install.ps1 first, or re-run this script without -SkipInstall.'
    )
}
Write-Ok "python: $venvPython"

# --- docker ------------------------------------------------------------------

Write-Step 'checking Docker Desktop'
$dockerPath = Resolve-Tool -Names @('docker')
if ($null -eq $dockerPath) {
    if ($DryRun) {
        Write-Note 'docker not found on PATH; the plan below assumes it is installed'
        $dockerPath = 'docker'
    } else {
        Stop-Demo 'Docker Desktop is not on PATH.' @(
            'Install Docker Desktop (Compose v2 ships with it) and re-run.'
        )
    }
} else {
    $dockerEngineReady = $false
    $composeReady = $false
    if ($DryRun) {
        Write-Detail (Format-Command $dockerPath @('version', '--format', '{{.Server.Version}}'))
        Write-Detail (Format-Command $dockerPath @('compose', 'version', '--short'))
    } else {
        & $dockerPath version --format '{{.Server.Version}}' 2>$null | Out-Null
        $dockerEngineReady = ($LASTEXITCODE -eq 0)
        & $dockerPath compose version --short 2>$null | Out-Null
        $composeReady = ($LASTEXITCODE -eq 0)
    }
    if (-not $DryRun -and -not $dockerEngineReady) {
        Stop-Demo 'Docker Desktop is not answering.' @(
            'Start Docker Desktop, wait for the whale to settle, and re-run.'
        )
    }
    if (-not $DryRun -and -not $composeReady) {
        Stop-Demo '`docker compose` (Compose v2) is not available.' @(
            'Update Docker Desktop; the v1 `docker-compose` shim is not supported.'
        )
    }
    if (-not $DryRun) { Write-Ok 'docker engine and Compose v2' }
}

# --- the database ------------------------------------------------------------

Write-Step 'resolving the local database'
$databaseUrlSource = ''
$databaseUrlValue = $null
if ($DatabaseUrl) {
    $databaseUrlValue = $DatabaseUrl
    $databaseUrlSource = '-DatabaseUrl'
} elseif ($env:ATLAS_DATABASE_URL) {
    $databaseUrlValue = $env:ATLAS_DATABASE_URL
    $databaseUrlSource = 'ATLAS_DATABASE_URL'
} elseif ($DryRun) {
    $databaseUrlSource = 'docker compose config; not read in a dry run'
    Write-Detail (Format-Command $dockerPath @('compose', '--file', $composeFile, 'config', '--format', 'json'))
    Write-Note 'no ATLAS_DATABASE_URL set, so the URL would be read from docker compose config'
} else {
    # Read the credentials out of the compose file rather than hard-coding them
    # here: a password written into a script is a password in a git history.
    # `compose` is the subcommand; `--file` is one of its flags, not a
    # top-level `docker` flag, so the two have to travel together.
    $composeConfigCommand = @('compose', '--file', $composeFile, 'config', '--format', 'json')
    Write-Detail (Format-Command $dockerPath $composeConfigCommand)
    $composeConfig = & $dockerPath @composeConfigCommand 2>$null
    $composeExit = $LASTEXITCODE
    if ($composeExit -ne 0 -or -not $composeConfig) {
        Stop-Demo 'could not read the database configuration from docker compose config.' @(
            'Set ATLAS_DATABASE_URL in this session, or pass -DatabaseUrl <url>.'
        )
    }
    $config = ($composeConfig -join "`n") | ConvertFrom-Json
    $service = Get-PropertyOrNull (Get-PropertyOrNull $config 'services') 'postgres'
    $composeEnvironment = Read-ComposeEnvironment (Get-PropertyOrNull $service 'environment')
    $composeUser = $composeEnvironment['POSTGRES_USER']
    $composePassword = $composeEnvironment['POSTGRES_PASSWORD']
    $composeDatabase = $composeEnvironment['POSTGRES_DB']
    if (-not $composeUser -or -not $composePassword -or -not $composeDatabase) {
        Stop-Demo 'docker compose config did not report POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB.' @(
            'Set ATLAS_DATABASE_URL in this session, or pass -DatabaseUrl <url>.'
        )
    }
    $publishedPort = $script:DatabasePort
    $portMappings = Get-PropertyOrNull $service 'ports'
    if ($null -ne $portMappings) {
        foreach ($mapping in @($portMappings)) {
            if ([string](Get-PropertyOrNull $mapping 'target') -eq '5432') {
                $publishedPort = [int](Get-PropertyOrNull $mapping 'published')
                break
            }
        }
    }
    $databaseUrlValue = 'postgresql+psycopg://{0}:{1}@127.0.0.1:{2}/{3}' -f `
        ([System.Uri]::EscapeDataString($composeUser)),
        ([System.Uri]::EscapeDataString($composePassword)),
        $publishedPort,
        ([System.Uri]::EscapeDataString($composeDatabase))
    $databaseUrlSource = 'docker compose config'
}

$databaseDescription = '127.0.0.1'
if ($null -ne $databaseUrlValue) {
    if ($databaseUrlValue -notmatch '^postgresql\+psycopg://') {
        Stop-Demo 'the database URL must be a postgresql+psycopg:// URL.' @(
            'PostgreSQL with the psycopg driver is the only supported engine; there is no fallback.'
        )
    }
    $parsedDatabaseUrl = $null
    if (-not [System.Uri]::TryCreate($databaseUrlValue, [System.UriKind]::Absolute, [ref]$parsedDatabaseUrl)) {
        Stop-Demo 'the database URL is not a valid URL.'
    }
    # Everything after the path is a connect-arg to SQLAlchemy and psycopg, and a
    # connect-arg wins over the authority: `?host=`, `?port=`, `?dbname=`, `?user=`,
    # `?password=`, `?service=` and `?options=` each redirect the connection, so
    # `...@127.0.0.1:5433/atlas_hq?host=evil.example.com` is read below as a
    # loopback URL and connects to evil.example.com. A `#` does not hide one
    # either: .NET calls what follows it a fragment, but the driver's own parse
    # reads the `?` after it as a query all the same, and
    # `...atlas_hq#f?host=evil.example.com` gets the same treatment. Nothing in a
    # demo DSN needs a query or a fragment, and a rule that had to enumerate the
    # keys would be one release away from the next one, so both are refused
    # outright - before the host is approved, because the host is not then the
    # host that would be connected to.
    if ($parsedDatabaseUrl.Query -or $parsedDatabaseUrl.Fragment) {
        Stop-Demo 'the database URL must not carry a query string or a fragment.' @(
            'Everything after the path is a connect-arg to SQLAlchemy and psycopg, and those',
            'override the URL: ?host=, ?port=, ?dbname=, ?user=, ?password=, ?service= and',
            '?options= can all point the connection somewhere this launcher never checked,',
            'and a # in front of the ? does not hide it. Put the values in the URL itself,',
            'e.g.  postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq'
        )
    }
    if (-not (Test-LoopbackHost $parsedDatabaseUrl.Host)) {
        Stop-Demo "the database host is $($parsedDatabaseUrl.Host), which is not loopback." @(
            'This launcher is a local development convenience and has no remote-database flag',
            '(contract 40.3).'
        )
    }
    # Only the part of the URL that is not a credential is ever printed.
    $databaseDescription = "$($parsedDatabaseUrl.Host):$($parsedDatabaseUrl.Port)"
}
Write-Ok "database $databaseDescription (from $databaseUrlSource)"

$childEnvironment = @{
    'ATLAS_DATABASE_URL'           = $databaseUrlValue
    'ATLAS_DATABASE_SCHEMA'        = 'atlas'
    'ATLAS_WEB_DEV_LOGIN'          = '1'
    'ATLAS_WEB_OPERATOR_PRINCIPAL' = $script:OperatorPrincipal
}

# --- ports -------------------------------------------------------------------

Write-Step 'checking the loopback ports'
foreach ($port in @($script:ApiPort, $script:WebPort)) {
    $owner = Get-PortOwner -Port $port
    if ($null -ne $owner -or (Test-TcpReachable -TargetHost '127.0.0.1' -Port $port)) {
        $named = if ($null -ne $owner) { "$($owner.ProcessName) (pid $($owner.Id))" } else { 'another process' }
        Stop-Demo "port $port is already in use by $named." @(
            'Free that port and re-run. This script stops only what it starts, so it will not',
            'stop the other process for you.'
        )
    }
    Write-Ok "127.0.0.1:$port is free"
}
if (Test-TcpReachable -TargetHost '127.0.0.1' -Port $script:DatabasePort) {
    Write-Note "port $($script:DatabasePort) is already answering; `docker compose up` will reuse it"
} else {
    Write-Ok "127.0.0.1:$($script:DatabasePort) is free"
}

# --- PostgreSQL --------------------------------------------------------------

Write-Step 'starting PostgreSQL'
$composeUp = @('compose', '--file', $composeFile, 'up', '--detach', 'postgres')
Write-Detail (Format-Command $dockerPath $composeUp)
if ($DryRun) {
    Write-Note 'dry run: PostgreSQL is not started and no volume is touched'
} else {
    # Only the postgres service. `docker compose down`, and `down -v` in
    # particular, never appear in this script: the local volume holds the demo
    # data, and removing it is the operator's decision.
    & $dockerPath @composeUp
    $composeExit = $LASTEXITCODE
    if ($composeExit -ne 0) {
        Stop-Demo "`docker compose up --detach postgres' failed with exit code $composeExit." @(
            'docker compose printed the reason above. This script never removes volumes, so the',
            'contents of atlas_postgres_data are still there.'
        )
    }
    Write-Ok 'postgres container started'
    if (-not (Wait-ForPort -TargetHost '127.0.0.1' -Port $script:DatabasePort -TimeoutSeconds 60)) {
        Stop-Demo "PostgreSQL did not start listening on 127.0.0.1:$($script:DatabasePort) within 60 seconds." @(
            'Check the container:  docker compose ps'
        )
    }
    Write-Ok "PostgreSQL is answering on 127.0.0.1:$($script:DatabasePort)"
}

# --- operator-init -----------------------------------------------------------

$operatorArguments = @(
    '-m', 'atlas_hq.cli', 'operator-init',
    '--principal', $script:OperatorPrincipal,
    '--organization', $script:OperatorOrganization,
    '--create-organization',
    '--organization-name', $script:OperatorOrganizationName
)
foreach ($grant in $script:OperatorGrants) { $operatorArguments += @('--grant', $grant) }

Write-Step 'operator principal'
if (-not $InitializeOperator) {
    Write-Note '-InitializeOperator was not passed, so nothing was written to the database.'
    Write-Note 'The console development login answers 503 until the principal exists. Run:'
    Write-Host ''
    Write-Host ('    ' + (Format-Command $venvPython $operatorArguments)) -ForegroundColor White
    Write-Host ''
} elseif ($DryRun) {
    Write-Detail (Format-Command $venvPython $operatorArguments)
    Write-Note 'dry run: operator-init is printed, not run'
} else {
    Write-Detail (Format-Command $venvPython $operatorArguments)
    New-Item -ItemType Directory -Path $script:LogRootPath -Force | Out-Null
    $operatorLog = Join-Path $script:LogRootPath 'operator-init.log'
    $operatorStartInfo = New-ChildStartInfo -FilePath $venvPython -Arguments $operatorArguments -Environment $childEnvironment
    $operator = New-Object System.Diagnostics.Process
    $operator.StartInfo = $operatorStartInfo
    $null = $operator.Start()
    $operatorOutTask = $operator.StandardOutput.ReadToEndAsync()
    $operatorErrTask = $operator.StandardError.ReadToEndAsync()
    if (-not $operator.WaitForExit(120000)) {
        # Reading the tasks below blocks until the pipes close, so a wedged
        # child has to be ended here rather than waited on.
        $operator.Kill()
        $null = $operator.WaitForExit(5000)
        Save-ContentToFile -Path $operatorLog -Text 'operator-init did not finish within 120 seconds and was stopped.'
        Stop-Demo 'operator-init did not finish within 120 seconds.' @(
            "its output so far is in '$operatorLog'",
            'The usual cause is an unreachable database. Check:  docker compose ps'
        )
    }
    $operatorOut = ''
    $operatorErr = ''
    try { $operatorOut = [string]$operatorOutTask.Result } catch { $operatorOut = '' }
    try { $operatorErr = [string]$operatorErrTask.Result } catch { $operatorErr = '' }
    Save-ContentToFile -Path $operatorLog -Text ($operatorOut + "`n" + $operatorErr)
    if ($operatorOut.Trim()) { Write-Host $operatorOut.TrimEnd() }
    if ($operatorErr.Trim()) { Write-Host $operatorErr.TrimEnd() -ForegroundColor Red }
    if ($operator.ExitCode -ne 0) {
        Stop-Demo "operator-init failed with exit code $($operator.ExitCode)." @(
            "its full output is in '$operatorLog'",
            'The refusal above is the reason. Fix it and re-run with -InitializeOperator.'
        )
    }
    Write-Ok "operator $($script:OperatorPrincipal) is active in $($script:OperatorOrganization)"
}

# --- the plan ----------------------------------------------------------------

if ($DryRun) {
    Write-Step 'dry run: no process is started'
    Write-Step 'the plan'
    Write-Detail (Format-Command $venvPython @('-m', 'atlas_web', '--host', $script:ApiHost, '--port', "$($script:ApiPort)"))
    $npmPlanPath = Resolve-Tool -Names @('npm.cmd', 'npm.exe', 'npm')
    if ($null -ne $npmPlanPath) {
        Write-Detail ((Format-Command $npmPlanPath @('run', 'dev', '--', '--host', $script:WebHost)) +
            "   # working directory: $webPath")
    } else {
        Write-Detail 'npm was not found, so the console cannot be started'
    }
    Write-Detail 'child environment (these four names, and no others):'
    foreach ($key in @($childEnvironment.Keys | Sort-Object)) { Write-Detail "  $key" }
    Write-Detail "log directory: $script:LogRootPath"
    Write-Detail "browser would open: $script:ConsoleUrl"
    Write-Host ''
    Write-Step 'dry run complete: nothing was started, nothing was written'
    Write-Host ''
    return
}

# --- servers -----------------------------------------------------------------

# contract.md 40.3: the tracked set is stopped on exit. One `try` wraps every
# step from the first child to the last line of this script, so a failure while
# the API is starting, while Vite is starting, or while readiness is being
# waited for still reaches the same `finally` and still reaps whatever did
# start. Nothing after a child is started can skip cleanup.
try {
    New-Item -ItemType Directory -Path $script:LogRootPath -Force | Out-Null
    $npmPath = Resolve-Tool -Names @('npm.cmd', 'npm.exe', 'npm')
    if ($null -eq $npmPath) {
        Stop-Demo 'npm was not found, so the web console cannot be started.' @(
            'Re-run .\install.ps1 without -SkipWeb, or install Node.js 20.19 or newer.'
        )
    }

    Write-Step 'starting the API'
    $api = Start-TrackedChild -Name 'api' -FilePath $venvPython `
        -Arguments @('-m', 'atlas_web', '--host', $script:ApiHost, '--port', "$($script:ApiPort)") `
        -WorkingDirectory $scriptDirectory -Environment $childEnvironment
    Write-Ok "api pid $($api.Process.Id), output -> $($api.OutPath)"

    Write-Step 'starting the web console'
    $web = Start-TrackedChild -Name 'web' -FilePath $npmPath `
        -Arguments @('run', 'dev', '--', '--host', $script:WebHost) `
        -WorkingDirectory $webPath -Environment $childEnvironment
    Write-Ok "console pid $($web.Process.Id), output -> $($web.OutPath)"

    $stillStarting = { -not ($api.Process.HasExited -and $web.Process.HasExited) }

    Write-Step 'waiting for the servers'
    $apiReady = Wait-ForPort -TargetHost $script:ApiHost -Port $script:ApiPort -TimeoutSeconds 60 -Abort $stillStarting
    $webReady = Wait-ForPort -TargetHost $script:WebHost -Port $script:WebPort -TimeoutSeconds 60 -Abort $stillStarting
    foreach ($entry in @($api, $web)) {
        if ($entry.Process.HasExited) {
            Save-TrackedOutput -Entry $entry
            Write-Host ''
            Write-Host "$($entry.Name) exited with code $($entry.Process.ExitCode)." -ForegroundColor Red
            Show-TrackedTail -Entry $entry
            Write-Host ''
        }
    }
    if (-not $apiReady) {
        Stop-Demo "the API never started listening on $($script:ApiHost):$($script:ApiPort)." @(
            "its captured output is in '$($api.OutPath)' and '$($api.ErrPath)'"
        )
    }
    if (-not $webReady) {
        Stop-Demo "the console never started listening on $($script:WebHost):$($script:WebPort)." @(
            "its captured output is in '$($web.OutPath)' and '$($web.ErrPath)'"
        )
    }

    Write-Host ''
    Write-Step 'the demo is up'
    Write-Ok "console:  $script:ConsoleUrl"
    Write-Ok "api:      http://$($script:ApiHost):$($script:ApiPort)"
    Write-Ok "database: $databaseDescription, schema atlas"
    Write-Detail "logs: $script:LogRootPath"
    Write-Detail 'Ctrl-C stops the two processes above and nothing else.'

    if ($OpenBrowser) {
        Start-Process $script:ConsoleUrl
        Write-Ok "opened $script:ConsoleUrl"
    }

    while ($true) {
        Start-Sleep -Milliseconds 500
        $dead = $null
        foreach ($entry in @($script:Tracked)) {
            if ($entry.Process.HasExited) { $dead = $entry; break }
        }
        if ($null -eq $dead) { continue }
        Save-TrackedOutput -Entry $dead
        Write-Host ''
        Write-Host "$($dead.Name) exited with code $($dead.Process.ExitCode)." -ForegroundColor Red
        Show-TrackedTail -Entry $dead
        Write-Host ''
        break
    }
} finally {
    Write-Step 'stopping'
    foreach ($line in (Stop-TrackedChildren)) { Write-Ok "stopped $line" }
    Write-Ok 'PostgreSQL is still running. Stop it yourself with:  docker compose stop postgres'
    Write-Host ''
}
