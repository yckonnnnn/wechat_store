from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple

from .business_hours import STANDARD_BUSINESS_HOURS_REPLY

PRECISE_ADDRESS_TO_STORE: Dict[str, str] = {
    "愚园路172号环球世界大厦A座": "sh_jingan",
    "汉口路650号亚洲大厦": "sh_renmin",
    "花园路16号嘉和国际大厦东楼": "sh_hongkou",
    "政通路177号，万达广场E栋C座": "sh_wujiaochang",
    "漕溪北路45号中航德必大厦": "sh_xuhui",
    "建外SOHO东区": "beijing_chaoyang",
}

STORE_RECOMMENDATION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "beijing_chaoyang": ("北京朝阳店", "北京朝阳门店", "朝阳店", "朝阳门店", "朝阳区", "建外soho", "建外soho东区", "东三环中路"),
    "sh_jingan": ("上海静安店", "上海静安门店", "静安店", "静安门店", "静安寺", "静安", "愚园路", "环球世界大厦"),
    "sh_renmin": ("上海人民广场店", "上海人民广场门店", "人民广场店", "人民广场门店", "人民广场", "人广店", "人广", "黄浦区", "黄埔区", "汉口路", "亚洲大厦"),
    "sh_hongkou": ("上海虹口店", "上海虹口门店", "虹口店", "虹口门店", "虹口", "花园路", "嘉和国际大厦"),
    "sh_wujiaochang": ("上海五角场店", "上海五角场门店", "五角场店", "五角场门店", "五角场", "政通路", "万达广场e栋c座"),
    "sh_xuhui": ("上海徐汇店", "上海徐汇门店", "徐汇店", "徐汇门店", "徐汇", "徐家汇", "漕溪北路", "中航德必大厦"),
}
STORE_RECOMMENDATION_POSITIVE_CUES = (
    "最近",
    "更近",
    "推荐",
    "方便",
    "过去",
    "过来",
    "到店",
    "来店",
    "可以去",
    "去就行",
    "去会更方便",
    "离",
)
STORE_RECOMMENDATION_EXCLUDE_CUES = (
    "上海有5家店",
    "上海共有5家店",
    "北京有1家",
    "北京只有1家",
    "哪个区域",
    "哪 个区域",
    "离哪个区域",
    "您离哪个区域",
    "靠近哪个区域",
    "您在哪个城市",
    "方便告诉我",
    "门店分布",
    "先确认一下",
    "确认一下",
    "您是在",
    "你是在",
    "您在徐汇吗",
    "您在静安吗",
    "您在人广吗",
    "您在人民广场吗",
)
ADDRESS_IMAGE_PROMISE_CUES = (
    "位置图",
    "位置图片",
    "发位置图",
    "发一张位置图",
    "给您发位置图",
    "给您发一张位置图",
    "看图",
    "按图",
    "跟着图",
    "看图片",
    "位置可以看图",
)

SERVICE_HOURS_QUERY_KEYWORDS = (
    "服务时间",
    "营业时间",
    "上班时间",
    "上班几点",
    "几点营业",
    "几点上班",
    "营业到几点",
    "几点下班",
    "开门时间",
    "关门时间",
)
SERVICE_HOURS_SAFE_REPLY = STANDARD_BUSINESS_HOURS_REPLY

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
    value = value.replace("～", "").replace("~", "")
    value = re.sub(r"吧到(?=[。！？!?，,；;]|$)", "吧", value)
    value = re.sub(r"呢到(?=[。！？!?，,；;]|$)", "呢", value)

    if any(k in value for k in agent._contact_compliance_block_keywords):
        value = "姐姐，您留个☎️方式，我来加您好友"
    elif any(k in value for k in agent._shipping_block_keywords):
        value = agent._shipping_block_replacement
        force_default_emoji = True

    if not value:
        value = "姐姐我在呢"
    can_shorten = (
        len(value) > 32
        and "门店" in value
        and "北京" in value
        and "上海" in value
        and any(token in value for token in ("静安", "人广", "虹口", "五角场", "徐汇"))
        and not re.search(r"\d{3,}", value)
        and "哪个城市" not in value
        and "什么城市" not in value
    )
    compact_candidates = [part.strip() for part in re.split(r"[；;，,]", value) if part.strip()]
    if can_shorten and compact_candidates:
        value = compact_candidates[0]
    if can_shorten and len(value) > 32:
        value = value[:32].rstrip("，,；;。！？!? ")
    value = value.rstrip("，,；; ")
    if not re.search(r"[。！？!?]$", value):
        value = f"{value}。"
    emoji = "🌹" if force_default_emoji else "🌹"
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


