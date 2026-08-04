param(
    [string]$Zip = (Join-Path $PSScriptRoot 'MPC27_FINAL.zip'),
    [string]$Destination = (Join-Path $env:USERPROFILE 'MPC27')
)

$ErrorActionPreference = 'Stop'
$zipPath = (Resolve-Path -LiteralPath $Zip).Path
$destinationPath = [IO.Path]::GetFullPath($Destination)

if (Test-Path -LiteralPath $destinationPath) {
    $existing = @(Get-ChildItem -LiteralPath $destinationPath -Force -ErrorAction Stop)
    if ($existing.Count -gt 0) {
        throw "Destination is not empty; refusing to overwrite: $destinationPath"
    }
} else {
    New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
}

Expand-Archive -LiteralPath $zipPath -DestinationPath $destinationPath -Force
$bundleRoot = Join-Path $destinationPath 'M'
if (-not (Test-Path -LiteralPath (Join-Path $bundleRoot 'EXECUTION_DEPENDENCY_AUDIT.json'))) {
    throw "Extraction verification marker is missing: $bundleRoot"
}

Write-Output "Extracted and verified package root: $bundleRoot"
