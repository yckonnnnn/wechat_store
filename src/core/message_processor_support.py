from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Protocol


MediaMessage = Dict[str, Any]
UnreadHint = Optional[Dict[str, str]]

MEDIA_PLACEHOLDER_TEXTS = {"[图片]", "[视频]", "[表情]"}
MEDIA_PREVIEW_TYPES = {"image", "video", "emoji"}
MEDIA_SYNTHETIC_TEXT_BY_TYPE = {
    "image": "[图片]",
    "video": "[视频]",
}
MEDIA_LOG_TEXT_BY_TYPE = {
    "[图片]": "发送了一张图片",
    "[视频]": "发送了一个视频",
    "[表情]": "发送了一个表情",
}
MEDIA_FAILURE_STEP_MAP = {
    "locate_image_button": "locate_image_button_failed",
    "native_click_image_button": "native_click_image_button_failed",
    "confirm_click": "confirm_click_failed",
    "confirm_click_after_enter": "confirm_click_after_enter_failed",
    "verify_timeout": "verify_timeout",
    "verified_soft_timeout": "verified_soft_timeout",
}


class _SessionStoreProtocol(Protocol):
    def get_existing_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Read an existing session snapshot if the store has one."""


def parse_js_payload(payload: Any) -> Dict[str, Any]:
    """Return a dict payload when JS bridge data is already structured or JSON encoded."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def latest_user_text(messages: List[MediaMessage]) -> str:
    """Return the last visible user message when the tail message is from the user."""
    if not messages:
        return ""
    if not messages[-1].get("is_user", False):
        return ""
    return str(messages[-1].get("text") or "").strip()


def maybe_append_unread_hint_message(
    messages: List[MediaMessage],
    unread_hint: UnreadHint,
) -> tuple[List[MediaMessage], Optional[str]]:
    """Append a synthetic media marker when the unread badge only exposes image/video."""
    hint = unread_hint or {}
    preview_type = str(hint.get("preview_type", "") or "").strip().lower()
    if preview_type not in {"image", "video"}:
        return messages, None
    if messages and messages[-1].get("is_user", False):
        return messages, None

    synthetic = {
        "text": MEDIA_SYNTHETIC_TEXT_BY_TYPE[preview_type],
        "message_type": preview_type,
        "is_user": True,
        "is_kf": False,
        "source": "unread_preview",
    }
    return [*messages, synthetic], f"🧩 使用未读预览补全最后一条用户消息: {synthetic['text']}"


def restrict_media_placeholders_to_unread_context(
    messages: List[MediaMessage],
    unread_hint: UnreadHint,
) -> List[MediaMessage]:
    """Hide placeholder media messages unless the unread hint already confirms media content."""
    hint = unread_hint or {}
    preview_type = str(hint.get("preview_type", "") or "").strip().lower()
    if preview_type in MEDIA_PREVIEW_TYPES:
        return list(messages or [])

    filtered: List[MediaMessage] = []
    for item in list(messages or []):
        if not isinstance(item, dict):
            filtered.append(item)
            continue

        message_type = str(item.get("message_type", "") or "").strip().lower()
        text = str(item.get("text", "") or "").strip()
        if message_type in MEDIA_PREVIEW_TYPES:
            continue
        if text in MEDIA_PLACEHOLDER_TEXTS:
            continue
        filtered.append(item)
    return filtered


def format_unread_preview_hint(hint: Dict[str, str]) -> str:
    """Render a short human-readable summary for unread preview labels."""
    preview_type = str(hint.get("preview_type", "") or "").strip().lower()
    mapping = {
        "image": "图片",
        "video": "视频",
        "emoji": "表情",
    }
    if preview_type in mapping:
        return mapping[preview_type]
    preview_text = str(hint.get("preview_text", "") or "").strip()
    return preview_text or "未知"


