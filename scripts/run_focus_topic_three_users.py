#!/usr/bin/env python3
"""
运行 3 个聚焦高频问题的完整对话场景，每个用户 20 轮，并输出逐轮媒体明细。
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
            "id": "user_a_price_store",
            "title": "用户 A：上海到店，重点追问价格、地址、预约",
            "messages": [
                "你好，我在上海徐汇，想了解下你们假发",
                "你们徐汇这边具体在哪",
                "我从徐家汇过去方便吗",
                "位置图发我看下",
                "价格大概怎么卖",
                "不同价位差在哪",
                "你们都是什么材质",
                "真人发和别的材质差别大吗",
                "我这种头顶稀疏适合做吗",
                "男士也能做吗",
                "到店要不要预约",
                "怎么预约比较方便",
                "营业时间是几点到几点",
                "周日晚上还能去吗",
                "如果我今天定，大概多久做好",
                "加急能不能快一点",
                "到时候做好后还可以再修剪吗",
                "联系方式给我一下",
                "位置图再发我一次",
                "你帮我把今天重点顺一遍",
            ],
        },
        {
            "id": "user_b_remote_delivery",
            "title": "用户 B：外地远程，重点追问快递、远程定制、周期",
            "messages": [
                "你好，我在杭州，想做假发",
                "外地能做吗",
                "远程定制具体怎么弄",
                "不去门店也可以吗",
                "你们怎么收费",
                "预算大概多少",
                "材质一般有哪些",
                "真人发好打理吗",
                "男士发际线后移能做吗",
                "我头围不会量怎么办",
                "做好以后可以快递给我吗",
                "快递一般几天到",
                "如果不合适还能调整吗",
                "整个流程大概要多久",
                "加急的话最快多久能好",
                "营业时间发我一下",
                "晚上能沟通吗",
                "联系方式发我一下",
                "后面远程沟通是微信还是电话",
                "你帮我总结下远程定制流程",
            ],
        },
        {
            "id": "user_c_men_material",
            "title": "用户 C：男士咨询，重点追问材质、效果、时间、门店",
            "messages": [
                "你好，我老公头顶脱发，男士能做吗",
                "做出来会不会很假",
                "你们一般是什么材质",
                "真人发和化纤差在哪",
                "价格一般多少",
                "贵一点和便宜一点区别在哪",
                "夏天戴会不会闷",
                "平时怎么清洗护理",
                "做一次能戴多久",
                "上海有哪几家店",
                "静安和徐汇哪家更方便男士去",
                "具体地址能发吗",
                "位置图给我看看",
                "到店之前要预约吗",
                "周六下午营业吗",
                "如果现场定制多久能弄好",
                "当天肯定拿不到吧",
                "后面能邮寄给我吗",
                "联系方式给我一下",
                "你顺一遍男士从咨询到拿到成品的流程",
            ],
        },
    ]


def media_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    details: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        details.append(
            {
                "type": str(item.get("type", "") or ""),
                "path": str(item.get("path", "") or ""),
                "target_store": str(item.get("target_store", "") or ""),
                "route_reason": str(item.get("route_reason", "") or ""),
                "trigger_source": str(item.get("trigger_source", "") or ""),
            }
        )
    return {
        "sent": bool(details),
        "types": [x["type"] for x in details if x["type"]],
        "details": details,
    }


def run_scenario(agent: CustomerServiceAgent, scenario: Dict[str, Any]) -> Dict[str, Any]:
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
        "session_id": session_id,
        "turn_count": len(turns),
        "turns": turns,
    }


def build_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# 三个用户完整对话仿真报告")
    lines.append("")
    lines.append(f"- 生成时间：{report['generated_at']}")
    lines.append(f"- 模型：{report['model_name']}")
    lines.append(f"- 场景数：{len(report['results'])}")
    lines.append("")

    for scenario in report["results"]:
        lines.append(f"## {scenario['title']}")
        lines.append("")
        lines.append(f"- 会话 ID：`{scenario['session_id']}`")
        lines.append(f"- 轮数：{scenario['turn_count']}")
        lines.append("")
        for turn in scenario["turns"]:
            lines.append(f"### 第 {turn['turn']} 轮")
            lines.append(f"- 用户：{turn['user']}")
            lines.append(f"- 回复：{turn['assistant']}")
            lines.append(f"- 回复来源：{turn['reply_source']} / {turn['rule_id'] or '无规则ID'}")
            lines.append(f"- 主线：{turn['intent']} / {turn['route_reason']}")
            lines.append(f"- 计划媒体：{turn['media_plan']}")
            lines.append(f"- 实际触发媒体：{', '.join(turn['media_types']) if turn['media_types'] else '无'}")
            if turn["media_details"]:
                for detail in turn["media_details"]:
                    extra = []
                    if detail["target_store"]:
                        extra.append(f"门店={detail['target_store']}")
                    if detail["route_reason"]:
                        extra.append(f"原因={detail['route_reason']}")
                    if detail["trigger_source"]:
                        extra.append(f"触发源={detail['trigger_source']}")
                    extra_text = f" ({', '.join(extra)})" if extra else ""
                    lines.append(f"- 媒体明细：{detail['type']}{extra_text}")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sim_data_dir = PROJECT_ROOT / "data" / "sim_focus_topics" / stamp
    report_dir = sim_data_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    agent = build_agent(sim_data_dir)
    results: List[Dict[str, Any]] = []
    for scenario in scenarios():
        print(f"[RUN] {scenario['title']}")
        results.append(run_scenario(agent, scenario))

    report = {
        "generated_at": datetime.now().isoformat(),
        "model_name": agent.llm_service.get_current_model_name(),
        "results": results,
    }

    json_path = report_dir / "three_user_focus_topics.json"
    md_path = report_dir / "three_user_focus_topics.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown(report), encoding="utf-8")

    print(f"[DONE] JSON: {json_path}")
    print(f"[DONE] Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
