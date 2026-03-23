from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .agent_types import AgentDecision


def decide_llm_reply(
    agent,
    latest_user_text: str,
    intent: str,
    route_reason: str,
    conversation_history: List[Dict[str, str]],
    session_state: Optional[Dict[str, Any]] = None,
    kb_blocked_by_polite_guard: bool = False,
    kb_polite_guard_reason: str = "",
    user_message_override: str = "",
    rule_id: str = "LLM_GENERAL",
    kb_match_score: float = 0.0,
    kb_match_question: str = "",
    kb_match_mode: str = "",
    kb_item_id: str = "",
    kb_variant_total: int = 0,
    kb_variant_selected_index: int = -1,
    kb_variant_fallback_llm: bool = False,
    kb_confident: bool = False,
    allow_address_guardrails: bool = True,
    allow_precise_address_closure: bool = True,
) -> AgentDecision:
    agent._current_prompt_conversation_history = conversation_history or []
    llm_started_at = time.perf_counter()
    prompt_started_at = time.perf_counter()
    composed_prompt, prompt_meta = agent._build_general_llm_prompt(latest_user_text)
    prompt_build_ms = int((time.perf_counter() - prompt_started_at) * 1000)
    agent.llm_service.set_system_prompt(composed_prompt)
    effective_user_message = user_message_override or latest_user_text
    conversation_state = prompt_meta.get("conversation_state", {}) if isinstance(prompt_meta, dict) else {}
    if (
        not user_message_override
        and bool(prompt_meta.get("standard_reply_hit", False))
        and str(prompt_meta.get("standard_reply_answer", "") or "").strip()
    ):
        effective_user_message = (
            f"用户刚问：{latest_user_text}\n"
            f"高置信标准话术核心结论：{str(prompt_meta.get('standard_reply_answer', '') or '').strip()}\n"
            "请严格保留关键事实、数字、时间或区间，再改写成自然的客服回复。"
        )
    if (
        not user_message_override
        and str(prompt_meta.get("standard_reply_intent", "") or "") == "appointment"
        and str(conversation_state.get("last_answer_type", "") or "") == "appointment"
    ):
        effective_user_message = (
            f"用户刚问：{latest_user_text}\n"
            "用户上一轮已经知道需要预约了，这一轮是在追问具体怎么预约。\n"
            "请直接说明下一步怎么操作，避免重复“我们是预约制的呢”。"
        )
    direct_standard_reply = (
        bool(prompt_meta.get("standard_reply_hit", False))
        and str(prompt_meta.get("standard_reply_intent", "") or "") in {"service_hours", "lifespan"}
        and str(prompt_meta.get("standard_reply_answer", "") or "").strip()
    )
    llm_result = agent.llm_service.generate_reply_sync(
        user_message=effective_user_message,
        conversation_history=conversation_history,
    )
    if isinstance(llm_result, tuple) and len(llm_result) == 3:
        success, result, llm_metrics = llm_result
    elif isinstance(llm_result, tuple) and len(llm_result) == 2:
        success, result = llm_result
        llm_metrics = {}
    else:
        success = False
        result = "invalid_llm_result"
        llm_metrics = {}
    llm_metrics = dict(llm_metrics or {})
    model_name = agent.llm_service.get_current_model_name()
    if not success:
        return AgentDecision(
            reply_text=agent._render_template("llm_fallback"),
            intent=intent,
            route_reason=route_reason,
            reply_goal="解答",
            media_plan="none",
            reply_source="fallback",
            rule_id="LLM_FALLBACK",
            rule_applied=False,
            llm_model=model_name,
            llm_fallback_reason=str(result or ""),
            kb_match_score=kb_match_score,
            kb_match_question=kb_match_question,
            kb_match_mode=kb_match_mode,
            kb_item_id=kb_item_id,
            kb_variant_total=kb_variant_total,
            kb_variant_selected_index=kb_variant_selected_index,
            kb_variant_fallback_llm=kb_variant_fallback_llm,
            kb_confident=kb_confident,
            kb_blocked_by_polite_guard=kb_blocked_by_polite_guard,
            kb_polite_guard_reason=kb_polite_guard_reason,
            reply_mode=agent.reply_mode,
            standard_reply_hit=bool(prompt_meta.get("standard_reply_hit", False)),
            standard_reply_question=str(prompt_meta.get("standard_reply_question", "") or ""),
            standard_reply_confidence=str(prompt_meta.get("standard_reply_confidence", "") or ""),
            standard_reply_intent=str(prompt_meta.get("standard_reply_intent", "") or ""),
            brand_knowledge_used=bool(prompt_meta.get("brand_knowledge_used", False)),
            prompt_build_ms=prompt_build_ms,
            llm_request_ms=int(llm_metrics.get("request_ms", 0) or 0),
            llm_total_ms=int((time.perf_counter() - llm_started_at) * 1000),
            llm_attempt_count=int(llm_metrics.get("attempt_count", 0) or 0),
            llm_message_count=int(llm_metrics.get("message_count", 0) or 0),
            system_prompt_chars=int(llm_metrics.get("system_prompt_chars", 0) or 0),
        )

    if direct_standard_reply:
        llm_reply = agent._normalize_reply_text(str(prompt_meta.get("standard_reply_answer", "") or ""))
    else:
        llm_reply = agent._normalize_reply_text(result)
    llm_reply, reply_closure_info = agent._apply_llm_reply_guardrails(
        latest_user_text=latest_user_text,
        reply_text=llm_reply,
        session_state=session_state or {},
        conversation_history=conversation_history,
        allow_address_guardrails=allow_address_guardrails,
        allow_precise_address_closure=allow_precise_address_closure,
    )

    return AgentDecision(
        reply_text=llm_reply,
        intent=intent,
        route_reason=route_reason,
        reply_goal="解答",
        media_plan="none",
        reply_source="llm",
        rule_id=rule_id,
        rule_applied=False,
        llm_model=model_name,
        kb_match_score=kb_match_score,
        kb_match_question=kb_match_question,
        kb_match_mode=kb_match_mode,
        kb_item_id=kb_item_id,
        kb_variant_total=kb_variant_total,
        kb_variant_selected_index=kb_variant_selected_index,
        kb_variant_fallback_llm=kb_variant_fallback_llm,
        kb_confident=kb_confident,
        kb_blocked_by_polite_guard=kb_blocked_by_polite_guard,
        kb_polite_guard_reason=kb_polite_guard_reason,
        reply_mode=agent.reply_mode,
        standard_reply_hit=bool(prompt_meta.get("standard_reply_hit", False)),
        standard_reply_question=str(prompt_meta.get("standard_reply_question", "") or ""),
        standard_reply_confidence=str(prompt_meta.get("standard_reply_confidence", "") or ""),
        standard_reply_intent=str(prompt_meta.get("standard_reply_intent", "") or ""),
        brand_knowledge_used=bool(prompt_meta.get("brand_knowledge_used", False)),
        prompt_build_ms=prompt_build_ms,
        llm_request_ms=int(llm_metrics.get("request_ms", 0) or 0),
        llm_total_ms=int((time.perf_counter() - llm_started_at) * 1000),
        llm_attempt_count=int(llm_metrics.get("attempt_count", 0) or 0),
        llm_message_count=int(llm_metrics.get("message_count", 0) or 0),
        system_prompt_chars=int(llm_metrics.get("system_prompt_chars", 0) or 0),
        reply_closure_info=dict(reply_closure_info or {}),
    )


