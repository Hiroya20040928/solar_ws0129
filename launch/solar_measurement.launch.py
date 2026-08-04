from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from mpc_solarcar.solar_profile import get_section, load_profile, merged_dict


def _launch_setup(context):
    profile_yaml = LaunchConfiguration('profile_yaml').perform(context)
    profile_path, cfg = load_profile(profile_yaml)
    runtime_cfg = get_section(cfg, 'runtime')
    measurement_cfg = get_section(cfg, 'measurement')
    logging_cfg = merged_dict(get_section(cfg, 'logging'), measurement_cfg.get('logging', {}))
    distance_cfg = merged_dict({
        'publish_rate_hz': measurement_cfg.get('distance_publish_rate_hz', 2.0),
        'max_dt_sec': measurement_cfg.get('distance_max_dt_sec', 2.5),
    }, get_section(measurement_cfg, 'distance'))
    grade_cfg = merged_dict({
        'gps_topic': measurement_cfg.get('grade_gps_topic', '/vehicle/gps'),
        'altitude_topic': measurement_cfg.get('grade_altitude_topic', '/vehicle/altitude_m'),
        'min_speed_kmh': measurement_cfg.get('grade_min_speed_kmh', 5.0),
        'altitude_alpha': measurement_cfg.get('grade_altitude_alpha', 0.2),
        'min_delta_s_km': measurement_cfg.get('grade_min_delta_s_km', 0.01),
    }, get_section(measurement_cfg, 'grade'))

    dashboard_host = str(runtime_cfg.get('dashboard_host', '0.0.0.0'))
    dashboard_port = int(runtime_cfg.get('dashboard_port', 8080))
    logger_dir = str(logging_cfg.get('log_dir', 'outputs/logs'))
    logger_prefix = str(logging_cfg.get('file_prefix', 'solar_measurement'))
    logger_rate_hz = float(logging_cfg.get('log_rate_hz', 2.0))

    nodes = [
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

    if bool(measurement_cfg.get('use_distance_node', True)):
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

    if bool(measurement_cfg.get('use_grade_node', True)):
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