def normalize_service_hours_check_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def is_service_hours_query(latest_user_text: str) -> bool:
    normalized = normalize_service_hours_check_text(latest_user_text)
    if not normalized:
        return False
    return any(keyword in normalized for keyword in SERVICE_HOURS_QUERY_KEYWORDS)


def reply_has_correct_service_hours(reply_text: str) -> bool:
    normalized = normalize_service_hours_check_text(reply_text)
    if not normalized:
        return False

    has_open_time = any(token in normalized for token in ("9:30", "9：30", "930", "上午9点30", "早上9点30"))
    has_close_time = any(
        token in normalized
        for token in ("18:00", "18：00", "1800", "下午6:00", "下午6：00", "下午6点", "晚上18:00", "晚18:00")
    )
    has_legacy_hours_phrase = any(
        token in normalized
        for token in ("全年无休", "周一到周五", "周六周日不上班", "周末不上班", "工作日周一到周五")
    )
    return has_open_time and has_close_time and not has_legacy_hours_phrase


def reply_has_non_whitelist_detailed_address(reply_text: str) -> bool:
    normalized = normalize_service_hours_check_text(reply_text)
    if not normalized:
        return False
    if detect_precise_address_in_reply(reply_text):
        return False

    detailed_patterns = (
        r"[\u4e00-\u9fa5a-z0-9]{2,20}(?:路|街|道|巷|弄)\d{1,4}号",
        r"\d{1,4}号楼",
        r"\d{1,3}层",
        r"\d{1,5}室",
        r"(?:东区|西区|南区|北区)\d{1,3}号楼",
        r"(?:中路|东路|西路|南路|北路)\d{1,4}号",
    )
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in detailed_patterns)


def _detect_unique_store_in_reply(reply_text: str) -> str:
    normalized = normalize_service_hours_check_text(reply_text)
    if not normalized:
        return ""
    if any(normalize_service_hours_check_text(cue) in normalized for cue in STORE_RECOMMENDATION_EXCLUDE_CUES):
        return ""

    matched_stores: List[str] = []
    for target_store, aliases in STORE_RECOMMENDATION_ALIASES.items():
        if any(normalize_service_hours_check_text(alias) in normalized for alias in aliases):
            matched_stores.append(target_store)
    matched_stores = list(dict.fromkeys(matched_stores))
    if len(matched_stores) != 1:
        return ""
    return matched_stores[0]


def detect_store_recommendation_in_reply(reply_text: str) -> Dict[str, Any]:
    normalized = normalize_service_hours_check_text(reply_text)
    if not normalized:
        return {}

    target_store = _detect_unique_store_in_reply(reply_text)
    if not target_store:
        return {}

    if not any(normalize_service_hours_check_text(cue) in normalized for cue in STORE_RECOMMENDATION_POSITIVE_CUES):
        return {}

    return {
        "target_store": target_store,
        "closure_type": "store_recommendation",
    }


