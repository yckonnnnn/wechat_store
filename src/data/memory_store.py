"""
会话记忆持久化存储
用于跨重启保存客服 Agent 的会话上下文与媒体发送状态。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


class MemoryStore:
    """跨重启记忆存储"""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._data: Dict[str, Any] = {
            "version": 4,
            "updated_at": "",
            "sessions": {},
            "users": {},
        }
        self.load()

    def load(self) -> bool:
        """加载记忆文件"""
        try:
            if self.file_path.exists():
                loaded = json.loads(self.file_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data["version"] = loaded.get("version", 1)
                    self._data["updated_at"] = loaded.get("updated_at", "")
                    self._data["sessions"] = loaded.get("sessions", {}) or {}
                    self._data["users"] = loaded.get("users", {}) or {}
            self._ensure_schema()
            return True
        except Exception:
            self._data = {
                "version": 4,
                "updated_at": "",
                "sessions": {},
                "users": {},
            }
            return False

    def save(self) -> bool:
        """保存记忆文件"""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self._data["updated_at"] = datetime.now().isoformat()
            self.file_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

    def _default_session_state(self, session_id: str, user_hash: str = "") -> Dict[str, Any]:
        now = datetime.now().isoformat()
        return {
            "session_id": session_id,
            "user_hash": user_hash,
            "session_fingerprint": "",
            "first_seen_at": now,
            "updated_at": now,
            "address_prompt_count": 0,
            "sent_address_stores": [],
            "address_image_sent_count": 0,
            "address_image_last_sent_at_by_store": {},
            "contact_image_sent_count": 0,
            "contact_image_last_sent_at": "",
            "contact_warmup": False,
            "geo_followup_round": 0,
            "geo_choice_offered": False,
            "last_geo_pending": False,
            "last_detected_region": "",
            "last_target_store": "",
            "last_geo_route_reason": "unknown",
            "last_geo_updated_at": "",
            "strong_intent_after_both_count": 0,
            "purchase_both_first_hint_sent": False,
            "session_video_armed": False,
            "session_video_sent": False,
            "session_post_contact_reply_count": 0,
            "pending_required_media": [],
            "pending_required_media_updated_at": "",
            "last_required_media_failure_code": "",
            "last_required_media_failure_detail": "",
            "required_media_retry_budget": {},
            "last_route_reason": "unknown",
            "last_intent": "general",
            "last_reply_goal": "解答",
        }

    def _default_user_state(self, user_hash: str) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        return {
            "user_hash": user_hash,
            "first_seen_at": now,
            "updated_at": now,
            "video_armed": False,
            "video_sent": False,
            "post_contact_reply_count": 0,
            "recent_reply_hashes": [],
        }

    def get_session_state(self, session_id: str, user_hash: str = "") -> Dict[str, Any]:
        sessions = self._data.setdefault("sessions", {})
        if session_id not in sessions:
            sessions[session_id] = self._default_session_state(session_id, user_hash)
        state = sessions[session_id]
        self._fill_session_defaults(state, session_id=session_id, user_hash=user_hash)
        if user_hash and not state.get("user_hash"):
            state["user_hash"] = user_hash
            state["updated_at"] = datetime.now().isoformat()
        return state

    def get_existing_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        sessions = self._data.setdefault("sessions", {})
        state = sessions.get(session_id)
        if not isinstance(state, dict):
            return None
        self._fill_session_defaults(state, session_id=session_id, user_hash=state.get("user_hash", ""))
        return state

    def update_session_state(self, session_id: str, updates: Dict[str, Any], user_hash: str = "") -> Dict[str, Any]:
        state = self.get_session_state(session_id, user_hash=user_hash)
        state.update(updates or {})
        state["updated_at"] = datetime.now().isoformat()
        return state

    def get_user_state(self, user_hash: str) -> Dict[str, Any]:
        users = self._data.setdefault("users", {})
        if user_hash not in users:
            users[user_hash] = self._default_user_state(user_hash)
        state = users[user_hash]
        self._fill_user_defaults(state, user_hash=user_hash)
        return state

    def update_user_state(self, user_hash: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        state = self.get_user_state(user_hash)
        state.update(updates or {})
        state["updated_at"] = datetime.now().isoformat()
        return state

    def prune_expired(self, ttl_days: int = 30) -> None:
        """清理超过 ttl_days 的会话/用户记录"""
        cutoff = datetime.now() - timedelta(days=max(1, ttl_days))

        sessions = self._data.setdefault("sessions", {})
        session_keys = list(sessions.keys())
        for key in session_keys:
            updated_at = sessions[key].get("updated_at", "")
            dt = self._parse_datetime(updated_at)
            if dt and dt < cutoff:
                sessions.pop(key, None)

        users = self._data.setdefault("users", {})
        user_keys = list(users.keys())
        for key in user_keys:
            updated_at = users[key].get("updated_at", "")
            dt = self._parse_datetime(updated_at)
            if dt and dt < cutoff:
                users.pop(key, None)

    def _parse_datetime(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _ensure_schema(self) -> None:
        self._data["version"] = max(int(self._data.get("version", 1) or 1), 4)
        sessions = self._data.setdefault("sessions", {})
        users = self._data.setdefault("users", {})
        for session_id, state in list(sessions.items()):
            if not isinstance(state, dict):
                sessions[session_id] = self._default_session_state(session_id)
                continue
            self._fill_session_defaults(state, session_id=session_id, user_hash=state.get("user_hash", ""))
        for user_hash, state in list(users.items()):
            if not isinstance(state, dict):
                users[user_hash] = self._default_user_state(user_hash)
                continue
            self._fill_user_defaults(state, user_hash=user_hash)

    def _fill_session_defaults(self, state: Dict[str, Any], session_id: str, user_hash: str = "") -> None:
        now = datetime.now().isoformat()
        state.setdefault("session_id", session_id)
        if user_hash:
            state.setdefault("user_hash", user_hash)
        else:
            state.setdefault("user_hash", "")
        state.setdefault("session_fingerprint", "")
        state.setdefault("first_seen_at", now)
        state.setdefault("updated_at", now)
        state.setdefault("address_prompt_count", 0)
        state.setdefault("sent_address_stores", [])
        state.setdefault("address_image_sent_count", 0)
        state.setdefault("address_image_last_sent_at_by_store", {})
        state.setdefault("contact_image_sent_count", 0)
        state.setdefault("contact_image_last_sent_at", "")
        state.setdefault("contact_warmup", False)
        state.setdefault("geo_followup_round", 0)
        state.setdefault("geo_choice_offered", False)
        state.setdefault("last_geo_pending", False)
        state.setdefault("last_detected_region", "")
        state.setdefault("last_target_store", "")
        state.setdefault("last_geo_route_reason", "unknown")
        state.setdefault("last_geo_updated_at", "")
        state.setdefault("strong_intent_after_both_count", 0)
        state.setdefault("purchase_both_first_hint_sent", False)
        state.setdefault("session_video_armed", False)
        state.setdefault("session_video_sent", False)
        state.setdefault("session_post_contact_reply_count", 0)
        state.setdefault("pending_required_media", [])
        state.setdefault("pending_required_media_updated_at", "")
        state.setdefault("last_required_media_failure_code", "")
        state.setdefault("last_required_media_failure_detail", "")
        state.setdefault("required_media_retry_budget", {})
        state.setdefault("last_route_reason", "unknown")
        state.setdefault("last_intent", "general")
        state.setdefault("last_reply_goal", "解答")
        if not isinstance(state.get("sent_address_stores"), list):
            state["sent_address_stores"] = []
        if not isinstance(state.get("address_image_last_sent_at_by_store"), dict):
            state["address_image_last_sent_at_by_store"] = {}
        if not isinstance(state.get("pending_required_media"), list):
            state["pending_required_media"] = []
        if not isinstance(state.get("required_media_retry_budget"), dict):
            state["required_media_retry_budget"] = {}

    def _fill_user_defaults(self, state: Dict[str, Any], user_hash: str) -> None:
        now = datetime.now().isoformat()
        state.setdefault("user_hash", user_hash)
        state.setdefault("first_seen_at", now)
        state.setdefault("updated_at", now)
        state.setdefault("video_armed", False)
        state.setdefault("video_sent", False)
        state.setdefault("post_contact_reply_count", 0)
        state.setdefault("recent_reply_hashes", [])
