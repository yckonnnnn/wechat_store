"""
配置管理器
负责模型配置和系统配置的持久化管理
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from PySide6.QtCore import QObject, Signal


class ConfigManager(QObject):
    """配置管理器，负责加载、保存和管理应用配置"""

    config_changed = Signal(str, object)  # 配置项变更信号 (key, value)

    def __init__(self, config_file: Path = None, env_file: Path = None):
        super().__init__()
        self.config_file = config_file
        self.env_file = env_file
        self._settings = {}
        self._default_settings = {
            "version": 1,
            "updated_at": "",
            "current_model": "ChatGPT",
            "models": {
                "ChatGPT": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                    "model": "gpt-4o-mini"
                },
                "Gemini": {
                    "base_url": "https://generativelanguage.googleapis.com",
                    "api_key": "",
                    "model": "gemini-1.5-flash"
                },
                "阿里千问": {
                    "base_url": "https://dashscope.aliyuncs.com",
                    "api_key": "",
                    "model": "qwen-plus"
                },
                "DeepSeek": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "",
                    "model": "deepseek-v3.2"
                },
                "豆包": {
                    "base_url": "",
                    "api_key": "",
                    "model": ""
                },
                "kimi": {
                    "base_url": "https://api.moonshot.cn/v1",
                    "api_key": "",
                    "model": "moonshot-v1-8k"
                }
            }
        }

        self._load_env()
        self.load()

    def _load_env(self) -> None:
        """从 .env 文件加载环境变量"""
        if not self.env_file or not self.env_file.exists():
            return

        try:
            raw = self.env_file.read_text(encoding="utf-8", errors="ignore")
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # 去除引号
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]

                if key and os.getenv(key) is None:
                    os.environ[key] = value
        except Exception as e:
            print(f"[ConfigManager] 加载 .env 文件失败: {e}")

    def load(self) -> bool:
        """从文件加载配置"""
        try:
            if self.config_file and self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 先用默认配置作为基础，然后用加载的配置覆盖
                    # 这样可以保留用户手动添加的 API Key
                    self._settings = self._deep_merge(self._default_settings.copy(), loaded)
            else:
                self._settings = self._default_settings.copy()
            return True
        except Exception as e:
            print(f"[ConfigManager] 加载配置失败: {e}")
            self._settings = self._default_settings.copy()
            return False

    def save(self) -> bool:
        """保存配置到文件"""
        try:
            if self.config_file:
                self.config_file.parent.mkdir(parents=True, exist_ok=True)
                
                # 先读取现有文件，保留未知字段（如未来扩展字段）
                if self.config_file.exists():
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        file_config = json.load(f)
                        # 合并规则：以内存中的当前配置为准，文件中的未知字段保留
                        self._settings = self._deep_merge_prefer_override(file_config, self._settings)
                
                self._settings["updated_at"] = datetime.now().isoformat()
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self._settings, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[ConfigManager] 保存配置失败: {e}")
            return False
    
    def _deep_merge_prefer_override(self, base: dict, override: dict) -> dict:
        """深度合并两个字典，优先使用 override 的值。

        用于 save() 场景：保留文件中未被当前内存配置覆盖的字段，
        但不回滚用户刚在界面里修改过的字段（如 model/base_url/api_key）。
        """
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge_prefer_override(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split('.')
        value = self._settings
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """设置配置项"""
        keys = key.split('.')
        target = self._settings
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        self.config_changed.emit(key, value)

    def get_model_config(self, model_name: str) -> dict:
        """获取指定模型的配置"""
        models = self._settings.get("models", {})
        return models.get(model_name, {})

    def set_model_config(self, model_name: str, config: dict) -> None:
        """设置指定模型的配置"""
        if "models" not in self._settings:
            self._settings["models"] = {}
        self._settings["models"][model_name] = config
        self.config_changed.emit(f"models.{model_name}", config)

    def get_current_model(self) -> str:
        """获取当前选中的模型名称"""
        return self._settings.get("current_model", "ChatGPT")

    def set_current_model(self, model_name: str) -> None:
        """设置当前选中的模型"""
        self._settings["current_model"] = model_name
        self.config_changed.emit("current_model", model_name)

    def get_available_models(self) -> list:
        """获取所有可用的模型名称列表"""
        return list(self._settings.get("models", {}).keys())

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """深度合并两个字典，保留 override 中的非空值"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                # 如果 override 中的值非空，使用 override 的值
                # 如果 override 中的值为空字符串，但 base 中有值，保留 base 的值
                if value or (not value and key not in result):
                    result[key] = value
                # 否则保留 base 中的值（result[key] 已经是 base 的值）
        return result
