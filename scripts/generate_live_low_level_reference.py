"""Generate the line-level live/live_wifi implementation reference.

The report is derived from the selected distribution tree so source listings,
line numbers, ROS interfaces, parameters, and function call summaries remain
synchronized with the package that operators actually receive.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


LIVE_FILES = (
    "SolarSim.ps1",
    "scripts/solar_control.sh",
    "launch/solar_race_live.launch.py",
    "launch/solar_race_live_wifi.launch.py",
    "mpc_solarcar/live_launch.py",
    "mpc_solarcar/solar_profile.py",
    "mpc_solarcar/path_utils.py",
    "mpc_solarcar/mpc_node.py",
    "mpc_solarcar/model.py",
    "mpc_solarcar/utils_maps.py",
    "mpc_solarcar/route_utils.py",
    "mpc_solarcar/schedule_utils.py",
    "mpc_solarcar/forecast_grid.py",
    "mpc_solarcar/upper_policy.py",
    "mpc_solarcar/upper_cost.py",
    "mpc_solarcar/upper_horizon.py",
    "mpc_solarcar/upper_solver.py",
    "mpc_solarcar/estimator.py",
    "mpc_solarcar/signal_utils.py",
    "mpc_solarcar/solar_preflight_logic.py",
    "mpc_solarcar/solar_preflight_node.py",
    "mpc_solarcar/distance_node.py",
    "mpc_solarcar/grade_node.py",
    "mpc_solarcar/weather_utils.py",
    "mpc_solarcar/weather_fetch_node.py",
    "mpc_solarcar/solar_autocal_logic.py",
    "mpc_solarcar/solar_autocal_node.py",
    "mpc_solarcar/speed_command_bridge_node.py",
    "mpc_solarcar/telemetry_protocol.py",
    "mpc_solarcar/telemetry_text_bridge_node.py",
    "mpc_solarcar/wind_correction_node.py",
    "mpc_solarcar/solar_logger_node.py",
    "mpc_solarcar/dashboard_node.py",
    "dashboard/index.html",
    "dashboard/app.js",
    "dashboard/style.css",
    "grafana/docker-compose.yml",
    "grafana/prometheus.yml",
    "grafana/provisioning/dashboards/dashboards.yml",
    "grafana/provisioning/datasources/prometheus.yml",
    "grafana/dashboards/solarcar-ems.json",
    "config/solar/bwsc_2027_demo.yaml",
    "package.xml",
    "setup.py",
)


@dataclass
class FunctionRecord:
    file: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: str
    calls: list[str]
    attributes_read: list[str]
    attributes_written: list[str]


@dataclass
class RosRecord:
    file: str
    line: int
    kind: str
    data_type: str
    name_or_topic: str
    callback_or_default: str


def source_expr(source: str, node: ast.AST | None) -> str:
    if node is None:
        return ""
    return (ast.get_source_segment(source, node) or ast.dump(node, include_attributes=False)).strip()


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def function_signature(source: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    first = source.splitlines()[node.lineno - 1].strip()
    if first.startswith(("def ", "async def ")) and first.endswith(":"):
        return first[:-1]
    names = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args)]
    if node.args.vararg is not None:
        names.append("*" + node.args.vararg.arg)
    elif node.args.kwonlyargs:
        names.append("*")
    names.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg is not None:
        names.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(names)})"


class FunctionFacts(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: set[str] = set()
        self.reads: set[str] = set()
        self.writes: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node.func)
        if name:
            self.calls.add(name)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            if isinstance(node.ctx, ast.Store):
                self.writes.add(node.attr)
            elif isinstance(node.ctx, ast.Load):
                self.reads.add(node.attr)
        self.generic_visit(node)


def iter_functions(tree: ast.AST) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for top in getattr(tree, "body", []):
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield top.name, top
        elif isinstance(top, ast.ClassDef):
            for item in top.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{top.name}.{item.name}", item


def ros_records(path: Path, rel: str, source: str, tree: ast.AST) -> list[RosRecord]:
    out: list[RosRecord] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method == "declare_parameter" and node.args:
            out.append(
                RosRecord(
                    rel,
                    node.lineno,
                    "parameter",
                    "",
                    source_expr(source, node.args[0]),
                    source_expr(source, node.args[1]) if len(node.args) > 1 else "",
                )
            )
        elif method in {"create_publisher", "create_subscription"} and len(node.args) >= 2:
            callback = source_expr(source, node.args[2]) if method == "create_subscription" and len(node.args) > 2 else ""
            out.append(
                RosRecord(
                    rel,
                    node.lineno,
                    "publisher" if method == "create_publisher" else "subscription",
                    source_expr(source, node.args[0]),
                    source_expr(source, node.args[1]),
                    callback,
                )
            )
        elif method == "create_timer" and node.args:
            out.append(
                RosRecord(
                    rel,
                    node.lineno,
                    "timer",
                    "period [s]",
                    source_expr(source, node.args[0]),
                    source_expr(source, node.args[1]) if len(node.args) > 1 else "",
                )
            )
    return out


def analyze(package_root: Path) -> tuple[list[FunctionRecord], list[RosRecord], list[dict]]:
    functions: list[FunctionRecord] = []
    ros: list[RosRecord] = []
    files: list[dict] = []
    for rel in LIVE_FILES:
        path = package_root / rel
        if not path.is_file():
            files.append({"path": rel, "exists": False, "lines": 0, "bytes": 0})
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        files.append(
            {
                "path": rel,
                "exists": True,
                "lines": len(source.splitlines()),
                "bytes": path.stat().st_size,
            }
        )
        if path.suffix != ".py":
            continue
        tree = ast.parse(source, filename=str(path))
        ros.extend(ros_records(path, rel, source, tree))
        for qualified, node in iter_functions(tree):
            facts = FunctionFacts()
            facts.visit(node)
            functions.append(
                FunctionRecord(
                    file=rel,
                    qualified_name=qualified,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    signature=function_signature(source, node),
                    calls=sorted(facts.calls),
                    attributes_read=sorted(facts.reads - facts.writes),
                    attributes_written=sorted(facts.writes),
                )
            )
    return functions, ros, files


def tex_escape(value: object) -> str:
    text = str(value)
    table = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(table.get(ch, ch) for ch in text)


def short_join(values: list[str], limit: int = 16) -> str:
    if not values:
        return "--"
    shown = values[:limit]
    suffix = f"; ... (+{len(values) - limit})" if len(values) > limit else ""
    return "; ".join(shown) + suffix


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def manual_body() -> str:
    return r"""