def build_message_marker(
    user_name: str,
    latest_user_text_value: str,
    messages: List[MediaMessage],
    unread_hint: UnreadHint = None,
) -> str:
    """Build the dedupe marker used to prevent reprocessing the same conversation tail."""
    media_marker = build_media_message_marker(
        user_name=user_name,
        latest_user_text_value=latest_user_text_value,
        unread_hint=unread_hint,
    )
    if media_marker:
        return media_marker
    user_count = len([message for message in messages if message.get("is_user")])
    raw = f"{user_name}|{latest_user_text_value}|{user_count}"
    return hash_id(raw)


def build_media_message_marker(
    user_name: str,
    latest_user_text_value: str,
    unread_hint: UnreadHint = None,
) -> str:
    """Build a media-specific marker so image/video unread items remain stable across retries."""
    normalized = str(latest_user_text_value or "").strip()
    if normalized not in {"[图片]", "[视频]"}:
        return ""

    hint = unread_hint or {}
    preview_type = str(hint.get("preview_type", "") or "").strip().lower()
    if preview_type not in {"image", "video"}:
        return ""

    session_text = str(hint.get("session_text", "") or "").strip()
    preview_text = str(hint.get("preview_text", "") or "").strip()
    badge_text = str(hint.get("badge_text", "") or "").strip()
    raw = f"media|{user_name}|{preview_type}|{preview_text}|{session_text}|{badge_text}"
    return hash_id(raw)


def is_duplicate_marker(
    marker: str,
    latest_user_text_value: str,
    *,
    last_processed_marker: str,
    recent_processed_media_markers: List[str],
) -> bool:
    """Check whether the current marker has already been handled."""
    normalized = str(latest_user_text_value or "").strip()
    if normalized in {"[图片]", "[视频]"}:
        return marker in recent_processed_media_markers
    return marker == last_processed_marker


def remember_processed_marker(
    marker: str,
    latest_user_text_value: str,
    *,
    last_processed_marker: str,
    recent_processed_media_markers: List[str],
) -> tuple[str, List[str]]:
    """Update marker state while keeping the media retry window bounded."""
    normalized = str(latest_user_text_value or "").strip()
    if normalized in {"[图片]", "[视频]"}:
        if not marker:
            return last_processed_marker, list(recent_processed_media_markers)
        updated = list(recent_processed_media_markers)
        updated.append(marker)
        if len(updated) > 10:
            updated = updated[-10:]
        return last_processed_marker, updated
    return marker, list(recent_processed_media_markers)


def convert_history(messages: List[MediaMessage]) -> List[Dict[str, str]]:
    """Convert the latest conversation slice into the role/content format used by the agent."""
    history: List[Dict[str, str]] = []
    source = messages[:-1] if messages and messages[-1].get("is_user", False) else messages
    for message in source:
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        role = "user" if message.get("is_user") else "assistant"
        history.append({"role": role, "content": text})
    return history


def hash_id(text: str) -> str:
    """Create the short stable hash used by session IDs and dedupe markers."""
    return hashlib.md5((text or "").encode("utf-8", errors="ignore")).hexdigest()[:10]


def build_session_id(
    memory_store: _SessionStoreProtocol,
    user_name: str,
    chat_session_key: str,
    chat_session_fingerprint: str = "",
) -> str:
    """Generate the stable session key used by the processor."""
    key = str(chat_session_key or "").strip()
    if key:
        return f"chat_{hash_id(key)}"

    user_key = f"user_{hash_id(user_name)}"
    fingerprint = str(chat_session_fingerprint or "").strip()
    if not fingerprint:
        return user_key

    existing = memory_store.get_existing_session_state(user_key)
    existing_fp = (existing or {}).get("session_fingerprint", "") if isinstance(existing, dict) else ""
    if not existing_fp or existing_fp == fingerprint:
        return user_key
    return f"{user_key}_{hash_id(fingerprint)[:6]}"


def build_user_hash(user_name: str, session_id: str) -> str:
    """Generate the user hash stored in conversation logs."""
    base = str(user_name or "").strip() or session_id
    return hash_id(base)


