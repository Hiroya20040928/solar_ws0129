from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from mpc_solarcar.solar_profile import get_path, get_section, load_profile, merged_dict


def _launch_setup(context):
    profile_yaml = LaunchConfiguration('profile_yaml').perform(context)
    profile_path, cfg = load_profile(profile_yaml)
    runtime_cfg = get_section(cfg, 'runtime')
    sim_cfg = get_section(cfg, 'simulation')
    logging_cfg = merged_dict(get_section(cfg, 'logging'), sim_cfg.get('logging', {}))

    dashboard_host = str(runtime_cfg.get('dashboard_host', '0.0.0.0'))
    dashboard_port = int(runtime_cfg.get('dashboard_port', 8080))
    forecast_time_mode = str(runtime_cfg.get('forecast_time_mode', 'relative'))
    forecast_time_tz = str(runtime_cfg.get('forecast_time_tz', 'Australia/Darwin'))
    gps_rate_hz = float(sim_cfg.get('gps_rate_hz', 1.0))
    gps_init_speed_kmh = float(sim_cfg.get('gps_init_speed_kmh', 40.0))
    logger_dir = str(logging_cfg.get('log_dir', 'outputs/logs'))
    logger_prefix = str(logging_cfg.get('file_prefix', 'solar_sim'))
    logger_rate_hz = float(logging_cfg.get('log_rate_hz', 2.0))

    return [
        Node(
            package='mpc_solarcar',
            executable='gps_sim_node',
            name='gps_sim_node',
            parameters=[{
                'route_csv': get_path(cfg, profile_path, 'route_waypoints_csv'),
                'dt': gps_rate_hz,
                'init_speed_kmh': gps_init_speed_kmh,
            }],
        ),
        Node(
            package='mpc_solarcar',
            executable='mpc_node',
            name='mpc_node',
            parameters=[{
                'forecast_csv': get_path(cfg, profile_path, 'forecast_csv'),
                'drive_eff_map': get_path(cfg, profile_path, 'drive_eff_map'),
                'regen_eff_map': get_path(cfg, profile_path, 'regen_eff_map'),
                'rint_map': get_path(cfg, profile_path, 'rint_map'),
                'drive_map_eco': get_path(cfg, profile_path, 'drive_map_eco'),
                'drive_map_power': get_path(cfg, profile_path, 'drive_map_power'),
                'regen_map_eco': get_path(cfg, profile_path, 'regen_map_eco'),
                'regen_map_power': get_path(cfg, profile_path, 'regen_map_power'),
                'panel_eff_map': get_path(cfg, profile_path, 'panel_eff_map'),
                'mppt_eff_map': get_path(cfg, profile_path, 'mppt_eff_map'),
                'ocv_soc_map': get_path(cfg, profile_path, 'ocv_soc_map'),
                'params_yaml': profile_path,
                'route_profile_csv': get_path(cfg, profile_path, 'route_profile_csv'),
                'speed_profile_csv': get_path(cfg, profile_path, 'speed_profile_csv'),
                'stop_yaml': get_path(cfg, profile_path, 'stop_yaml'),
                'drive_schedule_yaml': get_path(cfg, profile_path, 'drive_schedule_yaml'),
                'forecast_time_mode': forecast_time_mode,
                'forecast_time_tz': forecast_time_tz,
            }],
        ),
        Node(
            package='mpc_solarcar',
            executable='solar_state_node',
            name='solar_state_node',
        ),
        Node(
            package='mpc_solarcar',
            executable='dashboard_node',
            name='dashboard_node',
            parameters=[{
                'host': dashboard_host,
                'port': dashboard_port,
            }],
        ),
        Node(
            package='mpc_solarcar',
            executable='logger_node',
            name='logger_node',
            parameters=[{
                'mode': 'solar',
                'log_dir': logger_dir,
                'file_prefix': logger_prefix,
                'log_rate_hz': logger_rate_hz,
            }],
        ),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'profile_yaml',
            default_value=PathJoinSubstitution([
                FindPackageShare('mpc_solarcar'),
                'config',
                'solar',
                'bwsc_2027_demo.yaml',
            ]),
        ),
        OpaqueFunction(function=_launch_setup),
    ])
