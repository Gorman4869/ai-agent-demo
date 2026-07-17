param(
    [switch]$Authorized,
    [ValidateSet("M8")]
    [string]$Suite = "M8",
    [decimal]$InputPricePerMillionUsd = 0,
    [decimal]$OutputPricePerMillionUsd = 0
)

$ErrorActionPreference = "Stop"

if (-not $Authorized) {
    [Console]::Error.WriteLine(
        "M8-T6 online smoke refused: explicit one-time authorization is missing"
    )
    exit 64
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    [Console]::Error.WriteLine("M8-T6 online smoke refused: project Python is missing")
    exit 65
}

$inputPrice = $InputPricePerMillionUsd.ToString(
    [System.Globalization.CultureInfo]::InvariantCulture
)
$outputPrice = $OutputPricePerMillionUsd.ToString(
    [System.Globalization.CultureInfo]::InvariantCulture
)

Push-Location $repoRoot
try {
    & $python -X utf8 -B -m backend.app.online_smoke `
        --authorized `
        --suite $Suite `
        --input-price-per-million-usd $inputPrice `
        --output-price-per-million-usd $outputPrice
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
