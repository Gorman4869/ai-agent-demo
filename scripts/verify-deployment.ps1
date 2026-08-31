[CmdletBinding()]
param(
    [ValidatePattern('^ai-agent-demo-m13-[a-z0-9-]+$')]
    [string]$ProjectName = (
        "ai-agent-demo-m13-$PID-" +
        [Guid]::NewGuid().ToString('N').Substring(0, 8)
    ),

    [ValidateRange(1024, 65535)]
    [int]$FrontendPort = 15173,

    [ValidateRange(1024, 65535)]
    [int]$BackendPort = 18000,

    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 55434,

    [switch]$KeepRunning
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$composeFile = Join-Path $projectRoot 'deploy/compose.deployment.yaml'
$composeArguments = @(
    'compose',
    '--project-name',
    $ProjectName,
    '--file',
    $composeFile
)
$passwordFileName = 'AI_AGENT_DEPLOY_POSTGRES_PASSWORD_FILE'
$dsnFileName = 'AI_AGENT_DEPLOY_POSTGRES_DSN_FILE'
$frontendPortName = 'DEPLOY_FRONTEND_PORT'
$backendPortName = 'DEPLOY_BACKEND_PORT'
$postgresPortName = 'DEPLOY_POSTGRES_PORT'
$testPostgresDsnName = 'AI_AGENT_TEST_POSTGRES_DSN'
$testPgVectorDsnName = 'AI_AGENT_TEST_PGVECTOR_DSN'
$ownedEnvironment = @(
    $passwordFileName,
    $dsnFileName,
    $frontendPortName,
    $backendPortName,
    $postgresPortName,
    $testPostgresDsnName,
    $testPgVectorDsnName
)
$previousEnvironment = @{}
$secretFiles = @()
$ownsResources = $false

function Invoke-DockerStep {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    Write-Host "[deployment] $Name"
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed"
    }
}

function Read-DatabaseScalar {
    param(
        [Parameter(Mandatory)]
        [string]$Query
    )

    $output = & docker @composeArguments exec --no-TTY postgres `
        psql --username ai_agent --dbname ai_agent_deployment `
        --tuples-only --no-align --command $Query
    if ($LASTEXITCODE -ne 0) {
        throw 'database verification failed'
    }
    return ($output | Out-String).Trim()
}

