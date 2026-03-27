from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Optional

from .agent_types import AgentDecision
from . import agent_media
from . import agent_contact_flow


def _const(agent, name: str, default: Any = None) -> Any:
    module = sys.modules.get(agent.__class__.__module__)
    if module is None:
        return default
    return getattr(module, name, default)


def detect_intent(agent, text: str) -> str:
    aftercare_keywords = ("清洗", "售后", "保养", "打理", "维护", "怎么洗", "如何洗", "自己洗", "不会洗", "洗发", "护理")
    if any(k in (text or "") for k in aftercare_keywords):
        return "general"

    remote_location_keywords = ("不在上海", "不是上海", "不去上海", "不在北京", "不是北京", "不去北京",
                               "在异地", "在外地", "不在本地", "外地的", "异地的", "没办法到店", "无法到店", "不能到店")
    ambiguous_keywords = ("怎么办", "如何", "怎么做", "怎么弄")
    if any(k in (text or "") for k in remote_location_keywords) and any(k in (text or "") for k in ambiguous_keywords):
        if any(k in (text or "") for k in aftercare_keywords):
            return "general"
        return "general"

    if agent._looks_like_direct_contact_request(text):
        return "contact"

    if agent.knowledge_service.is_shanghai_route_alias_address_candidate(text):
        return "address"
    if agent.knowledge_service.is_address_query(text):
        return "address"
    if agent.knowledge_service.is_purchase_intent(text):
        return "purchase"
    if any(k in (text or "") for k in _const(agent, "CONTACT_INTENT_KEYWORDS", ())):
        return "contact"
    return "general"


def is_ambiguous_short_fragment(agent, text: str, intent: str, route: Dict[str, Any]) -> bool:
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized or len(normalized) > 2:
        return False
    if intent != "general":
        return False
    if str(route.get("reason", "unknown") or "unknown") != "unknown":
        return False
    ambiguous_tokens = {"址", "店", "路", "位", "地址", "位置"}
    return normalized in ambiguous_tokens


def looks_like_phone_submission(agent, text: str) -> bool:
    del agent
    normalized = re.sub(r"[^\d]", "", str(text or ""))
    if not normalized:
        return False
    return bool(re.fullmatch(r"1[3-9]\d{9}", normalized))


