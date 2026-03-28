from __future__ import annotations

import copy
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import agent_contact_flow
from .agent_types import AgentDecision, MediaJudgeDecision


CONTACT_TRIGGER_KEYWORDS = (
    "联系方式",
    "联系",
    "联系方法",
    "联系信息",
    "电话",
    "微信",
    "二维码",
    "路线",
    "导航",
    "邮寄",
    "快递",
    "寄快递",
)
CONTACT_TRIGGER_TAGS = (
    "联系",
    "联系方式",
    "预约",
    "加微信",
    "邮寄",
    "快递",
)
CONTACT_TRIGGER_INTENTS = ("appointment",)
APPOINTMENT_PRIORITY_KEYWORDS = (
    "预约",
    "约时间",
    "几点方便",
    "哪天方便",
    "怎么约",
    "怎么约呀",
    "约呀",
    "预月",
)
REQUIRED_MEDIA_TYPES = ("address_image", "contact_image", "delayed_video")
MATERIAL_LIBRARY_VIDEO_SENTINEL = "__material_library_video__"


def build_post_text_media_queue(
    agent,
    session_id: str,
    user_name: str,
    planned_media_items: List[Dict[str, Any]],
    extra_media_items: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    user_hash = agent._hash_user(user_name or session_id)
    session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
    carryover_items = sanitize_pending_required_media(
        agent,
        [
            *(session_state.get("planned_required_media", []) or []),
            *(session_state.get("pending_required_media", []) or []),
        ],
        session_state=session_state,
        latest_planned=planned_media_items,
    )
    queue: List[Dict[str, Any]] = []
    queue.extend(carryover_items)

    for item in planned_media_items or []:
        if not isinstance(item, dict):
            continue
        queue = _upsert_media_item(agent, queue, dict(item))

    for item in extra_media_items or []:
        if isinstance(item, dict):
            queue.append(dict(item))

    return queue


def register_planned_required_media(
    agent,
    session_id: str,
    user_name: str,
    media_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not media_items:
        return []

    user_hash = agent._hash_user(user_name or session_id)
    session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
    planned_items = sanitize_pending_required_media(
        agent,
        session_state.get("planned_required_media", []),
        session_state=session_state,
    )
    added_items: List[Dict[str, Any]] = []
    for raw_item in media_items or []:
        if not isinstance(raw_item, dict):
            continue
        if bool(raw_item.get("disable_compensation", False)):
            continue
        media_type = str(raw_item.get("type", "") or "")
        if media_type not in REQUIRED_MEDIA_TYPES:
            continue
        state_item = _build_required_media_state_item(raw_item)
        if not state_item:
            continue
        state_item["pending_media_id"] = pending_media_key(agent, state_item)
        state_item["pending_required"] = True
        planned_items = _upsert_media_item(agent, planned_items, state_item)
        added_items = _upsert_media_item(agent, added_items, dict(state_item))

    if not added_items:
        return []

    session_state["planned_required_media"] = planned_items
    session_state["planned_required_media_updated_at"] = datetime.now().isoformat()
    agent.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
    agent.memory_store.save()
    return added_items


def mark_reply_sent(
    agent,
    session_id: str,
    user_name: str,
    reply_text: str,
    *,
    is_first_turn_global: bool = False,
) -> Optional[Dict[str, Any]]:
    del is_first_turn_global
    if str(getattr(agent, "reply_mode", "") or "") == "llm_direct":
        user_hash = agent._hash_user(user_name or session_id)
        user_state = agent.memory_store.get_user_state(user_hash)
        normalized = agent._normalize_for_dedupe(reply_text)
        recent_hashes = list(user_state.get("recent_reply_hashes", []) or [])
        if normalized:
            recent_hashes.append(normalized)
        if len(recent_hashes) > 40:
            recent_hashes = recent_hashes[-40:]
        user_state["recent_reply_hashes"] = recent_hashes
        agent.memory_store.update_user_state(user_hash, user_state)
        agent.memory_store.save()
        return None
    user_hash = agent._hash_user(user_name or session_id)
    user_state = agent.memory_store.get_user_state(user_hash)
    normalized = agent._normalize_for_dedupe(reply_text)

    recent_hashes = list(user_state.get("recent_reply_hashes", []) or [])
    if normalized:
        recent_hashes.append(normalized)
    if len(recent_hashes) > 40:
        recent_hashes = recent_hashes[-40:]
    user_state["recent_reply_hashes"] = recent_hashes

    session_video = summarize_session_video_from_log(agent, session_id=session_id)
    if session_video.get("contact_sent") and not session_video.get("contact_followup_video_sent"):
        user_messages_after_contact = int(session_video.get("user_message_count_after_contact", 0) or 0)
        if user_messages_after_contact >= 2:
            video_item = build_video_media_item(agent, trigger_source="contact_followup")
            if video_item:
                agent.memory_store.update_user_state(user_hash, user_state)
                agent.memory_store.save()
                return video_item

    agent.memory_store.update_user_state(user_hash, user_state)
    agent.memory_store.save()
    return None


def judge_post_reply_media(
    agent,
    session_id: str,
    user_name: str,
    latest_user_text: str,
    reply_text: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    decision: Optional[AgentDecision] = None,
) -> MediaJudgeDecision:
    user_hash = agent._hash_user(user_name or session_id)
    session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
    session_media_summary = summarize_session_media_from_logs(agent, session_id=session_id)
    normalized_text = agent.knowledge_service.normalize_user_text(latest_user_text).strip()
    history = conversation_history or []
    route = agent.knowledge_service.resolve_store_recommendation(normalized_text)
    route = agent._enrich_route_from_conversation_state(
        latest_user_text=normalized_text,
        route=route,
        session_state=session_state,
    )
    intent = decision.intent if decision is not None else agent._detect_intent(normalized_text)
    is_appointment_decision = str(intent or "") == "appointment"
    is_remote_flow_decision = str(getattr(decision, "route_reason", "") or "") in {
        "remote_flow_entry",
        "remote_flow_followup",
        "out_of_coverage",
        "not_in_shanghai_remote",
    }
    remote_flow_active = bool(session_state.get("remote_flow_active", False) or is_remote_flow_decision)
    remote_contact_sent_in_session = bool(
        int(session_media_summary.get("contact_image_sent_count", 0) or 0) > 0
    )
    closure_info = agent._build_reply_closure_info(
        reply_text=reply_text,
        base_info=dict(getattr(decision, "reply_closure_info", {}) or {}) if decision is not None else None,
    )
    reply_store = str(closure_info.get("target_store", "") or agent._infer_store_from_context_text(reply_text) or "").strip()
    media_items: List[Dict[str, Any]] = list(getattr(decision, "media_items", []) or []) if decision is not None else []
    reasons: List[str] = ["planned_media"] if media_items else []
    skip_reason = str(getattr(decision, "media_skip_reason", "") or "") if decision is not None else ""
    block_unresolved_address_media = bool(
        decision is not None
        and callable(getattr(agent, "_should_block_unresolved_address_media", None))
        and agent._should_block_unresolved_address_media(
            latest_user_text=latest_user_text,
            decision=decision,
            route=route,
            session_state=session_state,
        )
    )

    if decision is not None and str(getattr(decision, "rule_id", "") or "") in {
        "CONTACT_PHONE_SUBMITTED",
        "CONTACT_ALREADY_ADDED",
        "CONTACT_ALREADY_CAPTURED",
    }:
        return MediaJudgeDecision(skip_reason="contact_already_captured")

    if (
        not block_unresolved_address_media
        and (not remote_flow_active)
        and (not is_appointment_decision)
        and str(session_state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
        and int(session_state.get("address_image_sent_count", 0) or 0) > 0
        and any(token in re.sub(r"\s+", "", str(latest_user_text or "")).lower() for token in ("位置图", "再发", "看图", "在哪", "哪儿"))
    ):
        item, reason_hint = queue_address_image(
            agent,
            session_id=session_id,
            session_state=session_state,
            target_store=str(session_state.get("last_target_store", "") or ""),
            route_reason="explicit_address_revisit",
            detected_region=route.get("detected_region", "") or "",
        )
        if item:
            media_items = _upsert_media_item(agent, media_items, item)
            reasons.append("explicit_address_revisit")
        elif reason_hint and not skip_reason:
            skip_reason = reason_hint

    if (
        not block_unresolved_address_media
        and (not remote_flow_active)
        and (not is_appointment_decision)
        and closure_info.get("precise_address_hit")
        and str(closure_info.get("target_store", "") or "")
    ):
        item, reason_hint = queue_address_image(
            agent,
            session_id=session_id,
            session_state=session_state,
            target_store=str(closure_info.get("target_store", "") or ""),
            route_reason="precise_address_closure",
            detected_region=route.get("detected_region", "") or "",
        )
        if item:
            media_items = _upsert_media_item(agent, media_items, item)
            reasons.append("precise_address_closure")
        elif reason_hint and not skip_reason:
            skip_reason = reason_hint

    if (
        not block_unresolved_address_media
        and (not remote_flow_active)
        and (not is_appointment_decision)
        and not any(str(x.get("type", "") or "") == "address_image" for x in media_items)
        and str(closure_info.get("closure_type", "") or "") in {"store_recommendation", "address_image_promise"}
    ):
        if (
            str(closure_info.get("closure_type", "") or "") == "store_recommendation"
            and int(session_state.get("address_image_sent_count", 0) or 0) > 0
        ):
            closure_target_store = ""
        else:
            closure_target_store = str(reply_store or route.get("target_store", "") or session_state.get("last_target_store", "") or "")
        already_sent_for_store = (
            closure_target_store
            and closure_target_store in {
                str(store).strip()
                for store in (session_state.get("sent_address_stores", []) or [])
                if str(store).strip()
            }
        )
        if already_sent_for_store:
            closure_target_store = ""
        if closure_target_store:
            item, reason_hint = queue_address_image(
                agent,
                session_id=session_id,
                session_state=session_state,
                target_store=closure_target_store,
                route_reason=(
                    "address_image_promise_closure"
                    if str(closure_info.get("closure_type", "") or "") == "address_image_promise"
                    else "store_recommendation_closure"
                ),
                detected_region=route.get("detected_region", "") or "",
            )
            if item:
                media_items = _upsert_media_item(agent, media_items, item)
                reasons.append(
                    "address_image_promise_closure"
                    if str(closure_info.get("closure_type", "") or "") == "address_image_promise"
                    else "store_recommendation_closure"
                )
            elif reason_hint and not skip_reason:
                skip_reason = reason_hint

    if not block_unresolved_address_media:
        normalized_reply = re.sub(r"\s+", "", str(reply_text or "")).lower()
        normalized_latest = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        known_store = str(reply_store or route.get("target_store", "") or session_state.get("last_target_store", "") or "")
        current_turn_action = str(session_state.get("current_turn_action", "") or "")
        conversation_stage = str(session_state.get("conversation_stage", "") or "")
        mentions_position_image = any(token in normalized_reply for token in ("位置图", "按图", "看图", "标注位置")) or any(
            token in normalized_latest for token in ("位置图", "再发", "看图", "在哪", "哪儿")
        )
        if (
            (not remote_flow_active)
            and (not is_appointment_decision)
            and known_store
            and known_store != "unknown"
            and mentions_position_image
            and (
                current_turn_action == "revisit_previous_info"
                or conversation_stage == "address_image_sent"
                or int(session_state.get("address_image_sent_count", 0) or 0) > 0
            )
        ):
            item, reason_hint = queue_address_image(
                agent,
                session_id=session_id,
                session_state=session_state,
                target_store=known_store,
                route_reason="conversation_address_revisit",
                detected_region=route.get("detected_region", "") or "",
            )
            if item:
                media_items = _upsert_media_item(agent, media_items, item)
                reasons.append("conversation_address_revisit")
            elif reason_hint and not skip_reason:
                skip_reason = reason_hint

    if block_unresolved_address_media and not skip_reason:
        skip_reason = "address_geo_pending"

    needs_contact_closure_image = bool(closure_info.get("contact_closure_hit"))
    if decision is not None and bool(getattr(decision, "force_contact_image", False)):
        needs_contact_closure_image = True
        reasons.append("decision_force_contact_image")
    if decision is not None and str(decision.reply_source or "") == "fallback":
        needs_contact_closure_image = True
        reasons.append("llm_fallback_contact")
    if agent._looks_like_direct_contact_request(normalized_text):
        needs_contact_closure_image = True
        reasons.append("direct_contact_request")
    if remote_flow_active and not remote_contact_sent_in_session and is_remote_flow_decision:
        needs_contact_closure_image = True
        reasons.append("remote_flow_session_contact")
    if remote_flow_active and remote_contact_sent_in_session and is_remote_flow_decision:
        needs_contact_closure_image = False
    if (
        not needs_contact_closure_image
        and int(session_state.get("contact_image_sent_count", 0) or 0) <= 0
        and (
            agent._looks_like_appointment_query(normalized_text)
            or str(getattr(decision, "intent", "") or "") == "appointment"
            or "预约" in re.sub(r"\s+", "", str(reply_text or ""))
        )
        and not agent._looks_like_phone_submission(normalized_text)
    ):
        needs_contact_closure_image = True
        reasons.append("appointment_contact_followup")

    allow_contact_with_address = (
        str(closure_info.get("closure_type", "") or "") == "precise_address"
        and bool(closure_info.get("contact_closure_hit"))
    )
    if needs_contact_closure_image and (
        allow_contact_with_address or not any(str(x.get("type", "") or "") == "address_image" for x in media_items)
    ):
        item, reason_hint = queue_contact_image(
            agent,
            session_id=session_id,
            text=normalized_text,
            intent="contact",
            reason="fixed_contact_closure",
            route=route,
            session_state=session_state,
            force_contact_image=True,
        )
        if item:
            media_items = _upsert_media_item(agent, media_items, item)
            if "fixed_contact_closure" not in reasons:
                reasons.append("fixed_contact_closure")
        elif reason_hint and not skip_reason:
            skip_reason = reason_hint

    if media_items:
        return MediaJudgeDecision(
            send_contact_image=any(str(x.get("type", "") or "") == "contact_image" for x in media_items),
            send_address_image=any(str(x.get("type", "") or "") == "address_image" for x in media_items),
            reason=",".join(dict.fromkeys(reasons)),
            reminder_only=False,
            skip_reason=str(skip_reason or ""),
            media_items=media_items,
        )

    if agent._should_trigger_precise_address_contact_image(
        latest_user_text=latest_user_text,
        normalized_text=normalized_text,
        reply_text=reply_text,
        intent=intent,
        route=route,
        session_state=session_state,
        conversation_history=history,
    ):
        media_items, skip_reason = plan_media_items(
            agent,
            session_id=session_id,
            text=normalized_text,
            intent="contact",
            route=route,
            route_reason="precise_address_followup",
            media_plan="contact_image",
            session_state=session_state,
            user_state=agent.memory_store.get_user_state(user_hash),
            force_contact_image=True,
        )
        return MediaJudgeDecision(
            send_contact_image=bool(media_items),
            reason="precise_address_followup",
            reminder_only=False,
            skip_reason=str(skip_reason or ""),
            media_items=media_items,
        )

    return MediaJudgeDecision(skip_reason=str(skip_reason or "no_media_rule_matched"))


def mark_media_sent(agent, session_id: str, user_name: str, media_item: Dict[str, Any], success: bool) -> None:
    if not success or not media_item:
        return

    user_hash = agent._hash_user(user_name or session_id)
    session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
    user_state = agent.memory_store.get_user_state(user_hash)
    now = datetime.now().isoformat()

    media_type = media_item.get("type", "")

    if media_type == "address_image":
        sent_count = int(session_state.get("address_image_sent_count", 0) or 0)
        session_state["address_image_sent_count"] = sent_count + 1
        stores = set(session_state.get("sent_address_stores", []) or [])
        target_store = media_item.get("target_store", "")
        sent_count_by_store = dict(session_state.get("address_image_sent_count_by_store", {}) or {})
        resend_count_by_store = dict(session_state.get("address_image_resend_count_by_store", {}) or {})
        stage_by_store = dict(session_state.get("address_delivery_stage_by_store", {}) or {})
        sent_paths_by_store = dict(session_state.get("address_image_sent_paths_by_store", {}) or {})
        if target_store:
            stores.add(target_store)
            previous_count = int(sent_count_by_store.get(target_store, 0) or 0)
            current_count = previous_count + 1
            sent_count_by_store[target_store] = current_count
            if previous_count >= 1:
                resend_count_by_store[target_store] = int(resend_count_by_store.get(target_store, 0) or 0) + 1
            stage_by_store[target_store] = "delivered_closed" if current_count >= 2 else "delivered_once"
            sent_map = session_state.get("address_image_last_sent_at_by_store", {}) or {}
            if not isinstance(sent_map, dict):
                sent_map = {}
            sent_map[target_store] = now
            session_state["address_image_last_sent_at_by_store"] = sent_map
            sent_paths = [
                str(path).strip()
                for path in (sent_paths_by_store.get(target_store, []) or [])
                if str(path).strip()
            ]
            media_path = str(media_item.get("path", "") or "").strip()
            if media_path and media_path not in sent_paths:
                sent_paths.append(media_path)
            sent_paths_by_store[target_store] = sent_paths
            session_state["address_image_sent_paths_by_store"] = sent_paths_by_store
            session_state["last_target_store"] = target_store
            session_state["current_store_context"] = target_store
            session_state["store_delivery_authority"] = target_store
            facts = dict(session_state.get("conversation_facts", {}) or {})
            facts["recommended_store"] = target_store
            session_state["conversation_facts"] = facts
            session_state["active_topic"] = "store_recommendation"
            session_state["conversation_stage"] = "address_image_sent"
        session_state["sent_address_stores"] = list(stores)
        session_state["address_image_sent_count_by_store"] = sent_count_by_store
        session_state["address_image_resend_count_by_store"] = resend_count_by_store
        session_state["address_delivery_stage_by_store"] = stage_by_store
        session_state["current_mainline"] = "business_answer"

    elif media_type == "contact_image":
        sent_count = int(session_state.get("contact_image_sent_count", 0) or 0)
        session_state["contact_image_sent_count"] = sent_count + 1
        if sent_count >= 1:
            resend_count = int(session_state.get("contact_image_resend_count", 0) or 0)
            session_state["contact_image_resend_count"] = resend_count + 1
        session_state["contact_delivery_stage"] = "delivered_closed" if (sent_count + 1) >= 3 else "delivered_once"
        session_state["contact_image_last_sent_at"] = now
        if bool(session_state.get("remote_flow_active", False)):
            session_state["remote_contact_image_sent"] = True
        sent_paths = [
            str(path).strip()
            for path in (session_state.get("contact_image_sent_paths", []) or [])
            if str(path).strip()
        ]
        media_path = str(media_item.get("path", "") or "").strip()
        if media_path and media_path not in sent_paths:
            sent_paths.append(media_path)
        session_state["contact_image_sent_paths"] = sent_paths
        session_state["contact_warmup"] = False
        session_state["last_geo_pending"] = False
        if str(session_state.get("conversation_stage", "") or "") == "appointment_ready":
            session_state["active_topic"] = "appointment"
        session_state["current_mainline"] = "business_answer"

    if media_type in REQUIRED_MEDIA_TYPES:
        agent._remove_pending_required_media(session_state, media_item)
        remove_planned_required_media(agent, session_state, media_item)
        budget = session_state.get("required_media_retry_budget", {}) or {}
        budget.pop(agent._pending_media_key(media_item), None)
        session_state["required_media_retry_budget"] = budget

    agent.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
    agent.memory_store.update_user_state(user_hash, user_state)
    agent.memory_store.save()


def enqueue_media_compensation(
    agent,
    session_id: str,
    user_name: str,
    media_item: Dict[str, Any],
    failure_code: str = "",
    failure_detail: str = "",
) -> Optional[Dict[str, Any]]:
    if not media_item:
        return None
    media_type = str(media_item.get("type", "") or "")
    if media_type not in REQUIRED_MEDIA_TYPES:
        return None

    user_hash = agent._hash_user(user_name or session_id)
    session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
    pending_items = agent._sanitize_pending_required_media(
        session_state.get("pending_required_media", []),
        session_state=session_state,
    )
    clean_item = _build_required_media_state_item(media_item)
    if not clean_item:
        return None
    clean_item["last_attempted_path"] = str(media_item.get("path", "") or "")
    pending_id = agent._pending_media_key(clean_item)
    clean_item["pending_media_id"] = pending_id
    clean_item["pending_required"] = True
    clean_item["queued_at"] = datetime.now().isoformat()

    # 按失败原因设置补偿优先级（数值越小越优先）
    compensation_priority_map = {
        "verify_timeout": 1,
        "verified_soft_timeout": 1,
        "confirm_click_failed": 1,
        "video_verify_timeout": 1,
        "unknown_media_failure": 2,
        "locate_image_button_failed": 2,
        "native_click_image_button_failed": 2,
        "missing_media_path": 3,
    }
    clean_item["_compensation_priority"] = compensation_priority_map.get(str(failure_code or ""), 2)

    pending_items = _upsert_media_item(agent, pending_items, clean_item)
    # 按补偿优先级排序队列
    pending_items.sort(key=lambda x: int(x.get("_compensation_priority", 2)))
    remove_planned_required_media(agent, session_state, clean_item)

    budget = session_state.get("required_media_retry_budget", {}) or {}
    budget[pending_id] = int(budget.get(pending_id, 0) or 0) + 1

    agent.memory_store.update_session_state(
        session_id,
        {
            "pending_required_media": pending_items,
            "pending_required_media_updated_at": datetime.now().isoformat(),
            "planned_required_media": session_state.get("planned_required_media", []),
            "planned_required_media_updated_at": session_state.get("planned_required_media_updated_at", ""),
            "last_required_media_failure_code": str(failure_code or ""),
            "last_required_media_failure_detail": str(failure_detail or ""),
            "required_media_retry_budget": budget,
        },
        user_hash=user_hash,
    )
    agent.memory_store.save()
    return clean_item


def clear_media_compensation(agent, session_id: str, user_name: str, media_item: Dict[str, Any]) -> None:
    user_hash = agent._hash_user(user_name or session_id)
    session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
    agent._remove_pending_required_media(session_state, media_item)
    remove_planned_required_media(agent, session_state, media_item)
    budget = session_state.get("required_media_retry_budget", {}) or {}
    budget.pop(agent._pending_media_key(media_item), None)
    session_state["required_media_retry_budget"] = budget
    agent.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
    agent.memory_store.save()


def plan_media_items(
    agent,
    session_id: str,
    text: str,
    intent: str,
    route: Dict[str, Any],
    route_reason: str,
    media_plan: str,
    session_state: Dict[str, Any],
    user_state: Dict[str, Any],
    force_contact_image: bool = False,
) -> Tuple[List[Dict[str, Any]], str]:
    del user_state
    items: List[Dict[str, Any]] = []
    skip_reason = ""
    target_store = route.get("target_store", "unknown")
    if media_plan == "address_image" and target_store in ("", "unknown"):
        target_store = str(session_state.get("last_target_store", "") or "unknown")
    reason = route_reason or route.get("reason", "unknown")
    detected_region = route.get("detected_region", "") or ""

    if media_plan == "address_image":
        if target_store == "unknown":
            skip_reason = "address_target_unknown"
        item, reason_hint = queue_address_image(
            agent,
            session_id=session_id,
            session_state=session_state,
            target_store=target_store,
            route_reason=reason,
            detected_region=detected_region,
        )
        if item:
            items.append(item)
        elif reason_hint:
            skip_reason = reason_hint

    if media_plan == "contact_image" and not items:
        item, reason_hint = queue_contact_image(
            agent,
            session_id=session_id,
            text=text,
            intent=intent,
            reason=reason,
            route=route,
            session_state=session_state,
            force_contact_image=force_contact_image,
        )
        if item:
            items.append(item)
        elif reason_hint and not skip_reason:
            skip_reason = reason_hint

    return items, skip_reason


def queue_address_image(
    agent,
    session_id: str,
    session_state: Dict[str, Any],
    target_store: str,
    route_reason: str,
    detected_region: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    del session_id
    if target_store == "unknown":
        return None, "address_target_unknown"
    stage_by_store = dict(session_state.get("address_delivery_stage_by_store", {}) or {})
    sent_count_by_store = dict(session_state.get("address_image_sent_count_by_store", {}) or {})
    if str(stage_by_store.get(target_store, "not_delivered") or "not_delivered") == "delivered_closed":
        return None, "address_image_closed"
    if int(sent_count_by_store.get(target_store, 0) or 0) >= 2:
        return None, "address_image_closed"
    image_path = pick_address_image(agent, target_store, session_state=session_state)
    if not image_path:
        return None, "address_image_missing"

    store = agent.knowledge_service.get_store_display(target_store)

    return (
        {
            "type": "address_image",
            "path": image_path,
            "target_store": target_store,
            "store_name": store.get("store_name", ""),
            "store_address": store.get("store_address", ""),
            "detected_region": detected_region,
            "route_reason": route_reason,
        },
        "",
    )


def queue_contact_image(
    agent,
    session_id: str,
    text: str,
    intent: str,
    reason: str,
    route: Dict[str, Any],
    session_state: Dict[str, Any],
    force_contact_image: bool = False,
) -> Tuple[Optional[Dict[str, Any]], str]:
    if bool(session_state.get("contact_captured", False)):
        return None, "contact_already_captured"
    sent_count = int(session_state.get("contact_image_sent_count", 0) or 0)
    delivery_stage = str(session_state.get("contact_delivery_stage", "not_delivered") or "not_delivered")
    explicit_resend = bool(
        agent_contact_flow.looks_like_explicit_contact_image_resend_request(text)
        or getattr(agent, "_looks_like_missing_media_request", lambda _text: False)(text)
    )
    if delivery_stage == "delivered_closed" or sent_count >= 3:
        return None, "contact_image_already_sent"
    if sent_count >= 1 and not explicit_resend and not force_contact_image:
        return None, "contact_image_resend_requires_explicit_request"
    if not agent._contact_images:
        return None, "contact_image_missing"

    if force_contact_image or intent == "contact":
        image_path = pick_contact_image_for_session(agent, session_state)
        if not image_path:
            return None, "contact_image_unique_exhausted"
        return (
            {
                "type": "contact_image",
                "path": image_path,
                "detected_region": route.get("detected_region", "") or route_region(reason, text),
                "route_reason": reason,
                "target_store": route.get("target_store", ""),
            },
            "",
        )

    return None, "contact_image_not_applicable"


def pick_contact_image_for_session(
    agent,
    session_state: Dict[str, Any],
    exclude_paths: Optional[List[str]] = None,
) -> Optional[str]:
    pool = [str(path) for path in agent._contact_images if str(path).strip()]
    if not pool:
        return None
    sent_paths = {
        str(path).strip()
        for path in (session_state.get("contact_image_sent_paths", []) or [])
        if str(path).strip()
    }
    excluded = {str(path).strip() for path in (exclude_paths or []) if str(path).strip()}
    available = [path for path in pool if path not in sent_paths and path not in excluded]
    if not available and excluded:
        available = [path for path in pool if path not in sent_paths]
    if not available:
        available = list(pool)
    return random.choice(available)


def resolve_kb_contact_trigger_type(agent, latest_user_text: str, kb_detail: Dict[str, Any]) -> str:
    del agent
    normalized_text = re.sub(r"\s+", "", (latest_user_text or ""))
    if any(keyword in normalized_text for keyword in CONTACT_TRIGGER_KEYWORDS):
        if any(keyword in normalized_text for keyword in APPOINTMENT_PRIORITY_KEYWORDS):
            return "appointment"
        return "shipping"

    tags = kb_detail.get("tags", [])
    if isinstance(tags, list):
        normalized_tags = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
        if "预约" in normalized_tags:
            return "appointment"
        if any(tag.lower() in normalized_tags for tag in CONTACT_TRIGGER_TAGS):
            return "shipping"

    kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
    if kb_intent in CONTACT_TRIGGER_INTENTS:
        return "appointment"
    return ""


def looks_like_appointment_query(agent, text: str) -> bool:
    del agent
    normalized_text = re.sub(r"\s+", "", (text or ""))
    if not normalized_text:
        return False
    return any(keyword in normalized_text for keyword in APPOINTMENT_PRIORITY_KEYWORDS)


def is_contact_image_sent_for_current_geo(agent, session_state: Dict[str, Any]) -> bool:
    del agent
    sent_count = int(session_state.get("contact_image_sent_count", 0) or 0)
    if sent_count <= 0:
        return False
    if str(session_state.get("contact_image_last_sent_at", "") or "").strip():
        return True
    sent_paths = [
        str(path).strip()
        for path in (session_state.get("contact_image_sent_paths", []) or [])
        if str(path).strip()
    ]
    return bool(sent_paths)


def has_both_images_sent(agent, session_state: Dict[str, Any]) -> bool:
    del agent
    return (
        int(session_state.get("address_image_sent_count", 0) or 0) > 0
        and int(session_state.get("contact_image_sent_count", 0) or 0) > 0
    )


def sync_media_state_from_conversation_log(
    agent,
    session_id: str,
    user_hash: str,
    session_state: Dict[str, Any],
) -> None:
    user_summary = summarize_user_media_from_logs(agent, user_id_hash=user_hash)
    session_summary = summarize_session_media_from_logs(agent, session_id=session_id)
    session_state["address_image_sent_count"] = max(
        int(session_state.get("address_image_sent_count", 0) or 0),
        int(user_summary.get("address_image_sent_count", 0) or 0),
        int(session_summary.get("address_image_sent_count", 0) or 0),
    )
    session_state["contact_image_sent_count"] = max(
        int(session_state.get("contact_image_sent_count", 0) or 0),
        int(user_summary.get("contact_image_sent_count", 0) or 0),
        int(session_summary.get("contact_image_sent_count", 0) or 0),
    )

    merged_address_last_sent = dict(session_state.get("address_image_last_sent_at_by_store", {}) or {})
    merged_address_last_sent.update(dict(user_summary.get("address_image_last_sent_at_by_store", {}) or {}))
    merged_address_last_sent.update(dict(session_summary.get("address_image_last_sent_at_by_store", {}) or {}))
    session_state["address_image_last_sent_at_by_store"] = merged_address_last_sent

    merged_paths_by_store = dict(session_state.get("address_image_sent_paths_by_store", {}) or {})
    for summary in (user_summary, session_summary):
        for store, paths in dict(summary.get("address_image_sent_paths_by_store", {}) or {}).items():
            existing_paths = [
                str(path).strip()
                for path in (merged_paths_by_store.get(store, []) or [])
                if str(path).strip()
            ]
            for path in (paths or []):
                clean_path = str(path).strip()
                if clean_path and clean_path not in existing_paths:
                    existing_paths.append(clean_path)
            merged_paths_by_store[store] = existing_paths
    session_state["address_image_sent_paths_by_store"] = merged_paths_by_store

    merged_sent_address_stores = set(session_state.get("sent_address_stores", []) or [])
    merged_sent_address_stores.update(user_summary.get("sent_address_stores", []) or [])
    merged_sent_address_stores.update(session_summary.get("sent_address_stores", []) or [])
    session_state["sent_address_stores"] = list(merged_sent_address_stores)
    session_state["address_image_sent_count_by_store"] = {
        store: len([str(path).strip() for path in (paths or []) if str(path).strip()])
        for store, paths in merged_paths_by_store.items()
    }
    session_state["address_image_resend_count_by_store"] = {
        store: max(int(count or 0) - 1, 0)
        for store, count in dict(session_state.get("address_image_sent_count_by_store", {}) or {}).items()
    }
    session_state["address_delivery_stage_by_store"] = {
        store: ("delivered_closed" if int(count or 0) >= 2 else "delivered_once" if int(count or 0) >= 1 else "not_delivered")
        for store, count in dict(session_state.get("address_image_sent_count_by_store", {}) or {}).items()
    }

    contact_last_sent = str(user_summary.get("contact_image_last_sent_at", "") or "")
    session_contact_last_sent = str(session_summary.get("contact_image_last_sent_at", "") or "")
    if session_contact_last_sent:
        contact_last_sent = session_contact_last_sent
    if contact_last_sent:
        session_state["contact_image_last_sent_at"] = contact_last_sent
    session_state["contact_image_sent_paths"] = list(
        dict.fromkeys(
            [
                *[
                    str(path).strip()
                    for path in (session_state.get("contact_image_sent_paths", []) or [])
                    if str(path).strip()
                ],
                *[
                    str(path).strip()
                    for path in (user_summary.get("contact_image_sent_paths", []) or [])
                    if str(path).strip()
                ],
                *[
                    str(path).strip()
                    for path in (session_summary.get("contact_image_sent_paths", []) or [])
                    if str(path).strip()
                ],
            ]
        )
    )
    session_state["contact_delivery_stage"] = (
        "delivered_closed"
        if int(session_state.get("contact_image_sent_count", 0) or 0) >= 3
        else "delivered_once"
        if int(session_state.get("contact_image_sent_count", 0) or 0) >= 1
        else "not_delivered"
    )

    latest_store = str(session_summary.get("last_target_store", "") or user_summary.get("last_target_store", "") or "").strip()
    if latest_store:
        session_state["last_target_store"] = latest_store
        facts = dict(session_state.get("conversation_facts", {}) or {})
        facts["recommended_store"] = latest_store
        session_state["conversation_facts"] = facts
        if max(
            int(user_summary.get("address_image_sent_count", 0) or 0),
            int(session_summary.get("address_image_sent_count", 0) or 0),
        ) > 0:
            session_state["conversation_stage"] = str(session_state.get("conversation_stage", "") or "address_image_sent")

    session_video = summarize_session_video_from_log(agent, session_id=session_id)
    session_state["session_video_armed"] = bool(session_video.get("contact_sent"))
    session_state["session_video_sent"] = bool(
        session_video.get("first_reply_video_sent") or session_video.get("contact_followup_video_sent")
    )
    session_state["session_post_contact_reply_count"] = int(session_video.get("assistant_reply_count_after_contact", 0) or 0)
    session_state["session_user_message_count_after_contact"] = int(session_video.get("user_message_count_after_contact", 0) or 0)


def sanitize_pending_required_media(
    agent,
    items: Any,
    session_state: Optional[Dict[str, Any]] = None,
    latest_planned: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    latest_address_targets = {
        str(item.get("target_store", "") or "")
        for item in (latest_planned or [])
        if isinstance(item, dict) and str(item.get("type", "")) == "address_image"
    }
    latest_has_contact = any(
        isinstance(item, dict) and str(item.get("type", "") or "") == "contact_image"
        for item in (latest_planned or [])
    )
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        media_type = str(raw.get("type", "") or "")
        if media_type not in REQUIRED_MEDIA_TYPES:
            continue
        item = copy.deepcopy(raw)
        if media_type == "address_image":
            target_store = str(item.get("target_store", "") or "")
            if latest_address_targets and target_store and target_store not in latest_address_targets:
                continue
        if media_type == "contact_image" and latest_has_contact:
            continue
        materialized = _materialize_required_media_item(
            agent,
            session_state=session_state or {},
            media_item=item,
        )
        if not materialized:
            continue
        materialized["pending_media_id"] = pending_media_key(agent, materialized)
        materialized["pending_required"] = True
        sanitized = _upsert_media_item(agent, sanitized, materialized)
    return sanitized


def _materialize_required_media_item(
    agent,
    session_state: Dict[str, Any],
    media_item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    media_type = str((media_item or {}).get("type", "") or "")
    item = _build_required_media_state_item(media_item)
    if not item:
        return None

    if media_type == "address_image":
        target_store = str(item.get("target_store", "") or "")
        if not target_store:
            return None
        exclude_paths = [
            str(item.get("last_attempted_path", "") or "").strip()
        ]
        image_path = pick_address_image(
            agent,
            target_store,
            session_state=session_state,
            exclude_paths=exclude_paths,
        )
        if not image_path:
            return None
        store = agent.knowledge_service.get_store_display(target_store)
        item["path"] = image_path
        item["store_name"] = str(item.get("store_name", "") or store.get("store_name", "") or "")
        item["store_address"] = str(item.get("store_address", "") or store.get("store_address", "") or "")
        return item

    if media_type == "contact_image":
        exclude_paths = [
            str(item.get("last_attempted_path", "") or "").strip()
        ]
        image_path = pick_contact_image_for_session(agent, session_state, exclude_paths=exclude_paths)
        if not image_path:
            return None
        item["path"] = image_path
        return item

    if media_type == "delayed_video":
        if not str(item.get("path", "") or ""):
            video_path = pick_video_media(agent)
            if not video_path:
                return None
            item["path"] = video_path
        return item
    return None


def _build_required_media_state_item(media_item: Dict[str, Any]) -> Dict[str, Any]:
    media_type = str((media_item or {}).get("type", "") or "")
    if media_type not in REQUIRED_MEDIA_TYPES:
        return {}
    item = {
        "type": media_type,
        "target_store": str((media_item or {}).get("target_store", "") or ""),
        "store_name": str((media_item or {}).get("store_name", "") or ""),
        "store_address": str((media_item or {}).get("store_address", "") or ""),
        "detected_region": str((media_item or {}).get("detected_region", "") or ""),
        "route_reason": str((media_item or {}).get("route_reason", "") or ""),
        "trigger_source": str((media_item or {}).get("trigger_source", "") or ""),
        "path": "",
        "last_attempted_path": str((media_item or {}).get("last_attempted_path", "") or ""),
    }
    if media_type == "delayed_video":
        item["path"] = str((media_item or {}).get("path", "") or "")
    return item


def _upsert_media_item(
    agent,
    items: List[Dict[str, Any]],
    media_item: Dict[str, Any],
) -> List[Dict[str, Any]]:
    media_key = pending_media_key(agent, media_item)
    updated = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if pending_media_key(agent, item) == media_key:
            continue
        updated.append(item)
    updated.append(dict(media_item))
    return updated


def remove_pending_required_media(agent, session_state: Dict[str, Any], media_item: Dict[str, Any]) -> None:
    media_key = pending_media_key(agent, media_item)
    pending_items = []
    for item in session_state.get("pending_required_media", []) or []:
        if not isinstance(item, dict):
            continue
        if pending_media_key(agent, item) == media_key:
            continue
        pending_items.append(item)
    session_state["pending_required_media"] = pending_items
    session_state["pending_required_media_updated_at"] = datetime.now().isoformat()


def remove_planned_required_media(agent, session_state: Dict[str, Any], media_item: Dict[str, Any]) -> None:
    media_key = pending_media_key(agent, media_item)
    planned_items = []
    for item in session_state.get("planned_required_media", []) or []:
        if not isinstance(item, dict):
            continue
        if pending_media_key(agent, item) == media_key:
            continue
        planned_items.append(item)
    session_state["planned_required_media"] = planned_items
    session_state["planned_required_media_updated_at"] = datetime.now().isoformat()


def pending_media_key(agent, media_item: Dict[str, Any]) -> str:
    del agent
    media_type = str((media_item or {}).get("type", "") or "")
    if media_type == "address_image":
        return f"address_image:{str((media_item or {}).get('target_store', '') or '')}"
    if media_type == "contact_image":
        return "contact_image"
    return f"{media_type}:{str((media_item or {}).get('path', '') or '')}"


def summarize_user_media_from_logs(agent, user_id_hash: str) -> Dict[str, Any]:
    summary = {
        "address_image_sent_count": 0,
        "contact_image_sent_count": 0,
        "address_image_last_sent_at_by_store": {},
        "address_image_sent_paths_by_store": {},
        "sent_address_stores": [],
        "contact_image_last_sent_at": "",
        "contact_image_sent_paths": [],
        "last_target_store": "",
    }
    if not user_id_hash:
        return summary

    address_ts_map: Dict[str, datetime] = {}
    address_sent_paths_by_store: Dict[str, List[str]] = {}
    sent_address_stores: set[str] = set()
    last_target_store = ""
    last_target_store_ts: Optional[datetime] = None
    contact_last_ts: Optional[datetime] = None
    contact_sent_paths: List[str] = []

    for log_path in agent.conversation_log_dir.glob("*.jsonl"):
        records = scan_session_media_records(agent, log_path=log_path, user_id_hash=user_id_hash)
        for rec in records:
            media_type = rec.get("type", "")
            ts = agent._parse_iso(str(rec.get("timestamp", "") or ""))
            if media_type == "address_image":
                summary["address_image_sent_count"] += 1
                target_store = str(rec.get("target_store", "") or "")
                media_path = str(rec.get("path", "") or "").strip()
                if target_store:
                    sent_address_stores.add(target_store)
                    store_paths = address_sent_paths_by_store.setdefault(target_store, [])
                    if media_path and media_path not in store_paths:
                        store_paths.append(media_path)
                    if ts and (target_store not in address_ts_map or ts > address_ts_map[target_store]):
                        address_ts_map[target_store] = ts
                    if ts and (not last_target_store_ts or ts > last_target_store_ts):
                        last_target_store = target_store
                        last_target_store_ts = ts
                    elif not ts and not last_target_store:
                        last_target_store = target_store
            elif media_type == "contact_image":
                summary["contact_image_sent_count"] += 1
                media_path = str(rec.get("path", "") or "").strip()
                if media_path and media_path not in contact_sent_paths:
                    contact_sent_paths.append(media_path)
                if ts and (not contact_last_ts or ts > contact_last_ts):
                    contact_last_ts = ts

    summary["sent_address_stores"] = sorted(sent_address_stores)
    summary["last_target_store"] = last_target_store
    summary["address_image_last_sent_at_by_store"] = {
        store: dt.isoformat() for store, dt in address_ts_map.items()
    }
    summary["address_image_sent_paths_by_store"] = address_sent_paths_by_store
    if contact_last_ts:
        summary["contact_image_last_sent_at"] = contact_last_ts.isoformat()
    summary["contact_image_sent_paths"] = contact_sent_paths
    return summary


def store_recommend_display_name(agent, target_store: str, fallback_name: str = "") -> str:
    del agent
    if target_store == "beijing_chaoyang":
        return "北京朝阳门店"
    return str(fallback_name or "门店")


def summarize_user_turns_from_logs(agent, user_id_hash: str) -> Dict[str, int]:
    summary = {
        "event_count": 0,
        "user_message_count": 0,
        "assistant_reply_count": 0,
    }
    if not user_id_hash:
        return summary

    for log_path in agent.conversation_log_dir.glob("*.jsonl"):
        try:
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                if str(record.get("user_id_hash", "") or "") != user_id_hash:
                    continue
                summary["event_count"] += 1
                event_type = str(record.get("event_type", "") or "")
                if event_type == "user_message":
                    summary["user_message_count"] += 1
                elif event_type == "assistant_reply":
                    summary["assistant_reply_count"] += 1
        except Exception:
            continue
    return summary


def is_user_first_turn_global(agent, user_id_hash: str) -> bool:
    turns = summarize_user_turns_from_logs(agent, user_id_hash=user_id_hash)
    return int(turns.get("event_count", 0) or 0) == 0


def build_first_turn_video_items(agent, session_id: str) -> List[Dict[str, Any]]:
    if str(getattr(agent, "reply_mode", "") or "") == "llm_direct":
        return []
    session_video = summarize_session_video_from_log(agent, session_id=session_id)
    if session_video.get("first_reply_video_sent"):
        return []
    video_item = build_video_media_item(agent, trigger_source="first_reply")
    if not video_item:
        return []
    video_item["first_turn_media"] = True
    return [video_item]


def populate_first_turn_media_plan(
    agent,
    session_id: str,
    user_name: str,
    decision: AgentDecision,
) -> None:
    decision.first_turn_image_items = []
    decision.first_turn_video_items = []
    decision.first_turn_text_required = bool(decision.is_first_turn_global)
    decision.first_turn_retry_policy = {}

    if not decision.is_first_turn_global:
        return

    user_hash = agent._hash_user(user_name or session_id)
    memory_store = getattr(agent, "memory_store", None)
    session_state = {}
    if memory_store is not None and hasattr(memory_store, "get_session_state"):
        session_state = memory_store.get_session_state(session_id, user_hash=user_hash)
    if callable(getattr(agent, "_should_block_unresolved_address_media", None)) and agent._should_block_unresolved_address_media(
        latest_user_text="",
        decision=decision,
        route={"reason": decision.route_reason},
        session_state=session_state,
    ):
        decision.first_turn_media_guard_applied = True
        decision.first_turn_image_items = []

    image_items = [
        dict(item)
        for item in (decision.media_items or [])
        if isinstance(item, dict) and str(item.get("type", "") or "") in ("address_image", "contact_image")
    ]
    for item in image_items:
        item["disable_compensation"] = True
        item["first_turn_media"] = True

    video_items: List[Dict[str, Any]] = []
    should_attach_first_reply_video = bool(decision.is_first_turn_global)
    if should_attach_first_reply_video:
        session_video = summarize_session_video_from_log(agent, session_id=session_id)
        if not session_video.get("first_reply_video_sent"):
            video_item = build_video_media_item(agent, trigger_source="first_reply")
            if video_item:
                video_item["first_turn_media"] = True
                video_items.append(video_item)

    decision.first_turn_image_items = image_items
    decision.first_turn_video_items = video_items
    decision.first_turn_retry_policy = {
        "image_retry_once_deferred": True,
        "video_retry_once_inline": True,
    }


def summarize_session_video_from_log(agent, session_id: str) -> Dict[str, Any]:
    summary = {
        "contact_sent": False,
        "first_reply_video_sent": False,
        "contact_followup_video_sent": False,
        "assistant_reply_count_after_contact": 0,
        "user_message_count_after_contact": 0,
    }
    lines = read_session_log_records(agent, session_id)
    if not lines:
        return summary

    latest_contact_idx = -1
    for idx, record in enumerate(lines):
        if not isinstance(record, dict):
            continue
        if str(record.get("event_type", "") or "") != "media_result":
            continue
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type", "") or "") == "contact_image" and bool(payload.get("success")):
            latest_contact_idx = idx

    if latest_contact_idx < 0:
        return summary
    summary["contact_sent"] = True

    reply_count = 0
    user_count = 0
    for idx in range(latest_contact_idx + 1, len(lines)):
        record = lines[idx]
        if not isinstance(record, dict):
            continue
        event_type = str(record.get("event_type", "") or "")
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        if event_type == "media_result":
            if str(payload.get("type", "") or "") == "delayed_video" and bool(payload.get("success")):
                trigger_source = str(payload.get("trigger_source", "") or "contact_followup")
                if trigger_source == "first_reply":
                    summary["first_reply_video_sent"] = True
                elif trigger_source == "contact_followup":
                    summary["contact_followup_video_sent"] = True
        elif event_type == "user_message":
            user_count += 1
        elif event_type == "assistant_reply":
            sent_types = payload.get("round_media_sent_types", [])
            if isinstance(sent_types, list) and "contact_image" in sent_types:
                continue
            reply_count += 1

    summary["assistant_reply_count_after_contact"] = reply_count
    summary["user_message_count_after_contact"] = user_count
    return summary


def summarize_session_media_from_logs(agent, session_id: str) -> Dict[str, Any]:
    summary = {
        "address_image_sent_count": 0,
        "contact_image_sent_count": 0,
        "address_image_last_sent_at_by_store": {},
        "address_image_sent_paths_by_store": {},
        "sent_address_stores": [],
        "contact_image_last_sent_at": "",
        "contact_image_sent_paths": [],
        "last_target_store": "",
    }
    records = scan_session_media_records_by_session(agent, session_id=session_id)
    if not records:
        return summary

    address_ts_map: Dict[str, datetime] = {}
    address_sent_paths_by_store: Dict[str, List[str]] = {}
    sent_address_stores: set[str] = set()
    last_target_store = ""
    last_target_store_ts: Optional[datetime] = None
    contact_last_ts: Optional[datetime] = None
    contact_sent_paths: List[str] = []

    for rec in records:
        media_type = rec.get("type", "")
        ts = agent._parse_iso(str(rec.get("timestamp", "") or ""))
        if media_type == "address_image":
            summary["address_image_sent_count"] += 1
            target_store = str(rec.get("target_store", "") or "")
            media_path = str(rec.get("path", "") or "").strip()
            if target_store:
                sent_address_stores.add(target_store)
                store_paths = address_sent_paths_by_store.setdefault(target_store, [])
                if media_path and media_path not in store_paths:
                    store_paths.append(media_path)
                if ts and (target_store not in address_ts_map or ts > address_ts_map[target_store]):
                    address_ts_map[target_store] = ts
                if ts and (not last_target_store_ts or ts > last_target_store_ts):
                    last_target_store = target_store
                    last_target_store_ts = ts
                elif not ts and not last_target_store:
                    last_target_store = target_store
        elif media_type == "contact_image":
            summary["contact_image_sent_count"] += 1
            media_path = str(rec.get("path", "") or "").strip()
            if media_path and media_path not in contact_sent_paths:
                contact_sent_paths.append(media_path)
            if ts and (not contact_last_ts or ts > contact_last_ts):
                contact_last_ts = ts

    summary["sent_address_stores"] = sorted(sent_address_stores)
    summary["last_target_store"] = last_target_store
    summary["address_image_last_sent_at_by_store"] = {
        store: dt.isoformat() for store, dt in address_ts_map.items()
    }
    summary["address_image_sent_paths_by_store"] = address_sent_paths_by_store
    if contact_last_ts:
        summary["contact_image_last_sent_at"] = contact_last_ts.isoformat()
    summary["contact_image_sent_paths"] = contact_sent_paths
    return summary


def build_video_media_item(agent, trigger_source: str) -> Optional[Dict[str, Any]]:
    custom_builder = getattr(agent, "_build_video_media_item", None)
    custom_func = getattr(custom_builder, "__func__", None)
    if callable(custom_builder) and custom_func is None:
        item = custom_builder(trigger_source)
        if isinstance(item, dict):
            return dict(item)
    video_path = pick_video_media(agent)
    if not video_path:
        return None
    return {
        "type": "delayed_video",
        "path": video_path,
        "trigger_source": str(trigger_source or ""),
    }


def read_session_log_records(agent, session_id: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for log_path in session_log_candidates(agent, session_id):
        try:
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                if str(record.get("session_id", "") or "") != session_id:
                    continue
                records.append(record)
        except Exception:
            continue
    return records


def scan_session_media_records(agent, log_path: Path, user_id_hash: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    pending_attempts: Dict[str, List[Dict[str, Any]]] = {
        "address_image": [],
        "contact_image": [],
        "delayed_video": [],
    }
    try:
        for raw_line in log_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            if str(record.get("user_id_hash", "") or "") != user_id_hash:
                continue
            event_type = str(record.get("event_type", "") or "")
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            if event_type == "media_attempt":
                media_type = str(payload.get("type", "") or "")
                if media_type in pending_attempts:
                    pending_attempts[media_type].append(payload)
                continue

            if event_type != "media_result":
                continue

            media_type = str(payload.get("type", "") or "")
            if media_type not in pending_attempts:
                continue
            if not bool(payload.get("success")):
                queue = pending_attempts.get(media_type, [])
                if queue:
                    queue.pop(0)
                continue

            attempt_payload = {}
            queue = pending_attempts.get(media_type, [])
            if queue:
                attempt_payload = queue.pop(0)

            path = str((attempt_payload or {}).get("path", "") or "")
            target_store = str((attempt_payload or {}).get("target_store", "") or "").strip()
            if media_type == "address_image" and not target_store:
                target_store = infer_store_from_image_path(agent, path)

            records.append(
                {
                    "type": media_type,
                    "timestamp": str(record.get("timestamp", "") or ""),
                    "path": path,
                    "target_store": target_store,
                    "store_name": str((attempt_payload or {}).get("store_name", "") or ""),
                    "store_address": str((attempt_payload or {}).get("store_address", "") or ""),
                    "detected_region": str((attempt_payload or {}).get("detected_region", "") or ""),
                    "route_reason": str((attempt_payload or {}).get("route_reason", "") or ""),
                }
            )
    except Exception:
        return records
    return records


def scan_session_media_records_by_session(agent, session_id: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    pending_attempts: Dict[str, List[Dict[str, Any]]] = {
        "address_image": [],
        "contact_image": [],
        "delayed_video": [],
    }
    for log_path in session_log_candidates(agent, session_id):
        try:
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                if str(record.get("session_id", "") or "") != session_id:
                    continue
                event_type = str(record.get("event_type", "") or "")
                payload = record.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}

                if event_type == "media_attempt":
                    media_type = str(payload.get("type", "") or "")
                    if media_type in pending_attempts:
                        pending_attempts[media_type].append(payload)
                    continue

                if event_type != "media_result":
                    continue

                media_type = str(payload.get("type", "") or "")
                if media_type not in pending_attempts:
                    continue
                if not bool(payload.get("success")):
                    queue = pending_attempts.get(media_type, [])
                    if queue:
                        queue.pop(0)
                    continue

                attempt_payload = {}
                queue = pending_attempts.get(media_type, [])
                if queue:
                    attempt_payload = queue.pop(0)

                path = str((attempt_payload or {}).get("path", "") or "")
                target_store = str((attempt_payload or {}).get("target_store", "") or "").strip()
                if media_type == "address_image" and not target_store:
                    target_store = infer_store_from_image_path(agent, path)

                records.append(
                    {
                        "type": media_type,
                        "timestamp": str(record.get("timestamp", "") or ""),
                        "path": path,
                        "target_store": target_store,
                        "store_name": str((attempt_payload or {}).get("store_name", "") or ""),
                        "store_address": str((attempt_payload or {}).get("store_address", "") or ""),
                        "detected_region": str((attempt_payload or {}).get("detected_region", "") or ""),
                        "route_reason": str((attempt_payload or {}).get("route_reason", "") or ""),
                    }
                )
        except Exception:
            continue
    return records


def session_log_file(agent, session_id: str) -> Path:
    candidates = session_log_candidates(agent, session_id)
    if candidates:
        return candidates[0]
    safe = re.sub(r"[^0-9A-Za-z_\\-]", "_", session_id or "unknown")
    root_dir = getattr(agent, "conversation_log_dir", Path("data") / "conversations")
    return root_dir / f"{safe}.jsonl"


def session_log_candidates(agent, session_id: str) -> List[Path]:
    safe = re.sub(r"[^0-9A-Za-z_\\-]", "_", session_id or "unknown")
    root_dir = getattr(agent, "conversation_log_dir", Path("data") / "conversations")
    legacy_path = root_dir / f"{safe}.jsonl"
    results: List[Path] = []
    if legacy_path.exists():
        results.append(legacy_path)

    for log_path in sorted(root_dir.glob("*.jsonl")):
        if log_path == legacy_path:
            continue
        try:
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                if str(record.get("session_id", "") or "") == session_id:
                    results.append(log_path)
                    break
        except Exception:
            continue
    return results


def infer_store_from_image_path(agent, media_path: str) -> str:
    name = Path(str(media_path or "")).name
    return infer_store_from_name(agent, name)


def infer_store_from_name(agent, name: str) -> str:
    del agent
    raw = str(name or "")
    if not raw:
        return ""
    if "北京" in raw:
        return "beijing_chaoyang"
    if "徐汇" in raw or "徐家汇" in raw:
        return "sh_xuhui"
    if "静安" in raw:
        return "sh_jingan"
    if "虹口" in raw:
        return "sh_hongkou"
    if "五角场" in raw or "杨浦" in raw:
        return "sh_wujiaochang"
    if any(k in raw for k in ("人广", "人民广场", "黄浦", "黄埔")):
        return "sh_renmin"
    return ""


def pick_address_image(
    agent,
    target_store: str,
    session_state: Optional[Dict[str, Any]] = None,
    exclude_paths: Optional[List[str]] = None,
) -> Optional[str]:
    pool = agent._address_index.get(target_store, [])
    if not pool and target_store.startswith("sh_"):
        pool = agent._address_index.get("sh_renmin", [])
    if not pool and target_store == "beijing_chaoyang":
        pool = agent._address_index.get("beijing_chaoyang", [])
    if not pool:
        return None
    sent_paths_by_store = dict((session_state or {}).get("address_image_sent_paths_by_store", {}) or {})
    sent_paths = {
        str(path).strip()
        for path in (sent_paths_by_store.get(target_store, []) or [])
        if str(path).strip()
    }
    excluded = {str(path).strip() for path in (exclude_paths or []) if str(path).strip()}
    available = [path for path in pool if path not in sent_paths and path not in excluded]
    if not available and excluded:
        available = [path for path in pool if path not in sent_paths]
    if not available:
        available = list(pool)
    return random.choice(available)


def pick_video_media(agent) -> Optional[str]:
    if agent._video_medias:
        return random.choice(agent._video_medias)
    return MATERIAL_LIBRARY_VIDEO_SENTINEL


def summarize_recent_assistant_hashes_from_logs(agent, user_id_hash: str, limit: int = 40) -> set[str]:
    if not user_id_hash:
        return set()
    entries: List[Tuple[Optional[datetime], str]] = []
    for log_path in sorted(agent.conversation_log_dir.glob("*.jsonl")):
        try:
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                if str(record.get("user_id_hash", "") or "") != user_id_hash:
                    continue
                if str(record.get("event_type", "") or "") != "assistant_reply":
                    continue
                payload = record.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                text = str(payload.get("text", "") or "").strip()
                if not text:
                    continue
                norm = agent._normalize_for_dedupe(text)
                if not norm:
                    continue
                ts = agent._parse_iso(str(record.get("timestamp", "") or ""))
                entries.append((ts, norm))
        except Exception:
            continue
    entries.sort(key=lambda item: (item[0] is None, item[0] or datetime.min))
    tail = entries[-max(1, int(limit or 1)) :]
    return {norm for _, norm in tail}


def is_media_whitelist_session(agent, session_id: str) -> bool:
    return session_id in agent._media_whitelist_sessions


def route_region(route_reason: str, text: str) -> str:
    if route_reason != "out_of_coverage":
        return ""
    m = re.search(r"([\u4e00-\u9fa5]{2,8}(?:省|市|区|县|州|盟|旗))", text or "")
    if not m:
        return ""
    candidate = m.group(1)
    tail = (text or "")[m.end():m.end() + 1]
    if candidate.endswith("区") and tail in ("别", "分"):
        return ""
    if any(token in candidate for token in ("什么区", "哪个区", "哪些区")):
        return ""
    return candidate
