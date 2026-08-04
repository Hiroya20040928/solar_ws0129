# Runtime Environment Snapshot

This repository currently assumes the following baseline runtime for reproducible simulation and validation work.

- Front-end: Windows PowerShell wrapper (`SolarSim.ps1`)
- Execution host: WSL2 Ubuntu 22.04
- ROS 2 distribution: Humble
- Python packages captured from the working validation environment:
  - `numpy==2.4.4`
  - `scipy==1.18.0`
  - `pandas==3.0.3`
  - `PyYAML==6.0.3`
  - `matplotlib==3.10.9`
  - `casadi==3.7.2`
  - `pytest==9.0.3`
- System package expected from ROS / apt side:
  - `python3-can`

Use `requirements-dev.txt` for the Python-side snapshot, and pair it with the ROS 2 Humble / Ubuntu 22.04 environment for regression testing.
