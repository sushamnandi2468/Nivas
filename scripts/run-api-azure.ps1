[CmdletBinding()]
param(
    [ValidateSet("runserver", "check", "makemigrations", "migrate", "showmigrations", "dev-session", "dev-lifecycle-fixture")]
    [string]$Command = "runserver",
    [string]$DatabaseHost = $env:PGHOST,
    [string]$DatabaseUser = "",
    [string]$DatabaseName = "nivasopsdb",
    [int]$DatabasePort = 5432,
    [ValidateRange(1, 65535)]
    [int]$RunserverPort = 8000,
    [string]$Phone = "+919876543210",
    [string]$SocietyCode = "NIVASOPS-DEV",
    [ValidateSet("FACILITY_MANAGER", "ESTATE_SUPERVISOR", "HELPDESK_OPERATOR")]
    [string]$Role = "FACILITY_MANAGER",
    [switch]$EnableDevSession,
    [string]$FixtureMarker = "browser-lifecycle",
    [switch]$EnableDevLifecycleFixture
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Python environment not found. Run .\scripts\bootstrap-local.ps1 -SkipContainers first."
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is not available. Install it, open a new terminal, and run 'az login'."
}

az account show --output none
if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI is not signed in. Run 'az login' and retry."
}

if ([string]::IsNullOrWhiteSpace($DatabaseUser)) {
    $DatabaseUser = az ad signed-in-user show --query userPrincipalName --output tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($DatabaseUser)) {
        throw "Could not determine the signed-in Entra user. Pass -DatabaseUser explicitly."
    }
    $DatabaseUser = $DatabaseUser.Trim()
}

$accessToken = az account get-access-token `
    --resource https://ossrdbms-aad.database.windows.net `
    --query accessToken `
    --output tsv

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($accessToken)) {
    throw "Could not acquire an Entra token for Azure Database for PostgreSQL."
}

try {
    $env:PGHOST = $DatabaseHost
    $env:PGUSER = $DatabaseUser
    $env:PGPORT = $DatabasePort.ToString()
    $env:PGDATABASE = $DatabaseName
    $env:PGPASSWORD = $accessToken.Trim()
    $env:PGSSLMODE = "require"
    $env:PGCONNECT_TIMEOUT = "10"
    $env:DATABASE_CONN_MAX_AGE = "0"

    $manage = Join-Path $root "backend\manage.py"
    if ($Command -eq "dev-session") {
        if (-not $EnableDevSession) {
            throw "Pass -EnableDevSession to explicitly allow development identity creation."
        }
        $env:DEBUG = "true"
        $env:ALLOW_DEV_SESSION_BOOTSTRAP = "true"
        & $python $manage dev_session --phone $Phone --society-code $SocietyCode --role $Role
    } elseif ($Command -eq "dev-lifecycle-fixture") {
        if (-not $EnableDevLifecycleFixture) {
            throw "Pass -EnableDevLifecycleFixture to explicitly allow development fixture creation."
        }
        $env:DEBUG = "true"
        $env:ALLOW_DEV_LIFECYCLE_FIXTURE = "true"
        & $python $manage dev_lifecycle_fixture --enable --society-code $SocietyCode --marker $FixtureMarker
    } elseif ($Command -eq "runserver") {
        & $python $manage runserver "127.0.0.1:$RunserverPort"
    } else {
        & $python $manage $Command
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Django command '$Command' failed with exit code $LASTEXITCODE."
    }
} finally {
    Remove-Item Env:PGHOST,Env:PGUSER,Env:PGPORT,Env:PGDATABASE,Env:PGPASSWORD, `
        Env:PGSSLMODE,Env:PGCONNECT_TIMEOUT,Env:DATABASE_CONN_MAX_AGE, `
        Env:DEBUG,Env:ALLOW_DEV_SESSION_BOOTSTRAP,Env:ALLOW_DEV_LIFECYCLE_FIXTURE `
        -ErrorAction SilentlyContinue
    $accessToken = $null
}