def should_apply_rule_decision(
    agent,
    text: str,
    intent: str,
    route: Dict[str, Any],
    session_state: Dict[str, Any],
) -> bool:
    if (
        agent_contact_flow.looks_like_store_recommendation_challenge(text)
        or agent_contact_flow.looks_like_store_preference_statement(text)
    ):
        return False
    aftercare_keywords = ("清洗", "售后", "保养", "打理", "维护", "怎么洗", "如何洗", "自己洗", "不会洗", "洗发", "护理")
    if any(k in (text or "") for k in aftercare_keywords):
        return False

    route_type = route.get("route_type", "unknown")
    target_store = route.get("target_store", "unknown")

    if intent == "address":
        session_target_store = str(session_state.get("last_target_store", "") or "")
        sent_stores = set(session_state.get("sent_address_stores", []) or [])
        text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
        contact_reply_count_by_store = dict(session_state.get("address_contact_reply_count_by_store", {}) or {})
        exhausted_store = target_store if target_store and target_store != "unknown" else session_target_store
        if (
            exhausted_store
            and exhausted_store != "unknown"
            and exhausted_store in sent_stores
            and int(text_reply_count_by_store.get(exhausted_store, 0) or 0) >= 1
            and int(contact_reply_count_by_store.get(exhausted_store, 0) or 0) >= 1
        ):
            return False

    if route_type in ("coverage", "non_coverage", "need_district", "need_clarify"):
        return True
    if intent in ("address", "purchase"):
        return True
    if intent == "appointment" and (
        str(route.get("target_store", "") or "").strip() not in {"", "unknown"}
        or str(session_state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
        or int(session_state.get("address_image_sent_count", 0) or 0) > 0
        or int(session_state.get("contact_image_sent_count", 0) or 0) > 0
    ):
        return True
    if bool(session_state.get("last_geo_pending", False)) and looks_like_geo_reply(agent, text=text, route=route):
        return True
    return False


def looks_like_geo_reply(agent, text: str, route: Dict[str, Any]) -> bool:
    del agent
    reason = route.get("reason", "unknown")
    if reason != "unknown":
        return True

    normalized = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", (text or ""))
    if not normalized:
        return False

    geo_tokens = (
        "北京", "上海", "徐汇", "徐家汇", "静安", "虹口", "杨浦", "五角场", "人广", "人民广场",
        "河北", "石家庄", "天津", "内蒙古", "江苏", "浙江", "苏州", "杭州", "东北", "省", "市", "区", "县", "州", "盟", "旗"
    )
    return any(token in normalized for token in geo_tokens)


def is_remote_geo_followup_reply(agent, text: str) -> bool:
    del agent
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return False
    return "外地" in normalized


def should_force_out_of_coverage_from_geo_followup(agent, text: str, session_state: Dict[str, Any]) -> bool:
    if not bool(session_state.get("last_geo_pending", False)):
        return False
    if not is_remote_geo_followup_reply(agent, text):
        return False
    normalized = re.sub(r"\s+", "", str(text or ""))
    last_geo_route_reason = str(session_state.get("last_geo_route_reason", "") or "")
    if last_geo_route_reason in ("need_district", "shanghai_need_district"):
        if any(keyword in normalized for keyword in _const(agent, "SHANGHAI_ROUTE_HELP_KEYWORDS", ())):
            return False
    return True


def build_address_text_after_image_decision(
    agent,
    latest_user_text: str,
    route: Dict[str, Any],
    intent: str,
    session_state: Dict[str, Any],
) -> Optional[AgentDecision]:
    normalized_text = agent.knowledge_service.normalize_user_text(latest_user_text)
    normalized = re.sub(r"\s+", "", str(normalized_text or "")).lower()
    same_store_followup = (
        any(token in normalized for token in ("这家", "这个店", "那家", "那个店", "还是这家", "还是那家", "就这家"))
        and any(token in normalized for token in ("地址", "位置", "地址给我", "把地址发我", "发我地址"))
    )
    explicit_revisit = any(token in normalized for token in ("位置图", "再发", "看图")) or same_store_followup
    explicit_missing_media = bool(getattr(agent, "_looks_like_missing_media_request", lambda _text: False)(latest_user_text))
    route_reason = str(route.get("reason", "unknown") or "unknown")
    if (
        not explicit_revisit
        and not same_store_followup
        and not explicit_missing_media
        and not agent._is_precise_address_followup(latest_user_text)
        and callable(getattr(agent, "_looks_like_generic_address_opening", None))
        and agent._looks_like_generic_address_opening(normalized_text, intent="address")
    ):
        return None
    if (
        intent != "address"
        and not explicit_revisit
        and not explicit_missing_media
        and not agent._is_precise_address_followup(latest_user_text)
        and not agent.knowledge_service.is_address_query(latest_user_text)
        and not agent.knowledge_service.is_shanghai_route_alias_address_candidate(latest_user_text)
    ):
        return None
    if not should_continue_address_followup(agent, latest_user_text=latest_user_text, session_state=session_state):
        return None
    if (
        not explicit_revisit
        and route_reason in {
            "unknown",
            "need_region",
            "need_district",
            "need_clarify",
            "sh_route_need_clarify",
            "shanghai_need_arrival_point",
            "shanghai_need_district",
        }
    ):
        return None

    target_store = str(route.get("target_store", "") or "")
    if not target_store or target_store == "unknown":
        target_store = str(session_state.get("last_target_store", "") or "")
    if not target_store or target_store == "unknown":
        return None
    if "上海" in normalized and not target_store.startswith("sh_"):
        return None
    if "北京" in normalized and target_store != "beijing_chaoyang":
        return None
    explicit_store = str(agent._infer_store_from_context_text(latest_user_text) or "").strip()
    if explicit_store and explicit_store != target_store:
        return None

    sent_stores = set(session_state.get("sent_address_stores", []) or [])
    last_target_store = str(session_state.get("last_target_store", "") or "")
    has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
    if target_store not in sent_stores and not (
        not sent_stores and has_sent_address and last_target_store == target_store
    ):
        return None

    text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
    if int(text_reply_count_by_store.get(target_store, 0) or 0) >= 1:
        return None

    sent_count_by_store = dict(session_state.get("address_image_sent_count_by_store", {}) or {})
    delivery_stage_by_store = dict(session_state.get("address_delivery_stage_by_store", {}) or {})
    if explicit_revisit and (
        int(sent_count_by_store.get(target_store, 0) or 0) >= 2
        or str(delivery_stage_by_store.get(target_store, "") or "") == "delivered_closed"
    ):
        pool = [str(item).strip() for item in (_const(agent, "ADDRESS_IMAGE_LIMIT_REPLY_POOL", ()) or ()) if str(item).strip()]
        if not pool:
            pool = [
                "姐姐，前面的位置图我已经发过了，平台这边没法一直重复补发；如果您没看到或者找不到，您留个电话，我来联系您语音跟您说会更方便一些❤️"
            ]
        counters = dict(session_state.get("address_limit_reply_counters", {}) or {})
        index = int(counters.get(target_store, 0) or 0) % len(pool)
        counters[target_store] = int(counters.get(target_store, 0) or 0) + 1
        session_state["address_limit_reply_counters"] = counters
        return AgentDecision(
            reply_text=pool[index],
            intent="address",
            route_reason="address_image_limit_reached",
            reply_goal="承接联系方式",
            media_plan="none",
            reply_source="rule",
            rule_id="ADDR_IMAGE_LIMIT_REPLY",
            rule_applied=True,
        )

    resend_image = explicit_revisit or (
        len(normalized) <= 4
        and any(token in normalized for token in ("在哪", "哪儿", "位置"))
    )
    if explicit_missing_media:
        reply_text = (
            agent._pick_fixed_reply(
                session_state=session_state,
                category="media_delivery_retry",
                replies=_const(agent, "MEDIA_DELIVERY_RETRY_FALLBACK_POOL", ()) or (),
                fallback=_const(agent, "MEDIA_DELIVERY_RETRY_FALLBACK", ""),
            )
            if callable(getattr(agent, "_pick_fixed_reply", None))
            else _const(agent, "MEDIA_DELIVERY_RETRY_FALLBACK", "")
        )
        resend_image = False
    else:
        reply_text = (
            "姐姐，我再给您发一下位置图，您看图里标注的位置会更直观哦。🌹"
            if resend_image
            else (
                agent._pick_fixed_reply(
                    session_state=session_state,
                    category="address_generic_followup",
                    replies=_const(agent, "ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK_POOL", ()) or (),
                    fallback=_const(agent, "ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK", ""),
                )
                if callable(getattr(agent, "_pick_fixed_reply", None))
                else _const(agent, "ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK", "")
            )
        )

    return AgentDecision(
        reply_text=reply_text,
        intent="address",
        route_reason=str(route.get("reason", "unknown") or "unknown"),
        reply_goal="解答",
        media_plan="address_image" if resend_image else "none",
        reply_source="rule",
        rule_id="ADDR_TEXT_AFTER_IMAGE",
        rule_applied=True,
    )


def build_address_contact_after_text_decision(
    agent,
    latest_user_text: str,
    route: Dict[str, Any],
    intent: str,
    session_state: Dict[str, Any],
) -> Optional[AgentDecision]:
    normalized_text = agent.knowledge_service.normalize_user_text(latest_user_text)
    normalized = re.sub(r"\s+", "", str(normalized_text or "")).lower()
    explicit_revisit = any(token in normalized for token in ("位置图", "再发", "看图"))
    route_reason = str(route.get("reason", "unknown") or "unknown")
    if (
        not explicit_revisit
        and not agent._is_precise_address_followup(latest_user_text)
        and callable(getattr(agent, "_looks_like_generic_address_opening", None))
        and agent._looks_like_generic_address_opening(normalized_text, intent="address")
    ):
        return None
    if (
        intent != "address"
        and not explicit_revisit
        and not agent._is_precise_address_followup(latest_user_text)
        and not agent.knowledge_service.is_address_query(latest_user_text)
        and not agent.knowledge_service.is_shanghai_route_alias_address_candidate(latest_user_text)
    ):
        return None
    if not should_continue_address_followup(agent, latest_user_text=latest_user_text, session_state=session_state):
        return None
    if route_reason in {
        "unknown",
        "need_region",
        "need_district",
        "need_clarify",
        "sh_route_need_clarify",
        "shanghai_need_arrival_point",
        "shanghai_need_district",
    }:
        return None

    target_store = str(route.get("target_store", "") or "")
    if not target_store or target_store == "unknown":
        target_store = str(session_state.get("last_target_store", "") or "")
    if not target_store or target_store == "unknown":
        return None
    if "上海" in normalized and not target_store.startswith("sh_"):
        return None
    if "北京" in normalized and target_store != "beijing_chaoyang":
        return None
    explicit_store = str(agent._infer_store_from_context_text(latest_user_text) or "").strip()
    if explicit_store and explicit_store != target_store:
        return None

    sent_stores = set(session_state.get("sent_address_stores", []) or [])
    last_target_store = str(session_state.get("last_target_store", "") or "")
    has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
    if target_store not in sent_stores and not (
        not sent_stores and has_sent_address and last_target_store == target_store
    ):
        return None

    text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
    if int(text_reply_count_by_store.get(target_store, 0) or 0) < 1:
        return None

    contact_reply_count_by_store = dict(session_state.get("address_contact_reply_count_by_store", {}) or {})
    if int(contact_reply_count_by_store.get(target_store, 0) or 0) >= 1:
        return None

    return AgentDecision(
        reply_text=(
            agent._pick_fixed_reply(
                session_state=session_state,
                category="address_generic_followup",
                replies=_const(agent, "ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK_POOL", ()) or (),
                fallback=_const(agent, "ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK", ""),
            )
            if callable(getattr(agent, "_pick_fixed_reply", None))
            else _const(agent, "ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK", "")
        ),
        intent="address",
        route_reason=str(route.get("reason", "unknown") or "unknown"),
        reply_goal="解答",
        media_plan="none",
        reply_source="rule",
        rule_id="ADDR_CONTACT_AFTER_TEXT",
        rule_applied=True,
    )


def build_contact_followup_decision(
    agent,
    latest_user_text: str,
    intent: str,
    session_state: Dict[str, Any],
) -> Optional[AgentDecision]:
    if bool(session_state.get("contact_captured", False)):
        return None
    explicit_missing_media = bool(getattr(agent, "_looks_like_missing_media_request", lambda _text: False)(latest_user_text))
    if intent != "contact" and not explicit_missing_media:
        return None
    if int(session_state.get("contact_image_sent_count", 0) or 0) < 1:
        return None
    if looks_like_phone_submission(agent, latest_user_text):
        return None
    if explicit_missing_media:
        return AgentDecision(
            reply_text=(
                agent._pick_fixed_reply(
                    session_state=session_state,
                    category="media_delivery_retry",
                    replies=_const(agent, "MEDIA_DELIVERY_RETRY_FALLBACK_POOL", ()) or (),
                    fallback=_const(agent, "MEDIA_DELIVERY_RETRY_FALLBACK", ""),
                )
                if callable(getattr(agent, "_pick_fixed_reply", None))
                else _const(agent, "MEDIA_DELIVERY_RETRY_FALLBACK", "")
            ),
            intent="contact",
            route_reason="contact_followup_missing_media",
            reply_goal="推进购买意图",
            media_plan="none",
            reply_source="rule",
            rule_id="CONTACT_FOLLOWUP_MISSING_MEDIA",
            rule_applied=True,
        )
    prompt_count = int(session_state.get("contact_followup_prompt_count", 0) or 0)
    session_state["contact_followup_prompt_count"] = prompt_count + 1
    template_key = "contact_followup_1" if (prompt_count % 2) == 0 else "contact_followup_2"
    return AgentDecision(
        reply_text=agent._render_template(template_key),
        intent="contact",
        route_reason="contact_followup",
        reply_goal="推进购买意图",
        media_plan="none",
        reply_source="rule",
        rule_id="CONTACT_FOLLOWUP",
        rule_applied=True,
    )


def build_travel_schedule_store_followup_decision(
    agent,
    latest_user_text: str,
    route: Dict[str, Any],
    session_state: Dict[str, Any],
) -> Optional[AgentDecision]:
    if not agent._looks_like_travel_schedule_statement(latest_user_text):
        return None

    route_city = str(route.get("city", "") or "").strip()
    target_store = str(route.get("target_store", "") or "").strip()
    explicit_store = str(agent._infer_store_from_context_text(latest_user_text) or "").strip()
    if explicit_store:
        target_store = explicit_store

    # 当前轮已经明确提到城市，但还没锁定具体门店时，不允许回退到旧会话门店，
    # 否则“去上海哪个门店比较好”会被历史门店（例如北京）带偏。
    if (
        (not target_store or target_store == "unknown")
        and route_city in {"shanghai", "beijing"}
    ):
        return None

    if not target_store or target_store == "unknown":
        target_store = str(session_state.get("last_target_store", "") or "").strip()
    if not target_store or target_store == "unknown":
        return None

    normalized_text = re.sub(r"\s+", "", str(latest_user_text or ""))
    if "上海" in normalized_text and not target_store.startswith("sh_"):
        return None
    if "北京" in normalized_text and target_store != "beijing_chaoyang":
        return None

    store = agent.knowledge_service.get_store_display(target_store)
    store_name = agent._store_recommend_display_name(target_store, str(store.get("store_name", "") or "门店"))
    city_name = "北京" if target_store == "beijing_chaoyang" else "上海"
    reply_text = agent._normalize_reply_text(
        f"姐姐，{city_name}这边是{store_name}，您过来前跟我说一声，我提前帮您安排就行"
    )
    return AgentDecision(
        reply_text=reply_text,
        intent="address",
        route_reason="travel_schedule_store_followup",
        reply_goal="解答",
        media_plan="none",
        reply_source="rule",
        rule_id="ADDR_TRAVEL_SCHEDULE_FOLLOWUP",
        rule_applied=True,
    )


def should_continue_address_followup(agent, latest_user_text: str, session_state: Dict[str, Any]) -> bool:
    normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
    if not normalized:
        return False

    if agent.knowledge_service.is_shanghai_route_alias_address_candidate(normalized):
        has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
        has_target_store = str(session_state.get("last_target_store", "") or "").strip() not in ("", "unknown")
        if has_sent_address and has_target_store:
            return True

    if any(keyword in normalized for keyword in _const(agent, "ADDRESS_FOLLOWUP_PRIORITY_KEYWORDS", ())):
        return True

    if any(keyword in normalized for keyword in _const(agent, "ADDRESS_FOLLOWUP_BLOCK_KEYWORDS", ())):
        return False

    if any(keyword in normalized for keyword in _const(agent, "ADDRESS_FOLLOWUP_EXPLICIT_KEYWORDS", ())):
        return True

    if any(keyword in normalized for keyword in _const(agent, "ADDRESS_FOLLOWUP_RESIDUAL_KEYWORDS", ())):
        has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
        has_target_store = str(session_state.get("last_target_store", "") or "").strip() not in ("", "unknown")
        return has_sent_address and has_target_store

    return False


def resolve_geo_context(agent, route: Dict[str, Any], session_state: Dict[str, Any]) -> Dict[str, Any]:
    target_store = route.get("target_store", "unknown")
    detected_region = route.get("detected_region", "") or ""
    if target_store and target_store != "unknown":
        return {
            "known": True,
            "source": "route_target_store",
            "target_store": target_store,
            "region": detected_region,
        }
    if detected_region:
        return {
            "known": True,
            "source": "route_detected_region",
            "target_store": session_state.get("last_target_store", ""),
            "region": detected_region,
        }

    last_target_store = session_state.get("last_target_store", "")
    if last_target_store and last_target_store != "unknown":
        return {
            "known": True,
            "source": "session_last_target_store",
            "target_store": last_target_store,
            "region": session_state.get("last_detected_region", ""),
        }

    last_region = session_state.get("last_detected_region", "")
    if last_region:
        return {
            "known": True,
            "source": "session_last_detected_region",
            "target_store": "",
            "region": last_region,
        }

    if int(session_state.get("address_image_sent_count", 0) or 0) > 0:
        return {
            "known": True,
            "source": "session_address_image_history",
            "target_store": "",
            "region": "",
        }

    return {"known": False, "source": "", "target_store": "", "region": ""}


def get_address_delivery_stage(state: Dict[str, Any], store_key: str) -> str:
    if not store_key or store_key == "unknown":
        return "not_delivered"
    stages = dict(state.get("address_delivery_stage_by_store", {}) or {})
    return str(stages.get(store_key, "not_delivered") or "not_delivered")


def get_address_sent_count(state: Dict[str, Any], store_key: str) -> int:
    counts = dict(state.get("address_image_sent_count_by_store", {}) or {})
    return max(0, int(counts.get(store_key, 0) or 0))


def infer_address_resend_target(agent, text: str, route: Dict[str, Any], state: Dict[str, Any]) -> str:
    explicit_store = str(agent._infer_store_from_context_text(text) or "").strip()
    route_store = str(route.get("target_store", "") or "").strip()
    sent_stores = [
        str(store).strip()
        for store in (state.get("sent_address_stores", []) or [])
        if str(store).strip()
    ]
    unique_sent = list(dict.fromkeys(sent_stores))
    if explicit_store and explicit_store != "unknown":
        return explicit_store
    if looks_like_explicit_address_resend_request(agent, text) and len(unique_sent) > 1:
        return ""
    if route_store and route_store != "unknown":
        return route_store
    last_store = str(state.get("last_target_store", "") or "").strip()
    if len(unique_sent) == 1:
        return unique_sent[0]
    if last_store and last_store != "unknown" and len(unique_sent) <= 1:
        return last_store
    return ""


def looks_like_explicit_address_resend_request(agent, text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "")).lower()
    if not normalized:
        return False
    if getattr(agent, "_looks_like_missing_media_request", lambda _text: False)(text):
        return any(token in normalized for token in ("地址", "位置", "位置图", "图"))
    return (
        any(token in normalized for token in ("再发", "重发", "重新发", "没看到", "没收到", "第二张"))
        and any(token in normalized for token in ("地址", "位置", "位置图", "地址图", "图"))
    )


