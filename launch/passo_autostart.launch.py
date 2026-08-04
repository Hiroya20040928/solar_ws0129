from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    can_interface = LaunchConfiguration('can_interface')
    log_dir = LaunchConfiguration('log_dir')
    config_path = LaunchConfiguration('config_path')
    force_wizard = LaunchConfiguration('force_wizard')
    no_save = LaunchConfiguration('no_save')
    cli_only = LaunchConfiguration('cli_only')
    manage_can = LaunchConfiguration('manage_can_interface')
    panel_headless = LaunchConfiguration('panel_headless')

    return LaunchDescription([
        DeclareLaunchArgument('can_interface', default_value='can0'),
        DeclareLaunchArgument('log_dir', default_value='/tmp/passo_logs'),
        DeclareLaunchArgument('config_path', default_value='~/.config/mpc_solarcar/passo_config.yaml'),
        DeclareLaunchArgument('force_wizard', default_value='false'),
        DeclareLaunchArgument('no_save', default_value='false'),
        DeclareLaunchArgument('cli_only', default_value='false'),
        DeclareLaunchArgument('manage_can_interface', default_value='false'),
        DeclareLaunchArgument('panel_headless', default_value='false'),

        Node(
            package='mpc_solarcar',
            executable='preflight_node',
            name='preflight_node',
            parameters=[{'can_interface': can_interface},
                        {'manage_can_interface': manage_can}],
        ),
        Node(
            package='mpc_solarcar',
            executable='config_wizard_node',
            name='config_wizard_node',
            parameters=[
                {'config_path': config_path},
                {'force_wizard': force_wizard},
                {'no_save': no_save},
                {'cli_only': cli_only},
            ],
        ),
        Node(
            package='mpc_solarcar',
            executable='can_obd_node',
            name='can_obd_node',
            parameters=[
                {'can_interface': can_interface},
                {'enabled': False},
            ],
        ),
        Node(
            package='mpc_solarcar',
            executable='distance_node',
            name='distance_node',
        ),
        Node(
            package='mpc_solarcar',
            executable='grade_node',
            name='grade_node',
        ),
        Node(
            package='mpc_solarcar',
            executable='mpc_node',
            name='mpc_node',
            parameters=[{'passo_mode': True}],
        ),
        Node(
            package='mpc_solarcar',
            executable='throttle_advisory_node',
            name='throttle_advisory_node',
        ),
        Node(
            package='mpc_solarcar',
            executable='panel_node',
            name='panel_node',
            parameters=[{'headless': panel_headless}],
        ),
        Node(
            package='mpc_solarcar',
            executable='logger_node',
            name='logger_node',
            parameters=[{'log_dir': log_dir}],
        ),
    ])
