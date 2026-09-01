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

    [switch]$KeepRunning,

    [switch]$LoadFault,

    [switch]$SkipDatabaseRegression,

    [ValidateRange(1, 100)]
    [int]$LoadFaultRuns = 16,

    [ValidateRange(1, 16)]
    [int]$LoadFaultConcurrency = 4
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
$temporaryFiles = @()
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

function Invoke-DurableRun {
    param(
        [Parameter(Mandatory)]
        [string]$BaseUrl,

        [ValidateRange(1, 120)]
        [int]$TimeoutSeconds = 30
    )

    $runCapability = [Guid]::NewGuid().ToString('N')
    $terminalFailures = 0
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $retryAfterTerminal = $false
        try {
            $createdRun = Invoke-RestMethod `
                -Method Post `
                -Uri "$BaseUrl/api/durable/runs" `
                -Headers @{ 'Idempotency-Key' = $runCapability } `
                -ContentType 'application/json' `
                -Body '{"message":"2 + 3"}' `
                -TimeoutSec 5
            if (
                -not $createdRun.id -or
                (
                    $createdRun.session_capability -and
                    $createdRun.session_capability -ne $runCapability
                )
            ) {
                throw 'durable Run create response is invalid'
            }
            do {
                $storedRun = Invoke-RestMethod `
                    -Uri "$BaseUrl/api/durable/runs/$($createdRun.id)" `
                    -Headers @{ 'X-Session-Token' = $runCapability } `
                    -TimeoutSec 5
                if ($storedRun.status -eq 'completed') {
                    return [pscustomobject]@{
                        run_id = $createdRun.id
                        capability = $runCapability
                        terminal_failures = $terminalFailures
                    }
                }
                if ($storedRun.status -in @('failed', 'cancelled')) {
                    $terminalFailures += 1
                    if ($terminalFailures -ge 8) {
                        break
                    }
                    $runCapability = [Guid]::NewGuid().ToString('N')
                    $retryAfterTerminal = $true
                    break
                }
                Start-Sleep -Milliseconds 50
            } while ([DateTime]::UtcNow -lt $deadline)
        }
        catch {
            # Reusing this durable idempotency key makes result-unknown safe.
        }
        if ($terminalFailures -ge 8) {
            break
        }
        if ($retryAfterTerminal) {
            Start-Sleep -Seconds 1
            continue
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'durable Run did not recover before the bounded deadline'
}

function Get-ProjectResourceSnapshot {
    param(
        [Parameter(Mandatory)]
        [string]$Phase
    )

    $containerIds = @(
        & docker @composeArguments ps --quiet postgres backend frontend
    )
    if ($LASTEXITCODE -ne 0 -or $containerIds.Count -ne 3) {
        throw 'deployment resource ownership inspection failed'
    }
    $statsArguments = @(
        'stats',
        '--no-stream',
        '--format',
        '{{json .}}'
    ) + $containerIds
    $statsLines = @(& docker @statsArguments)
    if ($LASTEXITCODE -ne 0 -or $statsLines.Count -ne 3) {
        throw 'deployment resource snapshot failed'
    }
    $containers = @(
        foreach ($line in $statsLines) {
            $item = $line | ConvertFrom-Json
            [pscustomobject]@{
                name = $item.Name
                cpu_percent = $item.CPUPerc
                memory_usage = $item.MemUsage
                memory_percent = $item.MemPerc
                pids = $item.PIDs
            }
        }
    )
    return [pscustomobject]@{
        phase = $Phase
        containers = $containers
    }
}

try {
    $pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'project virtualenv Python is unavailable'
    }
    if ($LoadFaultConcurrency -gt $LoadFaultRuns) {
        throw 'LoadFaultConcurrency must not exceed LoadFaultRuns'
    }
    if ($SkipDatabaseRegression -and -not $LoadFault) {
        throw 'SkipDatabaseRegression is allowed only for the M13-T6 load/fault path'
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

    if (-not $SkipDatabaseRegression) {
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
    }
    else {
        Write-Host '[deployment] Skip repeated M13-T4 database regression for M13-T6'
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

    if ($LoadFault) {
        $resourceSnapshots = @(
            Get-ProjectResourceSnapshot -Phase 'before_load'
        )
        $probeStderr = [System.IO.Path]::GetTempFileName()
        $temporaryFiles += $probeStderr
        $probeArguments = @(
            '-B',
            '-m',
            'backend.app.load_fault_probe',
            '--base-url',
            $frontendBaseUrl,
            '--runs',
            $LoadFaultRuns.ToString(),
            '--concurrency',
            $LoadFaultConcurrency.ToString()
        )
        Write-Host '[deployment] Run bounded M13-T6 load scenarios'
        $probeOutput = @(& $pythonPath @probeArguments 2> $probeStderr)
        $probeExitCode = $LASTEXITCODE
        $probeError = (Get-Content $probeStderr | Out-String).Trim()
        if ($probeError) {
            Write-Warning 'load probe produced bounded stderr output'
        }
        $probeLine = $probeOutput | Select-Object -Last 1
        if (-not $probeLine) {
            throw 'load probe did not produce a safe report'
        }
        try {
            $probeReport = $probeLine | ConvertFrom-Json
        }
        catch {
            throw 'load probe produced an invalid safe report'
        }
        if (
            $probeExitCode -ne 0 -or
            $probeReport.passed -ne $true
        ) {
            Write-Warning 'load probe safe failure report follows'
            $probeReport | ConvertTo-Json -Depth 12 -Compress
            throw 'load probe acceptance failed'
        }
        $resourceSnapshots += Get-ProjectResourceSnapshot -Phase 'after_load'

        Invoke-DockerStep -Name 'Stop owned PostgreSQL service' -Arguments (
            $composeArguments + @('stop', '--timeout', '15', 'postgres')
        )
        $outageCapability = [Guid]::NewGuid().ToString('N')
        $outageStatus = 0
        try {
            $outageResponse = Invoke-RestMethod `
                -Method Post `
                -Uri "$frontendBaseUrl/api/durable/runs" `
                -Headers @{ 'Idempotency-Key' = $outageCapability } `
                -ContentType 'application/json' `
                -Body '{"message":"2 + 3"}' `
                -TimeoutSec 8
            if ($outageResponse.id) {
                $outageStatus = 202
            }
        }
        catch {
            if ($_.Exception.Response) {
                $outageStatus = [int]$_.Exception.Response.StatusCode
            }
        }
        if ($outageStatus -gt 0 -and $outageStatus -lt 500) {
            throw 'database outage did not produce a bounded degraded response'
        }
        $databaseOutageResult = if ($outageStatus -eq 0) {
            'connection_failed'
        }
        else {
            'http_5xx'
        }

        Invoke-DockerStep -Name 'Start owned PostgreSQL service' -Arguments (
            $composeArguments + @('start', 'postgres')
        )
        Wait-HttpHealth -Uri "$backendBaseUrl/health"
        Wait-HttpHealth -Uri "$frontendBaseUrl/health"
        $recoveredRun = Invoke-DurableRun `
            -BaseUrl $frontendBaseUrl `
            -TimeoutSeconds 60
        $resourceSnapshots += Get-ProjectResourceSnapshot `
            -Phase 'after_database_recovery'

        Invoke-DockerStep -Name 'Restart owned backend service' -Arguments (
            $composeArguments + @('restart', 'backend')
        )
        Wait-HttpHealth -Uri "$backendBaseUrl/health"
        Wait-HttpHealth -Uri "$frontendBaseUrl/health"
        $recoveredAgain = Invoke-RestMethod `
            -Uri "$frontendBaseUrl/api/durable/runs/$runId" `
            -Headers @{ 'X-Session-Token' = $capability } `
            -TimeoutSec 10
        if (
            $recoveredAgain.id -ne $runId -or
            $recoveredAgain.status -ne 'completed'
        ) {
            throw 'durable Run did not survive the M13-T6 backend restart'
        }
        $resourceSnapshots += Get-ProjectResourceSnapshot `
            -Phase 'after_backend_restart'

        $loadFaultSummary = [ordered]@{
            suite = 'M13-T6'
            passed = $true
            project = $ProjectName
            load_probe = $probeReport
            database_outage = [ordered]@{
                degraded = $true
                result = $databaseOutageResult
                recovered = [bool]$recoveredRun.run_id
                terminal_failures_before_recovery = (
                    $recoveredRun.terminal_failures
                )
            }
            backend_restart = [ordered]@{
                recovered = $true
            }
            resource_snapshots = $resourceSnapshots
        }
    }

    Write-Host '[deployment] PASSED'
    Write-Host "[deployment] project=$ProjectName"
    Write-Host '[deployment] migrations=6 knowledge_migrations=1 seed=1'
    if ($SkipDatabaseRegression) {
        Write-Host (
            '[deployment] database_integration=skipped_reused_m13_t4 ' +
            'nginx_sse=passed'
        )
    }
    else {
        Write-Host '[deployment] database_integration=passed nginx_sse=passed'
    }
    Write-Host '[deployment] restart_recovery=passed'
    if ($LoadFault) {
        $loadFaultSummary | ConvertTo-Json -Depth 12 -Compress
    }
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
    foreach ($path in $temporaryFiles) {
        if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}
