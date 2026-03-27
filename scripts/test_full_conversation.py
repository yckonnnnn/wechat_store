#!/usr/bin/env python3
"""
单用户完整对话流程测试 - 模拟真实用户从开始到结束的全流程对话
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import BRAND_KNOWLEDGE_FILE, ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


# 模拟用户对话流程 - 覆盖所有高频场景
CONVERSATION_FLOW = [
    # 开场
    "你好",
    # 地址反问场景（用户问地址，客服反问城市）
    "你们地址在哪里",
    # 用户回答城市，触发门店推荐
    "我在上海",
    # 地址推荐后的承接（人广店）
    "人广店具体在哪",
    # 价格问题
    "假发什么价格",
    # 假发材质
    "是什么材质的",
    # 男士问题
    "男士能做吗",
    # 制作周期
    "多久弄好",
    # 快递/远程
    "可以快递吗",
    # 远程定制
    "远程定制怎么做",
    # 营业时间
    "你们营业时间是几点",
    # 再次确认制作时间
    "多久做好",
    # 收尾/预约意向
    "那我需要提前预约吗",
]


def run_full_conversation() -> Dict[str, Any]:
    """运行完整对话流程"""

    # 初始化 Agent
    sim_data_dir = PROJECT_ROOT / "data" / "full_conversation_test"
    sim_data_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_data_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = LLMService(config_manager)
    memory_store = MemoryStore(sim_data_dir / "agent_memory.json")

    agent = CustomerServiceAgent(
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
        conversation_log_dir=convo_dir,
    )
    agent.set_options(
        use_knowledge_first=agent.use_knowledge_first,
        knowledge_threshold=agent.knowledge_threshold,
        first_reply_video_enabled=False,
        reply_mode="llm_direct",
    )

    # 会话状态
    session_id = f"full_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    user_name = "完整测试用户"
    history: List[Dict[str, str]] = []
    conversation_log = []

    print("=" * 100)
    print(f"完整对话流程测试 - {session_id}")
    print(f"用户：{user_name}")
    print(f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    print()

    for turn_idx, user_message in enumerate(CONVERSATION_FLOW, 1):
        print(f"【第{turn_idx}轮】")
        print(f"用户：{user_message}")
        print("-" * 80)

        # 调用 Agent 决策
        decision = agent.decide(
            session_id=session_id,
            user_name=user_name,
            latest_user_text=user_message,
            conversation_history=history,
        )

        # 获取媒体队列
        extra_video = agent.mark_reply_sent(session_id, user_name, decision.reply_text)
        media_queue = list(decision.media_items or [])
        if extra_video:
            media_queue.append(extra_video)

        triggered_types = [str(item.get("type", "")) for item in media_queue if isinstance(item, dict)]

        # 解析地址信息
        address_info = ""
        for item in media_queue:
            if isinstance(item, dict):
                if item.get("type") == "address_image":
                    store_name = item.get("store_name", "")
                    store_address = item.get("store_address", "")
                    if store_name:
                        address_info = f"【地址图片】{store_name}"
                        if store_address:
                            address_info += f" - {store_address}"
                    else:
                        address_info = "【地址图片】通用地址"
                elif item.get("type") == "contact_image":
                    address_info = "【联系方式图片】"
                elif item.get("type") == "delayed_video":
                    address_info = "【延时视频】"

        # 输出回复
        print(f"客服：{decision.reply_text}")
        print()
        print(f"决策信息:")
        print(f"  - 回复来源：{decision.reply_source}")
        print(f"  - 规则 ID: {decision.rule_id}")
        print(f"  - 意图：{decision.intent}")
        print(f"  - 路由原因：{decision.route_reason}")
        print(f"  - 媒体计划：{decision.media_plan}")
        if triggered_types:
            print(f"  - 触发媒体：{', '.join(triggered_types)}")
        if address_info:
            print(f"  - 媒体详情：{address_info}")
        print()

        # 记录对话日志
        conversation_log.append({
            "turn": turn_idx,
            "user_message": user_message,
            "reply_text": decision.reply_text,
            "reply_source": decision.reply_source,
            "rule_id": decision.rule_id,
            "intent": decision.intent,
            "route_reason": decision.route_reason,
            "media_plan": decision.media_plan,
            "triggered_media_types": triggered_types,
            "media_details": address_info,
        })

        # 更新历史
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": decision.reply_text})
        if len(history) > 30:
            del history[:-30]

    # 输出总结
    print("=" * 100)
    print("对话总结")
    print("=" * 100)

    # 统计媒体触发
    address_count = sum(1 for log in conversation_log if "address_image" in log["triggered_media_types"])
    contact_count = sum(1 for log in conversation_log if "contact_image" in log["triggered_media_types"])
    video_count = sum(1 for log in conversation_log if "delayed_video" in log["triggered_media_types"])

    print(f"总轮数：{len(conversation_log)}")
    print(f"地址图片触发次数：{address_count}")
    print(f"联系方式图片触发次数：{contact_count}")
    print(f"视频触发次数：{video_count}")
    print()

    # 统计规则使用
    rule_stats = {}
    for log in conversation_log:
        rule = log["rule_id"]
        rule_stats[rule] = rule_stats.get(rule, 0) + 1

    print("规则使用情况:")
    for rule, count in sorted(rule_stats.items(), key=lambda x: -x[1]):
        print(f"  - {rule}: {count}次")
    print()

    # 保存报告
    report = {
        "session_id": session_id,
        "user_name": user_name,
        "timestamp": datetime.now().isoformat(),
        "total_turns": len(conversation_log),
        "media_stats": {
            "address_image": address_count,
            "contact_image": contact_count,
            "delayed_video": video_count,
        },
        "rule_stats": rule_stats,
        "conversation_log": conversation_log,
    }

    report_file = sim_data_dir / f"full_conversation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"完整报告已保存：{report_file}")

    return report


if __name__ == "__main__":
    run_full_conversation()
