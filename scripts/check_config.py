"""
配置检查工具
用于检查生产环境配置是否已正确设置
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.constants import (
    USER_DATA_DIR,
    MODEL_SETTINGS_FILE,
    AGENT_MEMORY_FILE,
    MODEL_SETTINGS_EXAMPLE,
    KNOWLEDGE_BASE_FILE,
)


def check_user_data_dir():
    """检查用户数据目录"""
    print("=" * 50)
    print("📁 用户数据目录检查")
    print("=" * 50)
    print(f"路径：{USER_DATA_DIR}")

    if USER_DATA_DIR.exists():
        print("✅ 目录已存在")
    else:
        print("⚠️  目录不存在（首次运行时会自动创建）")
    print()


def check_model_settings():
    """检查模型配置"""
    print("=" * 50)
    print("🔑 模型配置检查")
    print("=" * 50)
    print(f"配置文件：{MODEL_SETTINGS_FILE}")
    print(f"示例文件：{MODEL_SETTINGS_EXAMPLE}")
    print()

    # 检查示例文件
    if MODEL_SETTINGS_EXAMPLE.exists():
        print("✅ 示例文件存在")
    else:
        print("❌ 示例文件缺失")
    print()

    # 检查配置文件
    if MODEL_SETTINGS_FILE.exists():
        print("✅ 配置文件存在")

        try:
            with open(MODEL_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)

            models = config.get('models', {})
            print(f"📊 已配置模型数量：{len(models)}")
            print()

            # 检查各模型的 API Key
            print("API Key 配置状态:")
            for model_name, model_config in models.items():
                api_key = model_config.get('api_key', '')
                base_url = model_config.get('base_url', '')

                if api_key:
                    # 隐藏大部分 Key，只显示前后缀
                    masked_key = api_key[:4] + '***' + api_key[-4:] if len(api_key) > 8 else '***'
                    print(f"  ✅ {model_name}: {masked_key}")
                else:
                    print(f"  ⚠️  {model_name}: 未配置")

                if not base_url:
                    print(f"      ⚠️  Base URL 未配置")

        except json.JSONDecodeError as e:
            print(f"❌ JSON 格式错误：{e}")
        except Exception as e:
            print(f"❌ 读取失败：{e}")
    else:
        print("⚠️  配置文件不存在（首次运行时会自动从示例创建）")
    print()


def check_knowledge_base():
    """检查知识库配置"""
    print("=" * 50)
    print("📚 知识库检查")
    print("=" * 50)
    print(f"文件路径：{KNOWLEDGE_BASE_FILE}")

    if KNOWLEDGE_BASE_FILE.exists():
        print("✅ 知识库文件存在")

        try:
            with open(KNOWLEDGE_BASE_FILE, 'r', encoding='utf-8') as f:
                kb = json.load(f)

            items = kb if isinstance(kb, list) else kb.get('sessions', {})
            if isinstance(items, list):
                print(f"📊 知识库条目数：{len(items)}")
            else:
                print(f"📊 知识库会话数：{len(items)}")
        except Exception as e:
            print(f"❌ 读取失败：{e}")
    else:
        print("❌ 知识库文件缺失")
    print()


def check_business_configs():
    """检查业务配置"""
    print("=" * 50)
    print("⚙️  业务配置检查")
    print("=" * 50)

    config_dir = Path('config')
    business_files = [
        'image_categories.json',
        'address.json',
        'reply_templates.json',
        'media_whitelist.json',
    ]

    for file_name in business_files:
        file_path = config_dir / file_name
        if file_path.exists():
            print(f"✅ {file_name}")
        else:
            print(f"❌ {file_name} 缺失")
    print()


def show_summary():
    """显示总结"""
    print("=" * 50)
    print("📋 配置总结")
    print("=" * 50)
    print()
    print("生产环境部署建议:")
    print("1. 确保 model_settings.json 中的 API Key 已正确配置")
    print("2. 知识库内容已根据实际需求更新")
    print("3. 业务配置（地址、图片分类等）已正确设置")
    print("4. 不要将包含真实 API Key 的配置文件提交到 Git")
    print()
    print("📖 详细部署指南请参考：docs/生产环境部署指南.md")
    print()


def main():
    """主函数"""
    print()
    print("╔" + "=" * 48 + "╗")
    print("║" + " " * 10 + "AI 客服系统 - 配置检查工具" + " " * 10 + "║")
    print("╚" + "=" * 48 + "╝")
    print()

    check_user_data_dir()
    check_model_settings()
    check_knowledge_base()
    check_business_configs()
    show_summary()


if __name__ == "__main__":
    main()
