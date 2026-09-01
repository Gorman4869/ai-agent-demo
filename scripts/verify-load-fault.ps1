[CmdletBinding()]
param(
    [ValidatePattern('^ai-agent-demo-m13-[a-z0-9-]+$')]
    [string]$ProjectName = (
        "ai-agent-demo-m13-load-$PID-" +
        [Guid]::NewGuid().ToString('N').Substring(0, 8)
    ),

    [ValidateRange(1024, 65535)]
    [int]$FrontendPort = 15174,

    [ValidateRange(1024, 65535)]
    [int]$BackendPort = 18001,

    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 55435,

    [ValidateRange(1, 100)]
    [int]$Runs = 16,

    [ValidateRange(1, 16)]
    [int]$Concurrency = 4
)

$ErrorActionPreference = 'Stop'
$deploymentVerifier = Join-Path $PSScriptRoot 'verify-deployment.ps1'
if (-not (Test-Path -LiteralPath $deploymentVerifier -PathType Leaf)) {
    throw 'deployment verifier is unavailable'
}
if ($Concurrency -gt $Runs) {
    throw 'Concurrency must not exceed Runs'
}

& $deploymentVerifier `
    -ProjectName $ProjectName `
    -FrontendPort $FrontendPort `
    -BackendPort $BackendPort `
    -PostgresPort $PostgresPort `
    -LoadFault `
    -SkipDatabaseRegression `
    -LoadFaultRuns $Runs `
    -LoadFaultConcurrency $Concurrency
if ($LASTEXITCODE -ne 0) {
    throw 'M13-T6 deployment load/fault verification failed'
}
