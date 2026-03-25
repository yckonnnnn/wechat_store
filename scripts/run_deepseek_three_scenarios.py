#!/usr/bin/env python3
"""
运行 3 组真实 DeepSeek 对话模拟，并输出完整记录。
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
            "id": "repeat_questions",
            "title": "重复提问场景",
            "goal": "验证不会反复追问、不会乱跳、重复问位置和联系方式时媒体动作稳定",
            "messages": [
                "你好，我在北京朝阳，门店在哪呀？",
                "具体地址发我一下",
                "怎么去呀？",
                "位置图给我看看",
                "再发一次位置图",
                "我刚没看清，再发一下",
                "你们这边怎么联系？",
                "加微信怎么加？",
                "联系方式发我一下",
                "再发一次联系方式",
                "价格大概多少？",
                "价格多少呀",
                "你刚说的那个店具体在哪",
                "位置图再发我一下",
                "还是那个北京店对吧？",
                "那边要预约吗？",
                "怎么预约？",
                "联系方式再给我一下",
                "位置图还能发吗",
                "行，那你再总结一下我现在该怎么过去",
            ],
        },
        {
            "id": "typo_inputs",
            "title": "错别字场景",
            "goal": "验证带错别字和口语化输入时，仍能接住用户意思并保持上下文",
            "messages": [
                "泥嚎，我在上嗨，想做假法",
                "静俺寺附近有店嘛",
                "地只发我康康",
                "再发下味置图",
                "我从人呙过去方不方便",
                "价各大楷多少",
                "能先约一下麻",
                "怎么约阿",
                "连系方式给我下",
                "微新怎么加",
                "我刚没收到，在发一次",
                "那个店是静俺那个吗",
                "我周六下物过去可以吗",
                "需要提钱约吗",
                "如果我做完想邮计可以吗",
                "外地也能做吗",
                "那你把连系方式在给我下",
                "地只图再来一张",
                "我怕走错，到了咋找",
                "你帮我顺一遍流程吧",
            ],
        },
        {
            "id": "normal_user_flow",
            "title": "正常用户完整流程",
            "goal": "验证一个正常用户从咨询、选店、问价、预约、拿联系方式到确认到店的完整过程",
            "messages": [
                "你好，我想了解一下你们假发",
                "我在上海徐汇这边，有门店吗？",
                "具体是哪家店呀",
                "可以发个位置图吗",
                "我从徐家汇过去远吗",
                "你们一般都是什么价格",
                "不同价位差别大吗",
                "我主要是头发少，适合哪种",
                "可以先到店看看吗",
                "到店前需要预约吗",
                "那怎么预约比较方便",
                "你们联系方式给我一下",
                "我加了以后是和谁对接",
                "周日下午过去可以吗",
                "到时候去了怎么找你们",
                "位置图再给我看一下",
                "如果当天定了，多久能做好",
                "后续修剪也可以在店里做吗",
                "行，那你帮我总结一下今天要点",
                "我先加你们，晚点确定时间",
            ],
        },
    ]


def media_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    names: List[str] = []
    details: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("type", "") or "")
        path = str(item.get("path", "") or "")
        store = str(item.get("store", "") or "")
        if media_type:
            names.append(media_type)
            details.append({"type": media_type, "path": path, "store": store})
    return {
        "sent": bool(details),
        "types": names,
        "details": details,
    }


def run_scenario(agent: CustomerServiceAgent, scenario: Dict[str, Any], report_dir: Path) -> Dict[str, Any]:
    session_id = f"{scenario['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    user_name = scenario["id"]
    history: List[Dict[str, str]] = []
    turns: List[Dict[str, Any]] = []

    for index, message in enumerate(scenario["messages"], 1):
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

        media = media_summary(media_queue)
        turns.append(
            {
                "turn": index,
                "user": message,
                "assistant": decision.reply_text,
                "reply_source": decision.reply_source,
                "intent": decision.intent,
                "route_reason": decision.route_reason,
                "rule_id": decision.rule_id,
                "media_plan": decision.media_plan,
                "media_sent": media["sent"],
                "media_types": media["types"],
                "media_details": media["details"],
            }
        )

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": decision.reply_text})
        if len(history) > 20:
            del history[:-20]

    return {
        "scenario_id": scenario["id"],
        "title": scenario["title"],
        "goal": scenario["goal"],
        "session_id": session_id,
        "turn_count": len(turns),
        "turns": turns,
    }


def build_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# DeepSeek 三组真实对话模拟报告")
    lines.append("")
    lines.append(f"- 生成时间：{report['generated_at']}")
    lines.append(f"- 模型：{report['model_name']}")
    lines.append(f"- 总场景数：{len(report['results'])}")
    lines.append("")

    for scenario in report["results"]:
        lines.append(f"## {scenario['title']}")
        lines.append("")
        lines.append(f"- 目标：{scenario['goal']}")
        lines.append(f"- 会话 ID：`{scenario['session_id']}`")
        lines.append(f"- 轮数：{scenario['turn_count']}")
        lines.append("")
        for turn in scenario["turns"]:
            lines.append(f"### 第 {turn['turn']} 轮")
            lines.append(f"- 用户：{turn['user']}")
            lines.append(f"- 客服：{turn['assistant']}")
            lines.append(f"- 是否发送媒体：{'是' if turn['media_sent'] else '否'}")
            if turn["media_sent"]:
                lines.append(f"- 媒体动作：{', '.join(turn['media_types'])}")
                for detail in turn["media_details"]:
                    extra = []
                    if detail["store"]:
                        extra.append(f"门店={detail['store']}")
                    if detail["path"]:
                        extra.append(f"路径={detail['path']}")
                    lines.append(f"- 媒体明细：{detail['type']}" + (f"（{'；'.join(extra)}）" if extra else ""))
            else:
                lines.append(f"- 媒体动作：none")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sim_data_dir = PROJECT_ROOT / "data" / "deepseek_simulations" / timestamp
    report_dir = PROJECT_ROOT / "data" / "deepseek_simulation_reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    agent = build_agent(sim_data_dir)
    model_name = agent.llm_service.config_manager.get_current_model()

    results = [run_scenario(agent, scenario, report_dir) for scenario in scenarios()]

    report = {
        "generated_at": datetime.now().isoformat(),
        "model_name": model_name,
        "sim_data_dir": str(sim_data_dir),
        "results": results,
    }

    json_path = report_dir / f"deepseek_three_scenarios_{timestamp}.json"
    md_path = report_dir / f"deepseek_three_scenarios_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "json_report": str(json_path),
                "markdown_report": str(md_path),
                "sim_data_dir": str(sim_data_dir),
                "model_name": model_name,
                "scenario_count": len(results),
                "turns_per_scenario": [item["turn_count"] for item in results],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
