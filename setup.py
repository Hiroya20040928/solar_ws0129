import os
from setuptools import setup

package_name = 'mpc_solarcar'

def collect_data_files(src_dir):
    collected = []
    if not os.path.isdir(src_dir):
        return collected
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        if not files:
            continue
        collected.append((
            os.path.join('share', package_name, root),
            [os.path.join(root, f) for f in files],
        ))
    return collected

data_files = [
    ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
    ('share/' + package_name, ['package.xml']),
]

for directory in ('launch', 'inputs', 'maps', 'docs', 'scripts', 'templates', 'config', 'data'):
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
    description='Ultimate All-in-One Solar Car MPC execution package.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'solar_race_live_node = mpc_solarcar.solar_race_live_node:main',
            'solar_macro_planner_node = mpc_solarcar.solar_macro_planner_node:main',
        ],
    },
)
