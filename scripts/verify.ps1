param(
    [ValidateSet(
        'default',
        'offline',
        'mcp',
        'postgresql',
        'frontend',
        'e2e',
        'docker',
        'online',
        'integration',
        'all'
    )]
    [string]$Profile = 'default',
    [switch]$AuthorizedOnline,
    [switch]$SkipCompose
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$layerOrder = @(
    'offline',
    'mcp',
    'postgresql',
    'frontend',
    'e2e',
    'docker',
    'online'
)

function Resolve-ProjectPython {
    $candidates = @(
        (Join-Path $projectRoot '.venv/Scripts/python.exe'),
        (Join-Path $projectRoot '.venv/bin/python')
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    throw 'Project Python environment was not found.'
}

function Resolve-NpmCommand {
    if ($env:OS -eq 'Windows_NT') {
        return 'npm.cmd'
    }
    return 'npm'
}

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory)]
        [string]$Executable,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    Write-Host "`n==> $Name"
    Push-Location $WorkingDirectory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-OfflineLayer {
    $python = Resolve-ProjectPython

    Invoke-NativeStep `
        -Name 'Backend offline regression' `
        -WorkingDirectory $projectRoot `
        -Executable $python `
        -Arguments @('-B', '-m', 'unittest', 'discover', '-s', 'backend/tests', '-q')

    Invoke-NativeStep `
        -Name 'Controlled code-Agent demo' `
        -WorkingDirectory $projectRoot `
        -Executable $python `
        -Arguments @('-B', '-m', 'backend.app.advanced.code_demo')

    Invoke-NativeStep `
        -Name 'Python dependency check' `
        -WorkingDirectory $projectRoot `
        -Executable $python `
        -Arguments @('-m', 'pip', 'check')
}

function Invoke-McpLayer {
    $python = Resolve-ProjectPython
    $npm = Resolve-NpmCommand

    Invoke-NativeStep `
        -Name 'MCP TypeScript build' `
        -WorkingDirectory (Join-Path $projectRoot 'mcp-servers/knowledge-server') `
        -Executable $npm `
        -Arguments @('run', 'build')

    Invoke-NativeStep `
        -Name 'MCP local STDIO integration' `
        -WorkingDirectory $projectRoot `
        -Executable $python `
        -Arguments @(
            '-B',
            '-m',
            'unittest',
            'backend.tests.test_mcp_client_e2e',
            'backend.tests.test_mcp_tool_adapter',
            '-q'
        )
}

function Invoke-PostgresqlLayer {
    if (
        [string]::IsNullOrWhiteSpace($env:AI_AGENT_TEST_POSTGRES_DSN) -or
        [string]::IsNullOrWhiteSpace($env:AI_AGENT_TEST_PGVECTOR_DSN)
    ) {
        throw (
            'PostgreSQL verification requires both ' +
            'AI_AGENT_TEST_POSTGRES_DSN and AI_AGENT_TEST_PGVECTOR_DSN.'
        )
    }

    $python = Resolve-ProjectPython
    Invoke-NativeStep `
        -Name 'PostgreSQL and pgvector integration' `
        -WorkingDirectory $projectRoot `
        -Executable $python `
        -Arguments @(
            '-B',
            '-m',
            'unittest',
            'backend.tests.postgres_store_integration',
            'backend.tests.pgvector_integration',
            '-q'
        )
}

function Invoke-FrontendLayer {
    $npm = Resolve-NpmCommand

    Invoke-NativeStep `
        -Name 'Vue unit tests' `
        -WorkingDirectory (Join-Path $projectRoot 'frontend') `
        -Executable $npm `
        -Arguments @('run', 'test:unit')

    Invoke-NativeStep `
        -Name 'Vue production build' `
        -WorkingDirectory (Join-Path $projectRoot 'frontend') `
        -Executable $npm `
        -Arguments @('run', 'build')
}

function Invoke-E2eLayer {
    $npm = Resolve-NpmCommand
    Invoke-NativeStep `
        -Name 'Chromium durable Run E2E' `
        -WorkingDirectory (Join-Path $projectRoot 'frontend') `
        -Executable $npm `
        -Arguments @('run', 'test:e2e')
}

