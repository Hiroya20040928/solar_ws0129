from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
def generate_launch_description():
    pkg_share = FindPackageShare('mpc_solarcar')
    return LaunchDescription([
        Node(package='mpc_solarcar', executable='gps_sim_node', name='gps_sim_node',
             parameters=[{'route_csv': PathJoinSubstitution([pkg_share, 'inputs', 'route_waypoints.csv']),
                          'dt': 1.0, 'init_speed_kmh': 40.0}]),
        Node(package='mpc_solarcar', executable='mpc_node', name='mpc_node',
             parameters=[{'forecast_csv': PathJoinSubstitution([pkg_share, 'inputs', 'forecast_10min.csv']),
                          'maps_dir': PathJoinSubstitution([pkg_share, 'maps']),
                          'drive_map_eco': PathJoinSubstitution([pkg_share, 'maps', 'drive_eff_map_eco.csv']),
                          'drive_map_power': PathJoinSubstitution([pkg_share, 'maps', 'drive_eff_map_power.csv']),
                          'regen_map_eco': PathJoinSubstitution([pkg_share, 'maps', 'regen_eff_map_eco.csv']),
                          'regen_map_power': PathJoinSubstitution([pkg_share, 'maps', 'regen_eff_map_power.csv']),
                          'params_yaml': PathJoinSubstitution([pkg_share, 'inputs', 'solar_params.yaml']),
                          'panel_eff_map': PathJoinSubstitution([pkg_share, 'maps', 'panel_eff_map.csv']),
                          'mppt_eff_map': PathJoinSubstitution([pkg_share, 'maps', 'mppt_eff_map.csv']),
                          'route_profile_csv': PathJoinSubstitution([pkg_share, 'inputs', 'route_profile.csv']),
                          'speed_profile_csv': PathJoinSubstitution([pkg_share, 'inputs', 'speed_profile.csv']),
                          'drive_schedule_yaml': PathJoinSubstitution([pkg_share, 'inputs', 'drive_schedule.yaml']),
                          'dt': 600.0, 'horizon_steps': 9,
                          'forecast_time_tz': 'Australia/Darwin',
                          'hierarchical': True,
                          'lower_dt': 1.0,
                          'lower_horizon_steps': 30,
                          'lower_rate_hz': 5.0,
                          'forecast_time_mode': 'relative'}]),
        Node(package='mpc_solarcar', executable='dashboard_node', name='dashboard_node',
             parameters=[{'host': '0.0.0.0', 'port': 8080}]),
    ])