def select_kb_variant_answer(
    agent,
    answers: List[str],
    user_state: Dict[str, Any],
    user_id_hash: str = "",
) -> Tuple[str, int, bool]:
    candidates: List[str] = []
    seen: set[str] = set()
    for raw in answers or []:
        text = str(raw or "").strip()
        if not text:
            continue
        norm = agent._normalize_for_dedupe(text)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        candidates.append(text)
        if len(candidates) >= 5:
            break
    if not candidates:
        return "", -1, False

    previous = agent.summarize_recent_assistant_hashes_from_logs(user_id_hash=user_id_hash, limit=80)
    previous |= set(user_state.get("recent_reply_hashes", []) or [])
    for idx, candidate in enumerate(candidates):
        if agent._normalize_for_dedupe(candidate) not in previous:
            return candidate, idx, False
    return "", -1, True


def remember_selected_kb_answer(
    agent,
    user_state: Dict[str, Any],
    user_id_hash: str,
    answer_text: str,
) -> None:
    normalized = agent._normalize_for_dedupe(answer_text)
    if not normalized:
        return

    recent_hashes = list(user_state.get("recent_reply_hashes", []) or [])
    recent_hashes.append(normalized)
    if len(recent_hashes) > 40:
        recent_hashes = recent_hashes[-40:]
    user_state["recent_reply_hashes"] = recent_hashes

    if user_id_hash:
        agent.memory_store.update_user_state(user_id_hash, user_state)
        agent.memory_store.save()


