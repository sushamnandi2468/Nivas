[CmdletBinding()]
param(
    [string]$TestPath = "backend\tests",
    [string]$DatabaseHost = $env:PGHOST,
    [string]$DatabaseUser = "",
    [string]$DatabaseName = "nivasopsdb",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^(test_[a-z0-9_]+|nivasops[a-z0-9_]*test[a-z0-9_]*)$")]
    [string]$TestDatabaseName,
    [string[]]$PytestArguments = @(),
    [int]$DatabasePort = 5432
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$resolvedTestPath = Join-Path $root $TestPath

if (-not (Test-Path $python)) {
    throw "Python environment not found. Run .\scripts\bootstrap-local.ps1 -SkipContainers first."
}

if (-not (Test-Path $resolvedTestPath)) {
    throw "Test path not found: $resolvedTestPath"
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

$testExitCode = 1
try {
    $env:PGHOST = $DatabaseHost
    $env:PGUSER = $DatabaseUser
    $env:PGPORT = $DatabasePort.ToString()
    $env:PGDATABASE = $DatabaseName
    $env:TEST_PGDATABASE = $TestDatabaseName
    $env:PGPASSWORD = $accessToken.Trim()
    $env:PGSSLMODE = "require"
    $env:PGCONNECT_TIMEOUT = "10"
    $env:DATABASE_CONN_MAX_AGE = "0"

    & $python -m pytest $resolvedTestPath @PytestArguments -q
    $testExitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:PGHOST,Env:PGUSER,Env:PGPORT,Env:PGDATABASE,Env:PGPASSWORD, `
        Env:TEST_PGDATABASE,Env:PGSSLMODE,Env:PGCONNECT_TIMEOUT,Env:DATABASE_CONN_MAX_AGE `
        -ErrorAction SilentlyContinue
    $accessToken = $null
}

if ($testExitCode -ne 0) {
    throw "Backend tests failed with exit code $testExitCode."
}