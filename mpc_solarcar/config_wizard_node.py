import os
from typing import Any, Dict

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
import yaml


DEFAULT_CONFIG = {
    'v_min_kmh': 0.0,
    'v_max_kmh': 110.0,
    'v_ref_kmh': 40.0,
    'dv_max_kmhps': 4.0,
    'horizon_steps': 10,
    'dt_control': 1.0,
    'w_fuel': 1.0,
    'w_speed': 0.3,
    'w_dv': 0.2,
    'w_stop': 10000.0,
    'stop_points_yaml': 'inputs/stop_points.yaml',
    'model_a0': 0.4,
    'model_a1': 0.02,
    'model_a2': 0.001,
    'model_a3': 0.08,
    'model_a4': 0.02,
    'online_id_enabled': True,
    'throttle_kp': 0.8,
    'throttle_kff': 0.02,
}


class ConfigWizardNode(Node):
    def __init__(self):
        super().__init__('config_wizard_node')
        self.declare_parameter('config_path', os.path.expanduser('~/.config/mpc_solarcar/passo_config.yaml'))
        self.declare_parameter('force_wizard', False)
        self.declare_parameter('no_save', False)
        self.declare_parameter('cli_only', False)
        self.declare_parameter('publish_rate_hz', 1.0)

        self.config_path = os.path.expanduser(self.get_parameter('config_path').value)
        self.force_wizard = bool(self.get_parameter('force_wizard').value)
        self.no_save = bool(self.get_parameter('no_save').value)
        self.cli_only = bool(self.get_parameter('cli_only').value)
        publish_rate_hz = float(self.get_parameter('publish_rate_hz').value)

        self.config_ready = False
        self.config_required = False
        self.config = {}

        self.pub_config = self.create_publisher(String, '/system/config', 10)
        self.pub_ready = self.create_publisher(Bool, '/system/config_ready', 10)
        self.pub_required = self.create_publisher(Bool, '/system/config_required', 10)

        self._load_or_prompt()

        self.timer = self.create_timer(1.0 / publish_rate_hz, self._publish)
        self.get_logger().info('ConfigWizardNode started.')

    def _load_or_prompt(self):
        if os.path.exists(self.config_path) and not self.force_wizard:
            self.config = self._load_config(self.config_path)
            self.config_ready = True
            self.config_required = False
            return

        self.config_required = True
        self._publish()

        if self.cli_only or not self._try_gui_wizard():
            self.config = self._cli_wizard()
        self.config_ready = True
        self.config_required = False

        if not self.no_save:
            save = True
            if not self.cli_only:
                save = True
            else:
                save = self._prompt_bool('Save config to disk', True)
            if save:
                self._save_config(self.config_path, self.config)

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or DEFAULT_CONFIG.copy()
                if 'dv_max_kmh_per_s' in cfg and 'dv_max_kmhps' not in cfg:
                    cfg['dv_max_kmhps'] = cfg['dv_max_kmh_per_s']
                return cfg
        except Exception:
            return DEFAULT_CONFIG.copy()

    def _save_config(self, path: str, cfg: Dict[str, Any]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(cfg, f, sort_keys=False)
        self.get_logger().info(f'Saved config: {path}')

    def _publish(self):
        self.pub_ready.publish(Bool(data=self.config_ready))
        self.pub_required.publish(Bool(data=self.config_required))
        if self.config_ready:
            yaml_str = yaml.safe_dump(self.config, sort_keys=False)
            self.pub_config.publish(String(data=yaml_str))

    def _cli_wizard(self) -> Dict[str, Any]:
        cfg = self._load_config(self.config_path) if os.path.exists(self.config_path) else DEFAULT_CONFIG.copy()
        if 'dv_max_kmh_per_s' in cfg and 'dv_max_kmhps' not in cfg:
            cfg['dv_max_kmhps'] = cfg['dv_max_kmh_per_s']
        if 'dv_max_kmhps' not in cfg:
            cfg['dv_max_kmhps'] = DEFAULT_CONFIG.get('dv_max_kmhps', 4.0)
        print('\nPASSO MPC Config Wizard (CLI)')
        cfg['v_min_kmh'] = self._prompt_float('v_min_kmh', cfg['v_min_kmh'])
        cfg['v_max_kmh'] = self._prompt_float('v_max_kmh', cfg['v_max_kmh'])
        cfg['v_ref_kmh'] = self._prompt_float('v_ref_kmh', cfg['v_ref_kmh'])
        # Backward-compat: map legacy key if present
        if 'dv_max_kmh_per_s' in cfg and 'dv_max_kmhps' not in cfg:
            cfg['dv_max_kmhps'] = cfg['dv_max_kmh_per_s']
        cfg['dv_max_kmhps'] = self._prompt_float('dv_max_kmhps', cfg.get('dv_max_kmhps', 4.0))
        cfg['horizon_steps'] = int(self._prompt_float('horizon_steps', cfg['horizon_steps']))
        cfg['dt_control'] = self._prompt_float('dt_control', cfg['dt_control'])
        cfg['w_fuel'] = self._prompt_float('w_fuel', cfg['w_fuel'])
        cfg['w_speed'] = self._prompt_float('w_speed', cfg['w_speed'])
        cfg['w_dv'] = self._prompt_float('w_dv', cfg['w_dv'])
        cfg['w_stop'] = self._prompt_float('w_stop', cfg['w_stop'])
        cfg['stop_points_yaml'] = self._prompt_str('stop_points_yaml', cfg['stop_points_yaml'])
        cfg['model_a0'] = self._prompt_float('model_a0', cfg['model_a0'])
        cfg['model_a1'] = self._prompt_float('model_a1', cfg['model_a1'])
        cfg['model_a2'] = self._prompt_float('model_a2', cfg['model_a2'])
        cfg['model_a3'] = self._prompt_float('model_a3', cfg['model_a3'])
        cfg['model_a4'] = self._prompt_float('model_a4', cfg['model_a4'])
        cfg['online_id_enabled'] = self._prompt_bool('online_id_enabled', cfg['online_id_enabled'])
        cfg['throttle_kp'] = self._prompt_float('throttle_kp', cfg['throttle_kp'])
        cfg['throttle_kff'] = self._prompt_float('throttle_kff', cfg['throttle_kff'])
        print('Wizard complete.\n')
        return cfg

    def _try_gui_wizard(self) -> bool:
        try:
            if not os.environ.get('DISPLAY'):
                return False
            import tkinter as tk
        except Exception:
            return False

        cfg = self._load_config(self.config_path) if os.path.exists(self.config_path) else DEFAULT_CONFIG.copy()
        root = tk.Tk()
        root.title('PASSO MPC Config Wizard')
        entries = {}

        def add_row(label, key):
            row = tk.Frame(root)
            tk.Label(row, text=label, width=22, anchor='w').pack(side=tk.LEFT)
            ent = tk.Entry(row)
            ent.insert(0, str(cfg.get(key, '')))
            ent.pack(side=tk.RIGHT, expand=True, fill=tk.X)
            row.pack(fill=tk.X, padx=5, pady=2)
            entries[key] = ent

        for key in [
            'v_min_kmh', 'v_max_kmh', 'v_ref_kmh', 'dv_max_kmhps',
            'horizon_steps', 'dt_control', 'w_fuel', 'w_speed', 'w_dv', 'w_stop',
            'stop_points_yaml', 'model_a0', 'model_a1', 'model_a2', 'model_a3', 'model_a4',
            'online_id_enabled', 'throttle_kp', 'throttle_kff',
        ]:
            add_row(key, key)

        save_var = tk.BooleanVar(value=not self.no_save)
        save_chk = tk.Checkbutton(root, text='Save config', variable=save_var)
        save_chk.pack(anchor='w', padx=5, pady=4)

        done = {'ok': False}

        def on_submit():
            for key, ent in entries.items():
                val = ent.get().strip()
                if key == 'online_id_enabled':
                    cfg[key] = val.lower() in ('1', 'true', 'yes', 'y')
                elif key in ('horizon_steps',):
                    cfg[key] = int(float(val)) if val else int(cfg[key])
                elif key in ('stop_points_yaml',):
                    cfg[key] = val or cfg[key]
                else:
                    cfg[key] = float(val) if val else float(cfg[key])
            done['ok'] = True
            root.destroy()

        btn = tk.Button(root, text='Start', command=on_submit)
        btn.pack(pady=6)
        root.mainloop()

        if not done['ok']:
            return False

        self.config = cfg
        if not self.no_save and save_var.get():
            self._save_config(self.config_path, self.config)
        return True

    def _prompt_float(self, name: str, default: float) -> float:
        while True:
            val = input(f'{name} [{default}]: ').strip()
            if not val:
                return float(default)
            try:
                return float(val)
            except ValueError:
                print('Please enter a number.')

    def _prompt_str(self, name: str, default: str) -> str:
        val = input(f'{name} [{default}]: ').strip()
        return val if val else str(default)

    def _prompt_bool(self, name: str, default: bool) -> bool:
        hint = 'Y/n' if default else 'y/N'
        val = input(f'{name} [{hint}]: ').strip().lower()
        if not val:
            return bool(default)
        return val in ('y', 'yes', 'true', '1')


def main():
    rclpy.init()
    node = ConfigWizardNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
