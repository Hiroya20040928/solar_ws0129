from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    can_interface = LaunchConfiguration('can_interface')
    log_dir = LaunchConfiguration('log_dir')
    stop_points_yaml = LaunchConfiguration('stop_points_yaml')
    v_ref_kmh = LaunchConfiguration('v_ref_kmh')
    v_min_kmh = LaunchConfiguration('v_min_kmh')
    v_max_kmh = LaunchConfiguration('v_max_kmh')
    w_fuel = LaunchConfiguration('w_fuel')
    w_speed = LaunchConfiguration('w_speed')
    w_dv = LaunchConfiguration('w_dv')
    w_dv_limit = LaunchConfiguration('w_dv_limit')
    dv_max_kmhps = LaunchConfiguration('dv_max_kmhps')
    w_stop = LaunchConfiguration('w_stop')
    panel_headless = LaunchConfiguration('panel_headless')

    return LaunchDescription([
        DeclareLaunchArgument('can_interface', default_value='can0'),
        DeclareLaunchArgument('log_dir', default_value='/tmp/passo_logs'),
        DeclareLaunchArgument('stop_points_yaml', default_value='inputs/stop_points.yaml'),
        DeclareLaunchArgument('v_ref_kmh', default_value='40.0'),
        DeclareLaunchArgument('v_min_kmh', default_value='0.0'),
        DeclareLaunchArgument('v_max_kmh', default_value='110.0'),
        DeclareLaunchArgument('w_fuel', default_value='1.0'),
        DeclareLaunchArgument('w_speed', default_value='0.3'),
        DeclareLaunchArgument('w_dv', default_value='0.2'),
        DeclareLaunchArgument('w_dv_limit', default_value='2.0'),
        DeclareLaunchArgument('dv_max_kmhps', default_value='4.0'),
        DeclareLaunchArgument('w_stop', default_value='10000.0'),
        DeclareLaunchArgument('panel_headless', default_value='false'),

        Node(
            package='mpc_solarcar',
            executable='can_obd_node',
            name='can_obd_node',
            parameters=[{'can_interface': can_interface}],
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
            parameters=[
                {'passo_mode': True},
                {'stop_yaml': stop_points_yaml},
                {'v_ref_kmh': v_ref_kmh},
                {'v_min_kmh': v_min_kmh},
                {'v_max_kmh': v_max_kmh},
                {'w_fuel': w_fuel},
                {'w_speed': w_speed},
                {'w_dv': w_dv},
                {'w_dv_limit': w_dv_limit},
                {'dv_max_kmhps': dv_max_kmhps},
                {'w_stop': w_stop},
            ],
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
