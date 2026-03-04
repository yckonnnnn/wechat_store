import json
import tempfile
import unittest
from pathlib import Path

from src.data.config_manager import ConfigManager


class ConfigManagerSaveTestCase(unittest.TestCase):
    def test_save_uses_latest_model_config_instead_of_file_old_value(self):
        with tempfile.TemporaryDirectory() as td:
            config_file = Path(td) / "model_settings.json"
            config_file.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": "",
                        "current_model": "DeepSeek",
                        "models": {
                            "DeepSeek": {
                                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                                "api_key": "sk-old",
                                "model": "deepseek-v3.2",
                            }
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            manager = ConfigManager(config_file=config_file)
            manager.set_model_config(
                "DeepSeek",
                {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-old",
                    "model": "kimi-k2.5",
                },
            )

            self.assertTrue(manager.save())

            saved = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["models"]["DeepSeek"]["model"], "kimi-k2.5")

    def test_save_preserves_unknown_fields_from_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            config_file = Path(td) / "model_settings.json"
            config_file.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": "",
                        "current_model": "DeepSeek",
                        "custom_root": {"flag": True},
                        "models": {
                            "DeepSeek": {
                                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                                "api_key": "sk-old",
                                "model": "deepseek-v3.2",
                                "temperature": 0.3,
                            }
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            manager = ConfigManager(config_file=config_file)
            manager.set_model_config(
                "DeepSeek",
                {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-old",
                    "model": "deepseek-v3.2",
                },
            )

            self.assertTrue(manager.save())

            saved = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["custom_root"], {"flag": True})
            self.assertEqual(saved["models"]["DeepSeek"]["temperature"], 0.3)


if __name__ == "__main__":
    unittest.main()
