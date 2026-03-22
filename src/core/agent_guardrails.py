from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional


def normalize_reply_text(agent: Any, text: str) -> str:
    value = (text or "").strip()
    if not value:
        return agent._render_template("general_empty")

    value = re.sub(r"(?:\s+|^)(\d{1,2}:\d{2})(?:已读|未读|送达)?$", "", value).strip()
    value = " ".join(value.split())
    value = agent._strip_inline_emoji_symbols(value)
    value = re.sub(r"吧到(?=[。！？!?，,；;]|$)", "吧", value)
    value = re.sub(r"呢到(?=[。！？!?，,；;]|$)", "呢", value)

    if any(k in value for k in agent._contact_compliance_block_keywords):
        value = "姐姐，您留个☎️方式，我来加您好友"
    elif any(k in value for k in agent._shipping_block_keywords):
        value = agent._shipping_block_replacement

    if not value:
        value = "姐姐我在呢"
    value = value.rstrip("，,；; ")
    if not re.search(r"[。！？!?]$", value):
        value = f"{value}。"
    emoji = random.choice(agent._reply_emoji_pool)
    return f"{value}{emoji}"


def apply_llm_reply_guardrails(
    agent: Any,
    latest_user_text: str,
    reply_text: str,
    session_state: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    allow_address_guardrails: bool = True,
) -> str:
    text = (latest_user_text or "").strip()
    reply = (reply_text or "").strip()
    state = session_state or {}
    history = conversation_history or []

    if agent._contains_explicit_phone_number(reply):
        if agent._has_price_priority(text):
            return agent._render_guardrail_reply(agent._price_guardrail_safe_reply)
        if agent._needs_empathy_remote_support(text):
            return agent._render_guardrail_reply(agent._empathy_remote_support_fallback)
        if any(token in text for token in ("外地", "不在上海", "不在北京", "不方便到店", "远程定制", "不能去上海", "不能来上海")):
            return agent._render_guardrail_reply(agent._remote_support_fact_fallback)
        return agent._phone_leak_block_fallback

    if agent._contains_invalid_ma_teacher_claim(reply):
        if agent._is_ma_teacher_direct_query(text):
            return agent._ma_teacher_direct_query_fallback
        cleaned_reply = agent._strip_invalid_ma_teacher_service_clauses(reply)
        if cleaned_reply and cleaned_reply != reply:
            return cleaned_reply
        return agent._ma_teacher_role_fallback

    if agent._is_contact_fact_risk(text, reply):
        if agent._has_price_priority(text):
            return agent._render_guardrail_reply(agent._price_guardrail_safe_reply)
        if agent._needs_empathy_remote_support(text):
            return agent._render_guardrail_reply(agent._empathy_remote_support_fallback)
        if any(token in text for token in ("外地", "不在上海", "不在北京", "不方便到店", "远程定制", "不能去上海", "不能来上海")):
            return agent._render_guardrail_reply(agent._remote_support_fact_fallback)
        return agent._render_guardrail_reply(agent._contact_fact_fallback)

    if agent._has_price_priority(text):
        if agent._contains_low_price_quote(reply) or agent._contains_invalid_price_channel(reply):
            return agent._render_guardrail_reply(agent._price_guardrail_safe_reply)

    if allow_address_guardrails and agent._is_address_fact_risk(text, reply, state, history):
        if agent._is_address_unsupported_query(text):
            return agent._render_guardrail_reply(agent._address_fact_fallback)
        store_key = agent._resolve_guardrail_store_key(text, reply, state, history)
        if store_key:
            store = agent.knowledge_service.get_store_display(store_key)
            store_name = str(store.get("store_name", "") or "门店")
            return agent._normalize_reply_text(f"姐姐，{store_name}位置可以看图中圈圈的位置哦")
        if agent._reply_contains_unsupported_address_detail(reply):
            return agent._render_guardrail_reply(agent._address_fact_fallback)
        return agent._render_guardrail_reply(agent._address_fact_fallback)

    if allow_address_guardrails and agent._is_address_unsupported_query(text):
        return agent._normalize_reply_text(agent._address_unsupported_fallback)
    if agent._needs_empathy_remote_support(text) and not agent._reply_has_empathy(reply):
        return agent._normalize_reply_text(f"姐姐那您先注意休息，身体要紧，{reply.lstrip('姐姐，').lstrip('姐姐').strip()}")
    return reply_text