def looks_like_explicit_address_delivery_request(agent, text: str, route: Dict[str, Any]) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "")).lower()
    if not normalized:
        return False

    if looks_like_explicit_address_resend_request(agent, text):
        return True
    if (
        agent_contact_flow.looks_like_store_recommendation_challenge(text)
        or agent_contact_flow.looks_like_store_preference_statement(text)
    ):
        return False

    route_target_store = str(route.get("target_store", "") or "").strip()
    has_store_context = bool(route_target_store and route_target_store != "unknown")

    explicit_address_tokens = (
        "地址",
        "店在哪",
        "店在哪里",
        "怎么去",
        "怎么走",
        "路线",
        "导航",
        "定位",
        "发位置",
        "位置发我",
        "位置图",
        "地址图",
        "在哪儿",
        "在哪里",
    )
    if any(token in normalized for token in explicit_address_tokens):
        return True

    # “位置”是高噪音词，只在明显是问位置、且已经有明确门店时才算地址交付。
    if "位置" not in normalized or not has_store_context:
        return False

    negative_context_tokens = (
        "位置远",
        "位置有点远",
        "远点儿",
        "远一点",
        "远也行",
        "克服困难",
        "要求",
        "选一个",
        "好的门店",
        "推荐",
        "哪家",
        "是不是",
        "对不对",
        "还是让我去",
        "还是你确定",
        "直接让我去",
        "主要想找",
        "设计师",
    )
    if any(token in normalized for token in negative_context_tokens):
        return False

    location_question_tokens = ("在哪", "哪儿", "哪里", "怎么走", "怎么去", "发我", "给我")
    return any(token in normalized for token in location_question_tokens)


