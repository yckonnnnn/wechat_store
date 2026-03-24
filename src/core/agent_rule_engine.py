from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Optional

from .agent_types import AgentDecision
from . import agent_media


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
    normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
    explicit_revisit = any(token in normalized for token in ("位置图", "再发", "看图", "位置"))
    if (
        intent != "address"
        and not explicit_revisit
        and not agent.knowledge_service.is_address_query(latest_user_text)
        and not agent.knowledge_service.is_shanghai_route_alias_address_candidate(latest_user_text)
    ):
        return None
    if not should_continue_address_followup(agent, latest_user_text=latest_user_text, session_state=session_state):
        return None

    target_store = str(route.get("target_store", "") or "")
    if not target_store or target_store == "unknown":
        target_store = str(session_state.get("last_target_store", "") or "")
    if not target_store or target_store == "unknown":
        return None

    sent_stores = set(session_state.get("sent_address_stores", []) or [])
    last_target_store = str(session_state.get("last_target_store", "") or "")
    has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
    if target_store not in sent_stores and not (has_sent_address and last_target_store == target_store):
        return None

    text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
    if int(text_reply_count_by_store.get(target_store, 0) or 0) >= 1:
        return None

    store = agent.knowledge_service.get_store_display(target_store)
    store_name = str(store.get("store_name", "") or "门店")

    return AgentDecision(
        reply_text=agent._normalize_reply_text(f"姐姐，{store_name}位置直接看图片就可以哦"),
        intent="address",
        route_reason=str(route.get("reason", "unknown") or "unknown"),
        reply_goal="解答",
        media_plan="address_image",
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
    normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
    explicit_revisit = any(token in normalized for token in ("位置图", "再发", "看图", "位置"))
    if (
        intent != "address"
        and not explicit_revisit
        and not agent.knowledge_service.is_address_query(latest_user_text)
        and not agent.knowledge_service.is_shanghai_route_alias_address_candidate(latest_user_text)
    ):
        return None
    if not should_continue_address_followup(agent, latest_user_text=latest_user_text, session_state=session_state):
        return None

    target_store = str(route.get("target_store", "") or "")
    if not target_store or target_store == "unknown":
        target_store = str(session_state.get("last_target_store", "") or "")
    if not target_store or target_store == "unknown":
        return None

    sent_stores = set(session_state.get("sent_address_stores", []) or [])
    last_target_store = str(session_state.get("last_target_store", "") or "")
    has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
    if target_store not in sent_stores and not (has_sent_address and last_target_store == target_store):
        return None

    text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
    if int(text_reply_count_by_store.get(target_store, 0) or 0) < 1:
        return None

    contact_reply_count_by_store = dict(session_state.get("address_contact_reply_count_by_store", {}) or {})
    if int(contact_reply_count_by_store.get(target_store, 0) or 0) >= 1:
        return None

    return AgentDecision(
        reply_text=_const(agent, "ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK", ""),
        intent="address",
        route_reason=str(route.get("reason", "unknown") or "unknown"),
        reply_goal="解答",
        media_plan="none",
        reply_source="rule",
        rule_id="ADDR_CONTACT_AFTER_TEXT",
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
    reason = route.get("reason", "unknown")
    target_store = route.get("target_store", "unknown")
    geo_context = resolve_geo_context(agent, route, session_state)
    both_images_sent = agent._has_both_images_sent(session_state)
    neg_shanghai_hint = agent._has_neg_shanghai_hint(text)

    if is_first_turn_global and intent == "purchase" and reason in ("unknown", "need_region"):
        return agent._build_geo_followup_decision(session_state=session_state, route_reason="need_region", intent="purchase")

    if reason == "shanghai_need_arrival_point":
        session_state["last_geo_pending"] = True
        session_state["last_geo_route_reason"] = "need_arrival_point"
        return AgentDecision(
            reply_text=agent._render_template("ask_sh_arrival_point"),
            intent="address",
            route_reason="need_arrival_point",
            reply_goal="追问地区",
            media_plan="none",
            reply_source="rule",
            rule_id="ADDR_ASK_ARRIVAL_POINT",
            rule_applied=True,
            geo_context_source=geo_context.get("source", ""),
        )

    if reason == "shanghai_need_district":
        return agent._build_geo_followup_decision(session_state=session_state, route_reason="need_district", intent="address")

    if reason == "sh_route_need_clarify":
        session_state["last_geo_pending"] = True
        session_state["last_geo_route_reason"] = "need_clarify"
        return AgentDecision(
            reply_text=agent._render_template("ask_sh_route_clarify"),
            intent="address",
            route_reason="need_clarify",
            reply_goal="追问地区",
            media_plan="none",
            reply_source="rule",
            rule_id="ADDR_SH_ROUTE_NEED_CLARIFY",
            rule_applied=True,
            geo_context_source=geo_context.get("source", ""),
        )

    if (
        intent == "purchase"
        and neg_shanghai_hint
        and geo_context.get("known")
    ):
        session_state["last_geo_pending"] = False
        session_state["geo_followup_round"] = 0
        session_state["geo_choice_offered"] = False
        if agent._is_contact_image_sent_for_current_geo(session_state):
            return AgentDecision(
                reply_text=agent._render_template("purchase_contact_remote_remind_only"),
                intent="purchase",
                route_reason="not_in_shanghai_remote",
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="PURCHASE_REMOTE_CONTACT_REMIND_ONLY",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )
        return AgentDecision(
            reply_text=agent._render_template("purchase_contact_intro"),
            intent="purchase",
            route_reason="not_in_shanghai_remote",
            reply_goal="推进购买意图",
            media_plan="contact_image",
            reply_source="rule",
            rule_id="PURCHASE_REMOTE_CONTACT_IMAGE",
            rule_applied=True,
            geo_context_source=geo_context.get("source", ""),
        )

    if reason == "out_of_coverage":
        if agent._should_recover_to_shanghai_arrival_help(text, session_state):
            session_state["last_geo_pending"] = True
            session_state["last_geo_route_reason"] = "need_arrival_point"
            return AgentDecision(
                reply_text=agent._render_template("ask_sh_arrival_point"),
                intent="address",
                route_reason="need_arrival_point",
                reply_goal="追问地区",
                media_plan="none",
                reply_source="rule",
                rule_id="ADDR_ASK_ARRIVAL_POINT",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )
        region = route.get("detected_region") or agent_media.route_region(reason, text) or session_state.get("last_detected_region", "") or "您所在地区"
        session_state["last_geo_pending"] = False
        session_state["geo_followup_round"] = 0
        session_state["geo_choice_offered"] = False
        session_state["last_geo_route_reason"] = ""

        if (
            not agent_media.is_media_whitelist_session(agent, str(session_state.get("session_id", "") or ""))
            and int(session_state.get("contact_image_sent_count", 0) or 0) >= 3
        ):
            return AgentDecision(
                reply_text="姐姐，请往上滑看图片添加我哦～♥️",
                intent="purchase" if intent == "purchase" else "address",
                route_reason="out_of_coverage",
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="ADDR_OUT_OF_COVERAGE_REMIND_ONLY",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        return AgentDecision(
            reply_text=agent._render_template("non_coverage_contact", region=region),
            intent="purchase" if intent == "purchase" else "address",
            route_reason="out_of_coverage",
            reply_goal="推进购买意图",
            media_plan="contact_image",
            reply_source="rule",
            rule_id="ADDR_OUT_OF_COVERAGE",
            rule_applied=True,
            geo_context_source=geo_context.get("source", ""),
        )

    if reason == "north_fallback_beijing" and intent in ("purchase", "address"):
        session_state["last_geo_pending"] = False
        session_state["geo_followup_round"] = 0
        session_state["geo_choice_offered"] = False
        if agent._is_contact_image_sent_for_current_geo(session_state):
            return AgentDecision(
                reply_text=agent._render_template("purchase_contact_remote_remind_only"),
                intent="purchase",
                route_reason=reason,
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="PURCHASE_REMOTE_CONTACT_REMIND_ONLY",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        store = agent.knowledge_service.get_store_display("beijing_chaoyang")
        store_name = agent._store_recommend_display_name(
            "beijing_chaoyang",
            store.get("store_name", "北京朝阳门店"),
        )
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

    if intent == "purchase" and reason != "shanghai_need_district" and geo_context.get("known") and both_images_sent:
        strong_count = int(session_state.get("strong_intent_after_both_count", 0) or 0)
        session_state["strong_intent_after_both_count"] = strong_count + 1
        hint_sent = bool(session_state.get("purchase_both_first_hint_sent", False))
        if not hint_sent:
            session_state["purchase_both_first_hint_sent"] = True
            return AgentDecision(
                reply_text=agent._render_template("strong_intent_after_both_first"),
                intent="purchase",
                route_reason=reason if reason != "unknown" else "both_images_lock",
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="PURCHASE_AFTER_BOTH_FIRST_HINT",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
                both_images_sent_state=True,
                purchase_both_first_hint_sent=True,
            )

        follow_decision = agent._decide_general_reply(
            latest_user_text=text,
            intent=intent,
            route=route,
            conversation_history=conversation_history,
            session_state=session_state,
            user_state=user_state,
        )
        follow_decision.media_plan = "none"
        follow_decision.geo_context_source = geo_context.get("source", "")
        follow_decision.both_images_sent_state = True
        follow_decision.purchase_both_first_hint_sent = bool(
            session_state.get("purchase_both_first_hint_sent", False)
        )
        return follow_decision

    if intent == "purchase" and reason != "shanghai_need_district" and geo_context.get("known"):
        contact_sent = agent._is_contact_image_sent_for_current_geo(session_state)
        session_state["last_geo_pending"] = False
        session_state["geo_followup_round"] = 0
        session_state["geo_choice_offered"] = False
        if contact_sent:
            return AgentDecision(
                reply_text=agent._render_template("purchase_contact_remind_only"),
                intent="purchase",
                route_reason=reason if reason != "unknown" else "known_geo_context",
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="PURCHASE_CONTACT_REMIND_ONLY",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        return AgentDecision(
            reply_text=agent._render_template("purchase_contact_intro"),
            intent="purchase",
            route_reason=reason if reason != "unknown" else "known_geo_context",
            reply_goal="推进购买意图",
            media_plan="contact_image",
            reply_source="rule",
            rule_id="PURCHASE_CONTACT_FROM_KNOWN_GEO",
            rule_applied=True,
            geo_context_source=geo_context.get("source", ""),
        )

    if target_store != "unknown":
        store = agent.knowledge_service.get_store_display(target_store)
        store_name = agent._store_recommend_display_name(target_store, store.get("store_name", "门店"))
        session_state["last_geo_pending"] = False
        session_state["geo_followup_round"] = 0
        session_state["geo_choice_offered"] = False
        session_state["last_geo_route_reason"] = ""
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

    return agent._build_geo_followup_decision(session_state=session_state, route_reason="need_region", intent=intent)


def build_geo_followup_decision(agent, session_state: Dict[str, Any], route_reason: str, intent: str) -> AgentDecision:
    round_count = int(session_state.get("geo_followup_round", 0) or 0)
    choice_offered = bool(session_state.get("geo_choice_offered", False))

    if round_count < 2:
        next_round = round_count + 1
        session_state["geo_followup_round"] = next_round
        session_state["geo_choice_offered"] = False
        session_state["last_geo_pending"] = True
        session_state["last_geo_route_reason"] = route_reason
        if route_reason == "need_district":
            template_key = "ask_sh_district_r1" if next_round == 1 else "ask_sh_district_r2"
            rule_id = f"ADDR_ASK_DISTRICT_R{next_round}"
        else:
            template_key = "ask_region_r1" if next_round == 1 else "ask_region_r2"
            rule_id = f"ADDR_ASK_REGION_R{next_round}"
    elif not choice_offered:
        session_state["geo_choice_offered"] = True
        session_state["last_geo_pending"] = True
        session_state["last_geo_route_reason"] = route_reason
        template_key = "ask_sh_district_choice" if route_reason == "need_district" else "ask_region_choice"
        rule_id = "ADDR_ASK_DISTRICT_CHOICE" if route_reason == "need_district" else "ADDR_ASK_REGION_CHOICE"
    else:
        session_state["geo_followup_round"] = 1
        session_state["geo_choice_offered"] = False
        session_state["last_geo_pending"] = True
        session_state["last_geo_route_reason"] = route_reason
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
    route_reason = route.get("reason", "unknown")
    contact_sent = int(session_state.get("contact_image_sent_count", 0) or 0) >= 1
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

    if intent == "contact":
        if contact_sent:
            prompt_count = int(session_state.get("contact_followup_prompt_count", 0) or 0)
            session_state["contact_followup_prompt_count"] = prompt_count + 1
            template_key = "contact_followup_1" if (prompt_count % 2) == 0 else "contact_followup_2"
            return AgentDecision(
                reply_text=agent._render_template(template_key),
                intent="contact",
                route_reason=route_reason,
                reply_goal="推进购买意图",
                media_plan="none",
                reply_source="rule",
                rule_id="CONTACT_FOLLOWUP",
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

    if agent._is_follow_up_question(latest_user_text, conversation_history, session_state=session_state):
        return agent._decide_llm_reply(
            latest_user_text=latest_user_text,
            intent=intent,
            route_reason=route_reason,
            conversation_history=conversation_history,
            session_state=session_state,
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
