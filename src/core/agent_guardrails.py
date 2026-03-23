from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple


PRECISE_ADDRESS_TO_STORE: Dict[str, str] = {
    "愚园路172号环球世界大厦A座": "sh_jingan",
    "汉口路650号亚洲大厦": "sh_renmin",
    "花园路16号嘉和国际大厦东楼": "sh_hongkou",
    "政通路177号，万达广场E栋C座": "sh_wujiaochang",
    "漕溪北路45号中航德必大厦": "sh_xuhui",
    "建外SOHO东区": "beijing_chaoyang",
}

DEFAULT_PRECISE_ADDRESS_CLOSURE_POOL: List[str] = [
    "姐姐您看下我发的位置图，按图找会更直观些，方便的话我也可以继续帮您安排预约呀🌹",
    "姐姐具体位置我给您放在图片里啦，您照着图看更清楚，方便的话我继续帮您安排😊",
    "姐姐您直接看位置图会更好找一些，按图过去更直观，您要预约的话我也能接着帮您安排🌷",
    "姐姐位置我已经放到图里啦，您看图找会方便很多，需要的话我继续帮您安排呀❤️",
    "姐姐您看下位置图哦，照着图过去会更省事，方便的话我也可以帮您继续预约💗",
    "姐姐门店位置您看图片会更清楚些，按图找就好，需要我继续帮您安排的话您告诉我呀🌸",
    "姐姐我给您发位置图啦，您跟着图看会更明白，方便的话我继续帮您安排💐",
    "姐姐您看图片里的位置提示就行，找起来更直观些，要是想约我也可以继续帮您跟进🥰",
    "姐姐位置图您点开看一下哦，比文字更好找，方便的话我这边继续帮您安排😄",
    "姐姐您按我发的位置图看就好，会更容易找到，您要预约的话我也可以继续帮您处理🌺",
]

_PRECISE_ADDRESS_LOOKUP = {
    "".join(str(address).strip().lower().replace("，", ",").split()): {
        "address": address,
        "target_store": target_store,
    }
    for address, target_store in PRECISE_ADDRESS_TO_STORE.items()
}


def normalize_reply_text(agent: Any, text: str) -> str:
    value = (text or "").strip()
    if not value:
        return agent._render_template("general_empty")

    force_default_emoji = False
    value = re.sub(r"(?:\s+|^)(\d{1,2}:\d{2})(?:已读|未读|送达)?$", "", value).strip()
    value = " ".join(value.split())
    value = agent._strip_inline_emoji_symbols(value)
    value = re.sub(r"吧到(?=[。！？!?，,；;]|$)", "吧", value)
    value = re.sub(r"呢到(?=[。！？!?，,；;]|$)", "呢", value)

    if any(k in value for k in agent._contact_compliance_block_keywords):
        value = "姐姐，您留个☎️方式，我来加您好友"
    elif any(k in value for k in agent._shipping_block_keywords):
        value = agent._shipping_block_replacement
        force_default_emoji = True

    if not value:
        value = "姐姐我在呢"
    value = value.rstrip("，,；; ")
    if not re.search(r"[。！？!?]$", value):
        value = f"{value}。"
    emoji = "🌹" if force_default_emoji else random.choice(agent._reply_emoji_pool)
    return f"{value}{emoji}"


def empty_reply_closure_info(reply_text: str = "") -> Dict[str, Any]:
    return {
        "closure_type": "",
        "precise_address_hit": False,
        "contact_closure_hit": False,
        "target_store": "",
        "matched_address": "",
        "reply_text": str(reply_text or ""),
    }


def normalize_precise_address_match_text(text: str) -> str:
    return "".join(str(text or "").strip().lower().replace("，", ",").split())


def detect_precise_address_in_reply(reply_text: str) -> Dict[str, Any]:
    normalized_reply = normalize_precise_address_match_text(reply_text)
    if not normalized_reply:
        return {}
    for normalized_address, payload in _PRECISE_ADDRESS_LOOKUP.items():
        if normalized_address in normalized_reply:
            return dict(payload)
    return {}