def has_any_address_delivery_history(state: Dict[str, Any]) -> bool:
    stage_by_store = dict(state.get("address_delivery_stage_by_store", {}) or {})
    if any(str(stage or "") in {"delivered_once", "delivered_closed"} for stage in stage_by_store.values()):
        return True
    sent_count_by_store = dict(state.get("address_image_sent_count_by_store", {}) or {})
    if any(int(count or 0) > 0 for count in sent_count_by_store.values()):
        return True
    if any(str(store or "").strip() for store in (state.get("sent_address_stores", []) or [])):
        return True
    return int(state.get("address_image_sent_count", 0) or 0) > 0


def looks_like_explicit_store_recommendation_request(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "")).lower()
    if not normalized:
        return False

    positive_tokens = (
        "推荐哪家",
        "推荐哪个店",
        "推荐哪个门店",
        "哪家更适合",
        "哪个门店更适合",
        "哪家更方便",
        "哪家最近",
        "哪个店最近",
        "帮我选",
        "选哪个店",
        "选哪家店",
        "选一家",
        "安排哪家",
        "去哪家",
        "哪家比较好",
        "哪个店比较好",
    )
    if any(token in normalized for token in positive_tokens):
        return True

    negative_tokens = (
        "是不是",
        "对不对",
        "还是",
        "什么意思",
        "没听懂",
        "总重复",
        "位置远",
        "远点儿",
        "远一点",
        "位置图",
        "地址图",
        "怎么走",
        "怎么去",
        "路线",
        "导航",
        "在哪",
        "哪儿",
        "哪里",
        "发位置",
        "发地址",
        "我主要想问",
        "要求已经告诉",
        "按我的要求",
        "硬推",
        "直接让我去",
        "还是让我去",
        "还是你确定",
    )
    if any(token in normalized for token in negative_tokens):
        return False

    weak_positive_tokens = ("推荐", "哪家", "门店", "店")
    return any(token in normalized for token in weak_positive_tokens) and any(
        token in normalized for token in ("适合", "方便", "最近", "好", "选")
    )


