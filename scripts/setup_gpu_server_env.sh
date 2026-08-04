#!/usr/bin/env bash
set -euo pipefail

UV_VERSION="${UV_VERSION:-0.11.28}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
VENV_PATH="${MPC_GPU_VENV:-$HOME/.venvs/mpc_gpu}"
UV_PATH="$HOME/.local/bin/uv"

mkdir -p "$HOME/.local/bin" "$HOME/.venvs"
if [[ ! -x "$UV_PATH" ]]; then
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
    | env UV_UNMANAGED_INSTALL="$HOME/.local/bin" sh
fi

"$UV_PATH" python install "$PYTHON_VERSION"
"$UV_PATH" venv "$VENV_PATH" --python "$PYTHON_VERSION"
"$UV_PATH" pip install --python "$VENV_PATH/bin/python" \
  numpy pandas matplotlib scipy pyyaml
"$UV_PATH" pip install --python "$VENV_PATH/bin/python" \
  torch==2.5.1 --index-url https://download.pytorch.org/whl/cu124

"$VENV_PATH/bin/python" -c \
  'import torch; print(torch.__version__, torch.version.cuda)'

cat <<EOF
Environment ready: $VENV_PATH
Run GPU programs through Slurm, for example:
  srun --partition=lab_gpu --gres=gpu:1 --cpus-per-task=2 --mem=8G \\
    --time=00:03:00 $VENV_PATH/bin/python -c \\
    'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))'
EOF
