# 01. Windows入口 PowerShell ルータ

- ファイル: `SolarSim.ps1`
- 種別: `PowerShell`
- 区分: `入口`

## 役割

Windows PowerShell から build、launch、offline script、Grafana 操作をまとめて呼び出す最上位入口。

## 起動文脈

- 起動文脈: オペレータが最初に叩くコマンド入口。
- 呼び出し元: `人間の運用操作`
- 次に読むべきファイル: `scripts/solar_control.sh`, `launch/solar_race_live_wifi.launch.py`, `scripts/solar_sim.py`

## 主要ポイント

- WSL ディストリビューションを解決する。
- Action と Mode を shell 側へ受け渡す。
- dashboard や report の自動オープンも担う。

## 主要構造

action 分岐は 16 件。

## ファイルを上から読んだときの定義順

- L1: param(
- L2: [ValidateSet('up', 'build', 'start', 'stop', 'restart', 'status', 'graph', 'simulate', 'historical-weather', 'historical-simulate', 'forecast', 'identify', 'fit', 'learn', 'audit', 'package', 'blank', 'log', 'grafana', 'grafana-stop')]
- L3: [string]$Action = 'up',
- L4: [ValidateSet('sim', 'measure', 'live', 'live_wifi')]
- L5: [string]$Mode = 'sim',
- L6: [string]$Profile = 'project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml',
- L7: [string]$Distro = '',
- L8: [switch]$Help
- L9: )
- L11: $ErrorActionPreference = 'Stop'
- L13: if ($Help) {
- L14: @'
- L15: SolarSim.ps1 -Action <action> [-Mode <mode>] [-Profile <profile.yaml>] [-Distro <WSL name>]
- L17: Actions: up, build, start, stop, restart, status, graph, simulate, forecast,
- L18: identify, fit, learn, audit, package, blank, log, grafana, grafana-stop
- L19: Modes:   sim, measure, live, live_wifi
- L21: Examples:
- L22: .\SolarSim.ps1 -Action build
- L23: .\SolarSim.ps1 -Action up -Mode sim
- L24: .\SolarSim.ps1 -Action simulate -Profile project_packages/<vehicle>/profile.yaml
- L25: '@ | Write-Host
- L26: exit 0
- L27: }
- L29: function Normalize-WslText {
- L30: param([string]$Text)
- L31: if ($null -eq $Text) {
- L32: return ''
- L33: }
- L34: return ([string]$Text).Replace("`0", '').Trim()
- L35: }

## shell 分岐と外部コマンド

- Action L250: `up`
- Action L278: `build`
- Action L281: `start`
- Action L284: `stop`
- Action L287: `restart`
- Action L290: `status`
- Action L293: `graph`
- Action L299: `simulate`
- Action L306: `historical-weather`
- Action L309: `historical-simulate`
- Action L317: `forecast`
- Action L320: `identify`
- Action L323: `fit`
- Action L326: `learn`
- Action L329: `audit`
- Action L332: `log`
- Command L42: `$installed = (& wsl.exe -l -q) | ForEach-Object { Normalize-WslText $_ } | Where-Object { $_ }`
- Command L63: `return (& wsl.exe -d $TargetDistro wslpath -a $PathValue).Trim()`
- Command L76: `$wslRepo = (& wsl.exe -d $TargetDistro wslpath -a $RepoRoot).Trim()`
- Command L81: `& wsl.exe -d $TargetDistro bash -lc "cd '$wslRepo' && bash './scripts/solar_control.sh' '$Command' '$TargetMode' '$wslProfile'"`
- Command L207: `if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {`
- Command L214: `& docker compose up -d`
- Command L216: `throw "docker compose up failed with exit code $LASTEXITCODE"`
- Command L220: `& docker compose down`
- Command L222: `throw "docker compose down failed with exit code $LASTEXITCODE"`
- Command L235: `& python $builder --force`
- Command L257: `if (Get-Command docker -ErrorAction SilentlyContinue) {`
- Command L260: `& docker compose up -d`
- Command L262: `throw "docker compose up failed with exit code $LASTEXITCODE"`

## 処理の流れ

1. PowerShell 引数を解釈する。
2. WSL 側のパスへ変換する。
3. scripts/solar_control.sh を action と mode 付きで呼ぶ。
4. 必要に応じて dashboard、graph、report を開く。
