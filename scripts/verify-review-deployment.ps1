[CmdletBinding()]
param(
    [ValidatePattern('^ai-agent-demo-m14-[a-z0-9-]+$')]
    [string]$ProjectName = ("ai-agent-demo-m14-$PID-" + [Guid]::NewGuid().ToString('N').Substring(0, 8)),
    [ValidateRange(1024, 65535)][int]$FrontendPort = 15174,
    [ValidateRange(1024, 65535)][int]$BackendPort = 18082,
    [ValidateRange(1024, 65535)][int]$PostgresPort = 55435
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$composeArguments = @('compose', '--project-name', $ProjectName, '--file', (Join-Path $projectRoot 'deploy/compose.deployment.yaml'))
$ownedNames = @('AI_AGENT_DEPLOY_POSTGRES_PASSWORD_FILE', 'AI_AGENT_DEPLOY_POSTGRES_DSN_FILE',
    'AI_AGENT_REVIEW_DEMO_DSN_FILE', 'DEPLOY_POSTGRES_PORT', 'REVIEW_FRONTEND_PORT', 'REVIEW_BACKEND_PORT')
$previousEnvironment = @{}
$secretFiles = @()
$ownsResources = $false

function Invoke-DockerStep {
    param([string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'owned review deployment Docker step failed' }
}

function Assert-DatabaseScalar {
    param([string]$Query, [string]$Expected)
    $result = & docker @composeArguments exec --no-TTY postgres psql --username ai_agent `
        --dbname ai_agent_deployment --tuples-only --no-align --command $Query
    if ($LASTEXITCODE -ne 0 -or ($result | Out-String).Trim() -ne $Expected) {
        throw 'review deployment database assertion failed'
    }
}

try {
    foreach ($name in $ownedNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    if (@($FrontendPort, $BackendPort, $PostgresPort | Select-Object -Unique).Count -ne 3) {
        throw 'review deployment ports must be distinct'
    }
    $password = 'm14-' + [Guid]::NewGuid().ToString('N')
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $values = @{
        AI_AGENT_DEPLOY_POSTGRES_PASSWORD_FILE = $password
        AI_AGENT_DEPLOY_POSTGRES_DSN_FILE = "postgresql://ai_agent:$password@postgres:5432/ai_agent_deployment?sslmode=disable"
        AI_AGENT_REVIEW_DEMO_DSN_FILE = "postgresql://ai_agent:$password@127.0.0.1:$PostgresPort/ai_agent_deployment?sslmode=disable"
    }
    foreach ($name in $values.Keys) {
        $path = [System.IO.Path]::GetTempFileName()
        $secretFiles += $path
        [System.IO.File]::WriteAllText($path, $values[$name], $utf8)
        [Environment]::SetEnvironmentVariable($name, $path, 'Process')
    }
    [Environment]::SetEnvironmentVariable('DEPLOY_POSTGRES_PORT', $PostgresPort.ToString(), 'Process')
    [Environment]::SetEnvironmentVariable('REVIEW_FRONTEND_PORT', $FrontendPort.ToString(), 'Process')
    [Environment]::SetEnvironmentVariable('REVIEW_BACKEND_PORT', $BackendPort.ToString(), 'Process')
    Invoke-DockerStep ($composeArguments + @('config', '--quiet'))
    foreach ($kind in @('container', 'volume', 'network')) {
        $inspection = @($kind, 'ls', '--quiet', '--filter', "label=com.docker.compose.project=$ProjectName")
        if ($kind -eq 'container') { $inspection += '--all' }
        $existing = & docker @inspection
        if ($LASTEXITCODE -ne 0) { throw 'review deployment resource inspection failed' }
        if (($existing | Out-String).Trim()) { throw 'review deployment project already owns resources; choose a fresh project name' }
    }
    $ownsResources = $true
    Write-Host '[review-deployment] Start cached PostgreSQL with an isolated named volume'
    Invoke-DockerStep ($composeArguments + @('up', '--no-build', '--pull', 'never', '--detach', '--wait', '--wait-timeout', '90', 'postgres'))

    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'review Vue production build failed' }
        & .\node_modules\.bin\playwright.cmd test --config playwright.review-postgres.config.ts
        if ($LASTEXITCODE -ne 0) { throw 'review deployment browser acceptance failed' }
    }
    finally { Pop-Location }

    Assert-DatabaseScalar 'SELECT count(*) FROM app_schema_migrations' '8'
    Assert-DatabaseScalar 'SELECT count(*) FROM review_run_requests' '2'
    Assert-DatabaseScalar 'SELECT count(*) FROM review_publications' '1'
    Assert-DatabaseScalar 'SELECT current_revision FROM review_publication_heads' '2'
    Assert-DatabaseScalar "SELECT count(*) FROM tool_executions WHERE tool_name = 'publish_review' AND status = 'completed'" '1'
    Assert-DatabaseScalar "SELECT count(*) FROM agent_run_events WHERE type = 'review.evidence.recorded'" '6'
    Write-Host '[review-deployment] PASSED: built Vue + PostgreSQL + real fixture Chromium; two backend restarts; publication=1; rejection=unpublished'
}
finally {
    if ($ownsResources) {
        Write-Host "[review-deployment] Remove only owned verification project $ProjectName"
        & docker @composeArguments down --volumes
        if ($LASTEXITCODE -ne 0) { Write-Warning 'owned review deployment cleanup failed' }
    }
    foreach ($name in $ownedNames) {
        if ($null -eq $previousEnvironment[$name]) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
        }
    }
    foreach ($path in $secretFiles) {
        if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
    }
}
