import os

from setuptools import setup


package_name = 'mpc_solarcar'


def collect_data_files(src_dir):                                   # [関数定義] collect_data_files の処理実行ブロック
    collected = []
    if not os.path.isdir(src_dir):
        return collected                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        if not files:
            continue
        collected.append((
            os.path.join('share', package_name, root),
            [os.path.join(root, f) for f in files],
        ))
    return collected                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却


data_files = [
    ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
    ('share/' + package_name, ['package.xml']),
]

for directory in ('launch', 'inputs', 'maps', 'docs', 'scripts', 'templates', 'dashboard', 'dashboard_magnetic_coupler', 'config', 'data'):
    data_files.extend(collect_data_files(directory))


setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=data_files,
    install_requires=[
        'setuptools',
        'numpy',
        'scipy',
        'pandas',
        'pyyaml',
        'matplotlib',
        'python-can',
        'casadi',
    ],
    zip_safe=True,
    maintainer='you',
    maintainer_email='you@example.com',
    description='ROS2 nodes for solar car MPC with simulated GPS and a simple control panel.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'gps_sim_node = mpc_solarcar.gps_sim_node:main',
            'mpc_node = mpc_solarcar.mpc_node:main',
            'panel_node = mpc_solarcar.panel_node:main',
            'dashboard_node = mpc_solarcar.dashboard_node:main',
            'solar_state_node = mpc_solarcar.solar_state_node:main',
            'can_obd_node = mpc_solarcar.can_obd_node:main',
            'distance_node = mpc_solarcar.distance_node:main',
            'logger_node = mpc_solarcar.logger_node:main',
            'preflight_node = mpc_solarcar.preflight_node:main',
            'config_wizard_node = mpc_solarcar.config_wizard_node:main',
            'throttle_advisory_node = mpc_solarcar.throttle_advisory_node:main',
            'grade_node = mpc_solarcar.grade_node:main',
            'weather_fetch_node = mpc_solarcar.weather_fetch_node:main',
            'solar_autocal_node = mpc_solarcar.solar_autocal_node:main',
            'speed_command_bridge_node = mpc_solarcar.speed_command_bridge_node:main',
            'telemetry_text_bridge_node = mpc_solarcar.telemetry_text_bridge_node:main',
            'wind_correction_node = mpc_solarcar.wind_correction_node:main',
            'magnet_field_viewer = mpc_solarcar.magnet_field_viewer:main',
            'magnetic_coupler_rl = mpc_solarcar.magnetic_coupler_rl:main',
            'magnetic_coupler_hifi = mpc_solarcar.magnetic_coupler_hifi:main',
            'magnetic_coupler_dashboard = mpc_solarcar.magnetic_coupler_dashboard:main',
            'magnetic_coupler_cad = mpc_solarcar.magnetic_coupler_cad:main',
        ],
    },
)
