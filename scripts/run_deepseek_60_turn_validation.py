#!/usr/bin/env python3
"""
运行 3 个真实 DeepSeek 用户场景验证，每个场景 20 轮，共 60 轮。

输出内容固定包含：
1. 用户是怎么问的
2. 客服是怎么答的
3. 这一轮有没有触发媒体
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


def build_agent(sim_data_dir: Path) -> CustomerServiceAgent:
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
        use_knowledge_first=True,
        knowledge_threshold=0.6,
        first_reply_video_enabled=False,
        reply_mode="llm_direct",
    )
    return agent


def scenarios() -> List[Dict[str, Any]]:
    return [
        {
            "user_id": "user_typo",
            "title": "错别字场景",
            "messages": [
                "泥嚎，我想做假法",
                "我在上嗨徐汇，附近有店嘛",
                "地只发我康康",
                "再发下味置图",
                "我从徐家灰过去远不远",
                "你们价各大楷多少",
                "不同价各差哪里",
                "我这种头发少适合嘛",
                "能先约一下麻",
                "怎么约阿",
                "连系方式给我下",
                "微新怎么加",
                "我刚没收到，在发一次",
                "那个店还是徐汇那个吧",
                "周六下物过去行吗",
                "如果我临时去还能接待嘛",
                "到时候到了咋找",
                "地只图在给我看看",
                "我怕走错，导航好找嘛",
                "你帮我顺一下我现在该咋弄",
            ],
        },
        {
            "user_id": "user_normal",
            "title": "正常询问场景",
            "messages": [
                "你好，我想了解一下你们假发",
                "我在上海静安这边，你们有门店吗",
                "是哪一家店呀",
                "具体地址方便发我吗",
                "我从静安寺过去方便吗",
                "你们价格一般是多少",
                "如果我想自然一点，适合哪种",
                "可以先到店看看吗",
                "到店前需要预约吗",
                "那预约怎么安排",
                "联系方式发我一下吧",
                "加上以后是和谁沟通",
                "周日下午去可以吗",
                "如果我到店了怎么找你们",
                "位置图再给我看看",
                "当天能先设计吗",
                "后面修剪也能在店里做吗",
                "如果今天不定，改天再去也行吧",
                "那你帮我总结一下重点",
                "好，我先加你们，晚点定时间",
            ],
        },
        {
            "user_id": "user_loop_special",
            "title": "地址联系方式来回绕场景",
            "messages": [
                "你好，我不在上海，在杭州可以做吗",
                "那外地怎么预约",
                "是不是要先加你们联系方式",
                "联系方式发我一下",
                "我刚没看清，再发一次",
                "如果后面我要去上海门店呢",
                "那上海哪个店方便一点",
                "你先把位置图发我看看",
                "这个店怎么预约",
                "那联系方式是不是还得再发我",
                "我现在又不确定要不要去上海了",
                "如果我还是在杭州，你们怎么做",
                "那还能寄吗",
                "我如果下周去上海，再看哪家店近",
                "位置图再发我一次",
                "我刚又翻不到联系方式了",
                "那你现在帮我顺一下：外地、到店、预约分别怎么弄",
                "如果我最后决定去上海徐汇呢",
                "那我到店前是不是还得联系你们",
                "好，你最后再给我一句最直接的操作就行",
            ],
        },
    ]


def summarize_media(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    media_items: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("type", "") or "")
        if not media_type:
            continue
        media_items.append(
            {
                "type": media_type,
                "path": str(item.get("path", "") or ""),
                "target_store": str(item.get("target_store", "") or ""),
            }
        )
    return {
        "triggered": bool(media_items),
        "items": media_items,
        "types": [item["type"] for item in media_items],
    }


def run_scenario(agent: CustomerServiceAgent, scenario: Dict[str, Any]) -> Dict[str, Any]:
    session_id = f"{scenario['user_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    user_name = scenario["user_id"]
    history: List[Dict[str, str]] = []
    turns: List[Dict[str, Any]] = []

    for turn_no, message in enumerate(scenario["messages"], 1):
        decision = agent.decide(
            session_id=session_id,
            user_name=user_name,
            latest_user_text=message,
            conversation_history=history,
        )
        extra_video = agent.mark_reply_sent(session_id, user_name, decision.reply_text)
        media_queue = list(decision.media_items or [])

        post_media_decision = agent.judge_post_reply_media(
            session_id=session_id,
            user_name=user_name,
            latest_user_text=message,
            reply_text=decision.reply_text,
            conversation_history=history,
            decision=decision,
        )
        media_queue.extend(
            agent.build_post_text_media_queue(
                session_id=session_id,
                user_name=user_name,
                planned_media_items=list(post_media_decision.media_items or []),
                extra_media_items=[],
            )
        )
        if extra_video:
            media_queue.append(extra_video)

        for item in media_queue:
            if isinstance(item, dict):
                agent.mark_media_sent(session_id, user_name, item, success=True)

        media = summarize_media(media_queue)
        turns.append(
            {
                "turn": turn_no,
                "user_question": message,
                "assistant_reply": decision.reply_text,
                "media_triggered": media["triggered"],
                "media_types": media["types"],
                "media_items": media["items"],
                "intent": decision.intent,
                "route_reason": decision.route_reason,
                "reply_source": decision.reply_source,
                "rule_id": decision.rule_id,
            }
        )

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": decision.reply_text})
        if len(history) > 20:
            del history[:-20]

    return {
        "user_id": scenario["user_id"],
        "title": scenario["title"],
        "session_id": session_id,
        "turn_count": len(turns),
        "turns": turns,
    }


def build_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# DeepSeek 60 轮对话验证")
    lines.append("")
    lines.append(f"- 生成时间：{report['generated_at']}")
    lines.append(f"- 模型：{report['model_name']}")
    lines.append(f"- 总轮数：{report['total_turns']}")
    lines.append("")

    for scenario in report["results"]:
        lines.append(f"## {scenario['title']}")
        lines.append("")
        lines.append(f"- 用户 ID：`{scenario['user_id']}`")
        lines.append(f"- 会话 ID：`{scenario['session_id']}`")
        lines.append(f"- 轮数：{scenario['turn_count']}")
        lines.append("")
        for turn in scenario["turns"]:
            lines.append(f"### 第 {turn['turn']} 轮")
            lines.append(f"- 用户怎么问：{turn['user_question']}")
            lines.append(f"- 客服怎么答：{turn['assistant_reply']}")
            lines.append(f"- 这一轮有没有触发媒体：{'有' if turn['media_triggered'] else '没有'}")
            if turn["media_triggered"]:
                lines.append(f"- 媒体类型：{', '.join(turn['media_types'])}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    now = datetime.now()
    report_dir = PROJECT_ROOT / "data" / "deepseek_validation_reports"
    sim_root = PROJECT_ROOT / "data" / "deepseek_validation_runtime" / now.strftime("%Y%m%d_%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    sim_root.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict[str, Any]] = []
    model_name = ""

    for scenario in scenarios():
        scenario_dir = sim_root / scenario["user_id"]
        agent = build_agent(scenario_dir)
        if not model_name:
            model_name = str(agent.llm_service.get_current_model_name() or "")
        all_results.append(run_scenario(agent, scenario))

    report = {
        "generated_at": now.isoformat(),
        "model_name": model_name,
        "total_turns": sum(int(item["turn_count"]) for item in all_results),
        "results": all_results,
    }

    stamp = now.strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"deepseek_60_turn_validation_{stamp}.json"
    md_path = report_dir / f"deepseek_60_turn_validation_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown(report), encoding="utf-8")

    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "total_turns": report["total_turns"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