\chapter{実行入口}
\section{PowerShellからROS 2まで}
\begin{enumerate}[leftmargin=2.4em]
\item Windows PowerShellが \texttt{SolarSim.ps1} の引数を検証する。
\item \texttt{Resolve-WslDistro} がWSL distributionを決める。
\item Windows pathを \texttt{wslpath -a} でLinux pathへ変換する。
\item WSL内で \texttt{scripts/solar\_control.sh up live\_wifi <profile>} を実行する。
\item \texttt{colcon build --packages-select mpc\_solarcar} を実行する。
\item 既存launch processを停止する。
\item \texttt{ros2 launch mpc\_solarcar solar\_race\_live\_wifi.launch.py profile\_yaml:=...} を別process groupで起動する。
\item dashboard APIが応答するまでWindows側が最大90秒待つ。
\item DockerがあればPrometheusとGrafanaを起動し、なければ内蔵dashboardを開く。
\item rqt graph exporterが実際に存在するnode/topicを取得する。
\end{enumerate}

\section{標準コマンド}
\begin{lstlisting}
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Action up -Mode live_wifi `
  -Profile project_packages/<vehicle>/profile.yaml
\end{lstlisting}
\texttt{-Mode live} はROS topicを外部装置が直接publishする構成である。\texttt{-Mode live\_wifi} はUDP JSON文字列を \texttt{telemetry\_text\_bridge\_node} がROS topicへ変換する構成である。

\section{profile pathの解決}
相対pathはprofile YAML自身のdirectoryを基準にする。root基準ではない。計算は
\[
p_{\mathrm{resolved}}=\operatorname{resolve}(p_{\mathrm{profile.parent}},p_{\mathrm{yaml}})
\]
である。値の優先順位は、node内既定値、profileの\texttt{model/mpc/live}、launchが明示するruntime値、ROS launch overrideの順である。

\section{live採用profileの境界}
\texttt{config/solar/bwsc\_2027\_demo.yaml}と\texttt{project\_packages/bwsc2027\_template/profile.yaml}は入力schemaであり、車両定数0のままではpreflightを通さない。\texttt{bwsc2025\_fitted\_mle13\_grounded\_segmented}は履歴再現用で、受入資料の\texttt{high\_precision\_claim\_allowed=false}によりlive採用外である。live投入条件は、同定後の受入YAMLで\texttt{fullsim\_adoption\_gate\_pass=true}かつ\texttt{high\_precision\_claim\_allowed=true}、静的監査ERROR 0、実機preflight RUNNINGの全成立である。

\chapter{起動nodeと条件}
\begin{longtable}{p{0.26\linewidth}p{0.18\linewidth}p{0.48\linewidth}}
\toprule
node & 起動条件 & 処理\\\midrule
\endhead
solar\_preflight\_node & 常時 & 必須telemetryとplanner statusの鮮度を1秒周期で判定する。\\
mpc\_node & 常時 & 1時間級上位再計画、1秒級下位追従、物理model、制約判定を実行する。\\
dashboard\_node & 常時 & ROS値を共有stateへ格納しHTTP \texttt{/api/state} とPrometheus \texttt{/metrics} を公開する。\\
solar\_logger\_node & 常時 & profile指定rateでCSVへ時系列を書き込む。\\
\path{speed_command_bridge_node} & \path{command_bridge.enabled} & planner指令を安全gate、平滑化、rate limit後にROS/UDPへ出す。\\
\path{distance_node} & \path{use_distance_node} & 実測速度を時間積分して距離をpublishする。\\
\path{grade_node} & \path{use_grade_node} & 高度差と距離差から勾配を計算する。\\
\path{weather_fetch_node} & \path{weather.enabled} & chase GPS地点の予報を取得してruntime CSVをatomic replaceする。\\
\path{solar_autocal_node} & \path{autocal.enabled} & 太陽光gain、走行power gain、補機powerを限定条件下で逐次更新する。\\
\path{telemetry_text_bridge_node} & live\_wifiかつ\path{wifi_bridge.enabled} & UDP受信、timestamp検査、値域/rate検査、filter、ROS変換、返信を行う。\\
\path{wind_correction_node} & live\_wifiかつ\path{wind_model.enabled} & 実測向かい風誤差を距離相関で予報CSV全体へ伝播する。\\
\bottomrule
\end{longtable}

\chapter{時系列}
\section{process開始から定常周期まで}
\begin{longtable}{p{0.14\linewidth}p{0.28\linewidth}p{0.50\linewidth}}
\toprule
時刻 & 実行主体 & 処理\\\midrule
\endhead
$t=0$ & launch & profile読込、予報runtime fileの初期copy、node action生成。\\
$t\approx0$ & 各node constructor & parameter宣言、map/route/weather読込、publisher/subscriber/timer生成。\\
$t=0$--10 s & preflight & \texttt{STARTING}。command gateは安全速度を出す。\\
20 Hz & Wi-Fi bridge & non-blocking UDP socketをpollする。\\
5 Hz標準 & command bridge & gate、一次遅れ、加減速limit、量子化、publish。\\
2 Hz標準 & logger/distance & CSV保存、速度積分距離。\\
1 Hz & preflight & missing/stale判定。\\
1 Hz標準 & lower MPC & 現在速度から短期torque列を最適化して先頭指令をpublish。\\
1 s監視 & upper callback & 初回、再計画時刻、予報更新条件で長距離MPCを実行。\\
30 s標準 & autocal/wind & calibration更新、風補正CSV更新。\\
3600 s標準 & weather & 最新予報取得。\\
200 ms & browser & \texttt{/api/state}を取得して画面更新。\\
1 s & Prometheus & \texttt{/metrics}をscrapeしGrafanaへ供給。\\
\bottomrule
\end{longtable}

\section{並行性}
\path{mpc_node} は4 thread executorを使う。callback groupは次の4本である。
\begin{lstlisting}[numbers=none]
telemetry_callback_group : sensor reception
upper_callback_group     : long-horizon MPC
lower_callback_group     : short-horizon MPC
command_callback_group   : command publication
\end{lstlisting}
各group内は直列、異なるgroupは並行である。長い上位探索中もtelemetry callbackと下位指令周期を継続する。

\chapter{UDP文字列から状態量まで}
\section{受信packet}
UTF-8 JSONを1 datagram 1 packetで送る。最低限timestampを含める。
\begin{lstlisting}
{"source":"solar","ts_unix":1810000000.25,
 "vehicle":{"speed_kmh":70.2,"soc":0.73,"batt_voltage_v":89.1,
 "batt_current_a":8.7,"batt_temp_c":28.4,"solar_power_w":430.0,
 "latitude":-20.1,"longitude":133.2,"altitude_m":310.0}}
\end{lstlisting}
chase側は \texttt{source=chase} とし、GPS、風速、風向、進行方向を送る。packetはmissing timestamp、古すぎる、未来、duplicate、許容外out-of-orderの順に拒否される。

\section{timestamp判定}
\[
a=t_{\mathrm{receive}}-t_{\mathrm{source}}
\]
\[
\mathrm{accept}\iff -a_{\mathrm{future,max}}\le a\le a_{\mathrm{max}}
\land t_{\mathrm{source}}>t_{\mathrm{last}}-\Delta t_{\mathrm{reorder}}
\]
同一timestampはduplicateとして拒否する。PC、solar Raspberry Pi、chase Raspberry PiはNTPでUTCを同期する。

\section{一次遅れfilterとslew limit}
入力$x$、前回出力$y_{k-1}$、時刻差$\Delta t$、時定数$\tau$に対し
\[
\alpha=1-\exp(-\Delta t/\tau),\qquad
\tilde y_k=y_{k-1}+\alpha(x_k-y_{k-1}).
\]
上昇率$r_+$、下降率$r_-$を使い
\[
y_k=y_{k-1}+\operatorname{clip}(\tilde y_k-y_{k-1},-r_-\Delta t,r_+\Delta t)
\]
とする。最後に値域clip、deadband、量子化を適用する。

\chapter{距離と勾配}
\section{距離積分}
速度$v_k$ [km/h]を受けた時刻差を$\Delta t$ [s]として
\[
s_{k+1}=s_k+\frac{v_k}{3600}\min(\Delta t,\Delta t_{\max}).
\]
timerは保存済み$s$をpublishする。reset serviceは$s=0$へ戻す。

\section{勾配}
高度をEMAで
\[
h_f\leftarrow h_f+\alpha_h(h-h_f)
\]
とし、$\Delta s$が閾値以上かつ速度が閾値以上のとき
\[
g_{\%}=100\frac{h_{f,k}-h_{f,k-1}}{1000(s_k-s_{k-1})}
\]
をpublishする。GPS高度と専用高度topicの後着値が入力になる。

\chapter{天候取得と風補正}
\section{予報CSV}
weather nodeは現在のchase GPS、未受信時はfallback緯度経度を使う。Open-Meteo応答を指定stepへ補間し、temporary fileへ書いてから置換する。MPCは\texttt{forecast\_reload\_sec}ごとにmtimeを確認し、変更時だけ再読込する。

\section{cell温度近似}
\[
T_{\mathrm{cell}}=T_{\mathrm{amb}}+k_T G_{\mathrm{POA}}
\]
である。$k_T$はprofileの\texttt{live.weather.tcell\_gain}から入る。

\section{向かい風成分}
風向$\psi_w$、進行方向$\psi_c$、風速$u_w$に対し、source定義に合わせて
\[
u_h=u_w\cos(\psi_w-\psi_c)
\]
を得る。符号規約は正を向かい風とし、bridgeで\texttt{max\_abs\_headwind\_ms}へclipする。

\section{距離相関補正}
現在地点$s_0$の残差$e_0=u_{h,\mathrm{meas}}-u_{h,\mathrm{forecast}}$を
\[
e(s)=e_0\exp\left(-\frac{|s-s_0|}{L_c}\right)
\]
で伝播する。予報分散は予測時間と共に増やし、指定quantileでplanner用風速を作る。

\chapter{車両物理model}
\section{空気密度}
constant modeでは$\rho$を直接使う。ideal-gas-altitude modeでは
\[
p(h)=p_0\left(1-\frac{0.0065h}{288.15}\right)^{5.255877},\qquad
\rho=\frac{p(h)}{287.05(T_{\mathrm{amb}}+273.15)}.
\]

\section{走行抵抗}
\[
v_r=\max(0,v+u_h),\quad \theta=\tan^{-1}(g_{\%}/100)
\]
\[
F_a=\frac12\rho C_dA v_r^2,\quad
F_r=C_{rr}mg\cos\theta,\quad
F_g=mg\sin\theta.
\]
\[
P_{\mathrm{road}}=(F_a+F_r+F_g)v,\qquad
P_{\mathrm{wheel}}=P_{\mathrm{road}}+P_{\mathrm{inertia}}.
\]
空力抵抗は対気速度で求め、仕事率は対地速度を掛ける。

\section{motor map}
\[
\omega_w=v/r_w,\quad T_w=P_{\mathrm{wheel}}/(\omega_w+10^{-3}),
\quad T_m=T_w/i_g.
\]
CSV格子$(v,T)$の4点から双線形補間して$\eta_d$または$\eta_r$を得る。駆動時
\[
P_{dc,d}=\frac{\max(P_{\mathrm{wheel}},0)}{\eta_d\eta_g\eta_{inv}},
\]
回生時
\[
P_{dc,r}=u_r\eta_r\eta_g\eta_{inv}\max(-P_{\mathrm{wheel}},0).
\]

\section{太陽電池}
mapがあれば$(G,T_c)$で$\eta_p$と$\eta_{mppt}$を双線形補間する。なければ
\[
\eta_p=\max\{0,\eta_{ref}[1+\mu_p(T_c-25)]\}g_p.
\]
\[
P_{pv,raw}=\eta_p A_{pv}G,\quad
P_{pv}=\min(P_{pv,raw}\eta_{mppt},P_{pv,max}).
\]

\section{pack電力と電池}
\[
P_{pack}=P_{dc,d}-P_{dc,r}+P_{aux}-P_{pv}.
\]
\[
R_t=R_{int}(T,z)+R_{line}+R_p,\quad
P_{pack}=I(V_{oc}-IR_t).
\]
低電流側の根を選び
\[
I=\frac{V_{oc}-\sqrt{V_{oc}^2-4R_tP_{pack}}}{2R_t},\qquad
V=V_{oc}-IR_t.
\]
$Q_{nom}>0$ならcoulomb counting
\[
z_{k+1}=z_k-\eta_c\frac{I_k\Delta t}{3600Q_{nom}},
\]
未設定のlegacy profileだけenergy integrationを使う。

\section{補機電力}
走行中は$P_{aux}$、停止かつ夜間閾値以下は$P_{aux,night}$、停止昼間は$P_{aux,stopped}$を使う。夜間0 W設定はここで実現する。

\chapter{上位MPC}
\section{距離離散化}
残距離を固定4分割しない。\texttt{upper\_horizon.py}が最小/最大距離刻み、成長率、control point、最大step数から境界$s_i$を生成する。各区間の決定変数は速度$v_i$である。
\[
\Delta t_i=\frac{1000(s_{i+1}-s_i)}{v_i/3.6}.
\]
route勾配、標高、速度制限は区間平均または補間、予報は$(t,s)$格子補間で得る。

\section{状態遷移}
各区間で物理modelから$P_{pack},I,V$を計算し、SoCと温度を進める。走行可能時間外はscheduleが次の開始まで待機時間を挿入し、停止時太陽光と補機でSoCを進める。control stopはstop定義のhold時間を挿入する。

\section{目的関数}
\texttt{objective\_mode=fastest\_feasible}では
\[
J=\sum_i(\Delta t_{travel,i}+w_{wait}\Delta t_{wait,i})
+c\sum_j[\max(0,g_j)]^2
\]
である。$g_j$は速度、SoC、電流、電圧、温度、走行時間帯、終端条件の違反量である。weighted modeはさらに速度平滑、電流二乗、pack energy、Joule損、空力energy、機械energy、pack power slew、SoC barrier等を加える。全項の実装は本書の\texttt{upper\_cost.py}全文と関数表を参照する。

\section{探索}
\begin{enumerate}[leftmargin=2.4em]
\item 前回解またはinitial upper policyをhorizonへ補間する。
\item 決定論的seedと物理seedを生成する。
\item CEMがbounded populationを評価しelite平均・分散を更新する。
\item 上位候補をL-BFGS-Bで局所refineする。
\item 設定時はSHGOまたは有限grid証明を追加する。
\item 目的値最小のfinite feasible candidateを採用する。
\end{enumerate}
MPCは一度作った2025速度列を2027へ固定適用しない。vehicle modelは同定済み資産として共用するが、2027予報と現在状態で上位問題を再構成する。

\chapter{下位MPCと指令}
\section{reference}
上位距離計画$v^U(s)$を現在距離から1秒刻みでsampleし、加速上限、減速上限、deadbandで整形して$v^{ref}_{0:N}$を作る。

\section{下位目的関数}
制御変数はmotor torque列$u_{0:N-1}$である。
\[
J_L=\sum_{k=0}^{N-1}\left[
w_t(v_k-v^{ref}_k)^2+w_u u_k^2+w_{\Delta u}(u_k-u_{k-1})^2
\right].
\]
\[
v_{k+1}=\max\left(0,v_k+\frac{F_{trac}(u_k)-F_{res}(v_k)}{m}\Delta t\right).
\]
L-BFGS-Bにtorque boundsを渡し、先頭torqueから速度指令、throttle、drive modeをpublishする。

\section{外部指令gate}
許可条件は
\[
t-t_0\ge t_{hold},\quad a_{speed}\le a_{speed,max},\quad
state=\mathrm{RUNNING},\quad a_{state}\le a_{state,max}.
\]
一つでも偽ならtargetは\texttt{safe\_speed\_kmh}、modeは\texttt{stop}である。速度とmodeの受信時刻は別に保持する。平滑化後にROS output topicと任意UDPへ出す。

\chapter{MHEと自動校正}
\section{battery MHE}
window内の入力$P_{pack},T_{amb}$と観測$V,T_b$を使い、初期$z_0,T_{b,0}$をbounded optimizationする。
\[
J_{MHE}=\sum_k w_V(V_k-\hat V_k)^2+w_T(T_{b,k}-\hat T_{b,k})^2
+w_z(z_0-z_{prior})^2.
\]
推定失敗または観測不足時はfilter済み実測/内部状態を維持する。

\section{autocal}
停止昼間で太陽光powerの比からsolar gain、十分な走行速度で実測pack powerとmodel metricの比からdrive gain、条件成立時だけ補機推定をEMA更新する。各gainはYAMLのmin/maxでclipする。校正topicをMPCが受け、model overrideへ反映する。

\chapter{保存と表示}
\section{CSV logger}
ROS callbackは共有dictionaryを更新し、timerだけが1行を書き込む。1行にはUTC、距離、上位/下位/出力/実測速度、SoC、温度、電圧、電流、環境、power、system state、diagnosticを含む。書込周期は\texttt{logging.log\_rate\_hz}である。

\section{内蔵dashboard}
dashboard nodeはROS値をlock付きstateへ保存する。HTTP threadはJSON snapshotを返す。browserは200 ms周期で取得する。表示値は制御入力ではない。

\section{Grafana}
dashboard nodeの\texttt{/metrics}をPrometheusが1秒周期で取得し、Grafana provisioned dashboardが表示する。Grafana停止やbrowser停止はROS制御processへ影響しない。

\chapter{1周期の数値計算}
\section{入力}
$m=235$ kg、$C_dA=0.11$ m$^2$、$C_{rr}=0.008$、$\rho=1.18$ kg/m$^3$、$v=70$ km/h、向かい風2 m/s、勾配0、$\eta_d=0.92$、$\eta_g=1$、$\eta_{inv}=0.98$、$P_{aux}=21$ W、$P_{pv}=400$ Wとする。

\section{抵抗と電力}
\[
v=70/3.6=19.444\ \mathrm{m/s},\quad v_r=21.444\ \mathrm{m/s}
\]
\[
F_a=0.5\times1.18\times0.11\times21.444^2=29.82\ \mathrm{N}
\]
\[
F_r=0.008\times235\times9.80665=18.44\ \mathrm{N}
\]
\[
P_{road}=(29.82+18.44)\times19.444=938.4\ \mathrm{W}
\]
\[
P_{dc,d}=938.4/(0.92\times0.98)=1040.9\ \mathrm{W}
\]
\[
P_{pack}=1040.9+21-400=661.9\ \mathrm{W}.
\]

\section{電池とSoC}
$V_{oc}=92$ V、$R_t=0.10\ \Omega$とすると
\[
I=\frac{92-\sqrt{92^2-4\times0.10\times661.9}}{0.20}=7.25\ \mathrm{A},
\quad V=91.28\ \mathrm{V}.
\]
$Q_{nom}=33$ Ah、$\Delta t=1$ sなら
\[
\Delta z=-\frac{7.25}{3600\times33}=-6.10\times10^{-5}.
\]
この結果を制約、logger、dashboardへ同じ周期で渡す。

\chapter{故障時遷移}
\begin{longtable}{p{0.27\linewidth}p{0.28\linewidth}p{0.37\linewidth}}
\toprule
事象 & 検出 & 出力\\\midrule
\endhead
速度packet欠落 & speed age $>$ timeout & safe speedへrate制限、mode stop。\\
preflight DEGRADED & system state不一致 & 同上。\\
古いUDP packet & source timestamp age & packet破棄、statusへ理由。\\
異常jump & value/rate filter & clipまたは破棄、前回filter値維持。\\
予報API失敗 & exception/status & 既存runtime forecastを保持。\\
上位solver失敗 & finite/feasible検査 & 前回解またはfallback。\\
下位solver失敗 & optimizer result検査 & reference/fallback指令。\\
dashboard/Grafana停止 & HTTP/Dockerのみ & plannerとloggerは継続。\\
\bottomrule
\end{longtable}

\chapter{監査で修正した箇所}
\begin{longtable}{p{0.30\linewidth}p{0.30\linewidth}p{0.32\linewidth}}
\toprule
修正前 & 修正 & 効果\\\midrule
\endhead
配布生成時に巨大external docsをcopy後削除 & copy段階でignore & disk不足による生成失敗を防止。\\
現行MPC更新と配布snapshotが不一致 & solar依存だけ同期 & forecast grid、route平均、initial policy等を配布へ反映。\\
command bridgeのenabled未使用 & launch条件へ反映 & false指定nodeを起動しない。\\
wifi bridgeのenabled未使用 & launch条件へ反映 & false指定socketを開かない。\\
mode受信で速度鮮度も更新 & 受信時刻を分離 & 古い速度指令の延命を防止。\\
preflightは表示だけ & command gateへ接続 & DEGRADED時の速度出力を防止。\\
launch依存未宣言 & package.xmlへ追加 & clean ROS環境での依存解決を明示。\\
dashboardの年表示固定 & vehicle非依存表記 & 2027運用時の誤認防止。\\
相対importの同梱検査なし & ASTで全local importを解決 & \texttt{mpc\_node.py}から\texttt{estimator.py}等の欠落をERROR化。\\
PDF/fullsimの存在だけで fitted modelを配布 & 受入YAML二重gateを必須化 & 低精度MLE13/MLE19のlive誤採用を防止。\\
旧MLE13を検証済みlive入口と表記 & 歴史再現用へ明確化 & 物理契約15警告を未解決のまま運用しない。\\
\bottomrule
\end{longtable}
"""


def build_tex(package_root: Path, functions: list[FunctionRecord], ros: list[RosRecord], files: list[dict]) -> str:
    missing = [row["path"] for row in files if not row["exists"]]
    existing = [row for row in files if row["exists"]]
    total_lines = sum(row["lines"] for row in existing)
    generated = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    parts = [
        r"\documentclass[a4paper,10pt,oneside]{book}",
        r"\usepackage[top=14mm,bottom=16mm,left=15mm,right=15mm]{geometry}",
        r"\usepackage{fontspec}",
        r"\usepackage{xeCJK}",
        r"\setmainfont{Times New Roman}",
        r"\setCJKmainfont{Yu Gothic}",
        r"\setmonofont{Consolas}",
        r"\setCJKmonofont{Yu Gothic}",
        r"\usepackage{amsmath,amssymb,booktabs,longtable,array,tabularx,enumitem,pdflscape,seqsplit}",
        r"\usepackage[unicode,hidelinks]{hyperref}",
        r"\usepackage{listings}",
        r"\usepackage{fancyhdr}",
        r"\lstset{basicstyle=\ttfamily\fontsize{6.2}{7.3}\selectfont,breaklines=true,breakatwhitespace=false,columns=fullflexible,keepspaces=true,numbers=left,numberstyle=\tiny,numbersep=4pt,xleftmargin=12pt,framexleftmargin=10pt,frame=single,showstringspaces=false,tabsize=4}",
        r"\setlength{\parindent}{1em}",
        r"\setlength{\parskip}{0.25em}",
        r"\setlength{\emergencystretch}{3em}",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\pagestyle{fancy}\fancyhf{}\fancyhead[L]{SolarCar live implementation}\fancyhead[R]{\thepage}",
        r"\begin{document}",
        r"\frontmatter",
        r"\begin{titlepage}\centering\vspace*{25mm}{\Huge\bfseries ソーラーカーEMS\\live / live\_wifi\\実装・計算完全解説\par}\vspace{12mm}{\Large PowerShell入口から速度指令まで\par}\vfill",
        f"{{\\large 生成日時: {tex_escape(generated)}\\par}}",
        f"{{\\large 対象file: {len(existing)}、対象source行: {total_lines}\\par}}",
        r"\end{titlepage}",
        r"\tableofcontents",
        r"\mainmatter",
        manual_body(),
        r"\chapter{live到達file一覧}",
        r"\begin{longtable}{p{0.67\linewidth}r r}\toprule path & lines & bytes\\\midrule\endhead",
    ]
    for row in existing:
        parts.append(f"\\path{{{row['path']}}} & {row['lines']} & {row['bytes']}\\\\")
    parts.extend([r"\bottomrule\end{longtable}"])
    if missing:
        parts.append(r"\section{欠落file}")
        parts.append(r"\begin{itemize}")
        parts.extend(f"\\item \\texttt{{{tex_escape(item)}}}" for item in missing)
        parts.append(r"\end{itemize}")

    parts.extend(
        [
            r"\chapter{ROS interface完全表}",
            r"\begin{landscape}\tiny\setlength{\tabcolsep}{2pt}",
            r"\begin{longtable}{p{0.20\linewidth}r p{0.08\linewidth}p{0.14\linewidth}p{0.20\linewidth}p{0.26\linewidth}}",
            r"\toprule file & line & kind & type/period & topic/name & callback/default\\\midrule\endhead",
        ]
    )
    for row in sorted(ros, key=lambda r: (r.file, r.line, r.kind)):
        parts.append(
            f"\\seqsplit{{{tex_escape(row.file)}}} & {row.line} & {tex_escape(row.kind)} & "
            f"\\seqsplit{{{tex_escape(row.data_type)}}} & \\seqsplit{{{tex_escape(row.name_or_topic)}}} & "
            f"\\seqsplit{{{tex_escape(row.callback_or_default)}}}\\\\"
        )
    parts.append(r"\bottomrule\end{longtable}\end{landscape}")

    parts.append(r"\chapter{全関数の入出力・呼出関係}")
    current_file = None
    for record in sorted(functions, key=lambda r: (r.file, r.start_line)):
        if record.file != current_file:
            current_file = record.file
            parts.append(f"\\section{{\\texttt{{{tex_escape(current_file)}}}}}")
        facts = "\n".join(
            (
                f"signature: {record.signature}",
                f"calls: {short_join(record.calls)}",
                f"self read: {short_join(record.attributes_read)}",
                f"self write: {short_join(record.attributes_written)}",
            )
        )
        parts.extend(
            [
                f"\\subsection*{{{tex_escape(record.qualified_name)} [L{record.start_line}--L{record.end_line}]}}",
                r"\begin{lstlisting}[numbers=none]",
                facts,
                r"\end{lstlisting}",
            ]
        )

    parts.append(r"\appendix")
    parts.append(r"\chapter{live到達source全文}")
    for row in existing:
        rel = row["path"]
        parts.append(f"\\section{{\\texttt{{{tex_escape(rel)}}}}}")
        parts.append(f"\\lstinputlisting{{../../{rel}}}")
    parts.extend([r"\end{document}", ""])
    return "\n".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    package_root = args.package_root.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else package_root / "docs" / "live_low_level_reference"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    functions, ros, files = analyze(package_root)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_root": str(package_root),
        "files": files,
        "functions": [asdict(item) for item in functions],
        "ros_interfaces": [asdict(item) for item in ros],
    }
    (output_dir / "live_static_inventory.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(
        output_dir / "live_file_inventory.csv",
        files,
        ["path", "exists", "lines", "bytes"],
    )
    write_csv(
        output_dir / "live_function_inventory.csv",
        (
            {
                "file": row.file,
                "qualified_name": row.qualified_name,
                "start_line": row.start_line,
                "end_line": row.end_line,
                "signature": row.signature,
                "calls": " | ".join(row.calls),
                "attributes_read": " | ".join(row.attributes_read),
                "attributes_written": " | ".join(row.attributes_written),
            }
            for row in functions
        ),
        [
            "file",
            "qualified_name",
            "start_line",
            "end_line",
            "signature",
            "calls",
            "attributes_read",
            "attributes_written",
        ],
    )
    write_csv(
        output_dir / "live_ros_interface_inventory.csv",
        (asdict(row) for row in ros),
        ["file", "line", "kind", "data_type", "name_or_topic", "callback_or_default"],
    )
    tex = build_tex(package_root, functions, ros, files)
    (output_dir / "solarcar_live_low_level_reference.tex").write_text(tex, encoding="utf-8")
    print(output_dir)
    print(f"files={sum(1 for row in files if row['exists'])} functions={len(functions)} ros={len(ros)}")


if __name__ == "__main__":
    main()
