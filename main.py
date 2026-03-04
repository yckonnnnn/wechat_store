"""
AI 微信小店客服系统 - 主程序入口

这是一个基于 Python + PySide6 开发的 AI 智能客服系统，
专门为微信小店设计，支持多种大语言模型。
"""

import sys
import os
import signal
import shutil
from pathlib import Path

from PySide6.QtWidgets import QApplication

# PyInstaller 打包后的路径处理
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

# 添加 src 到路径
sys.path.insert(0, str(BASE_DIR))

from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.ui.main_window import MainWindow
from src.utils.constants import (
    MODEL_SETTINGS_FILE,
    AGENT_MEMORY_FILE,
    KNOWLEDGE_BASE_FILE,
    ENV_FILE,
    USER_DATA_DIR,
    MODEL_SETTINGS_EXAMPLE,
)


def setup_signal_handlers(app: QApplication):
    """设置信号处理器"""

    def signal_handler(signum, frame):
        print("\n收到终止信号，正在退出...")
        app.quit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def init_user_data_dir():
    """初始化用户数据目录（跨平台支持）"""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✅ 用户数据目录：{USER_DATA_DIR}")


def init_default_configs():
    """初始化默认配置文件（业务配置）"""
    config_dir = Path('config')
    config_dir.mkdir(parents=True, exist_ok=True)

    images_dir = Path('images')
    images_dir.mkdir(parents=True, exist_ok=True)

    # 业务配置文件（从打包目录复制到当前目录）
    business_config_files = [
        'image_categories.json',
        'address.json',
        'reply_templates.json',
        'media_whitelist.json',
        'knowledge_base.json',
    ]

    if getattr(sys, 'frozen', False):
        source_config_dir = BASE_DIR / 'config'
        for config_file in business_config_files:
            dest_file = config_dir / config_file
            source_file = source_config_dir / config_file

            if not dest_file.exists() and source_file.exists():
                shutil.copy2(source_file, dest_file)
                print(f"✅ 已复制业务配置：{config_file}")


def init_user_configs():
    """初始化用户配置文件（敏感配置）"""
    # 模型配置：从示例文件复制或创建默认配置
    if not MODEL_SETTINGS_FILE.exists():
        if MODEL_SETTINGS_EXAMPLE.exists():
            shutil.copy2(MODEL_SETTINGS_EXAMPLE, MODEL_SETTINGS_FILE)
            print(f"✅ 已从示例创建模型配置：{MODEL_SETTINGS_FILE}")
        else:
            print(f"⚠️  请配置模型设置：{MODEL_SETTINGS_FILE}")


def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setApplicationName("AI 智能客服系统")
    app.setApplicationVersion("2.0.0")

    setup_signal_handlers(app)

    # 1. 初始化用户数据目录
    init_user_data_dir()

    # 2. 初始化业务配置（项目目录）
    init_default_configs()

    # 3. 初始化用户配置（用户数据目录）
    init_user_configs()

    config_manager = ConfigManager(
        config_file=MODEL_SETTINGS_FILE,
        env_file=ENV_FILE,
    )
    knowledge_repository = KnowledgeRepository(
        data_file=KNOWLEDGE_BASE_FILE,
    )

    window = MainWindow(config_manager, knowledge_repository)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