function Wait-HttpHealth {
    param(
        [Parameter(Mandatory)]
        [string]$Uri,

        [ValidateRange(1, 300)]
        [int]$TimeoutSeconds = 120
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri $Uri -TimeoutSec 3
            if ($response.status -eq 'ok') {
                return
            }
        }
        catch {
            # A restarting container may refuse connections until it is ready.
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'restarted deployment did not become healthy'
}

try {
    $pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'project virtualenv Python is unavailable'
    }

    foreach ($name in $ownedEnvironment) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable(
            $name,
            'Process'
        )
    }

    $password = "m13-$([Guid]::NewGuid().ToString('N'))"
    $containerDsn = (
        "postgresql://ai_agent:$password@postgres:5432/" +
        'ai_agent_deployment?sslmode=disable'
    )
    $passwordFile = [System.IO.Path]::GetTempFileName()
    $secretFiles += $passwordFile
    $dsnFile = [System.IO.Path]::GetTempFileName()
    $secretFiles += $dsnFile
    $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($passwordFile, $password, $utf8WithoutBom)
    [System.IO.File]::WriteAllText($dsnFile, $containerDsn, $utf8WithoutBom)
    [Environment]::SetEnvironmentVariable(
        $passwordFileName,
        $passwordFile,
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        $dsnFileName,
        $dsnFile,
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        $frontendPortName,
        $FrontendPort.ToString(),
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        $backendPortName,
        $BackendPort.ToString(),
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        $postgresPortName,
        $PostgresPort.ToString(),
        'Process'
    )

    Invoke-DockerStep -Name 'Validate Compose configuration' -Arguments (
        $composeArguments + @('config', '--quiet')
    )
    $existing = & docker @composeArguments ps --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'existing deployment inspection failed'
    }
    if (($existing | Out-String).Trim()) {
        throw "deployment project $ProjectName already owns containers"
    }

    $ownsResources = $true
    Invoke-DockerStep -Name 'Build and start deployment' -Arguments (
        $composeArguments + @(
            'up',
            '--build',
            '--detach',
            '--wait',
            '--wait-timeout',
            '240'
        )
    )

    $frontendBaseUrl = "http://127.0.0.1:$FrontendPort"
    $backendBaseUrl = "http://127.0.0.1:$BackendPort"
    $uiHealth = Invoke-RestMethod -Uri "$frontendBaseUrl/ui-health"
    $proxiedHealth = Invoke-RestMethod -Uri "$frontendBaseUrl/health"
    $backendHealth = Invoke-RestMethod -Uri "$backendBaseUrl/health"
    $uiHealthText = ($uiHealth | Out-String).Trim()
    if (
        $uiHealthText -ne 'ok' -or
        $proxiedHealth.status -ne 'ok' -or
        $backendHealth.status -ne 'ok'
    ) {
        throw 'deployment health verification failed'
    }

    if ((Read-DatabaseScalar -Query 'SELECT count(*) FROM app_schema_migrations') -ne '6') {
        throw 'application migrations are incomplete'
    }
    if ((Read-DatabaseScalar -Query 'SELECT count(*) FROM knowledge_schema_migrations') -ne '1') {
        throw 'knowledge migrations are incomplete'
    }
    if ((Read-DatabaseScalar -Query "SELECT count(*) FROM knowledge_documents WHERE id = 'agent-course'") -ne '1') {
        throw 'deployment seed is incomplete'
    }
    if ((Read-DatabaseScalar -Query "SELECT count(*) FROM pg_extension WHERE extname = 'vector'") -ne '1') {
        throw 'pgvector extension is unavailable'
    }

    Invoke-DockerStep -Name 'Create PostgreSQL Store integration database' -Arguments (
        $composeArguments + @(
            'exec',
            '--no-TTY',
            'postgres',
            'createdb',
            '--username',
            'ai_agent',
            'ai_agent_store_test'
        )
    )
    Invoke-DockerStep -Name 'Create pgvector integration database' -Arguments (
        $composeArguments + @(
            'exec',
            '--no-TTY',
            'postgres',
            'createdb',
            '--username',
            'ai_agent',
            'ai_agent_pgvector_test'
        )
    )
    $hostDsnPrefix = (
        "postgresql://ai_agent:$password@127.0.0.1:$PostgresPort/"
    )
    [Environment]::SetEnvironmentVariable(
        $testPostgresDsnName,
        $hostDsnPrefix + 'ai_agent_store_test?sslmode=disable',
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        $testPgVectorDsnName,
        $hostDsnPrefix + 'ai_agent_pgvector_test?sslmode=disable',
        'Process'
    )
    Write-Host '[deployment] Run PostgreSQL and pgvector integration tests'
    & $pythonPath -B -m unittest `
        backend.tests.postgres_store_integration `
        backend.tests.pgvector_integration `
        -q
    if ($LASTEXITCODE -ne 0) {
        throw 'database integration tests failed'
    }

    $capability = [Guid]::NewGuid().ToString('N')
    $created = Invoke-RestMethod `
        -Method Post `
        -Uri "$frontendBaseUrl/api/durable/runs" `
        -Headers @{ 'Idempotency-Key' = $capability } `
        -ContentType 'application/json' `
        -Body '{"message":"2 + 3"}'
    $runId = $created.id
    if (-not $runId -or $created.session_capability -ne $capability) {
        throw 'durable Run creation failed'
    }

    $sseUrl = "$frontendBaseUrl/api/durable/runs/$runId/events?after=0"
    $sseResponse = & curl.exe `
        --silent `
        --show-error `
        --no-buffer `
        --max-time 30 `
        --dump-header - `
        --header "X-Session-Token: $capability" `
        $sseUrl
    if ($LASTEXITCODE -ne 0) {
        throw 'Nginx SSE request failed'
    }
    $sseText = ($sseResponse | Out-String)
    if (
        $sseText -notmatch '(?im)^content-type:\s*text/event-stream' -or
        $sseText -notmatch '(?m)^event: run.started\r?$' -or
        $sseText -notmatch '(?m)^event: run.completed\r?$'
    ) {
        throw 'Nginx SSE stream is incomplete'
    }
    $startedIndex = $sseText.IndexOf('event: run.started')
    $completedIndex = $sseText.IndexOf('event: run.completed')
    if ($startedIndex -lt 0 -or $completedIndex -le $startedIndex) {
        throw 'Nginx SSE event order is invalid'
    }

    Invoke-DockerStep -Name 'Restart backend container' -Arguments (
        $composeArguments + @('restart', 'backend')
    )
    Write-Host '[deployment] Wait for restarted backend health'
    Wait-HttpHealth -Uri "$backendBaseUrl/health"
    Wait-HttpHealth -Uri "$frontendBaseUrl/health"
    $recovered = Invoke-RestMethod `
        -Uri "$frontendBaseUrl/api/durable/runs/$runId" `
        -Headers @{ 'X-Session-Token' = $capability }
    if ($recovered.id -ne $runId -or $recovered.status -ne 'completed') {
        throw 'durable Run did not survive the backend restart'
    }

    Write-Host '[deployment] PASSED'
    Write-Host "[deployment] project=$ProjectName"
    Write-Host '[deployment] migrations=6 knowledge_migrations=1 seed=1'
    Write-Host '[deployment] database_integration=passed nginx_sse=passed'
    Write-Host '[deployment] restart_recovery=passed'
}
catch {
    if ($ownsResources) {
        Write-Warning 'deployment failed; collecting bounded project diagnostics'
        & docker @composeArguments ps --all
        & docker @composeArguments logs `
            --no-color `
            --tail 80 `
            knowledge-seed `
            backend `
            frontend
    }
    throw
}
finally {
    if ($ownsResources -and -not $KeepRunning) {
        Write-Host "[deployment] Removing verification project $ProjectName"
        & docker @composeArguments down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "deployment cleanup failed for project $ProjectName"
        }
    }
    foreach ($name in $ownedEnvironment) {
        [Environment]::SetEnvironmentVariable(
            $name,
            $previousEnvironment[$name],
            'Process'
        )
    }
    foreach ($path in $secretFiles) {
        if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}
