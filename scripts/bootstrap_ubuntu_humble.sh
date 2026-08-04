#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -r /etc/os-release ]]; then
  echo "This installer requires Ubuntu 22.04." >&2
  exit 2
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
  echo "Supported target: Ubuntu 22.04 with ROS 2 Humble; found ${PRETTY_NAME:-unknown}." >&2
  exit 2
fi

sudo apt-get update
sudo apt-get install -y \
  locales curl gnupg lsb-release software-properties-common
sudo add-apt-repository -y universe
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

if [[ ! -f /usr/share/keyrings/ros-archive-keyring.gpg ]]; then
  sudo curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
fi

arch="$(dpkg --print-architecture)"
repo_line="deb [arch=${arch} signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu jammy main"
echo "${repo_line}" | sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null

sudo apt-get update
sudo apt-get install -y \
  ros-humble-desktop ros-dev-tools ros-humble-rqt-graph \
  python3-numpy python3-scipy python3-pandas python3-yaml \
  python3-matplotlib python3-can python3-pip python3-pytest \
  graphviz git chrony

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  sudo rosdep init
fi
rosdep update

# CasADi has no consistent Jammy rosdep key, so install it explicitly.
python3 -m pip install --user "casadi>=3.6,<4"

cd "${ROOT_DIR}"
rosdep install --from-paths . --ignore-src -r -y --skip-keys=python3-casadi

set +u
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
set -u
colcon build --packages-select mpc_solarcar
python3 -m pytest -q

echo
echo "Installation and tests completed."
echo "Next: bash scripts/solar_control.sh up sim config/solar/bwsc_2027_demo.yaml"