function Invoke-DockerLayer {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is required by the selected docker profile.'
    }

    Invoke-NativeStep `
        -Name 'Application Compose configuration' `
        -WorkingDirectory $projectRoot `
        -Executable 'docker' `
        -Arguments @('compose', '-f', 'deploy/compose.yaml', 'config', '--quiet')

    Invoke-NativeStep `
        -Name 'Integration Compose configuration' `
        -WorkingDirectory $projectRoot `
        -Executable 'docker' `
        -Arguments @(
            'compose',
            '-f',
            'deploy/compose.integration.yaml',
            'config',
            '--quiet'
        )
}

function Invoke-OnlineLayer {
    $powerShell = (Get-Process -Id $PID).Path
    $arguments = @('-NoProfile')
    if ($env:OS -eq 'Windows_NT') {
        $arguments += @('-ExecutionPolicy', 'Bypass')
    }
    $arguments += @(
        '-File',
        (Join-Path $PSScriptRoot 'verify-online.ps1'),
        '-Authorized',
        '-Suite',
        'M8'
    )

    Invoke-NativeStep `
        -Name 'Authorized online smoke' `
        -WorkingDirectory $projectRoot `
        -Executable $powerShell `
        -Arguments $arguments
}

switch ($Profile) {
    'default' {
        $selectedLayers = @('offline', 'mcp', 'frontend')
    }
    'integration' {
        $selectedLayers = @('postgresql')
    }
    'all' {
        $selectedLayers = $layerOrder
    }
    default {
        $selectedLayers = @($Profile)
    }
}

$results = [ordered]@{}
foreach ($layer in $layerOrder) {
    $results[$layer] = [pscustomobject]@{
        Status = 'SKIPPED'
        Detail = "not selected by profile '$Profile'"
    }
}

if ($SkipCompose -and ($selectedLayers -contains 'docker')) {
    $selectedLayers = @($selectedLayers | Where-Object { $_ -ne 'docker' })
    $results['docker'].Detail = 'disabled explicitly by -SkipCompose'
}

$failed = $false
foreach ($layer in $layerOrder) {
    if (-not ($selectedLayers -contains $layer)) {
        continue
    }
    if ($failed) {
        $results[$layer].Detail = 'not run after a previous required layer failed'
        continue
    }

    try {
        $layerSkipped = $false
        switch ($layer) {
            'offline' { Invoke-OfflineLayer }
            'mcp' { Invoke-McpLayer }
            'postgresql' { Invoke-PostgresqlLayer }
            'frontend' { Invoke-FrontendLayer }
            'e2e' { Invoke-E2eLayer }
            'docker' { Invoke-DockerLayer }
            'online' {
                if (-not $AuthorizedOnline) {
                    $results[$layer].Detail = (
                        'explicit one-time authorization is missing; ' +
                        'no online command was executed'
                    )
                    $layerSkipped = $true
                }
                else {
                    Invoke-OnlineLayer
                }
            }
        }
        if ($layerSkipped) {
            continue
        }
        $results[$layer].Status = 'PASSED'
        $results[$layer].Detail = 'all required steps passed'
    }
    catch {
        $results[$layer].Status = 'FAILED'
        $results[$layer].Detail = $_.Exception.Message
        $failed = $true
    }
}

Write-Host "`nVerification layer summary"
Write-Host '--------------------------'
foreach ($layer in $layerOrder) {
    $result = $results[$layer]
    Write-Host ('{0,-12} {1,-7} {2}' -f $layer, $result.Status, $result.Detail)
}

$passedCount = @($results.Values | Where-Object { $_.Status -eq 'PASSED' }).Count
$skippedCount = @($results.Values | Where-Object { $_.Status -eq 'SKIPPED' }).Count
$failedCount = @($results.Values | Where-Object { $_.Status -eq 'FAILED' }).Count

if ($failedCount -gt 0) {
    [Console]::Error.WriteLine(
        "Verification failed: $passedCount passed, $skippedCount skipped, " +
        "$failedCount failed."
    )
    exit 1
}

if ($skippedCount -gt 0) {
    Write-Host (
        "Verification completed: $passedCount passed, $skippedCount skipped, " +
        '0 failed.'
    )
    exit 0
}

Write-Host 'All selected required verification layers passed.'
exit 0