def format_log_message_text(message: Dict[str, Any]) -> str:
    """Normalize media placeholders into log-friendly Chinese descriptions."""
    text = str(message.get("text") or "").strip()
    message_type = str(message.get("message_type") or "").strip().lower()
    if text == "[图片]" or message_type == "image":
        return MEDIA_LOG_TEXT_BY_TYPE["[图片]"]
    if text == "[视频]" or message_type == "video":
        return MEDIA_LOG_TEXT_BY_TYPE["[视频]"]
    if text == "[表情]" or message_type == "emoji":
        return MEDIA_LOG_TEXT_BY_TYPE["[表情]"]
    return text


def media_event_name(media_type: str, stage: str) -> str:
    """Build the media telemetry event name used by conversation logging."""
    alias = "contact_image" if media_type == "contact_image" else "address_image" if media_type == "address_image" else media_type
    return f"{alias}_send_{stage}"


def pending_media_id(item: Dict[str, Any]) -> str:
    """Return the stable media identifier used by retry and compensation flows."""
    media_type = str(item.get("type", "") or "")
    if media_type == "address_image":
        return f"address_image:{str(item.get('target_store', '') or '')}"
    if media_type == "contact_image":
        return "contact_image"
    return f"{media_type}:{str(item.get('path', '') or '')}"


def extract_failure_code(result: Any) -> str:
    """Translate browser failure payloads into a stable retry classification."""
    if isinstance(result, dict):
        code = str(result.get("failure_code", "") or "").strip()
        if code:
            return code
        step = str(result.get("step", "") or "").strip()
        return MEDIA_FAILURE_STEP_MAP.get(step, step or "unknown_media_failure")
    if isinstance(result, str) and result.strip():
        return "unknown_media_failure"
    return ""


def extract_failure_detail(result: Any) -> str:
    """Extract the human-readable failure detail shown in logs."""
    if isinstance(result, dict):
        return str(result.get("error") or result.get("detail") or result.get("warning") or "")
    if isinstance(result, str):
        return result
    return ""


class MessageProcessorSupport:
    """Lightweight wrapper around the module helpers for ergonomic dependency injection."""

    def __init__(self, memory_store: _SessionStoreProtocol):
        self._memory_store = memory_store

    parse_js_payload = staticmethod(parse_js_payload)
    latest_user_text = staticmethod(latest_user_text)
    maybe_append_unread_hint_message = staticmethod(maybe_append_unread_hint_message)
    restrict_media_placeholders_to_unread_context = staticmethod(restrict_media_placeholders_to_unread_context)
    format_unread_preview_hint = staticmethod(format_unread_preview_hint)
    build_message_marker = staticmethod(build_message_marker)
    build_media_message_marker = staticmethod(build_media_message_marker)
    is_duplicate_marker = staticmethod(is_duplicate_marker)
    remember_processed_marker = staticmethod(remember_processed_marker)
    convert_history = staticmethod(convert_history)
    hash_id = staticmethod(hash_id)
    format_log_message_text = staticmethod(format_log_message_text)
    media_event_name = staticmethod(media_event_name)
    pending_media_id = staticmethod(pending_media_id)
    extract_failure_code = staticmethod(extract_failure_code)
    extract_failure_detail = staticmethod(extract_failure_detail)

    def build_session_id(
        self,
        user_name: str,
        chat_session_key: str,
        chat_session_fingerprint: str = "",
    ) -> str:
        return build_session_id(
            self._memory_store,
            user_name=user_name,
            chat_session_key=chat_session_key,
            chat_session_fingerprint=chat_session_fingerprint,
        )

    def build_user_hash(self, user_name: str, session_id: str) -> str:
        return build_user_hash(user_name=user_name, session_id=session_id)


__all__ = [
    "MessageProcessorSupport",
    "build_message_marker",
    "build_media_message_marker",
    "build_session_id",
    "build_user_hash",
    "convert_history",
    "extract_failure_code",
    "extract_failure_detail",
    "format_log_message_text",
    "format_unread_preview_hint",
    "hash_id",
    "is_duplicate_marker",
    "latest_user_text",
    "maybe_append_unread_hint_message",
    "media_event_name",
    "parse_js_payload",
    "pending_media_id",
    "remember_processed_marker",
    "restrict_media_placeholders_to_unread_context",
]
