#!/usr/bin/env python3
"""
地址图片路由测试

验证：
1. _address_index 是否正确加载
2. pick_address_image() 是否能正确选择图片
3. 拦截器与图片路由集成是否正常工作
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.data.knowledge_repository import KnowledgeRepository
from src.data.config_manager import ConfigManager


# 配置文件路径
MODEL_SETTINGS_FILE = Path("config") / "model_settings.json"
ENV_FILE = Path(".env")
KNOWLEDGE_BASE_FILE = Path("config") / "knowledge_base.json"
BRAND_KNOWLEDGE_FILE = Path("config") / "brand_knowledge.json"


def build_agent() -> CustomerServiceAgent:
    """创建 Agent 实例（与 chat_simulator 对齐）"""
    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = LLMService(config_manager)
    memory_store = MemoryStore(Path("data") / "agent_memory.json")

    return CustomerServiceAgent(
        knowledge_service=knowledge_service,
        llm_service=llm_service,
        memory_store=memory_store,
        images_dir=Path("images"),
        image_categories_path=Path("config") / "image_categories.json",
        system_prompt_doc_path=Path("docs") / "system_prompt_private_ai_customer_service.md",
        playbook_doc_path=Path("docs") / "private_ai_customer_service_playbook.md",
        brand_knowledge_doc_path=BRAND_KNOWLEDGE_FILE,
        reply_templates_path=Path("config") / "reply_templates.json",
        media_whitelist_path=Path("config") / "media_whitelist.json",
        conversation_log_dir=Path("data") / "conversations",
    )


def test_address_index_loading():
    """测试地址图片索引加载"""
    print("=" * 80)
    print("📍 测试 1: 地址图片索引加载")
    print("=" * 80)

    # 创建 Agent 实例
    agent = build_agent()

    # 加载媒体库
    agent.reload_media_library()

    # 打印索引状态
    print("\n📊 地址图片索引状态:")
    for store_key, image_paths in agent._address_index.items():
        print(f"   {store_key}: {len(image_paths)} 张图片")
        if image_paths:
            # 只打印文件名，不打印完整路径
            sample_names = [Path(p).name for p in image_paths[:3]]
            if len(image_paths) > 3:
                sample_names.append(f"... 共{len(image_paths)}张")
            print(f"      示例：{', '.join(sample_names)}")

    total_images = sum(len(v) for v in agent._address_index.values())
    print(f"\n   总计：{total_images} 张地址图片")

    # 验证：每个门店至少应该有 1 张图片
    print("\n✅ 验证结果:")
    all_loaded = True
    for store_key, image_paths in agent._address_index.items():
        if len(image_paths) == 0:
            print(f"   ❌ {store_key}: 0 张图片")
            all_loaded = False
        else:
            print(f"   ✅ {store_key}: {len(image_paths)} 张图片")

    if all_loaded:
        print("\n✅ 所有门店地址图片加载成功！")
    else:
        print("\n⚠️  部分门店地址图片未加载")

    return agent


def test_pick_address_image(agent):
    """测试 pick_address_image() 函数"""
    print("\n" + "=" * 80)
    print("📍 测试 2: pick_address_image() 函数")
    print("=" * 80)

    session_state = {
        "address_image_sent_paths_by_store": {
            "sh_jingan": [],
        }
    }

    print("\n📤 测试：为 sh_jingan 选择图片")
    image_path = agent.pick_address_image("sh_jingan", session_state=session_state)
    if image_path:
        print(f"   ✅ 已选择：{Path(image_path).name}")
    else:
        print(f"   ❌ 返回 None")

    # 测试多次选择（应该随机）
    print("\n📤 测试：多次选择（验证随机性）")
    selected_paths = set()
    for i in range(5):
        path = agent.pick_address_image("sh_jingan", session_state=session_state)
        if path:
            selected_paths.add(Path(path).name)

    print(f"   5 次选择结果：{len(selected_paths)} 张不同的图片")
    for name in selected_paths:
        print(f"      - {name}")

    # 测试避重
    print("\n📤 测试：避重功能")
    if agent._address_index.get("sh_jingan"):
        # 模拟所有图片都已发送
        sent_paths = [str(p) for p in agent._address_index["sh_jingan"]]
        session_state_with_sent = {
            "address_image_sent_paths_by_store": {
                "sh_jingan": sent_paths,
            }
        }
        path = agent.pick_address_image("sh_jingan", session_state=session_state_with_sent)
        if path is None:
            print(f"   ✅ 所有图片已发送，返回 None（正确）")
        else:
            print(f"   ⚠️  所有图片已发送但仍返回：{Path(path).name}")

    # 测试上海门店兜底
    print("\n📤 测试：上海门店兜底（sh_wujiaochang 没有图片时使用 sh_renmin）")
    # 首先检查 sh_wujiaochang 是否有图片
    wujiaochang_count = len(agent._address_index.get("sh_wujiaochang", []))
    print(f"   sh_wujiaochang: {wujiaochang_count} 张图片")
    if wujiaochang_count > 0:
        path = agent.pick_address_image("sh_wujiaochang", session_state=session_state)
        if path:
            print(f"   ✅ 已选择：{Path(path).name}")
        else:
            print(f"   ❌ 返回 None")


def test_interceptor_store_mapping():
    """测试拦截器门店映射"""
    print("\n" + "=" * 80)
    print("📍 测试 3: 拦截器门店 → 索引 key 映射")
    print("=" * 80)

    from src.services.address_interceptor import AddressInterceptor

    interceptor = AddressInterceptor()

    # 映射表（与 message_processor.py 中的一致）
    mapping = {
        "静安店": "sh_jingan",
        "人民广场店": "sh_renmin",
        "虹口店": "sh_hongkou",
        "五角场店": "sh_wujiaochang",
        "徐汇店": "sh_xuhui",
        "北京店": "beijing_chaoyang",
    }

    # 测试每个门店
    test_cases = [
        ("静安店", "姐姐，静安店在愚园路 172 号环球世界大厦 A 座。"),
        ("虹口店", "虹口店在花园路 16 号嘉和国际大厦东楼。"),
        ("人民广场店", "人民广场店在汉口路 650 号亚洲大厦。"),
        ("五角场店", "五角场店在政通路 177 号万达广场 A 栋。"),
        ("徐汇店", "徐汇店在漕溪北路 500 号中航德必大厦。"),
        ("北京店", "北京店在建外 SOHO 东区。"),
    ]

    print("\n📤 测试：拦截器识别 + 映射")
    for store_name, test_text in test_cases:
        result = interceptor.intercept(test_text)
        if result.is_intercepted:
            expected_key = mapping.get(result.target_store)
            actual_key = mapping.get(store_name)
            status = "✅" if expected_key == actual_key else "❌"
            print(f"   {status} {store_name}: 拦截器识别为 '{result.target_store}' → 索引 key '{expected_key}'")
        else:
            print(f"   ❌ {store_name}: 未拦截")


def main():
    print("=" * 80)
    print("🚀 地址图片路由测试")
    print("=" * 80)

    # 测试 1: 索引加载
    agent = test_address_index_loading()

    # 测试 2: pick_address_image()
    test_pick_address_image(agent)

    # 测试 3: 拦截器映射
    test_interceptor_store_mapping()

    print("\n" + "=" * 80)
    print("✅ 所有测试完成！")
    print("=" * 80)


if __name__ == "__main__":
    main()
