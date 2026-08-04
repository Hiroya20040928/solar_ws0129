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
    live_cfg = get_section(cfg, 'live')
    logging_cfg = merged_dict(get_section(cfg, 'logging'), live_cfg.get('logging', {}))
    weather_cfg = merged_dict({
        'enabled': live_cfg.get('enable_weather_fetch', True),
        'provider': live_cfg.get('weather_provider', 'openmeteo'),
        'gps_topic': live_cfg.get('weather_gps_topic', '/chase/gps'),
        'fetch_period_sec': live_cfg.get('weather_fetch_period_sec', 3600.0),
        'forecast_days': live_cfg.get('weather_forecast_days', 3),
        'step_minutes': live_cfg.get('weather_step_minutes', 10),
        'timezone_name': live_cfg.get('forecast_time_tz', runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')),
        'fallback_latitude': live_cfg.get('fallback_latitude', -12.4634),
        'fallback_longitude': live_cfg.get('fallback_longitude', 130.8456),
        'tcell_gain': live_cfg.get('weather_tcell_gain', 0.03),
    }, get_section(live_cfg, 'weather'))
    autocal_cfg = merged_dict({
        'enabled': live_cfg.get('enable_autocal', True),
        'publish_period_sec': live_cfg.get('autocal_period_sec', 30.0),
        'aux_power_w_init': get_section(cfg, 'model').get('P_aux', 8.0),
    }, get_section(live_cfg, 'autocal'))
    bridge_cfg = merged_dict({
        'enabled': live_cfg.get('enable_speed_bridge', True),
        'output_speed_topic': live_cfg.get('output_speed_topic', '/vehicle/speed_cmd_kmh'),
        'output_drive_mode_topic': live_cfg.get('output_drive_mode_topic', '/vehicle/drive_mode_cmd'),
        'udp_enabled': live_cfg.get('udp_enabled', False),
        'udp_host': live_cfg.get('udp_host', '127.0.0.1'),
        'udp_port': live_cfg.get('udp_port', 50050),
        'publish_rate_hz': 5.0,
        'input_timeout_sec': 3.0,
        'safe_speed_kmh': 0.0,
        'startup_hold_sec': 2.0,
        'filter_tau_sec': 1.0,
        'accel_limit_kmhps': 1.5,
        'decel_limit_kmhps': 4.0,
        'speed_deadband_kmh': 0.1,
        'speed_quantize_step_kmh': 0.1,
        'max_output_speed_kmh': 130.0,
        'drive_mode_min_hold_sec': 5.0,
    }, get_section(live_cfg, 'command_bridge'))
    distance_cfg = merged_dict({
        'publish_rate_hz': live_cfg.get('distance_publish_rate_hz', 2.0),
        'max_dt_sec': live_cfg.get('distance_max_dt_sec', 2.5),
    }, get_section(live_cfg, 'distance'))
    grade_cfg = merged_dict({
        'gps_topic': live_cfg.get('grade_gps_topic', '/vehicle/gps'),
        'altitude_topic': live_cfg.get('grade_altitude_topic', '/vehicle/altitude_m'),
        'min_speed_kmh': live_cfg.get('grade_min_speed_kmh', 5.0),
        'altitude_alpha': live_cfg.get('grade_altitude_alpha', 0.2),
        'min_delta_s_km': live_cfg.get('grade_min_delta_s_km', 0.01),
    }, get_section(live_cfg, 'grade'))

    dashboard_host = str(runtime_cfg.get('dashboard_host', '0.0.0.0'))
    dashboard_port = int(runtime_cfg.get('dashboard_port', 8080))
    forecast_time_mode = str(live_cfg.get('forecast_time_mode', runtime_cfg.get('forecast_time_mode', 'absolute')))
    forecast_time_tz = str(live_cfg.get('forecast_time_tz', runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')))
    logger_dir = str(logging_cfg.get('log_dir', 'outputs/logs'))
    logger_prefix = str(logging_cfg.get('file_prefix', 'solar_live'))
    logger_rate_hz = float(logging_cfg.get('log_rate_hz', 2.0))
    forecast_csv = get_path(cfg, profile_path, 'forecast_csv')

    nodes = [
        Node(
            package='mpc_solarcar',
            executable='mpc_node',
            name='mpc_node',
            parameters=[{
                'forecast_csv': forecast_csv,
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

    if bool(weather_cfg.get('enabled', True)):
        nodes.append(
            Node(
                package='mpc_solarcar',
                executable='weather_fetch_node',
                name='weather_fetch_node',
                parameters=[{
                    'forecast_csv': forecast_csv,
                    'provider': str(weather_cfg.get('provider', 'openmeteo')),
                    'gps_topic': str(weather_cfg.get('gps_topic', '/chase/gps')),
                    'fetch_period_sec': float(weather_cfg.get('fetch_period_sec', 3600.0)),
                    'forecast_days': int(weather_cfg.get('forecast_days', 3)),
                    'step_minutes': int(weather_cfg.get('step_minutes', 10)),
                    'timezone_name': str(weather_cfg.get('timezone_name', forecast_time_tz)),
                    'fallback_latitude': float(weather_cfg.get('fallback_latitude', -12.4634)),
                    'fallback_longitude': float(weather_cfg.get('fallback_longitude', 130.8456)),
                    'tcell_gain': float(weather_cfg.get('tcell_gain', 0.03)),
                }],
            )
        )

    if bool(autocal_cfg.get('enabled', True)):
        nodes.append(
            Node(
                package='mpc_solarcar',
                executable='solar_autocal_node',
                name='solar_autocal_node',
                parameters=[{
                    'publish_period_sec': float(autocal_cfg.get('publish_period_sec', 30.0)),
                    'stationary_speed_kmh': float(autocal_cfg.get('stationary_speed_kmh', 2.0)),
                    'drive_speed_kmh': float(autocal_cfg.get('drive_speed_kmh', 25.0)),
                    'night_ghi_threshold': float(autocal_cfg.get('night_ghi_threshold', 50.0)),
                    'day_ghi_threshold': float(autocal_cfg.get('day_ghi_threshold', 150.0)),
                    'alpha': float(autocal_cfg.get('alpha', 0.2)),
                    'solar_gain_init': float(autocal_cfg.get('solar_gain_init', 1.0)),
                    'drive_power_gain_init': float(autocal_cfg.get('drive_power_gain_init', 1.0)),
                    'aux_power_w_init': float(autocal_cfg.get('aux_power_w_init', get_section(cfg, 'model').get('P_aux', 8.0))),
                    'solar_gain_min': float(autocal_cfg.get('solar_gain_min', 0.5)),
                    'solar_gain_max': float(autocal_cfg.get('solar_gain_max', 1.5)),
                    'drive_power_gain_min': float(autocal_cfg.get('drive_power_gain_min', 0.7)),
                    'drive_power_gain_max': float(autocal_cfg.get('drive_power_gain_max', 1.4)),
                    'aux_power_w_min': float(autocal_cfg.get('aux_power_w_min', 0.0)),
                    'aux_power_w_max': float(autocal_cfg.get('aux_power_w_max', 300.0)),
                }],
            )
        )

    if bool(bridge_cfg.get('enabled', True)):
        nodes.append(
            Node(
                package='mpc_solarcar',
                executable='speed_command_bridge_node',
                name='speed_command_bridge_node',
                parameters=[{
                    'output_speed_topic': str(bridge_cfg.get('output_speed_topic', '/vehicle/speed_cmd_kmh')),
                    'output_drive_mode_topic': str(bridge_cfg.get('output_drive_mode_topic', '/vehicle/drive_mode_cmd')),
                    'udp_enabled': bool(bridge_cfg.get('udp_enabled', False)),
                    'udp_host': str(bridge_cfg.get('udp_host', '127.0.0.1')),
                    'udp_port': int(bridge_cfg.get('udp_port', 50050)),
                    'publish_rate_hz': float(bridge_cfg.get('publish_rate_hz', 5.0)),
                    'input_timeout_sec': float(bridge_cfg.get('input_timeout_sec', 3.0)),
                    'safe_speed_kmh': float(bridge_cfg.get('safe_speed_kmh', 0.0)),
                    'startup_hold_sec': float(bridge_cfg.get('startup_hold_sec', 2.0)),
                    'filter_tau_sec': float(bridge_cfg.get('filter_tau_sec', 1.0)),
                    'accel_limit_kmhps': float(bridge_cfg.get('accel_limit_kmhps', 1.5)),
                    'decel_limit_kmhps': float(bridge_cfg.get('decel_limit_kmhps', 4.0)),
                    'speed_deadband_kmh': float(bridge_cfg.get('speed_deadband_kmh', 0.1)),
                    'speed_quantize_step_kmh': float(bridge_cfg.get('speed_quantize_step_kmh', 0.1)),
                    'max_output_speed_kmh': float(bridge_cfg.get('max_output_speed_kmh', 130.0)),
                    'drive_mode_min_hold_sec': float(bridge_cfg.get('drive_mode_min_hold_sec', 5.0)),
                }],
            )
        )

    if bool(live_cfg.get('use_distance_node', True)):
        nodes.append(
            Node(
                package='mpc_solarcar',
                executable='distance_node',
                name='distance_node',
                parameters=[{
                    'publish_rate_hz': float(distance_cfg.get('publish_rate_hz', 2.0)),
                    'max_dt_sec': float(distance_cfg.get('max_dt_sec', 2.5)),
                }],
            )
        )

    if bool(live_cfg.get('use_grade_node', True)):
        nodes.append(
            Node(
                package='mpc_solarcar',
                executable='grade_node',
                name='grade_node',
                parameters=[{
                    'gps_topic': str(grade_cfg.get('gps_topic', '/vehicle/gps')),
                    'altitude_topic': str(grade_cfg.get('altitude_topic', '/vehicle/altitude_m')),
                    'min_speed_kmh': float(grade_cfg.get('min_speed_kmh', 5.0)),
                    'altitude_alpha': float(grade_cfg.get('altitude_alpha', 0.2)),
                    'min_delta_s_km': float(grade_cfg.get('min_delta_s_km', 0.01)),
                }],
            )
        )

    return nodes


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
