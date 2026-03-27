from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.core.agent_types import AgentDecision


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def looks_like_explicit_contact_image_resend_request(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    explicit_patterns = (
        "联系方式再发一下",
        "联系方式再给我一下",
        "联系方式再发一次",
        "再发一次联系方式",
        "再发一下联系方式",
        "联系方式图呢",
        "联系图呢",
        "刚才没看到联系方式",
        "没看到联系方式图",
        "没看到联系图",
        "怎么加",
        "如何加",
        "怎么联系",
        "如何联系",
    )
    if any(pattern in normalized for pattern in explicit_patterns):
        return True
    return bool(
        ("再发" in normalized or "重发" in normalized or "重新发" in normalized or "没看到" in normalized or "没收到" in normalized)
        and any(token in normalized for token in ("联系", "联系方式", "微信", "电话", "图"))
    )


def looks_like_human_check(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(
        pattern in normalized
        for pattern in (
            "你是机器人",
            "你是个机器人",
            "是不是机器人",
            "机器人吧",
            "究竟是不是人工",
            "有活人吗",
            "是不是人工",
            "是真人吗",
            "人工吗",
        )
    )


def looks_like_repetition_frustration(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(
        pattern in normalized
        for pattern in (
            "总说重复的话",
            "反复说",
            "反反复复",
            "总重复",
            "你怎么总重复",
            "我好好的跟你说话",
            "跟你沟通又不理我",
            "什么意思",
            "听懂我的话吗",
            "没听懂",
            "我没听懂",
            "你让我怎么留方式",
            "你总说那张图",
            "一步一步的给教我",
            "太讨厌了",
            "不回答",
            "又不回答",
            "好好说话",
        )
    )


def looks_like_store_recommendation_challenge(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    patterns = (
        "你是不是让我去",
        "你是不是非让我去",
        "是不是让我去",
        "按我要求选",
        "按照我的要求选",
        "还是直接让我去",
        "还是你确定让我",
        "你到底是在按我要求选还是硬推",
        "你是给我选一个好的分店还是直接让我去",
        "硬推",
        "我主要想问",
    )
    return any(pattern in normalized for pattern in patterns)


def looks_like_store_preference_statement(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    preference_patterns = (
        "位置远点",
        "位置远一点",
        "远点儿",
        "远一点",
        "远也没关系",
        "远点也没关系",
        "我主要看设计师",
        "主要想找",
        "做事认真",
        "做的漂亮",
        "样品都差不多",
    )
    return any(pattern in normalized for pattern in preference_patterns)


def sanitize_contact_push_reply(
    agent: Any,
    latest_user_text: str,
    reply_text: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    session_state = session_state if isinstance(session_state, dict) else {}
    reply = str(reply_text or "").strip()
    if not reply:
        picker = getattr(agent, "_pick_fixed_reply", None)
        if callable(picker):
            return picker(
                session_state=session_state,
                category="contact_fact_fallback",
                replies=getattr(agent, "CONTACT_FACT_FALLBACK_POOL", ()) or (),
                fallback="姐姐，我把这轮重点直接跟您说清楚。",
            )
        return "姐姐，我把这轮重点直接跟您说清楚。"
    normalized_reply = _normalize_text(reply)
    risky_reply_tokens = set(getattr(agent, "_contact_compliance_block_keywords", ()) or ()) | {
        "加您",
        "加你",
        "加好友",
        "留个方式",
        "具体沟通",
        "主动跟您介绍",
        "我来加您",
    }
    if not any(keyword.lower() in normalized_reply for keyword in risky_reply_tokens):
        return reply

    if looks_like_human_check(latest_user_text) or looks_like_repetition_frustration(latest_user_text):
        return "姐姐，刚刚是我没说清楚，我直接把您这轮的问题说清楚。"

    if agent._looks_like_direct_contact_request(latest_user_text):
        if bool(session_state.get("contact_captured", False)):
            return "姐姐，电话我这边已经收到了，不用重复发，您有别的问题我直接接着说。"
        return "姐姐，联系方式图我这边已经发过了，您按图里的方式联系就可以。"

    if bool(session_state.get("contact_captured", False)):
        return "姐姐，电话我这边已经收到了，您这轮想确认什么我直接接着说。"
    picker = getattr(agent, "_pick_fixed_reply", None)
    if callable(picker):
        return picker(
            session_state=session_state,
            category="contact_fact_fallback",
            replies=getattr(agent, "CONTACT_FACT_FALLBACK_POOL", ()) or (),
            fallback="姐姐，我按您这轮真正想确认的问题继续说。",
        )
    return "姐姐，我按您这轮真正想确认的问题继续说。"


def looks_like_contact_added_confirmation(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    patterns = (
        "刚才加你了",
        "刚刚加你了",
        "已经加你了",
        "加你了",
        "加你微信了",
        "加你好友了",
        "加上你了",
        "加上了",
    )
    return any(pattern in normalized for pattern in patterns)


def looks_like_contact_already_captured(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    patterns = (
        "我早给了你电话的呀",
        "我早给你电话了",
        "留了呀",
        "留了啊",
        "我都留了",
        "电话号码没看到吗",
        "电话没看到吗",
        "不是留电话给你了吗",
        "电话号码都留给你了",
        "你究竟是要微信还是要电话号码呀",
        "你究竟是要微信还是电话",
        "还是要微信啊",
        "还是要电话啊",
        "留了两次电话",
        "留过电话了",
        "留过两次电话",
        "已经留过电话了",
        "已经留电话了",
        "留了电话了",
        "刚才留过电话",
        "我都留两次电话了",
        "我都留电话了",
    )
    return any(pattern in normalized for pattern in patterns)


def persist_contact_capture_state(
    agent: Any,
    session_id: str,
    user_hash: str,
    session_state: Dict[str, Any],
    decision: AgentDecision,
) -> None:
    agent.memory_store.update_session_state(
        session_id,
        {
            "contact_captured": True,
            "remote_contact_captured": True,
            "current_mainline": "business_answer",
            "last_intent": decision.intent,
            "last_reply_goal": decision.reply_goal,
            "last_route_reason": decision.route_reason,
            "last_answer_text_normalized": agent._normalize_for_dedupe(decision.reply_text),
            "session_runtime_turn_count": int(session_state.get("session_runtime_turn_count", 0) or 0) + 1,
        },
        user_hash=user_hash,
    )
    agent.memory_store.save()


def build_contact_progress_ack_decision(
    agent: Any,
    text: str,
    session_state: Dict[str, Any],
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Optional[AgentDecision]:
    history = conversation_history or []
    has_contact_context = (
        bool(session_state.get("contact_captured", False))
        or int(session_state.get("contact_image_sent_count", 0) or 0) > 0
        or int(session_state.get("session_post_contact_reply_count", 0) or 0) > 0
        or any(agent._looks_like_phone_submission(str(item.get("content", "") or "")) for item in history if item.get("role") == "user")
        or any("稍后加您好友" in str(item.get("content", "") or "") for item in history if item.get("role") == "assistant")
    )
    if looks_like_contact_added_confirmation(text) and has_contact_context:
        reply_text = agent.CONTACT_ALREADY_ADDED_REPLY if hasattr(agent, "CONTACT_ALREADY_ADDED_REPLY") else "好的姐姐，我这边看到了，咱们就按刚才的方式接着聊，我来给您详细介绍❤️"
        picker = getattr(agent, "_pick_fixed_reply", None)
        if callable(picker):
            reply_text = picker(
                session_state=session_state,
                category="contact_already_added",
                replies=getattr(agent, "CONTACT_ALREADY_ADDED_REPLY_POOL", ()) or (),
                fallback=reply_text,
            )
        return AgentDecision(
            reply_text=reply_text,
            intent="contact",
            route_reason="contact_already_added",
            reply_goal="承接联系方式",
            media_plan="none",
            reply_source="rule",
            rule_id="CONTACT_ALREADY_ADDED",
            rule_applied=True,
            reply_mode=agent.reply_mode,
        )
    if looks_like_contact_already_captured(text) and has_contact_context:
        reply_text = agent.CONTACT_ALREADY_CAPTURED_REPLY if hasattr(agent, "CONTACT_ALREADY_CAPTURED_REPLY") else "收到啦姐姐，您之前留的方式我这边已经记下了，不用重复发，我会尽快联系您详细介绍❤️"
        picker = getattr(agent, "_pick_fixed_reply", None)
        if callable(picker):
            reply_text = picker(
                session_state=session_state,
                category="contact_already_captured",
                replies=getattr(agent, "CONTACT_ALREADY_CAPTURED_REPLY_POOL", ()) or (),
                fallback=reply_text,
            )
        return AgentDecision(
            reply_text=reply_text,
            intent="contact",
            route_reason="contact_already_captured",
            reply_goal="承接联系方式",
            media_plan="none",
            reply_source="rule",
            rule_id="CONTACT_ALREADY_CAPTURED",
            rule_applied=True,
            reply_mode=agent.reply_mode,
        )
    return None
