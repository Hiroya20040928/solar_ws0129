# SolarSim - ソーラーカー最適制御・シミュレーション一括起動スクリプト
Param(
    [string]$Mode = "live",
    [string]$Config = "config/solar/bwsc_2027_demo.yaml"
)

Write-Host "=========================================================================" -ForegroundColor Cyan
Write-Host " SolarCar MPCEMS v2.0 - 高精度物理同定 & 3,000km CEM計画 & 10s CasADi MPC" -ForegroundColor Cyan
Write-Host "=========================================================================" -ForegroundColor Cyan

python "$PSScriptRoot/solar_control.py" --mode $Mode --config $Config
