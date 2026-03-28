#!/usr/bin/env python3
"""
补充一组“地址反问绕圈子”模拟对话，并按硬规则验收。
"""

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


SCENARIO: List[Dict[str, Any]] = [
    {
        "user": "人民广场附近是不是最近呀",
        "must_not_contain": ["位置直接看图", "我直接继续回答您这轮的问题"],
    },
    {
        "user": "你是不是想让我去人民广场啊，你是在按我要求选还是硬推",
        "must_not_contain": ["位置直接看图", "看图片", "位置图"],
    },
    {
        "user": "位置远点也没关系，我主要看设计师",
        "must_not_contain": ["位置直接看图", "哪个城市", "哪个区域"],
        "forbid_media_types": ["address_image"],
    },
    {
        "user": "那人民广场店地址发我看看",
        "must_not_contain": ["我直接继续回答您这轮的问题"],
        "expect_media_types": ["address_image"],
    },
    {
        "user": "我看到图了",
        "must_not_contain": ["位置直接看图", "我直接继续回答您这轮的问题"],
    },
    {
        "user": "但你到底是按我要求选，还是还在推这家",
        "must_not_contain": ["位置直接看图", "看图片", "位置图"],
        "forbid_media_types": ["address_image"],
    },
    {
        "user": "那静安和人民广场你觉得哪家更适合",
        "must_not_contain": ["位置直接看图"],
    },
    {
        "user": "13962923599",
        "must_contain_any": ["电话", "记下", "收到"],
        "must_not_contain": ["加您好友"],
    },
    {
        "user": "微信都可以啊，那怎么联系",
        "must_not_contain": ["留个", "加您", "加好友", "位置直接看图", "我直接继续回答您这轮的问题"],
        "forbid_media_types": ["contact_image"],
    },
]


def build_agent(run_dir: Path) -> CustomerServiceAgent:
    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = LLMService(config_manager)
    memory_store = MemoryStore(run_dir / "agent_memory.json")

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
        conversation_log_dir=run_dir / "conversations",
    )
    agent.set_options(
        use_knowledge_first=agent.use_knowledge_first,
        knowledge_threshold=agent.knowledge_threshold,
        first_reply_video_enabled=False,
        reply_mode="llm_direct",
    )
    return agent


def run() -> int:
    run_dir = PROJECT_ROOT / "data" / f"address_loop_sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent = build_agent(run_dir)

    session_id = "address_loop_sim"
    user_name = "地址反问模拟用户"
    history: List[Dict[str, str]] = []
    failures: List[str] = []
    results: List[Dict[str, Any]] = []

    for turn, case in enumerate(SCENARIO, start=1):
        user_text = str(case["user"])
        decision = agent.decide(session_id, user_name, user_text, history)
        media_items = list(decision.media_items or [])
        for item in media_items:
            agent.mark_media_sent(session_id, user_name, item, success=True)

        reply_text = str(decision.reply_text or "")
        media_types = [str(item.get("type", "")) for item in media_items if isinstance(item, dict)]
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply_text})

        for blocked in case.get("must_not_contain", []):
            if blocked and blocked in reply_text:
                failures.append(f"第{turn}轮命中禁词: {blocked}")
        must_contain_any = list(case.get("must_contain_any", []) or [])
        if must_contain_any and not any(token in reply_text for token in must_contain_any):
            failures.append(f"第{turn}轮未命中应答关键词: {' / '.join(must_contain_any)}")
        expected_media = list(case.get("expect_media_types", []) or [])
        for media_type in expected_media:
            if media_type not in media_types:
                failures.append(f"第{turn}轮缺少媒体: {media_type}")
        forbidden_media = list(case.get("forbid_media_types", []) or [])
        for media_type in forbidden_media:
            if media_type in media_types:
                failures.append(f"第{turn}轮误发媒体: {media_type}")

        results.append(
            {
                "turn": turn,
                "user": user_text,
                "assistant": reply_text,
                "media_types": media_types,
                "rule_id": decision.rule_id,
            }
        )

    output = {
        "run_dir": str(run_dir),
        "passed": not failures,
        "failures": failures,
        "results": results,
    }
    output_path = run_dir / "simulation_results.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in results:
        print(f"[{item['turn']}] 用户: {item['user']}")
        print(f"    回复: {item['assistant']}")
        print(f"    媒体: {item['media_types'] or []}")

    if failures:
        print("\n模拟验收失败：")
        for failure in failures:
            print(f"- {failure}")
        print(f"\n结果文件: {output_path}")
        return 1

    print(f"\n模拟验收通过，结果文件: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
