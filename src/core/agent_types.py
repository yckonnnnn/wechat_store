from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


@dataclass
class AgentDecision:
    reply_text: str
    intent: str
    route_reason: str
    reply_goal: str
    media_plan: str
    media_items: List[Dict[str, Any]] = field(default_factory=list)
    reply_source: str = "rule"
    rule_id: str = ""
    rule_applied: bool = False
    llm_model: str = ""
    llm_fallback_reason: str = ""
    geo_context_source: str = ""
    media_skip_reason: str = ""
    both_images_sent_state: bool = False
    kb_match_score: float = 0.0
    kb_match_question: str = ""
    kb_match_mode: str = ""
    kb_item_id: str = ""
    kb_variant_total: int = 0
    kb_variant_selected_index: int = -1
    kb_variant_fallback_llm: bool = False
    kb_confident: bool = False
    kb_blocked_by_polite_guard: bool = False
    kb_polite_guard_reason: str = ""
    is_first_turn_global: bool = False
    first_turn_media_guard_applied: bool = False
    first_turn_image_items: List[Dict[str, Any]] = field(default_factory=list)
    first_turn_video_items: List[Dict[str, Any]] = field(default_factory=list)
    first_turn_text_required: bool = False
    first_turn_retry_policy: Dict[str, Any] = field(default_factory=dict)
    kb_repeat_rewritten: bool = False
    purchase_both_first_hint_sent: bool = False
    video_trigger_user_count: int = 0
    force_contact_image: bool = False
    kb_contact_trigger_type: str = ""
    reply_mode: str = "legacy"
    standard_reply_hit: bool = False
    standard_reply_question: str = ""
    standard_reply_confidence: str = ""
    standard_reply_intent: str = ""
    brand_knowledge_used: bool = False
    prompt_build_ms: int = 0
    llm_request_ms: int = 0
    llm_total_ms: int = 0
    llm_attempt_count: int = 0
    llm_message_count: int = 0
    system_prompt_chars: int = 0
    reply_closure_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaJudgeDecision:
    send_contact_image: bool = False
    send_address_image: bool = False
    send_delayed_video: bool = False
    reason: str = ""
    reminder_only: bool = False
    skip_reason: str = ""
    media_items: List[Dict[str, Any]] = field(default_factory=list)
