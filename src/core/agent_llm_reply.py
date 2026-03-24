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
    agent._current_prompt_session_state = dict(session_state or {})
    llm_started_at = time.perf_counter()
    prompt_started_at = time.perf_counter()
    composed_prompt, prompt_meta = agent._build_general_llm_prompt(latest_user_text)
    prompt_build_ms = int((time.perf_counter() - prompt_started_at) * 1000)
    agent.llm_service.set_system_prompt(composed_prompt)
    effective_user_message = user_message_override or latest_user_text
    conversation_state = prompt_meta.get("conversation_state", {}) if isinstance(prompt_meta, dict) else {}
    previous_topic = str((session_state or {}).get("last_answer_topic", "") or "")
    previous_facts = dict((session_state or {}).get("last_answer_facts", {}) or {})
    previous_answer_text = str((session_state or {}).get("last_answer_text_normalized", "") or "")
    current_topic = str(prompt_meta.get("standard_reply_intent", "") or "").strip().lower()
    if current_topic not in {"price", "service_hours", "lifespan"}:
        current_topic = infer_answer_type(agent, latest_user_text)
        if current_topic == "address_general" and str(conversation_state.get("store_confirmed", "") or "").strip() != "未知":
            current_topic = "store_recommendation"
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
        and previous_topic
        and previous_topic == current_topic
        and previous_answer_text
    ):
        current_fact_text = str(prompt_meta.get("standard_reply_answer", "") or "").strip()
        if not current_fact_text:
            current_fact_text = base_followup_fact_hint(current_topic=current_topic, previous_facts=previous_facts, conversation_state=conversation_state)
        if current_fact_text:
            effective_user_message = (
                f"用户当前问题：{latest_user_text}\n"
                f"上一轮已经回答的主题：{previous_topic}\n"
                f"当前会话阶段：{str((session_state or {}).get('conversation_stage', '') or 'unknown')}\n"
                f"本轮动作：{str((session_state or {}).get('current_turn_action', '') or 'followup_same_topic')}\n"
                f"上一轮核心事实：{_format_contextual_facts(previous_facts)}\n"
                f"这一轮必须保留的核心事实：{current_fact_text}\n"
                "请只回答用户这轮新增的问题，不要整段重复上一轮；核心数字、时间、门店名不能改；"
                "除非用户明确问怎么联系，否则不要转去留电话或加好友。"
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
    success, result, llm_metrics = unpack_llm_result(llm_result)
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
        ok, result, _metrics = unpack_llm_result(agent.llm_service.generate_reply_sync(
            user_message=rewrite_prompt,
            conversation_history=conversation_history,
        ))
        if not ok:
            continue
        candidate = agent._normalize_reply_text(result)
        if agent._normalize_for_dedupe(candidate) not in previous:
            return candidate, True
        rewrite_prompt = f"仍重复，请再次改写这句客服回复：{candidate}"

    fallback = agent._avoid_repeat(user_state, reply_text)
    return fallback, agent._normalize_for_dedupe(fallback) != normalized


def contextualize_topic_followup_reply(
    agent,
    latest_user_text: str,
    base_reply_text: str,
    current_topic: str,
    previous_topic: str,
    previous_facts: Dict[str, Any],
    current_facts: Dict[str, Any],
    conversation_history: List[Dict[str, str]],
    session_state: Dict[str, Any],
) -> Tuple[str, bool]:
    if current_topic not in {"price", "service_hours", "lifespan", "store_recommendation", "appointment"}:
        return base_reply_text, False
    if current_topic != previous_topic:
        if not (
            current_topic == "appointment"
            and previous_topic == "store_recommendation"
            and str((session_state or {}).get("current_turn_action", "") or "") == "advance_to_next_step"
        ):
            return base_reply_text, False
    previous_expression = str(((session_state or {}).get("topic_reply_memory", {}) or {}).get(current_topic, "") or "")
    stage = str((session_state or {}).get("conversation_stage", "") or "")
    action = str((session_state or {}).get("current_turn_action", "") or "")
    previous_text = str(session_state.get("last_answer_text_normalized", "") or "")
    previous_store_facts = dict(previous_facts or {})
    if current_topic == "appointment" and not current_facts.get("target_store") and previous_store_facts.get("target_store"):
        current_facts = dict(current_facts or {})
        current_facts["target_store"] = previous_store_facts.get("target_store")
    if current_topic == "appointment" and not current_facts.get("appointment_ready"):
        current_facts = dict(current_facts or {})
        current_facts["appointment_ready"] = True

    if not previous_text and current_topic != "appointment":
        return base_reply_text, False

    prompt = (
        f"用户当前问题：{latest_user_text}\n"
        f"上一轮已回答主题：{previous_topic}\n"
        f"当前会话阶段：{stage or 'unknown'}\n"
        f"本轮动作：{action or 'followup_same_topic'}\n"
        f"本主题最近一次表达方式：{previous_expression or 'unknown'}\n"
        f"上一轮核心事实：{_format_contextual_facts(previous_facts)}\n"
        f"这一轮必须保留的核心事实：{_format_contextual_facts(current_facts)}\n"
        f"这一轮基准回复：{base_reply_text}\n"
        "请用一句自然客服话术回答用户这轮新增问题。\n"
        "要求：不要整段重复上一轮；核心事实、数字、时间、门店名不能改；"
        "如果用户是在确认、比较、补问，就补充差异点；如果是在表达异议，先回应异议；"
        "如果已经确认门店或已经发过位置图，不要回头重新问城市；"
        "如果是在继续问预约，就直接承接预约下一步，不要跳去联系方式，除非用户明确问怎么联系。"
    )
    agent._current_prompt_session_state = dict(session_state or {})
    composed_prompt, _ = agent._build_general_llm_prompt(latest_user_text)
    agent.llm_service.set_system_prompt(composed_prompt)
    success, result, _metrics = unpack_llm_result(
        agent.llm_service.generate_reply_sync(
            user_message=prompt,
            conversation_history=conversation_history,
        )
    )
    if success:
        candidate = agent._normalize_reply_text(result)
        normalized_candidate = agent._normalize_for_dedupe(candidate)
        if candidate and normalized_candidate and _candidate_preserves_contextual_facts(current_topic=current_topic, current_facts=current_facts, candidate=candidate):
            if not previous_text or normalized_candidate != previous_text:
                return candidate, True
            if current_topic == "appointment" and action == "advance_to_next_step":
                return candidate, True

    fallback = build_contextual_followup_fallback(
        agent,
        current_topic=current_topic,
        current_facts=current_facts,
        previous_facts=previous_facts,
    )
    if fallback and agent._normalize_for_dedupe(fallback) != previous_text:
        return fallback, True
    return base_reply_text, False


def build_contextual_followup_fallback(
    agent,
    current_topic: str,
    current_facts: Dict[str, Any],
    previous_facts: Dict[str, Any],
) -> str:
    del previous_facts
    if current_topic == "price":
        return agent._normalize_reply_text(
            "姐姐，大方向还是在3000、4000、5000、6000这些区间里，不过具体还要看材质、长度和想要的效果。"
        )
    if current_topic == "service_hours":
        business_hours = str(current_facts.get("business_hours", "") or "上午9:30到下午6:00")
        return agent._normalize_reply_text(f"姐姐，时间没变哦，还是{business_hours}。")
    if current_topic == "lifespan":
        lifespan = str(current_facts.get("lifespan", "") or "3到5年")
        return agent._normalize_reply_text(f"姐姐，大方向还是{lifespan}，主要看平时护理和佩戴频率。")
    if current_topic == "store_recommendation":
        store_name = str(current_facts.get("store_name", "") or "这家门店")
        return agent._normalize_reply_text(f"姐姐，是的哦，推荐您去{store_name}会更方便，位置图我已经给您发了。")
    if current_topic == "appointment":
        return agent._normalize_reply_text("姐姐，是需要提前预约的，您把大概方便的时间告诉我，我这边就帮您往下安排。")
    return ""


def _format_contextual_facts(facts: Dict[str, Any]) -> str:
    if not isinstance(facts, dict) or not facts:
        return "无"
    pairs = []
    for key, value in facts.items():
        if value in (None, "", [], {}):
            continue
        pairs.append(f"{key}={value}")
    return "；".join(pairs) if pairs else "无"


def base_followup_fact_hint(
    current_topic: str,
    previous_facts: Dict[str, Any],
    conversation_state: Dict[str, Any],
) -> str:
    if current_topic == "price":
        return str(previous_facts.get("price_range", "") or "3000-6000")
    if current_topic == "service_hours":
        return str(previous_facts.get("business_hours", "") or "上午9:30到下午6:00")
    if current_topic == "lifespan":
        return str(previous_facts.get("lifespan", "") or "3到5年")
    if current_topic == "store_recommendation":
        store_name = str(previous_facts.get("store_name", "") or conversation_state.get("store_confirmed", "") or "").strip()
        return store_name if store_name and store_name != "未知" else ""
    if current_topic == "appointment":
        target_store = str(previous_facts.get("target_store", "") or "").strip()
        return target_store or "需要预约"
    return ""


def _candidate_preserves_contextual_facts(current_topic: str, current_facts: Dict[str, Any], candidate: str) -> bool:
    normalized = re.sub(r"\s+", "", str(candidate or "")).lower()
    if not normalized:
        return False
    if current_topic == "price":
        return "3000" in normalized and "6000" in normalized
    if current_topic == "service_hours":
        return any(token in normalized for token in ("9:30", "930")) and any(
            token in normalized for token in ("18:00", "1800", "下午6:00", "下午6点")
        )
    if current_topic == "lifespan":
        return any(token in normalized for token in ("3到5年", "3-5年", "3～5年", "三到五年"))
    if current_topic == "store_recommendation":
        store_name = re.sub(r"\s+", "", str(current_facts.get("store_name", "") or "")).lower()
        return bool(store_name) and store_name in normalized
    if current_topic == "appointment":
        return any(token in normalized for token in ("预约", "安排", "时间", "到店"))
    return True


def unpack_llm_result(llm_result: Any) -> Tuple[bool, str, Dict[str, Any]]:
    if isinstance(llm_result, tuple) and len(llm_result) == 3:
        success, result, llm_metrics = llm_result
        return bool(success), str(result or ""), dict(llm_metrics or {})
    if isinstance(llm_result, tuple) and len(llm_result) == 2:
        success, result = llm_result
        return bool(success), str(result or ""), {}
    return False, "invalid_llm_result", {}


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
