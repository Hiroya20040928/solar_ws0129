# 01. Windows入口 PowerShell ルータ

- ファイル: `SolarSim.ps1`
- ソースSHA-256: `fa039bfbc741ab4719218ffc48738f42ce3ea6f7c3ccf33dd0c4987ea87f29c1`
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

## このファイルを読む前に必要な基礎知識

次の章は、構文やROS用語を既知と仮定しないための説明である。

### プログラム、プロセス、メモリ、オブジェクトを区別する

ソースファイルはディスク上の文字列であり、それ自体は走っていない。Python実行可能プログラムがソースを読み、OSがその実行を一つのプロセスとして管理する。プロセスには仮想メモリ、開いているファイル、スレッド、終了コードなどが対応する。

```text
ソースファイル -> Pythonインタプリタが読み込む -> OS上のプロセス -> Pythonオブジェクトをメモリに生成 -> 関数やcallbackを実行
```

「メモリ上に生成する」とは、実行中プロセスが使う記憶領域に、その値の型、属性、参照関係を表す実体を用意することである。変数は実体そのものというより、そのオブジェクトを指す名前として理解するとPythonの代入が読みやすい。

```python
node = MPCNode()
alias = node
# nodeとaliasは同じオブジェクトを参照する。
```

一つのプロセスには複数スレッドを持たせられる。スレッドは同じプロセスのメモリを共有するため、受信callbackと最適化callbackが同じself.zを書き換える場合は実行順と排他を検討する必要がある。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

### CLI、PowerShell、Bash、環境変数、終了コード

CLIは端末からプログラム名と引数を渡す操作界面である。`argparse`は文字列として届く引数を名前、型、既定値、必須性に従って解析する。

PowerShellとBashは別のshellであり、変数記法、改行継続、引用、パス表記が異なる。このプロジェクトではWindows側のSolarSim.ps1がWSL側のsolar_control.shへ処理を渡す。

環境変数は親プロセスから子プロセスへ受け渡される名前付き文字列である。ROS_DOMAIN_ID、RMW_IMPLEMENTATION、Pythonの数値スレッド数などはコード外から動作を変えるため、実行記録へ残す必要がある。

終了コード0は一般に成功、0以外は失敗を示す。shellルータは子プロセスの終了コードを握り潰さず上位へ返すことで、自動運用が失敗を検知できる。

根拠資料:

- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

### 例外、try/finally、with、資源解放

例外は通常の戻り値とは別経路で異常を呼出元へ伝える。`try/except`は想定した異常を処理し、`finally`は成功・失敗にかかわらず後始末を行う。

`with open(...) as f:`はcontext managerを使い、ブロックを出るとファイルを閉じる。CSVやログの破損を避けるため、開いた資源の所有者と閉じる場所を明確にする。

`except Exception: pass`はノードを止めない利点がある一方、入力異常を隠して原因追跡を難しくする。安全に関係する値では、少なくとも頻度制限付き警告、異常カウンタ、fallback状態のpublishを検討する。

### 天候、route、補間、時刻、単位

予報は時刻だけの系列か、時刻とroute距離の2次元gridになり得る。現在時刻tと距離sがgrid点の間なら、周囲の値から補間して日射、温度、風を求める。

UTC、現地timezone、naive datetimeを混ぜると数時間のずれが発生する。入力でtimezoneを確定し、内部比較はUTC、表示は現地時刻という役割分担が安全である。

route距離のkm、速度のkm/hとm/s、時間の秒、energyのWhとJを跨ぐため、変換係数3.6、3600、1000の意味を各式で確認する。

### freshness、filter、guard、fallback、fail-safe

分散システムでは最後に受け取った値が現在も有効とは限らない。受信時刻とtimeoutからfreshnessを判定し、stale値を計画状態へ無条件に同期しない。

filterはnoiseと一時的な飛び値を抑えるが、遅れを生む。slew limitは指令変化率を制限する。安全guardはsolverのcost罰則とは別に、現在出力へ強制制約を適用する最後の防波堤である。

fallbackは失敗時の代替動作を事前に決める設計である。前回計画保持、物理に基づく決定論的入力、停止、低速制限などから、故障modeごとに選ぶ。fallback発生はstatusとlogへ残し、正常解と区別する。

### launch Action、Node Action、実行可能名、remapping

`launch_ros.actions.Node(...)`はrclpyのNode基底クラスではなく、指定したpackageのexecutableをプロセスとして起動するlaunch Actionである。

`DeclareLaunchArgument`はlaunch実行時に受け取る入力欄を宣言し、`LaunchConfiguration`はその値を後で解決するsubstitutionを表す。`perform(context)`は実行時contextから確定文字列を取り出す。

launchの`name`はNode名override、`parameters`は起動時parameter、`remappings`はNodeやtopicの既定名を別名へ対応付ける。launchはPythonファイルからmainという名前を推測せず、executableとしてインストールされたconsole scriptを起動する。

根拠資料:

- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)
- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

### 単体試験、SILS、replay、観測可能性

単体試験は関数やモデル項の局所契約、SILSは複数Nodeと時間進行を含む閉ループ、historical replayは実測入力への再現性、本番preflightは実機通信と停止動作を確認する。目的が異なるため一つで代用しない。

再現可能な診断には、入力、出力、内部状態、solver成否、候補数、計算時間、fallback、source revision、profile hashを同じrun IDで記録する。

非同期不具合は最終値だけでは追えない。topic周期、message age、callback所要時間、queue遅延、Node生存、publisher数を同時に観測する。

根拠資料:

- [ROS 2 Humble公式: rqt_graph](https://docs.ros.org/en/ros2_packages/humble/api/rqt_graph/index.html)
- [ROS 2 Humble公式: Recording and playing back data](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.html)
- [ROS 2公式: Executors](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Executors.html)


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