def determine_current_mainline(
    agent,
    text: str,
    intent: str,
    route: Dict[str, Any],
    state: Dict[str, Any],
) -> str:
    normalized = re.sub(r"\s+", "", str(text or "")).lower()
    if agent_contact_flow.looks_like_human_check(text) or agent_contact_flow.looks_like_repetition_frustration(text):
        return "conversation_repair"
    if (
        intent in {"recommendation_clarify", "store_preference"}
        or agent_contact_flow.looks_like_store_recommendation_challenge(text)
        or agent_contact_flow.looks_like_store_preference_statement(text)
    ):
        return "business_answer"

    address_resend_target = infer_address_resend_target(agent, text, route, state)
    if looks_like_explicit_address_resend_request(agent, text) and list(state.get("sent_address_stores", []) or []):
        return "address_delivery"
    if (
        looks_like_explicit_address_resend_request(agent, text)
        and address_resend_target
        and get_address_delivery_stage(state, address_resend_target) == "delivered_once"
    ):
        return "address_delivery"

    if (
        agent_contact_flow.looks_like_explicit_contact_image_resend_request(text)
        and not bool(state.get("contact_captured", False))
        and str(state.get("contact_delivery_stage", "not_delivered") or "not_delivered") == "delivered_once"
    ):
        return "contact_delivery"

    route_target_store = str(route.get("target_store", "") or "").strip()
    if (
        intent == "address"
        and looks_like_explicit_address_delivery_request(agent, text, route)
        and route_target_store
        and route_target_store != "unknown"
        and get_address_delivery_stage(state, route_target_store) == "not_delivered"
    ):
        return "address_delivery"

    if (
        not has_any_address_delivery_history(state)
        and route_target_store
        and route_target_store != "unknown"
        and looks_like_explicit_store_recommendation_request(text)
    ):
        return "store_recommendation"
    if (
        not has_any_address_delivery_history(state)
        and str(state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
        and looks_like_explicit_store_recommendation_request(text)
    ):
        return "store_recommendation"
    return "business_answer"


def decide_rule_reply(
    agent,
    text: str,
    intent: str,
    route: Dict[str, Any],
    session_state: Dict[str, Any],
    conversation_history: List[Dict[str, str]],
    user_state: Dict[str, Any],
    is_first_turn_global: bool = False,
) -> AgentDecision:
    state = agent._current_unified_state if hasattr(agent, "_current_unified_state") and agent._current_unified_state else session_state
    reason = str(route.get("reason", "unknown") or "unknown")
    target_store = str(route.get("target_store", "unknown") or "unknown")
    geo_context = resolve_geo_context(agent, route, state)
    current_mainline = determine_current_mainline(agent, text, intent, route, state)
    state["current_mainline"] = current_mainline

    if current_mainline == "conversation_repair":
        repair_decision = agent._decide_llm_reply(
            latest_user_text=text,
            intent="general",
            route_reason="conversation_repair",
            conversation_history=conversation_history,
            session_state=state,
            rule_id="LLM_CONVERSATION_REPAIR",
            allow_address_guardrails=False,
            allow_precise_address_closure=False,
        )
        repair_decision.media_plan = "none"
        repair_decision.reply_goal = "修复沟通"
        return repair_decision

    if current_mainline == "address_delivery":
        resend_target = infer_address_resend_target(agent, text, route, state)
        if not resend_target:
            return AgentDecision(
                reply_text="姐姐，您是想看哪家门店的位置图，我给您对应发哦。",
                intent="address",
                route_reason="address_resend_need_store",
                reply_goal="确认门店",
                media_plan="none",
                reply_source="rule",
                rule_id="ADDRESS_RESEND_NEED_STORE",
                rule_applied=True,
            )
        stage = get_address_delivery_stage(state, resend_target)
        if stage == "delivered_once" and looks_like_explicit_address_resend_request(agent, text):
            store = agent.knowledge_service.get_store_display(resend_target)
            store_name = agent._store_recommend_display_name(resend_target, str(store.get("store_name", "") or "门店"))
            return AgentDecision(
                reply_text=agent._normalize_reply_text(f"姐姐，{store_name}的位置图我再给您发一次，您直接看图就行"),
                intent="address",
                route_reason="address_resend",
                reply_goal="地址补发",
                media_plan="address_image",
                reply_source="rule",
                rule_id="ADDRESS_DELIVERY_RESEND",
                rule_applied=True,
            )
        if stage == "not_delivered":
            store = agent.knowledge_service.get_store_display(resend_target)
            store_name = agent._store_recommend_display_name(resend_target, str(store.get("store_name", "") or "门店"))
            return AgentDecision(
                reply_text=agent._normalize_reply_text(f"姐姐，{store_name}的位置我给您放图片里，您直接按图看会更方便"),
                intent="address",
                route_reason="address_delivery_first",
                reply_goal="地址交付",
                media_plan="address_image",
                reply_source="rule",
                rule_id="ADDRESS_DELIVERY_FIRST",
                rule_applied=True,
            )

    if current_mainline == "contact_delivery":
        contact_stage = str(state.get("contact_delivery_stage", "not_delivered") or "not_delivered")
        if bool(state.get("contact_captured", False)):
            return agent._decide_llm_reply(
                latest_user_text=text,
                intent="general",
                route_reason="contact_already_captured",
                conversation_history=conversation_history,
                session_state=state,
                rule_id="LLM_CONTACT_CAPTURED",
                allow_address_guardrails=False,
                allow_precise_address_closure=False,
            )
        if contact_stage == "delivered_once" and agent_contact_flow.looks_like_explicit_contact_image_resend_request(text):
            return AgentDecision(
                reply_text=agent._normalize_reply_text("姐姐，联系方式图我再给您发一次，您按图联系就可以"),
                intent="contact",
                route_reason="contact_resend",
                reply_goal="联系方式补发",
                media_plan="contact_image",
                reply_source="rule",
                rule_id="CONTACT_DELIVERY_RESEND",
                rule_applied=True,
            )
        if contact_stage == "not_delivered":
            return AgentDecision(
                reply_text=agent._normalize_reply_text("姐姐，联系方式我给您放图片里，您直接按图联系就可以"),
                intent="contact",
                route_reason="contact_delivery_first",
                reply_goal="联系方式交付",
                media_plan="contact_image",
                reply_source="rule",
                rule_id="CONTACT_DELIVERY_FIRST",
                rule_applied=True,
            )

    if current_mainline == "store_recommendation":
        if target_store != "unknown":
            store = agent.knowledge_service.get_store_display(target_store)
            store_name = agent._store_recommend_display_name(target_store, store.get("store_name", "门店"))
            state["last_geo_pending"] = False
            state["geo_followup_round"] = 0
            state["geo_choice_offered"] = False
            state["last_geo_route_reason"] = ""
            return AgentDecision(
                reply_text=agent._render_template("store_recommend", store_name=store_name),
                intent="address",
                route_reason=reason,
                reply_goal="解答",
                media_plan="address_image",
                reply_source="rule",
                rule_id="STORE_RECOMMENDATION",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )
        route_reason = "need_region" if reason in {"unknown", "need_clarify"} else reason
        return agent._build_geo_followup_decision(session_state=state, route_reason=route_reason, intent="address")

    if intent in {"recommendation_clarify", "store_preference"}:
        return agent._decide_llm_reply(
            latest_user_text=text,
            intent="general",
            route_reason="recommendation_clarify",
            conversation_history=conversation_history,
            session_state=state,
            rule_id="LLM_RECOMMENDATION_CLARIFY",
            allow_address_guardrails=False,
            allow_precise_address_closure=False,
        )

    normalized_text = re.sub(r"\s+", "", str(text or "")).lower()
    first_turn_geo_arrival = (
        is_first_turn_global
        and any(token in normalized_text for token in ("我在", "在北京", "在上海", "北京", "上海", "徐汇", "静安", "虹口", "人民广场", "人广", "五角场"))
        and not any(token in normalized_text for token in ("还是", "对不对", "是不是", "硬推", "按我要求"))
    )
    allow_store_recommend = (
        intent == "address"
        or looks_like_explicit_store_recommendation_request(text)
        or first_turn_geo_arrival
        or looks_like_geo_reply(agent, text=text, route=route)
    )
    unseen_store_for_address = (
        target_store != "unknown"
        and target_store not in {
            str(store).strip()
            for store in (state.get("sent_address_stores", []) or [])
            if str(store).strip()
        }
    )
    if (
        target_store != "unknown"
        and intent in {"general", "address"}
        and (
            (not has_any_address_delivery_history(state) and allow_store_recommend)
            or (allow_store_recommend and unseen_store_for_address)
        )
        and not agent_contact_flow.looks_like_store_recommendation_challenge(text)
        and not agent_contact_flow.looks_like_store_preference_statement(text)
    ):
        store = agent.knowledge_service.get_store_display(target_store)
        store_name = agent._store_recommend_display_name(target_store, store.get("store_name", "门店"))
        state["last_geo_pending"] = False
        state["geo_followup_round"] = 0
        state["geo_choice_offered"] = False
        state["last_geo_route_reason"] = ""
        return AgentDecision(
            reply_text=agent._render_template("store_recommend", store_name=store_name),
            intent="address",
            route_reason=reason,
            reply_goal="解答",
            media_plan="address_image",
            reply_source="rule",
            rule_id="ADDR_STORE_RECOMMEND",
            rule_applied=True,
            geo_context_source=geo_context.get("source", ""),
        )

    unresolved_geo_reasons = {
        "unknown",
        "need_region",
        "need_district",
        "need_clarify",
        "sh_route_need_clarify",
        "shanghai_need_arrival_point",
        "shanghai_need_district",
    }
    if (
        intent == "address"
        and str(route.get("target_store", "") or "").strip() in {"", "unknown"}
        and reason in unresolved_geo_reasons
    ):
        route_reason = "need_region" if reason in {"unknown", "need_clarify"} else reason
        return agent._build_geo_followup_decision(session_state=state, route_reason=route_reason, intent="address")

    if is_first_turn_global and intent == "purchase" and reason in ("unknown", "need_region"):
        return agent._build_geo_followup_decision(session_state=state, route_reason="need_region", intent="purchase")

    if intent == "contact" and bool(state.get("contact_captured", False)):
        return agent._decide_llm_reply(
            latest_user_text=text,
            intent="general",
            route_reason="contact_already_captured",
            conversation_history=conversation_history,
            session_state=state,
            rule_id="LLM_CONTACT_CAPTURED",
            allow_precise_address_closure=False,
        )

    return decide_general_reply(
        agent,
        latest_user_text=text,
        intent=intent,
        route=route,
        conversation_history=conversation_history,
        session_state=state,
        user_state=user_state,
    )


def build_geo_followup_decision(agent, session_state: Dict[str, Any], route_reason: str, intent: str) -> AgentDecision:
    # 优先使用统一状态（如果有）
    if hasattr(agent, '_current_unified_state') and agent._current_unified_state:
        state = agent._current_unified_state
    else:
        state = session_state

    round_count = int(state.get("geo_followup_round", 0) or 0)
    choice_offered = bool(state.get("geo_choice_offered", False))

    if round_count < 2:
        next_round = round_count + 1
        state["geo_followup_round"] = next_round
        state["geo_followup_exhausted"] = False
        state["geo_choice_offered"] = False
        state["last_geo_pending"] = True
        state["last_geo_route_reason"] = route_reason
        if route_reason == "need_district":
            template_key = "ask_sh_district_r1" if next_round == 1 else "ask_sh_district_r2"
            rule_id = f"ADDR_ASK_DISTRICT_R{next_round}"
        else:
            template_key = "ask_region_r1" if next_round == 1 else "ask_region_r2"
            rule_id = f"ADDR_ASK_REGION_R{next_round}"
    elif not choice_offered:
        state["geo_choice_offered"] = True
        state["geo_followup_exhausted"] = False
        state["last_geo_pending"] = True
        state["last_geo_route_reason"] = route_reason
        template_key = "ask_sh_district_choice" if route_reason == "need_district" else "ask_region_choice"
        rule_id = "ADDR_ASK_DISTRICT_CHOICE" if route_reason == "need_district" else "ADDR_ASK_REGION_CHOICE"
    else:
        state["geo_followup_round"] = 1
        state["geo_followup_exhausted"] = False
        state["geo_choice_offered"] = False
        state["last_geo_pending"] = True
        state["last_geo_route_reason"] = route_reason
        template_key = "ask_sh_district_r1_reset" if route_reason == "need_district" else "ask_region_r1_reset"
        rule_id = "ADDR_ASK_DISTRICT_R1_RESET" if route_reason == "need_district" else "ADDR_ASK_REGION_R1_RESET"

    out_intent = intent if intent in ("address", "purchase") else "address"
    return AgentDecision(
        reply_text=agent._render_template(template_key),
        intent=out_intent,
        route_reason=route_reason,
        reply_goal="追问地区",
        media_plan="none",
        reply_source="rule",
        rule_id=rule_id,
        rule_applied=True,
    )


def should_recover_to_shanghai_arrival_help(agent, text: str, session_state: Dict[str, Any]) -> bool:
    if not bool(session_state.get("last_geo_pending", False)):
        return False
    if str(session_state.get("last_geo_route_reason", "") or "") not in ("need_district", "shanghai_need_district"):
        return False
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return False
    return any(keyword in normalized for keyword in _const(agent, "SHANGHAI_ROUTE_HELP_KEYWORDS", ()))


def is_follow_up_question(
    agent,
    text: str,
    conversation_history: List[Dict[str, str]],
    session_state: Optional[Dict[str, Any]] = None,
) -> bool:
    text_stripped = text.strip()
    normalized = re.sub(r"\s+", "", text_stripped)
    if not normalized:
        return False

    if any(keyword in text_stripped for keyword in _const(agent, "SERVICE_HOURS_PRIORITY_KEYWORDS", ())):
        return False
    if agent._looks_like_appointment_query(text_stripped):
        return False
    if agent._looks_like_lifespan_query(text_stripped) and not any(token in normalized for token in ("那", "也是", "这个", "这款", "一样")):
        return False

    try:
        kb_detail = agent.knowledge_service.find_answer_detail(
            text_stripped,
            threshold=getattr(agent, "knowledge_threshold", 0.6),
        )
    except Exception:
        kb_detail = {}
    if bool(kb_detail.get("matched")) or bool(kb_detail.get("blocked_by_polite_guard")):
        return False

    state = dict(session_state or {})
    known_store = str(state.get("last_target_store", "") or "").strip()
    text_reply_count_by_store = dict(state.get("address_text_reply_count_by_store", {}) or {})
    contact_reply_count_by_store = dict(state.get("address_contact_reply_count_by_store", {}) or {})
    if (
        known_store
        and agent.knowledge_service.is_address_query(text_stripped)
        and int(text_reply_count_by_store.get(known_store, 0) or 0) >= 1
        and int(contact_reply_count_by_store.get(known_store, 0) or 0) >= 1
    ):
        return True

    follow_up_keywords = [
        "那",
        "呢",
        "吗",
        "是不是",
        "对吧",
        "是吧",
        "也是",
        "一样",
        "差不多",
        "还",
        "再",
        "还是",
        "周二",
        "周三",
        "周四",
        "周五",
    ]
    follow_up_cues = any(k in text_stripped for k in follow_up_keywords)

    active_topic = str((session_state or {}).get("active_topic", "") or "")
    if (not conversation_history or len(conversation_history) < 2):
        if active_topic in {"price", "service_hours", "lifespan", "store_recommendation", "appointment"} and follow_up_cues and len(text_stripped) <= 18:
            return True
        return False

    last_user_msg = conversation_history[-2].get("content", "")
    last_assistant_msg = conversation_history[-1].get("content", "")

    def extract_keywords(s):
        s = re.sub(r"[，。！？、,.!?~\s]+", "", s)
        common_words = set("的了吗呢啊哦嗯姐姐我们您")
        return set(c for c in s if c not in common_words)

    user_words = extract_keywords(text_stripped)
    last_words = extract_keywords(last_user_msg + last_assistant_msg)

    overlap = 0.0
    if user_words and last_words:
        overlap = len(user_words & last_words) / len(user_words)

    if follow_up_cues and len(text_stripped) <= 18:
        return True
    if overlap > 0.45 and len(text_stripped) <= 18:
        return True

    return False


def decide_general_reply(
    agent,
    latest_user_text: str,
    intent: str,
    route: Dict[str, Any],
    conversation_history: List[Dict[str, str]],
    session_state: Dict[str, Any],
    user_state: Dict[str, Any],
    user_id_hash: str = "",
) -> AgentDecision:
    # 优先使用统一状态（如果有）
    if hasattr(agent, '_current_unified_state') and agent._current_unified_state:
        state = agent._current_unified_state
    else:
        state = session_state

    # 只有当前轮仍在处理地区补充时，才允许用追问耗尽兜底强制转联系方式。
    geo_followup_exhausted = state.get("geo_followup_exhausted", False)
    geo_followup_round = state.get("geo_followup_round", 0)
    route_reason = route.get("reason", "unknown")
    unresolved_geo_reasons = {
        "need_region",
        "need_district",
        "shanghai_need_district",
        "sh_route_need_clarify",
        "shanghai_need_arrival_point",
    }
    geo_followup_active = bool(state.get("last_geo_pending", False)) or route_reason in unresolved_geo_reasons
    has_known_store = str(route.get("target_store", "") or state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
    current_turn_still_geo_like = looks_like_geo_reply(agent, text=latest_user_text, route=route) or (
        intent == "address" and str(route.get("target_store", "") or "").strip() in {"", "unknown"}
    )

    if (
        (geo_followup_exhausted or geo_followup_round >= 2)
        and geo_followup_active
        and current_turn_still_geo_like
        and not has_known_store
    ):
        contact_sent = state.get("contact_image_sent", False) or state.get("contact_image_sent_count", 0) >= 1
        if contact_sent:
            return AgentDecision(
                reply_text="姐姐，请往上滑看图片添加我好友哦～♥️",
                intent="contact",
                route_reason="geo_followup_exhausted",
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="GEO_FOLLOWUP_EXHAUSTED_REMIND",
            )
        else:
            return AgentDecision(
                reply_text="姐姐，您直接留个联系方式，我让客服联系您详细说❤️",
                intent="contact",
                route_reason="geo_followup_exhausted",
                reply_goal="推进购买意图",
                media_plan="contact_image",
                reply_source="rule",
                rule_id="GEO_FOLLOWUP_EXHAUSTED",
            )

    contact_sent = int(state.get("contact_image_sent_count", 0) or 0) >= 1
    kb_blocked_by_polite_guard = False
    kb_polite_guard_reason = ""

    media_placeholder_decision = agent._decide_media_placeholder_reply(
        latest_user_text=latest_user_text,
        route_reason=route_reason,
        user_state=user_state,
        user_id_hash=user_id_hash,
    )
    if media_placeholder_decision is not None:
        return media_placeholder_decision

    lifespan_priority_decision = agent._decide_lifespan_priority_reply(
        latest_user_text=latest_user_text,
        route=route,
        user_state=user_state,
        user_id_hash=user_id_hash,
    )
    if lifespan_priority_decision is not None:
        return lifespan_priority_decision

    if callable(getattr(agent, "_looks_like_closing_confirmation", None)) and agent._looks_like_closing_confirmation(latest_user_text):
        return AgentDecision(
            reply_text=agent._build_closing_confirmation_reply(),
            intent="general",
            route_reason=route_reason,
            reply_goal="承接联系方式",
            media_plan="none",
            reply_source="rule",
            rule_id="CLOSING_CONFIRM_REPLY",
            rule_applied=True,
        )

    # 【新增】处理状态确认意图
    if intent.startswith("status_confirm_"):
        confirm_type = intent.replace("status_confirm_", "")
        if confirm_type == "address":
            if state.get("address_image_sent") or int(state.get("address_image_sent_count", 0) or 0) > 0:
                return AgentDecision(
                    reply_text="姐姐，地址位置图已经发了，您往上滑看一下哦～♥️",
                    intent="status_confirm",
                    route_reason="address_already_sent",
                    reply_goal="确认已发送",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="STATUS_CONFIRM_ADDRESS_SENT",
                )
        elif confirm_type == "contact":
            if state.get("contact_image_sent") or int(state.get("contact_image_sent_count", 0) or 0) > 0:
                return AgentDecision(
                    reply_text="姐姐，联系方式已经发了，您往上滑看一下哦～♥️",
                    intent="status_confirm",
                    route_reason="contact_already_sent",
                    reply_goal="确认已发送",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="STATUS_CONFIRM_CONTACT_SENT",
                )

    if intent == "contact":
        if bool(state.get("contact_captured", False)):
            return agent._decide_llm_reply(
                latest_user_text=latest_user_text,
                intent=intent,
                route_reason=route_reason,
                conversation_history=conversation_history,
                session_state=state,
                rule_id="LLM_CONTACT_CAPTURED",
            )
        if callable(getattr(agent, "_looks_like_missing_media_request", None)) and agent._looks_like_missing_media_request(latest_user_text):
            return AgentDecision(
                reply_text=_const(agent, "MEDIA_DELIVERY_RETRY_FALLBACK", ""),
                intent="contact",
                route_reason="contact_followup_missing_media",
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="CONTACT_FOLLOWUP_MISSING_MEDIA",
                rule_applied=True,
            )
        if contact_sent:
            return AgentDecision(
                reply_text=agent._normalize_reply_text("姐姐，联系方式图刚才已经发过了，您按图联系就可以"),
                intent="contact",
                route_reason=route_reason,
                reply_goal="承接联系方式",
                media_plan="none",
                reply_source="rule",
                rule_id="CONTACT_ALREADY_SENT_ACK",
                rule_applied=True,
            )
        return AgentDecision(
            reply_text=agent._render_template("contact_intro"),
            intent="contact",
            route_reason=route_reason,
            reply_goal="推进购买意图",
            media_plan="contact_image",
            reply_source="rule",
            rule_id="CONTACT_SEND_IMAGE",
            rule_applied=True,
        )

    geo_context = resolve_geo_context(agent, route, state)
    if intent in ("purchase", "appointment") and route_reason != "shanghai_need_district" and geo_context.get("known"):
        appointment_reply = ""
        if intent == "appointment":
            appointment_reply = str(
                agent._build_store_appointment_contact_reply(
                    latest_user_text,
                    route,
                    session_state=state,
                    conversation_history=conversation_history,
                ) or ""
            ).strip()
        if contact_sent:
            return AgentDecision(
                reply_text=appointment_reply or "姐姐，您直接看上面的图片加专属客服就可以，把您方便的时间跟老师说一下就行。🌹",
                intent="appointment" if appointment_reply else "purchase",
                route_reason=route_reason if route_reason != "unknown" else "known_geo_context",
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="PURCHASE_CONTACT_REMIND_ONLY",
                rule_applied=True,
            )
        return AgentDecision(
            reply_text=appointment_reply or agent._render_template("purchase_contact_intro"),
            intent="appointment" if appointment_reply else "purchase",
            route_reason=route_reason if route_reason != "unknown" else "known_geo_context",
            reply_goal="推进购买意图",
            media_plan="contact_image",
            reply_source="rule",
            rule_id="PURCHASE_CONTACT_FROM_KNOWN_GEO",
            rule_applied=True,
        )

    if agent._is_ambiguous_short_fragment(latest_user_text, intent=intent, route=route):
        return AgentDecision(
            reply_text=agent._render_template("ask_ambiguous_short_fragment"),
            intent="address",
            route_reason="ambiguous_short_fragment",
            reply_goal="追问地区",
            media_plan="none",
            reply_source="rule",
            rule_id="ADDR_AMBIGUOUS_SHORT_FRAGMENT",
            rule_applied=True,
        )

    if agent._is_follow_up_question(latest_user_text, conversation_history, session_state=state):
        return agent._decide_llm_reply(
            latest_user_text=latest_user_text,
            intent=intent,
            route_reason=route_reason,
            conversation_history=conversation_history,
            session_state=state,
            rule_id="LLM_FOLLOW_UP",
        )

    if agent.use_knowledge_first:
        kb_detail = agent.knowledge_service.find_answer_detail(
            latest_user_text,
            threshold=agent.knowledge_threshold,
        )
        kb_blocked_by_polite_guard = bool(kb_detail.get("blocked_by_polite_guard", False))
        kb_polite_guard_reason = str(kb_detail.get("polite_guard_reason", "") or "")
        if kb_detail.get("matched"):
            kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
            kb_tags = {
                str(tag).strip()
                for tag in (kb_detail.get("tags", []) or [])
                if str(tag).strip()
            }
            if kb_intent in {"service_hours", "lifespan"} and agent._looks_like_travel_schedule_statement(latest_user_text):
                kb_intent = ""
                kb_tags = set()
            force_direct_kb = kb_intent == "service_hours" or "营业时间" in kb_tags
            confidence = kb_detail.get("confidence", "high")
            if confidence in ["low", "medium"] and not force_direct_kb:
                return agent._decide_llm_reply(
                    latest_user_text=latest_user_text,
                    intent=intent,
                    route_reason=route_reason,
                    conversation_history=conversation_history,
                    session_state=session_state,
                    kb_match_score=kb_detail.get("score", 0.0),
                    kb_match_question=kb_detail.get("question", ""),
                    kb_match_mode=kb_detail.get("mode", ""),
                    kb_item_id=kb_detail.get("item_id", ""),
                    rule_id="LLM_LOW_CONFIDENCE_KB",
                )

            kb_contact_trigger_type = agent._resolve_kb_contact_trigger_type(
                latest_user_text=latest_user_text,
                kb_detail=kb_detail,
            )
            force_contact_image = bool(kb_contact_trigger_type)
            kb_answer = str(kb_detail.get("answer", "") or "").strip()
            kb_answers = [
                str(x).strip()
                for x in (kb_detail.get("answers", []) or [])
                if str(x).strip()
            ]
            if kb_answer and kb_answer not in kb_answers:
                kb_answers.insert(0, kb_answer)

            selected_answer, selected_index, exhausted = agent._select_kb_variant_answer(
                answers=kb_answers,
                user_state=user_state,
                user_id_hash=user_id_hash,
            )
            if selected_answer:
                return AgentDecision(
                    reply_text=selected_answer,
                    intent=intent,
                    route_reason=route_reason,
                    reply_goal="解答",
                    media_plan="contact_image" if force_contact_image else "none",
                    reply_source="knowledge",
                    rule_id="KB_MATCH_CONTACT_IMAGE" if force_contact_image else "KB_MATCH",
                    rule_applied=False,
                    kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
                    kb_match_question=str(kb_detail.get("question", "") or ""),
                    kb_match_mode=str(kb_detail.get("mode", "") or ""),
                    kb_item_id=str(kb_detail.get("item_id", "") or ""),
                    kb_variant_total=len(kb_answers),
                    kb_variant_selected_index=selected_index,
                    kb_variant_fallback_llm=False,
                    kb_confident=True,
                    kb_blocked_by_polite_guard=False,
                    kb_polite_guard_reason="",
                    force_contact_image=force_contact_image,
                    kb_contact_trigger_type=kb_contact_trigger_type,
                )

            if exhausted:
                rewrite_prompt = agent._build_kb_variant_fallback_prompt(
                    latest_user_text=latest_user_text,
                    kb_question=str(kb_detail.get("question", "") or ""),
                    kb_answer=kb_answer or (kb_answers[0] if kb_answers else ""),
                )
                return agent._decide_llm_reply(
                    latest_user_text=latest_user_text,
                    intent=intent,
                    route_reason=route_reason,
                    conversation_history=conversation_history,
                    session_state=session_state,
                    kb_blocked_by_polite_guard=False,
                    kb_polite_guard_reason="",
                    user_message_override=rewrite_prompt,
                    rule_id="LLM_KB_VARIANT_FALLBACK",
                    kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
                    kb_match_question=str(kb_detail.get("question", "") or ""),
                    kb_match_mode=str(kb_detail.get("mode", "") or ""),
                    kb_item_id=str(kb_detail.get("item_id", "") or ""),
                    kb_variant_total=len(kb_answers),
                    kb_variant_selected_index=-1,
                    kb_variant_fallback_llm=True,
                    kb_confident=True,
                )

    return agent._decide_llm_reply(
        latest_user_text=latest_user_text,
        intent=intent,
        route_reason=route_reason,
        conversation_history=conversation_history,
        session_state=session_state,
        kb_blocked_by_polite_guard=kb_blocked_by_polite_guard,
        kb_polite_guard_reason=kb_polite_guard_reason,
    )
