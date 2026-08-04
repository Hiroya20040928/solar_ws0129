param(
    [string]$Distro = 'Ubuntu-22.04'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installed = @(wsl.exe --list --quiet) -replace "`0", '' | ForEach-Object { $_.Trim() } | Where-Object { $_ }

if ($Distro -notin $installed) {
    Write-Host "WSL distribution '$Distro' is not installed."
    Write-Host "Run the following command from an Administrator PowerShell, reboot if requested, then run this installer again:"
    Write-Host "  wsl --install -d $Distro"
    exit 2
}

$wslRepo = (wsl.exe -d $Distro wslpath -a $repoRoot).Trim()
if (-not $wslRepo) {
    throw 'Could not convert the repository path for WSL.'
}

wsl.exe -d $Distro bash -lc "cd '$wslRepo' && bash scripts/bootstrap_ubuntu_humble.sh"
if ($LASTEXITCODE -ne 0) {
    throw "Ubuntu bootstrap failed with exit code $LASTEXITCODE."
}

Write-Host 'Setup completed. Run:'
Write-Host '  powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action audit'
