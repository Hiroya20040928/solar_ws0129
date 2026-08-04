from __future__ import annotations

from pathlib import Path
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='mpc_solarcar',
            executable='solar_race_live_node',
            name='solar_race_live_node',
            output='screen',
            emulate_tty=True,
        ),
    ])
