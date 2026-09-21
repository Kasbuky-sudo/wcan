# Authored by SONGJUNSONG (School of Finance and Economics, Jilin Business and Technology College)
import yaml
import os
import re
from werss.print import print_error


class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            try:
                from paths import user_dir
                config_path = os.path.join(user_dir(), "config.yaml")
            except Exception:
                config_path = "config.yaml"
        self.config_path = config_path
        self.config = {}
        if os.path.dirname(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        self.load()

    def load(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f.read()) or {}
        except Exception as e:
            print_error(f"加载配置文件 {self.config_path} 错误: {e}")
            self.config = {}

    def save(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            print_error(f"保存配置文件失败: {e}")

    def _fix(self, v: str):
        if v in ("", "''", '""', None):
            return ""
        try:
            if isinstance(v, str) and v.lower() in ('true', 'false'):
                return v.lower() == 'true'
            if isinstance(v, str) and v.isdigit():
                return int(v)
            return v
        except Exception:
            return v

    def get(self, key, default=None):
        keys = key.split('.')
        value = self.config
        try:
            for k in keys:
                value = value[k]
            val = self._fix(value)
            if val is None and default is not None:
                return default
            # 对字符串值自动进行环境变量替换（支持 ${VAR} 和 ${VAR:-default} 语法）
            if isinstance(val, str):
                val = self.replace_env_vars(val)
            return val
        except (KeyError, TypeError):
            return default

    def set(self, key, value):
        keys = key.split('.')
        d = self.config
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    def reload(self):
        self.load()

    def replace_env_vars(self, data):
        if isinstance(data, dict):
            return {k: self.replace_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.replace_env_vars(item) for item in data]
        elif isinstance(data, str):
            pattern = re.compile(r'\$\{([^}:]+)(?::-([^}]*))?\}')
            def replace_match(match):
                var_name = match.group(1)
                default_value = match.group(2)
                if default_value is not None:
                    return os.getenv(var_name, default_value)
                return os.getenv(var_name, '')
            return pattern.sub(replace_match, data)
        return data


cfg = Config()