def build_reply_closure_info(
    agent: Any,
    reply_text: str,
    base_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    info = empty_reply_closure_info(reply_text=reply_text)
    if isinstance(base_info, dict):
        info.update({k: v for k, v in base_info.items() if v not in (None, "")})

    precise_hit = detect_precise_address_in_reply(reply_text)
    if precise_hit:
        info["precise_address_hit"] = True
        info["target_store"] = str(precise_hit.get("target_store", "") or info.get("target_store", ""))
        info["matched_address"] = str(precise_hit.get("address", "") or info.get("matched_address", ""))
        if not info.get("closure_type"):
            info["closure_type"] = "precise_address"

    fixed_contact_norms = set(getattr(agent, "_fixed_contact_closure_norms", set()) or set())
    if fixed_contact_norms and agent._normalize_for_dedupe(reply_text) in fixed_contact_norms:
        info["contact_closure_hit"] = True
        if not info.get("closure_type"):
            info["closure_type"] = "contact"

    info["reply_text"] = str(reply_text or "")
    return info


def select_precise_address_closure_text(
    agent: Any,
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    raw_pool = getattr(agent, "_precise_address_closure_pool", []) or []
    candidates = [str(item).strip() for item in raw_pool if str(item).strip()]
    if not candidates:
        candidates = list(DEFAULT_PRECISE_ADDRESS_CLOSURE_POOL)

    previous: set[str] = set()
    user_hash = str((session_state or {}).get("user_hash", "") or "")
    if user_hash:
        try:
            user_state = agent.memory_store.get_user_state(user_hash)
            previous |= set(user_state.get("recent_reply_hashes", []) or [])
        except Exception:
            pass
        summarize_recent = getattr(agent, "summarize_recent_assistant_hashes_from_logs", None)
        if callable(summarize_recent):
            try:
                previous |= set(summarize_recent(user_id_hash=user_hash, limit=80) or set())
            except Exception:
                pass

    for candidate in candidates:
        if agent._normalize_for_dedupe(candidate) not in previous:
            return agent._randomize_template_emoji(candidate)
    return agent._randomize_template_emoji(random.choice(candidates))


def apply_llm_reply_guardrails(
    agent: Any,
    latest_user_text: str,
    reply_text: str,
    session_state: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    allow_address_guardrails: bool = True,
    allow_precise_address_closure: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    text = (latest_user_text or "").strip()
    reply = (reply_text or "").strip()
    state = session_state or {}
    history = conversation_history or []
    closure_info = empty_reply_closure_info(reply_text=reply)

    def finalize(final_reply: str, base_info: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        return final_reply, build_reply_closure_info(agent, final_reply, base_info or closure_info)

    if agent._contains_explicit_phone_number(reply):
        if agent._has_price_priority(text):
            return finalize(agent._render_guardrail_reply(agent._price_guardrail_safe_reply))
        if agent._needs_empathy_remote_support(text):
            return finalize(agent._render_guardrail_reply(agent._empathy_remote_support_fallback))
        if any(token in text for token in ("外地", "不在上海", "不在北京", "不方便到店", "远程定制", "不能去上海", "不能来上海")):
            return finalize(agent._render_guardrail_reply(agent._remote_support_fact_fallback))
        return finalize(agent._phone_leak_block_fallback, {"contact_closure_hit": True, "closure_type": "contact"})

    if agent._contains_invalid_ma_teacher_claim(reply):
        if agent._is_ma_teacher_direct_query(text):
            return finalize(agent._ma_teacher_direct_query_fallback)
        cleaned_reply = agent._strip_invalid_ma_teacher_service_clauses(reply)
        if cleaned_reply and cleaned_reply != reply:
            return finalize(cleaned_reply)
        return finalize(agent._ma_teacher_role_fallback)

    if agent._is_contact_fact_risk(text, reply):
        if agent._has_price_priority(text):
            return finalize(agent._render_guardrail_reply(agent._price_guardrail_safe_reply))
        if agent._needs_empathy_remote_support(text):
            return finalize(agent._render_guardrail_reply(agent._empathy_remote_support_fallback))
        if any(token in text for token in ("外地", "不在上海", "不在北京", "不方便到店", "远程定制", "不能去上海", "不能来上海")):
            return finalize(agent._render_guardrail_reply(agent._remote_support_fact_fallback))
        return finalize(
            agent._render_guardrail_reply(agent._contact_fact_fallback),
            {"contact_closure_hit": True, "closure_type": "contact"},
        )

    if agent._has_price_priority(text):
        if agent._contains_low_price_quote(reply) or agent._contains_invalid_price_channel(reply):
            return finalize(agent._render_guardrail_reply(agent._price_guardrail_safe_reply))

    if allow_precise_address_closure:
        precise_hit = detect_precise_address_in_reply(reply)
        if precise_hit:
            closure_text = select_precise_address_closure_text(agent, session_state=state)
            return finalize(
                agent._normalize_reply_text(closure_text),
                {
                    "closure_type": "precise_address",
                    "precise_address_hit": True,
                    "target_store": str(precise_hit.get("target_store", "") or ""),
                    "matched_address": str(precise_hit.get("address", "") or ""),
                },
            )

    if allow_address_guardrails and agent._is_address_fact_risk(text, reply, state, history):
        if agent._is_address_unsupported_query(text):
            return finalize(agent._render_guardrail_reply(agent._address_fact_fallback))
        store_key = agent._resolve_guardrail_store_key(text, reply, state, history)
        if store_key:
            store = agent.knowledge_service.get_store_display(store_key)
            store_name = str(store.get("store_name", "") or "门店")
            return finalize(agent._normalize_reply_text(f"姐姐，{store_name}位置可以看图中圈圈的位置哦"))
        if agent._reply_contains_unsupported_address_detail(reply):
            return finalize(agent._render_guardrail_reply(agent._address_fact_fallback))
        return finalize(agent._render_guardrail_reply(agent._address_fact_fallback))

    if allow_address_guardrails and agent._is_address_unsupported_query(text):
        return finalize(agent._normalize_reply_text(agent._address_unsupported_fallback))
    if agent._needs_empathy_remote_support(text) and not agent._reply_has_empathy(reply):
        return finalize(agent._normalize_reply_text(f"姐姐那您先注意休息，身体要紧，{reply.lstrip('姐姐，').lstrip('姐姐').strip()}"))
    return finalize(reply_text)
