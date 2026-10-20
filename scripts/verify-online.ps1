param(
    [switch]$Authorized,
    [ValidateSet("M8", "M14")]
    [string]$Suite = "M8",
    [ValidateSet("OpenAI", "MiniMax")]
    [string]$VisionProvider = "OpenAI",
    [string]$VisionModel = "",
    [string]$MiniMaxBillingMode = "",
    [decimal]$InputPricePerMillionUsd = 0,
    [decimal]$OutputPricePerMillionUsd = 0,
    [decimal]$InputPricePerMillionCny = 0,
    [decimal]$OutputPricePerMillionCny = 0
)

$ErrorActionPreference = "Stop"
$suiteLabel = if ($Suite -eq "M14") { "M14-T4 vision" } else { "M8-T6" }

if (-not $Authorized) {
    [Console]::Error.WriteLine(
        "$suiteLabel online smoke refused: explicit one-time authorization is missing"
    )
    exit 64
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    [Console]::Error.WriteLine(
        "$suiteLabel online smoke refused: project Python is missing"
    )
    exit 65
}

$inputPrice = $InputPricePerMillionUsd.ToString(
    [System.Globalization.CultureInfo]::InvariantCulture
)
$outputPrice = $OutputPricePerMillionUsd.ToString(
    [System.Globalization.CultureInfo]::InvariantCulture
)
$inputPriceCny = $InputPricePerMillionCny.ToString(
    [System.Globalization.CultureInfo]::InvariantCulture
)
$outputPriceCny = $OutputPricePerMillionCny.ToString(
    [System.Globalization.CultureInfo]::InvariantCulture
)

Push-Location $repoRoot
try {
    if ($Suite -eq "M14") {
        if ($VisionProvider -eq "MiniMax") {
            if ($MiniMaxBillingMode -eq "Payg") {
                $billingMode = "payg"
            }
            elseif ($MiniMaxBillingMode -eq "MPlan") {
                $billingMode = "m_plan"
            }
            else {
                [Console]::Error.WriteLine(
                    "$suiteLabel online smoke refused: MiniMax billing mode must be Payg or MPlan"
                )
                exit 65
            }
            & $python -X utf8 -B -m backend.app.minimax_vision_smoke `
                --authorized `
                --suite $Suite `
                --vision-model $VisionModel `
                --billing-mode $billingMode `
                --input-price-per-million-cny $inputPriceCny `
                --output-price-per-million-cny $outputPriceCny
        }
        else {
            & $python -X utf8 -B -m backend.app.vision_online_smoke `
                --authorized `
                --suite $Suite `
                --vision-model $VisionModel `
                --input-price-per-million-usd $inputPrice `
                --output-price-per-million-usd $outputPrice
        }
    }
    else {
        & $python -X utf8 -B -m backend.app.online_smoke `
            --authorized `
            --suite $Suite `
            --input-price-per-million-usd $inputPrice `
            --output-price-per-million-usd $outputPrice
    }
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