def build_kb_variant_fallback_prompt(agent, latest_user_text: str, kb_question: str, kb_answer: str) -> str:
    del agent
    return (
        f"用户刚问：{latest_user_text}\n"
        f"命中的知识库问题：{kb_question}\n"
        f"核心结论：{kb_answer}\n"
        "请保持核心结论不变，改写成结论先行、完整自然的客服回复。"
    )


def rewrite_if_repeated(
    agent,
    reply_text: str,
    latest_user_text: str,
    conversation_history: List[Dict[str, str]],
    user_state: Dict[str, Any],
    user_id_hash: str = "",
) -> Tuple[str, bool]:
    normalized = agent._normalize_for_dedupe(reply_text)
    if not normalized:
        return reply_text, False

    previous = agent.summarize_recent_assistant_hashes_from_logs(user_id_hash=user_id_hash, limit=40)
    memory_hashes = set(user_state.get("recent_reply_hashes", []) or [])
    if memory_hashes:
        previous |= memory_hashes
    if normalized not in previous:
        return reply_text, False

    rewrite_prompt = (
        f"用户刚问：{latest_user_text}\n"
        f"下面这句客服话术和历史重复，请保留核心意思但换一种自然表达：{reply_text}"
    )
    composed_prompt, _ = agent._build_general_llm_prompt(latest_user_text)
    agent.llm_service.set_system_prompt(composed_prompt)

    for _ in range(2):
        ok, result, _metrics = agent.llm_service.generate_reply_sync(
            user_message=rewrite_prompt,
            conversation_history=conversation_history,
        )
        if not ok:
            continue
        candidate = agent._normalize_reply_text(result)
        if agent._normalize_for_dedupe(candidate) not in previous:
            return candidate, True
        rewrite_prompt = f"仍重复，请再次改写这句客服回复：{candidate}"

    fallback = agent._avoid_repeat(user_state, reply_text)
    return fallback, agent._normalize_for_dedupe(fallback) != normalized


def infer_answer_type(agent, text: str) -> str:
    normalized = agent.knowledge_service.normalize_user_text(text)
    if not normalized:
        return "未知"
    if any(token in normalized for token in ("愚园路", "汉口路", "花园路", "政通路", "漕溪北路", "建外soho", "亚洲大厦")):
        return "store_address"
    if any(token in normalized for token in ("上海有5家", "上海共有5家", "北京只有1家", "北京1家", "静安", "人民广场", "人广", "虹口", "五角场", "徐汇", "朝阳区")) and any(
        token in normalized for token in ("门店", "地址", "位置", "区域", "城市")
    ):
        return "address_general"
    if "预约" in normalized:
        return "appointment"
    if any(token in normalized for token in ("9:30", "18:00", "营业时间", "周一到周五")):
        return "service_hours"
    if any(token in normalized for token in ("3到5年", "3-5年", "三到五年")):
        return "lifespan"
    if any(token in normalized for token in ("远程定制", "不方便到店")):
        return "remote_support"
    if any(token in normalized for token in ("3000", "4000", "5000", "6000", "价格")):
        return "price"
    return "general"


def top_kb_examples(agent, query: str, limit: int = 3) -> List[Tuple[str, str]]:
    q = agent._normalize_for_dedupe(agent.knowledge_service.normalize_user_text(query))
    if not q:
        return []

    scored: List[Tuple[float, Tuple[str, str]]] = []
    items = agent.knowledge_service.get_all_items()
    for item in items:
        question = (item.question or "").strip()
        answer = (item.answer or "").strip()
        if not question or not answer:
            continue
        score = simple_overlap_score(agent, q, agent._normalize_for_dedupe(question))
        if score > 0:
            scored.append((score, (question, answer)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:limit]]


def top_brand_knowledge_snippets(agent, query: str, limit: int = 3) -> List[str]:
    text = agent._brand_knowledge_doc_text.strip()
    q = agent._normalize_for_dedupe(agent.knowledge_service.normalize_user_text(query))
    if not text or not q:
        return []

    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    scored: List[Tuple[float, str]] = []
    for chunk in chunks:
        normalized_chunk = agent._normalize_for_dedupe(agent.knowledge_service.normalize_user_text(chunk))
        score = simple_overlap_score(agent, q, normalized_chunk)
        if score > 0:
            scored.append((score, chunk[:360]))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def simple_overlap_score(agent, a: str, b: str) -> float:
    del agent
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
