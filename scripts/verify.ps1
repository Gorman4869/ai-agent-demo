param(
    [switch]$SkipCompose
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

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

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python environment was not found: $python"
}

Invoke-NativeStep `
    -Name 'Backend regression' `
    -WorkingDirectory $projectRoot `
    -Executable $python `
    -Arguments @('-m', 'unittest', 'discover', '-s', 'backend/tests', '-v')

Invoke-NativeStep `
    -Name 'Controlled code-Agent demo' `
    -WorkingDirectory $projectRoot `
    -Executable $python `
    -Arguments @('-m', 'backend.app.advanced.code_demo')

Invoke-NativeStep `
    -Name 'Python dependency check' `
    -WorkingDirectory $projectRoot `
    -Executable $python `
    -Arguments @('-m', 'pip', 'check')

Invoke-NativeStep `
    -Name 'Vue production build' `
    -WorkingDirectory (Join-Path $projectRoot 'frontend') `
    -Executable 'npm.cmd' `
    -Arguments @('run', 'build')

Invoke-NativeStep `
    -Name 'MCP TypeScript build' `
    -WorkingDirectory (Join-Path $projectRoot 'mcp-servers\knowledge-server') `
    -Executable 'npm.cmd' `
    -Arguments @('run', 'build')

if (-not $SkipCompose) {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Invoke-NativeStep `
            -Name 'Docker Compose configuration' `
            -WorkingDirectory $projectRoot `
            -Executable 'docker' `
            -Arguments @('compose', '-f', 'deploy/compose.yaml', 'config', '--quiet')
    }
    else {
        Write-Warning 'Docker CLI was not found; Compose configuration was skipped.'
    }
}

Write-Host "`nAll requested verification steps passed."
