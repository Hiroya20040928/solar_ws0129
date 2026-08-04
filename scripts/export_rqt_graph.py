#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault('QT_LOGGING_RULES', '*.debug=false')

import rclpy
from rclpy.node import Node

from qt_dotgraph.pydotfactory import PydotFactory
from rqt_graph.dotcode import NODE_TOPIC_ALL_GRAPH, RosGraphDotcodeGenerator
from rqt_graph.rosgraph2_impl import Graph


EXPECTED_NODES = {
    'sim': {'gps_sim_node', 'mpc_node', 'solar_state_node', 'dashboard_node'},
    'measure': {'dashboard_node', 'logger_node', 'distance_node', 'grade_node'},
    'live': {'mpc_node', 'dashboard_node', 'logger_node', 'speed_command_bridge_node'},
    'live_wifi': {
        'mpc_node',
        'dashboard_node',
        'logger_node',
        'speed_command_bridge_node',
        'telemetry_text_bridge_node',
        'wind_correction_node',
    },
}


def cli_node_names() -> set[str]:
    try:
        out = subprocess.run(
            ['ros2', 'node', 'list'],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return set()
    result = set()
    for line in out.stdout.splitlines():
        name = line.strip().lstrip('/')
        if name:
            result.add(name)
    return result


def cli_topic_names() -> set[str]:
    try:
        out = subprocess.run(
            ['ros2', 'topic', 'list'],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def graph_is_meaningful(node_names: set[str], topic_names: set[str], expected: set[str]) -> bool:
    actual_nodes = {name for name in node_names if name != 'solar_rqt_graph_export'}
    actual_topics = {name for name in topic_names if name not in {'/parameter_events', '/rosout'}}
    if expected:
        if expected.issubset(node_names):
            return True
        if len(expected & node_names) >= max(2, min(4, len(expected))):
            return True
    return len(actual_nodes) >= 2 and len(actual_topics) >= 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-base', default='rqt_graph_solar')
    parser.add_argument('--wait-sec', type=float, default=8.0)
    parser.add_argument('--mode', default='', choices=['', 'sim', 'measure', 'live', 'live_wifi'])
    args = parser.parse_args()

    output_base = Path(args.output_base)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    expected = EXPECTED_NODES.get(args.mode, set())

    rclpy.init()
    node = Node('solar_rqt_graph_export')
    dotcode = ''
    last_node_names = set()
    last_topic_names = set()
    try:
        graph = Graph(node)
        generator = RosGraphDotcodeGenerator(node)
        deadline = time.monotonic() + max(3.0, args.wait_sec)

        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.3)
            graph.update()
            last_node_names = {name.lstrip('/') for name in node.get_node_names()}
            last_topic_names = set(name for name, _ in node.get_topic_names_and_types())
            cli_names = cli_node_names()
            cli_topics = cli_topic_names()
            if cli_names:
                last_node_names |= cli_names
            if cli_topics:
                last_topic_names |= cli_topics
            if graph_is_meaningful(last_node_names, last_topic_names, expected):
                break
            time.sleep(0.4)

        rclpy.spin_once(node, timeout_sec=0.3)
        graph.update()
        dotcode = generator.generate_dotcode(
            graph,
            '',
            '',
            NODE_TOPIC_ALL_GRAPH,
            PydotFactory(),
            hide_single_connection_topics=False,
            hide_dead_end_topics=False,
            cluster_namespaces_level=0,
            accumulate_actions=True,
            orientation='LR',
            rank='same',
            rankdir='LR',
            quiet=False,
        )
    finally:
        node.destroy_node()
        rclpy.shutdown()

    if not graph_is_meaningful(last_node_names, last_topic_names, expected):
        expected_text = ', '.join(sorted(expected)) if expected else '(none)'
        found_nodes = ', '.join(sorted(last_node_names)) or '(none)'
        found_topics = ', '.join(sorted(last_topic_names)) or '(none)'
        sys.stderr.write(
            'rqt_graph export failed: ROS graph is not populated enough.\n'
            f'expected nodes: {expected_text}\n'
            f'found nodes: {found_nodes}\n'
            f'found topics: {found_topics}\n'
        )
        raise SystemExit(1)

    if '/solar_rqt_graph_export' in dotcode and 'mpc_node' not in dotcode and 'dashboard_node' not in dotcode:
        sys.stderr.write('rqt_graph export failed: generated dotcode still contains only the exporter node.\n')
        raise SystemExit(1)

    dot_path = output_base.with_suffix('.dot')
    dot_path.write_text(dotcode, encoding='utf-8')
    print(f'dot saved: {dot_path}')

    dot_bin = shutil.which('dot')
    if not dot_bin:
        print('graphviz dot was not found; only the .dot file was written.')
        return

    for ext, fmt in (('.png', 'png'), ('.svg', 'svg')):
        out_path = output_base.with_suffix(ext)
        subprocess.run([dot_bin, f'-T{fmt}', str(dot_path), '-o', str(out_path)], check=True)
        print(f'{fmt} saved: {out_path}')


if __name__ == '__main__':
    main()
