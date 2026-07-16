[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$planPath = Join-Path $repoRoot 'docs\implementation-plan.md'
$statusPath = Join-Path $repoRoot 'docs\continuity\status.md'
$specPath = Join-Path $repoRoot 'docs\superpowers\specs\2026-07-16-ai-agent-transition-completion-design.md'

function Read-Utf8File {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

$errors = [System.Collections.Generic.List[string]]::new()
$plan = Read-Utf8File -Path $planPath
$status = Read-Utf8File -Path $statusPath
$spec = Read-Utf8File -Path $specPath

$taskMatches = [regex]::Matches(
    $plan,
    '(?m)^###\s+((?:C0|M(?:8|9|10|11|12|13|14))-T\d+)'
)
$taskIds = @($taskMatches | ForEach-Object { $_.Groups[1].Value })
$duplicateTaskIds = @(
    $taskIds |
        Group-Object |
        Where-Object Count -gt 1 |
        Select-Object -ExpandProperty Name
)

if ($taskIds.Count -eq 0) {
    $errors.Add('No stable task IDs were found in implementation-plan.md.')
}
foreach ($taskId in $duplicateTaskIds) {
    $errors.Add("Duplicate task ID: $taskId")
}

$currentTaskMatch = [regex]::Match(
    $status,
    '(?m)^\|\s*[^|]+\s*\|\s*`((?:C0|M(?:8|9|10|11|12|13|14))-T\d+)`\s*\|\s*$'
)
if (-not $currentTaskMatch.Success) {
    $errors.Add('No current task ID was found in status.md.')
} elseif ($taskIds -notcontains $currentTaskMatch.Groups[1].Value) {
    $errors.Add("Current task is not defined in the plan: $($currentTaskMatch.Groups[1].Value)")
}

if ($spec -notmatch 'accepted') {
    $errors.Add('The completion design spec is not marked as accepted.')
}

$markdownFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $repoRoot 'docs') -Recurse -File -Filter '*.md'
)
$markdownFiles += Get-Item -LiteralPath (Join-Path $repoRoot 'README.md')
$markdownFiles += Get-Item -LiteralPath (Join-Path $repoRoot 'AGENTS.md')

foreach ($file in $markdownFiles) {
    $content = Read-Utf8File -Path $file.FullName
    $linkMatches = [regex]::Matches($content, '\[[^\]]+\]\(([^)]+)\)')
    foreach ($linkMatch in $linkMatches) {
        $target = $linkMatch.Groups[1].Value.Trim()
        if (
            $target.StartsWith('#') -or
            $target.StartsWith('http://') -or
            $target.StartsWith('https://') -or
            $target.StartsWith('mailto:')
        ) {
            continue
        }

        $pathPart = $target.Split('#')[0]
        $decodedPath = [System.Uri]::UnescapeDataString($pathPart)
        $resolvedPath = [System.IO.Path]::GetFullPath(
            (Join-Path $file.DirectoryName $decodedPath)
        )
        if (-not (Test-Path -LiteralPath $resolvedPath)) {
            $relativeFile = $file.FullName.Substring($repoRoot.Length + 1)
            $errors.Add("Invalid Markdown link: $relativeFile -> $target")
        }
    }
}

$referencedTaskIds = [regex]::Matches(
    ((Read-Utf8File -Path (Join-Path $repoRoot 'docs\syllabus-map.md'))),
    '(?:C0|M(?:8|9|10|11|12|13|14))-T\d+'
) | ForEach-Object { $_.Value } | Sort-Object -Unique

foreach ($taskId in $referencedTaskIds) {
    if ($taskIds -notcontains $taskId) {
        $errors.Add("syllabus-map.md references an undefined task: $taskId")
    }
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Continuity check passed: $($taskIds.Count) stable tasks, $($markdownFiles.Count) Markdown files."
