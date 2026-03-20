#!/usr/bin/env python3
"""
导出多轮对话的真实 LLM 请求样例与回复结果。
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
from src.services.llm_service import LLMService, LLMWorker
from src.utils.constants import BRAND_KNOWLEDGE_FILE, ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


def build_agent(sim_dir: Path) -> CustomerServiceAgent:
    sim_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)
    agent = CustomerServiceAgent(
        knowledge_service=KnowledgeService(
            KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE),
            address_config_path=Path("config") / "address.json",
        ),
        llm_service=LLMService(ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)),
        memory_store=MemoryStore(sim_dir / "agent_memory.json"),
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


def build_soft_context_prompt(agent: CustomerServiceAgent, latest_user_text: str) -> Dict[str, Any]:
    normalized_text = agent.knowledge_service.normalize_user_text(latest_user_text)
    faq_detail = agent.knowledge_service.find_answer_detail(normalized_text, threshold=agent.knowledge_threshold)
    faq_examples = agent._top_kb_examples(normalized_text, limit=3)
    faq_block = "\n".join([f"- 问：{q}\n  答：{a}" for q, a in faq_examples]) or "（当前无高相关标准话术）"
    enterprise_guard = agent._enterprise_guard_doc_text or "（企业知识约束文档缺失，请按已有品牌口径稳妥回复）"
    brand_snippets = agent._top_brand_knowledge_snippets(normalized_text, limit=3)
    brand_block = "\n\n".join(brand_snippets) if brand_snippets else "（当前无高相关品牌知识片段）"

    faq_priority_block = "（当前无高置信标准话术命中）"
    prompt_meta = {
        "standard_reply_hit": False,
        "standard_reply_question": "",
        "standard_reply_confidence": "",
        "standard_reply_answer": "",
        "standard_reply_intent": "",
        "brand_knowledge_used": bool(brand_snippets),
    }
    if faq_detail.get("matched"):
        prompt_meta.update(
            {
                "standard_reply_hit": True,
                "standard_reply_question": str(faq_detail.get("question", "") or ""),
                "standard_reply_confidence": str(faq_detail.get("confidence", "") or ""),
                "standard_reply_answer": str(faq_detail.get("answer", "") or "").strip(),
                "standard_reply_intent": str(faq_detail.get("intent", "") or "").strip().lower(),
            }
        )
        faq_priority_block = (
            f"问题：{prompt_meta['standard_reply_question'] or '未知'}\n"
            f"建议答案：{prompt_meta['standard_reply_answer']}\n"
            f"置信度：{prompt_meta['standard_reply_confidence'] or 'unknown'}"
        )

    prompt = (
        "你是艾耐儿假发客服助理，请只根据当前对话上下文、标准话术、企业知识约束和品牌知识库自然回复。\n"
        "不要输出解释，不要输出JSON，只输出最终客服回复。\n\n"
        f"【高置信标准话术命中】\n{faq_priority_block}\n\n"
        f"【企业知识约束】\n{enterprise_guard}\n\n"
        f"【相关标准话术参考】\n{faq_block}\n\n"
        f"【品牌知识库参考】\n{brand_block}"
    )
    return {
        "system_prompt": prompt,
        "prompt_meta": prompt_meta,
        "effective_user_message": latest_user_text,
    }


def build_request_payload(
    agent: CustomerServiceAgent,
    latest_user_text: str,
    conversation_history: List[Dict[str, str]],
    mode: str,
) -> Dict[str, Any]:
    if mode == "soft_context":
        request_info = build_soft_context_prompt(agent, latest_user_text)
        prompt = request_info["system_prompt"]
        prompt_meta = request_info["prompt_meta"]
        effective_user_message = request_info["effective_user_message"]
    else:
        prompt, prompt_meta = agent._build_general_llm_prompt(latest_user_text)
        effective_user_message = latest_user_text
        if (
            bool(prompt_meta.get("standard_reply_hit", False))
            and str(prompt_meta.get("standard_reply_answer", "") or "").strip()
        ):
            effective_user_message = (
                f"用户刚问：{latest_user_text}\n"
                f"高置信标准话术核心结论：{str(prompt_meta.get('standard_reply_answer', '') or '').strip()}\n"
                "请严格保留关键事实、数字、时间或区间，再改写成自然的客服回复。"
            )
    model_name = agent.llm_service.get_current_model_name()
    model_config = agent.llm_service.config_manager.get_model_config(model_name)
    payload = {
        "model": model_config.get("model", ""),
        "messages": [
            {"role": "system", "content": prompt},
            *conversation_history,
            {"role": "user", "content": effective_user_message},
        ],
        "stream": False,
        "temperature": LLMWorker.DEFAULT_TEMPERATURE,
        "max_tokens": 500,
    }
    return {
        "system_prompt": prompt,
        "prompt_meta": prompt_meta,
        "effective_user_message": effective_user_message,
        "payload": payload,
    }


def run_case(messages: List[str], mode: str = "soft_context") -> Dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sim_dir = Path("data") / "request_inspection_runtime" / timestamp
    agent = build_agent(sim_dir)
    history: List[Dict[str, str]] = []
    session_id = f"inspect_{timestamp}"
    user_name = f"inspect_{timestamp}"
    turns: List[Dict[str, Any]] = []
    request_samples: List[Dict[str, Any]] = []

    for idx, text in enumerate(messages, 1):
        request_info = build_request_payload(agent, text, history, mode=mode)
        agent.llm_service.set_system_prompt(request_info["system_prompt"])
        ok, result = agent.llm_service.generate_reply_sync(
            user_message=request_info["effective_user_message"],
            conversation_history=history,
        )
        reply_text = str(result or "").strip()
        if not ok:
            reply_text = f"[LLM调用失败] {reply_text}"
        turns.append(
            {
                "turn": idx,
                "user": text,
                "reply_text": reply_text,
                "reply_source": "llm_raw",
                "intent": "",
                "route_reason": "",
                "media_plan": "none",
                "standard_reply_hit": bool(request_info["prompt_meta"].get("standard_reply_hit", False)),
                "standard_reply_question": str(request_info["prompt_meta"].get("standard_reply_question", "") or ""),
                "standard_reply_confidence": str(request_info["prompt_meta"].get("standard_reply_confidence", "") or ""),
                "brand_knowledge_used": bool(request_info["prompt_meta"].get("brand_knowledge_used", False)),
            }
        )
        request_samples.append(
            {
                "turn": idx,
                "user": text,
                "effective_user_message": request_info["effective_user_message"],
                "prompt_meta": request_info["prompt_meta"],
                "payload": request_info["payload"],
            }
        )
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply_text})

    report = {
        "messages": messages,
        "mode": mode,
        "turns": turns,
        "request_samples": request_samples,
        "sim_dir": str(sim_dir),
    }
    out_dir = Path("data") / "request_inspection_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{timestamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(out_path)
    return report


def main() -> int:
    messages = [
        "地址在哪",
        "上海地区地址给我",
        "我知道人广",
        "人广我可以去",
        "人广要预约吗？",
        "怎么预约？",
    ]
    report = run_case(messages, mode="soft_context")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