def detect_address_image_promise_in_reply(reply_text: str) -> Dict[str, Any]:
    normalized = normalize_service_hours_check_text(reply_text)
    if not normalized:
        return {}

    target_store = _detect_unique_store_in_reply(reply_text)
    if not target_store:
        return {}

    if not any(normalize_service_hours_check_text(cue) in normalized for cue in ADDRESS_IMAGE_PROMISE_CUES):
        return {}

    return {
        "target_store": target_store,
        "closure_type": "address_image_promise",
    }


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

    recommendation_hit = detect_store_recommendation_in_reply(reply_text)
    if recommendation_hit and not info.get("precise_address_hit"):
        info["target_store"] = str(recommendation_hit.get("target_store", "") or info.get("target_store", ""))
        if not info.get("closure_type"):
            info["closure_type"] = str(recommendation_hit.get("closure_type", "") or "store_recommendation")

    address_image_promise_hit = detect_address_image_promise_in_reply(reply_text)
    if (
        address_image_promise_hit
        and not info.get("precise_address_hit")
        and str(info.get("closure_type", "") or "") not in {"store_recommendation", "precise_address"}
    ):
        info["target_store"] = str(address_image_promise_hit.get("target_store", "") or info.get("target_store", ""))
        if not info.get("closure_type"):
            info["closure_type"] = str(address_image_promise_hit.get("closure_type", "") or "address_image_promise")

    fixed_contact_norms = set(getattr(agent, "_fixed_contact_closure_norms", set()) or set())
    if fixed_contact_norms and agent._normalize_for_dedupe(reply_text) in fixed_contact_norms:
        info["contact_closure_hit"] = True
        if not info.get("closure_type"):
            info["closure_type"] = "contact"
    normalized_reply = normalize_service_hours_check_text(reply_text)
    if (
        not info.get("contact_closure_hit")
        and str(info.get("closure_type", "") or "") not in {"store_recommendation", "address_image_promise", "precise_address"}
        and normalized_reply
        and any(token in normalized_reply for token in ("留个", "留个☎️", "留个方式", "加您", "加你", "加好友", "联系您", "主动跟您介绍", "具体沟通"))
    ):
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

    if is_service_hours_query(text) and not reply_has_correct_service_hours(reply):
        return finalize(agent._render_guardrail_reply(SERVICE_HOURS_SAFE_REPLY))

    if (
        allow_address_guardrails
        and
        int(state.get("address_image_sent_count", 0) or 0) > 0
        and str((state.get("conversation_facts", {}) or {}).get("recommended_store", "") or state.get("last_target_store", "") or "")
        and (
            agent.knowledge_service.is_address_query(text)
            or any(token in normalize_service_hours_check_text(text) for token in ("位置图", "再发", "看图", "位置"))
        )
    ):
        normalized_reply = normalize_service_hours_check_text(reply)
        if any(token in normalized_reply for token in ("留个", "加您", "加你", "加好友", "联系方式", "具体沟通", "主动跟您介绍")):
            store_key = str((state.get("conversation_facts", {}) or {}).get("recommended_store", "") or state.get("last_target_store", "") or "")
            if store_key and store_key != "unknown":
                store = agent.knowledge_service.get_store_display(store_key)
                store_name = str(store.get("store_name", "") or "门店")
                return finalize(
                    agent._normalize_reply_text(f"姐姐，{store_name}位置直接看图片就可以哦"),
                    {
                        "closure_type": "address_image_promise",
                        "target_store": store_key,
                        "contact_closure_hit": False,
                    },
                )

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

    if allow_address_guardrails and reply_has_non_whitelist_detailed_address(reply):
        store_key = agent._resolve_guardrail_store_key(text, reply, state, history)
        if store_key:
            store = agent.knowledge_service.get_store_display(store_key)
            store_name = str(store.get("store_name", "") or "门店")
            return finalize(
                agent._normalize_reply_text(f"姐姐，{store_name}位置直接看图片就可以哦"),
                {
                    "closure_type": "store_recommendation",
                    "target_store": store_key,
                },
            )
        return finalize(agent._render_guardrail_reply(agent._address_fact_fallback))

    if allow_address_guardrails and agent._is_address_fact_risk(text, reply, state, history):
        if agent._is_address_unsupported_query(text):
            return finalize(agent._render_guardrail_reply(agent._address_fact_fallback))
        store_key = agent._resolve_guardrail_store_key(text, reply, state, history)
        if store_key:
            store = agent.knowledge_service.get_store_display(store_key)
            store_name = str(store.get("store_name", "") or "门店")
            return finalize(agent._normalize_reply_text(f"姐姐，{store_name}位置直接看图片就可以哦"))
        if agent._reply_contains_unsupported_address_detail(reply):
            return finalize(agent._render_guardrail_reply(agent._address_fact_fallback))
        return finalize(agent._render_guardrail_reply(agent._address_fact_fallback))

    if allow_address_guardrails and agent._is_address_unsupported_query(text):
        return finalize(agent._normalize_reply_text(agent._address_unsupported_fallback))
    if agent._needs_empathy_remote_support(text) and not agent._reply_has_empathy(reply):
        return finalize(agent._normalize_reply_text(f"姐姐那您先注意休息，身体要紧，{reply.lstrip('姐姐，').lstrip('姐姐').strip()}"))
    return finalize(reply_text)
