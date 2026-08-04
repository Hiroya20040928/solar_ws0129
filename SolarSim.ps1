param(
    [ValidateSet('up', 'build', 'start', 'stop', 'restart', 'status', 'graph', 'simulate', 'forecast', 'identify', 'log')]
    [string]$Action = 'up',
    [ValidateSet('sim', 'measure', 'live', 'live_wifi')]
    [string]$Mode = 'sim',
    [string]$Profile = 'config/solar/bwsc_2027_demo.yaml',
    [string]$Distro = ''
)

$ErrorActionPreference = 'Stop'

function Normalize-WslText {
    param([string]$Text)
    if ($null -eq $Text) {
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    return ([string]$Text).Replace("`0", '').Trim()                # [戻り値] 計算結果・計算状態の呼び出し元への返却
}

function Resolve-WslDistro {
    param([string]$Preferred)
    if ($Preferred) {
        return (Normalize-WslText $Preferred)                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    $installed = (& wsl.exe -l -q) | ForEach-Object { Normalize-WslText $_ } | Where-Object { $_ }
    foreach ($candidate in @('Ubuntu-22.04', 'Ubuntu', 'Ubuntu-24.04')) {
        if ($installed -contains $candidate) {
            return $candidate                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        }
    }
    if ($installed.Count -gt 0) {
        return $installed[0]                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    throw 'WSL distro was not found.'
}

function Resolve-WslArgPath {
    param(
        [string]$TargetDistro,
        [string]$PathValue
    )
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return (& wsl.exe -d $TargetDistro wslpath -a $PathValue).Trim()  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    return ($PathValue -replace '\\', '/')                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
}

function Invoke-WslRepoCommand {
    param(
        [string]$RepoRoot,
        [string]$TargetDistro,
        [string]$Command,
        [string]$TargetMode,
        [string]$ProfilePath
    )
    $wslRepo = (& wsl.exe -d $TargetDistro wslpath -a $RepoRoot).Trim()
    if (-not $wslRepo) {
        throw 'Failed to resolve the workspace path in WSL.'
    }
    $wslProfile = Resolve-WslArgPath -TargetDistro $TargetDistro -PathValue $ProfilePath
    & wsl.exe -d $TargetDistro bash -lc "cd '$wslRepo' && bash './scripts/solar_control.sh' '$Command' '$TargetMode' '$wslProfile'"
}

function Wait-ForDashboard {
    param([int]$Port = 8080)
    $uris = @(
        "http://localhost:$Port/api/state",
        "http://127.0.0.1:$Port/api/state",
        "http://wsl.localhost:$Port/api/state"
    )
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        foreach ($uri in $uris) {
            try {
                $res = Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 2
                if ($null -ne $res.ts) {
                    return $uri                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
                }
            } catch {
            }
        }
        Start-Sleep -Milliseconds 750
    }
    return $null                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
}

function Get-ProfileDashboardPort {
    param([string]$ProfilePath)
    $resolved = Join-Path $repoRoot $ProfilePath
    if (-not (Test-Path $resolved)) {
        return 8080                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    $inRuntime = $false
    foreach ($line in Get-Content $resolved) {
        if ($line -match '^\s*runtime\s*:\s*$') {
            $inRuntime = $true
            continue
        }
        if ($inRuntime -and $line -match '^\S') {
            break
        }
        if ($inRuntime -and $line -match '^\s*dashboard_port\s*:\s*([0-9]+)\s*$') {
            return [int]$Matches[1]                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        }
    }
    return 8080                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
}

function Get-ProfileSimulationReportPath {
    param([string]$ProfilePath)
    $resolved = Join-Path $repoRoot $ProfilePath
    $outputDir = 'outputs/prerace'
    $outputPrefix = 'solar_prerace'
    $reportHtml = ''
    $latestManifest = ''
    if (-not (Test-Path $resolved)) {
        return (Join-Path $repoRoot (Join-Path $outputDir "$outputPrefix`_report.html"))  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    $inSimulation = $false
    foreach ($line in Get-Content $resolved) {
        if ($line -match '^\s*simulation\s*:\s*$') {
            $inSimulation = $true
            continue
        }
        if ($inSimulation -and $line -match '^\S') {
            break
        }
        if (-not $inSimulation) {
            continue
        }
        if ($line -match '^\s*output_dir\s*:\s*(.+?)\s*$') {
            $outputDir = $Matches[1].Trim().Trim("'`"")
            continue
        }
        if ($line -match '^\s*output_prefix\s*:\s*(.+?)\s*$') {
            $outputPrefix = $Matches[1].Trim().Trim("'`"")
            continue
        }
        if ($line -match '^\s*report_html\s*:\s*(.+?)\s*$') {
            $reportHtml = $Matches[1].Trim().Trim("'`"")
            continue
        }
        if ($line -match '^\s*latest_manifest_json\s*:\s*(.+?)\s*$') {
            $latestManifest = $Matches[1].Trim().Trim("'`"")
        }
    }
    if ([string]::IsNullOrWhiteSpace($latestManifest)) {
        $latestManifest = Join-Path $outputDir 'latest_simulation_run.json'
    }
    if (-not [System.IO.Path]::IsPathRooted($latestManifest)) {
        $latestManifest = Join-Path $repoRoot $latestManifest
    }
    if (Test-Path $latestManifest) {
        try {
            $manifest = Get-Content $latestManifest -Raw | ConvertFrom-Json
            if ($null -ne $manifest.report_html -and -not [string]::IsNullOrWhiteSpace([string]$manifest.report_html)) {
                $candidate = [string]$manifest.report_html
                if (-not [System.IO.Path]::IsPathRooted($candidate)) {
                    $candidate = Join-Path $repoRoot $candidate
                }
                return $candidate                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
            }
        } catch {
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($reportHtml)) {
        if ([System.IO.Path]::IsPathRooted($reportHtml)) {
            return $reportHtml                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
        }
        return (Join-Path $repoRoot $reportHtml)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    }
    return (Join-Path $repoRoot (Join-Path $outputDir "$outputPrefix`_report.html"))  # [戻り値] 計算結果・計算状態の呼び出し元への返却
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$resolvedDistro = Resolve-WslDistro -Preferred $Distro
$graphPath = Join-Path $repoRoot "rqt_graph_solar_$Mode.png"
$dashboardPort = Get-ProfileDashboardPort -ProfilePath $Profile

switch ($Action) {
    'up' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'up' -TargetMode $Mode -ProfilePath $Profile
        if ($Mode -in @('sim', 'measure', 'live', 'live_wifi')) {
            $dashboardUri = Wait-ForDashboard -Port $dashboardPort
            if (-not $dashboardUri) {
                throw "Dashboard did not become available on port $dashboardPort."
            }
            Start-Process $dashboardUri | Out-Null
            Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'graph' -TargetMode $Mode -ProfilePath $Profile
            if (Test-Path $graphPath) {
                Start-Process $graphPath | Out-Null
            }
        }
    }
    'build' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'build' -TargetMode $Mode -ProfilePath $Profile
    }
    'start' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'start' -TargetMode $Mode -ProfilePath $Profile
    }
    'stop' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'stop' -TargetMode $Mode -ProfilePath $Profile
    }
    'restart' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'restart' -TargetMode $Mode -ProfilePath $Profile
    }
    'status' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'status' -TargetMode $Mode -ProfilePath $Profile
    }
    'graph' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'graph' -TargetMode $Mode -ProfilePath $Profile
        if (Test-Path $graphPath) {
            Start-Process $graphPath | Out-Null
        }
    }
    'simulate' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'simulate' -TargetMode 'sim' -ProfilePath $Profile
        $reportPath = Get-ProfileSimulationReportPath -ProfilePath $Profile
        if (Test-Path $reportPath) {
            Start-Process $reportPath | Out-Null
        }
    }
    'forecast' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'forecast' -TargetMode 'sim' -ProfilePath $Profile
    }
    'identify' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'identify' -TargetMode 'sim' -ProfilePath $Profile
    }
    'log' {
        Invoke-WslRepoCommand -RepoRoot $repoRoot -TargetDistro $resolvedDistro -Command 'log' -TargetMode $Mode -ProfilePath $Profile
    }
}
