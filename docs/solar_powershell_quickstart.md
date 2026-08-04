# Solar PowerShell Quickstart

通常の入口はこれです。

```powershell
.\SolarSim.ps1
```

よく使う呼び方:

```powershell
.\SolarSim.ps1 -Mode sim -Action up
.\SolarSim.ps1 -Action simulate
.\SolarSim.ps1 -Mode measure -Action up
.\SolarSim.ps1 -Mode live -Action up
.\SolarSim.ps1 -Mode sim -Action graph
.\SolarSim.ps1 -Mode sim -Action stop
```

既定 profile:

```text
config/solar/bwsc_2027_demo.yaml
```

別 profile を使うとき:

```powershell
.\SolarSim.ps1 -Profile config/solar/bwsc_2027_demo.yaml -Mode live -Action up
```

全体の流れと必要データは [`docs/solar_workflow.md`](./solar_workflow.md) を見てください。
