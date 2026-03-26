"""
会话记忆持久化存储
按用户拆分文件，避免全局共享记忆互相污染。
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


class MemoryStore:
    """跨重启记忆存储（按 user_hash 拆分文件）"""

    CURRENT_VERSION = 6
    ANONYMOUS_USER_HASH = "__anonymous__"

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.user_root = self.file_path.parent / "memory" / "users"
        self._user_cache: Dict[str, Dict[str, Any]] = {}
        self._dirty_users: set[str] = set()
        self._locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()
        self._legacy_migrated = False
        self.load()

    def load(self) -> bool:
        """初始化目录并在需要时迁移旧总文件。"""
        try:
            self.user_root.mkdir(parents=True, exist_ok=True)
            self.migrate_legacy_global_memory()
            return True
        except Exception as exc:
            print(f"[MemoryStore] 初始化失败，继续使用空记忆: {exc}")
            return False

    def save(self) -> bool:
        """只保存脏用户文件，不再全量重写。"""
        dirty_users = list(self._dirty_users)
        if not dirty_users:
            return True

        ok = True
        for user_hash in dirty_users:
            if not self._save_user_doc(user_hash):
                ok = False
        return ok

    def get_session_state(self, session_id: str, user_hash: str = "") -> Dict[str, Any]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        doc = self._get_user_doc(normalized_user_hash)
        sessions = doc.setdefault("sessions", {})
        if session_id not in sessions:
            sessions[session_id] = self._default_session_state(session_id, normalized_user_hash)
            self._mark_dirty(normalized_user_hash)
        state = sessions[session_id]
        self._fill_session_defaults(state, session_id=session_id, user_hash=normalized_user_hash)
        return state

    def get_existing_session_state(self, session_id: str, user_hash: str = "") -> Optional[Dict[str, Any]]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        doc = self._get_user_doc(normalized_user_hash)
        state = (doc.get("sessions", {}) or {}).get(session_id)
        if not isinstance(state, dict):
            return None
        self._fill_session_defaults(state, session_id=session_id, user_hash=normalized_user_hash)
        return state

    def update_session_state(self, session_id: str, updates: Dict[str, Any], user_hash: str = "") -> Dict[str, Any]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        state = self.get_session_state(session_id, user_hash=normalized_user_hash)
        state.update(updates or {})
        state["updated_at"] = datetime.now().isoformat()
        self._mark_dirty(normalized_user_hash)
        return state

    def update_session_field(self, session_id: str, user_hash: str, key: str, value: Any) -> Dict[str, Any]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        state = self.get_session_state(session_id, user_hash=normalized_user_hash)
        state[key] = value
        state["updated_at"] = datetime.now().isoformat()
        self._mark_dirty(normalized_user_hash)
        return state

    def get_user_state(self, user_hash: str) -> Dict[str, Any]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        doc = self._get_user_doc(normalized_user_hash)
        state = doc.setdefault("user_state", self._default_user_state(normalized_user_hash))
        self._fill_user_defaults(state, user_hash=normalized_user_hash)
        return state

    def update_user_state(self, user_hash: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        state = self.get_user_state(normalized_user_hash)
        state.update(updates or {})
        state["updated_at"] = datetime.now().isoformat()
        self._mark_dirty(normalized_user_hash)
        return state

    def prune_expired(self, ttl_days: int = 30) -> None:
        """逐用户文件清理过期 session，空用户文件直接删除。"""
        cutoff = datetime.now() - timedelta(days=max(1, ttl_days))

        for path in self._iter_user_files():
            user_hash = path.stem
            doc = self._get_user_doc(user_hash)
            sessions = dict(doc.get("sessions", {}) or {})
            changed = False
            for session_id in list(sessions.keys()):
                updated_at = str((sessions.get(session_id) or {}).get("updated_at", "") or "")
                dt = self._parse_datetime(updated_at)
                if dt and dt < cutoff:
                    sessions.pop(session_id, None)
                    changed = True
            if changed:
                doc["sessions"] = sessions
                self._mark_dirty(user_hash)
                self._save_user_doc(user_hash)
            if not sessions and not self._has_meaningful_user_state(doc.get("user_state", {})):
                self._delete_user_file(user_hash)

    def migrate_legacy_global_memory(self) -> bool:
        """
        将旧的总文件结构拆分为按用户文件存储。

        兼容规则：
        - 新目录已存在有效用户文件时直接跳过
        - 旧文件不存在时直接跳过
        - 迁移失败不覆盖旧文件
        """
        if self._legacy_migrated:
            return True

        self.user_root.mkdir(parents=True, exist_ok=True)
        if any(self.user_root.glob("*.json")):
            self._legacy_migrated = True
            return True
        if not self.file_path.exists():
            self._legacy_migrated = True
            return True

        try:
            loaded = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[MemoryStore] 旧记忆文件读取失败，跳过迁移: {exc}")
            return False

        if not isinstance(loaded, dict) or ("sessions" not in loaded and "users" not in loaded):
            self._legacy_migrated = True
            return True

        sessions = dict(loaded.get("sessions", {}) or {})
        users = dict(loaded.get("users", {}) or {})
        grouped: Dict[str, Dict[str, Any]] = {}

        for session_id, raw_state in sessions.items():
            if not isinstance(raw_state, dict):
                continue
            user_hash = self._normalize_user_hash(raw_state.get("user_hash", ""))
            doc = grouped.setdefault(user_hash, self._default_user_doc(user_hash))
            state = dict(raw_state)
            self._fill_session_defaults(state, session_id=session_id, user_hash=user_hash)
            doc["sessions"][session_id] = state

        for user_hash, raw_user_state in users.items():
            normalized_user_hash = self._normalize_user_hash(user_hash)
            doc = grouped.setdefault(normalized_user_hash, self._default_user_doc(normalized_user_hash))
            state = dict(raw_user_state) if isinstance(raw_user_state, dict) else {}
            self._fill_user_defaults(state, user_hash=normalized_user_hash)
            doc["user_state"] = state

        try:
            for user_hash, doc in grouped.items():
                self._user_cache[user_hash] = doc
                self._dirty_users.add(user_hash)
                if not self._save_user_doc(user_hash):
                    raise RuntimeError(f"save_failed:{user_hash}")
            backup = self.file_path.with_name(
                f"{self.file_path.stem}.legacy_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{self.file_path.suffix}"
            )
            self.file_path.replace(backup)
            print(f"[MemoryStore] 旧记忆迁移完成: {self.file_path} -> {backup}")
            self._legacy_migrated = True
            return True
        except Exception as exc:
            print(f"[MemoryStore] 旧记忆迁移失败，保留原文件: {exc}")
            return False

    def get_stats(self) -> Dict[str, int]:
        total_users = 0
        total_sessions = 0
        for path in self._iter_user_files():
            total_users += 1
            user_hash = path.stem
            doc = self._get_user_doc(user_hash)
            total_sessions += len(dict(doc.get("sessions", {}) or {}))
        return {
            "total_users": total_users,
            "total_sessions": total_sessions,
        }

    def _default_user_doc(self, user_hash: str) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        return {
            "version": self.CURRENT_VERSION,
            "updated_at": now,
            "user_state": self._default_user_state(user_hash),
            "sessions": {},
        }

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
            "address_image_sent_paths_by_store": {},
            "address_image_sent_count_by_store": {},
            "address_image_resend_count_by_store": {},
            "address_delivery_stage_by_store": {},
            "contact_image_sent_count": 0,
            "contact_image_resend_count": 0,
            "contact_image_last_sent_at": "",
            "contact_image_sent_paths": [],
            "contact_delivery_stage": "not_delivered",
            "contact_captured": False,
            "geo_followup_round": 0,
            "geo_choice_offered": False,
            "last_geo_pending": False,
            "last_detected_region": "",
            "last_target_store": "",
            "current_store_context": "",
            "store_delivery_authority": "",
            "store_candidates": [],
            "last_geo_route_reason": "unknown",
            "last_geo_updated_at": "",
            "strong_intent_after_both_count": 0,
            "purchase_both_first_hint_sent": False,
            "session_video_armed": False,
            "session_video_sent": False,
            "session_post_contact_reply_count": 0,
            "pending_required_media": [],
            "pending_required_media_updated_at": "",
            "planned_required_media": [],
            "planned_required_media_updated_at": "",
            "last_required_media_failure_code": "",
            "last_required_media_failure_detail": "",
            "required_media_retry_budget": {},
            "last_route_reason": "unknown",
            "last_intent": "general",
            "last_reply_goal": "解答",
            "current_mainline": "business_answer",
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
            "reply_timestamps": {},
        }

    def _get_user_doc(self, user_hash: str) -> Dict[str, Any]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        with self._global_lock:
            cached = self._user_cache.get(normalized_user_hash)
            if cached is not None:
                return cached

            path = self._user_file_path(normalized_user_hash)
            if not path.exists():
                doc = self._default_user_doc(normalized_user_hash)
                self._user_cache[normalized_user_hash] = doc
                return doc

            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("invalid_user_doc")
            except Exception as exc:
                print(f"[MemoryStore] 用户记忆损坏，回退为空状态: user={normalized_user_hash}, error={exc}")
                doc = self._default_user_doc(normalized_user_hash)
                self._user_cache[normalized_user_hash] = doc
                self._dirty_users.add(normalized_user_hash)
                return doc

            doc = self._ensure_user_doc_schema(loaded, normalized_user_hash)
            self._user_cache[normalized_user_hash] = doc
            return doc

    def _ensure_user_doc_schema(self, doc: Dict[str, Any], user_hash: str) -> Dict[str, Any]:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        result = dict(doc or {})
        result["version"] = max(int(result.get("version", 1) or 1), self.CURRENT_VERSION)
        result.setdefault("updated_at", "")
        user_state = dict(result.get("user_state", {}) or {})
        self._fill_user_defaults(user_state, user_hash=normalized_user_hash)
        result["user_state"] = user_state
        sessions = dict(result.get("sessions", {}) or {})
        normalized_sessions: Dict[str, Dict[str, Any]] = {}
        for session_id, raw_state in sessions.items():
            state = dict(raw_state or {})
            self._fill_session_defaults(state, session_id=session_id, user_hash=normalized_user_hash)
            normalized_sessions[session_id] = state
        result["sessions"] = normalized_sessions
        return result

    def _save_user_doc(self, user_hash: str) -> bool:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        doc = self._get_user_doc(normalized_user_hash)
        path = self._user_file_path(normalized_user_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._locks.setdefault(normalized_user_hash, threading.RLock())

        with lock:
            doc["updated_at"] = datetime.now().isoformat()
            payload = json.dumps(doc, ensure_ascii=False, indent=2)
            try:
                with self._file_mutex(path):
                    tmp_path = path.with_name(f"{path.name}.tmp")
                    tmp_path.write_text(payload, encoding="utf-8")
                    os.replace(tmp_path, path)
                self._dirty_users.discard(normalized_user_hash)
                print(f"[MemoryStore] 已保存用户记忆: {path}")
                return True
            except Exception as exc:
                print(f"[MemoryStore] 保存用户记忆失败: user={normalized_user_hash}, error={exc}")
                return False

    def _delete_user_file(self, user_hash: str) -> None:
        normalized_user_hash = self._normalize_user_hash(user_hash)
        path = self._user_file_path(normalized_user_hash)
        try:
            self._user_cache.pop(normalized_user_hash, None)
            self._dirty_users.discard(normalized_user_hash)
            if path.exists():
                path.unlink()
            print(f"[MemoryStore] 已删除空用户记忆: {path}")
        except Exception as exc:
            print(f"[MemoryStore] 删除空用户记忆失败: user={normalized_user_hash}, error={exc}")

    @contextmanager
    def _file_mutex(self, path: Path, timeout_seconds: float = 5.0):
        lock_path = path.with_suffix(path.suffix + ".lock")
        start = time.time()
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                if time.time() - start >= timeout_seconds:
                    raise TimeoutError(f"lock_wait_timeout:{lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                if lock_path.exists():
                    lock_path.unlink()
            except Exception:
                pass

    def _iter_user_files(self):
        if not self.user_root.exists():
            return []
        return sorted(path for path in self.user_root.glob("*.json") if path.is_file())

    def _user_file_path(self, user_hash: str) -> Path:
        return self.user_root / f"{self._normalize_user_hash(user_hash)}.json"

    def _normalize_user_hash(self, user_hash: Any) -> str:
        value = str(user_hash or "").strip()
        return value or self.ANONYMOUS_USER_HASH

    def _mark_dirty(self, user_hash: str) -> None:
        self._dirty_users.add(self._normalize_user_hash(user_hash))

    def _parse_datetime(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _has_meaningful_user_state(self, state: Dict[str, Any]) -> bool:
        if not isinstance(state, dict):
            return False
        return bool(
            state.get("video_armed")
            or state.get("video_sent")
            or int(state.get("post_contact_reply_count", 0) or 0) > 0
            or list(state.get("recent_reply_hashes", []) or [])
        )

    def _fill_session_defaults(self, state: Dict[str, Any], session_id: str, user_hash: str = "") -> None:
        now = datetime.now().isoformat()
        normalized_user_hash = self._normalize_user_hash(user_hash)
        state.setdefault("session_id", session_id)
        state.setdefault("user_hash", normalized_user_hash)
        state.setdefault("session_fingerprint", "")
        state.setdefault("first_seen_at", now)
        state.setdefault("updated_at", now)
        state.setdefault("address_prompt_count", 0)
        state.setdefault("sent_address_stores", [])
        state.setdefault("address_image_sent_count", 0)
        state.setdefault("address_image_last_sent_at_by_store", {})
        state.setdefault("address_image_sent_paths_by_store", {})
        state.setdefault("address_image_sent_count_by_store", {})
        state.setdefault("address_image_resend_count_by_store", {})
        state.setdefault("address_delivery_stage_by_store", {})
        state.setdefault("contact_image_sent_count", 0)
        state.setdefault("contact_image_resend_count", 0)
        state.setdefault("contact_image_last_sent_at", "")
        state.setdefault("contact_image_sent_paths", [])
        state.setdefault("contact_delivery_stage", "not_delivered")
        state.setdefault("contact_captured", False)
        state.setdefault("geo_followup_round", 0)
        state.setdefault("geo_choice_offered", False)
        state.setdefault("last_geo_pending", False)
        state.setdefault("last_detected_region", "")
        state.setdefault("last_target_store", "")
        state.setdefault("current_store_context", "")
        state.setdefault("store_delivery_authority", "")
        state.setdefault("store_candidates", [])
        state.setdefault("last_geo_route_reason", "unknown")
        state.setdefault("last_geo_updated_at", "")
        state.setdefault("strong_intent_after_both_count", 0)
        state.setdefault("purchase_both_first_hint_sent", False)
        state.setdefault("session_video_armed", False)
        state.setdefault("session_video_sent", False)
        state.setdefault("session_post_contact_reply_count", 0)
        state.setdefault("pending_required_media", [])
        state.setdefault("pending_required_media_updated_at", "")
        state.setdefault("planned_required_media", [])
        state.setdefault("planned_required_media_updated_at", "")
        state.setdefault("last_required_media_failure_code", "")
        state.setdefault("last_required_media_failure_detail", "")
        state.setdefault("required_media_retry_budget", {})
        state.setdefault("last_route_reason", "unknown")
        state.setdefault("last_intent", "general")
        state.setdefault("last_reply_goal", "解答")
        state.setdefault("current_mainline", "business_answer")
        if not isinstance(state.get("sent_address_stores"), list):
            state["sent_address_stores"] = []
        if not isinstance(state.get("address_image_last_sent_at_by_store"), dict):
            state["address_image_last_sent_at_by_store"] = {}
        if not isinstance(state.get("address_image_sent_paths_by_store"), dict):
            state["address_image_sent_paths_by_store"] = {}
        if not isinstance(state.get("address_image_sent_count_by_store"), dict):
            state["address_image_sent_count_by_store"] = {}
        if not isinstance(state.get("address_image_resend_count_by_store"), dict):
            state["address_image_resend_count_by_store"] = {}
        if not isinstance(state.get("address_delivery_stage_by_store"), dict):
            state["address_delivery_stage_by_store"] = {}
        if not isinstance(state.get("contact_image_sent_paths"), list):
            state["contact_image_sent_paths"] = []
        if not isinstance(state.get("pending_required_media"), list):
            state["pending_required_media"] = []
        if not isinstance(state.get("planned_required_media"), list):
            state["planned_required_media"] = []
        if not isinstance(state.get("required_media_retry_budget"), dict):
            state["required_media_retry_budget"] = {}
        if not isinstance(state.get("store_candidates"), list):
            state["store_candidates"] = []
        self._migrate_delivery_state(state)

    def _migrate_delivery_state(self, state: Dict[str, Any]) -> None:
        contact_sent_count = max(0, int(state.get("contact_image_sent_count", 0) or 0))
        state["contact_image_sent_count"] = contact_sent_count
        contact_resend_count = max(0, int(state.get("contact_image_resend_count", 0) or 0))
        state["contact_image_resend_count"] = min(contact_resend_count, max(contact_sent_count - 1, 0))
        contact_stage = str(state.get("contact_delivery_stage", "") or "").strip()
        inferred_contact_stage = (
            "delivered_closed"
            if contact_sent_count >= 3
            else "delivered_once"
            if contact_sent_count >= 1
            else "not_delivered"
        )
        if contact_stage not in {"not_delivered", "delivered_once", "delivered_closed"}:
            contact_stage = inferred_contact_stage
        elif inferred_contact_stage == "delivered_closed":
            contact_stage = "delivered_closed"
        elif inferred_contact_stage == "delivered_once" and contact_stage == "not_delivered":
            contact_stage = "delivered_once"
        state["contact_delivery_stage"] = contact_stage

        sent_paths_by_store = dict(state.get("address_image_sent_paths_by_store", {}) or {})
        sent_count_by_store = dict(state.get("address_image_sent_count_by_store", {}) or {})
        resend_count_by_store = dict(state.get("address_image_resend_count_by_store", {}) or {})
        delivery_stage_by_store = dict(state.get("address_delivery_stage_by_store", {}) or {})
        sent_stores = {
            str(store).strip()
            for store in (state.get("sent_address_stores", []) or [])
            if str(store).strip()
        }
        sent_stores.update(str(store).strip() for store in sent_paths_by_store.keys() if str(store).strip())
        sent_stores.update(str(store).strip() for store in sent_count_by_store.keys() if str(store).strip())

        total_address_count = 0
        for store in sorted(sent_stores):
            path_count = len([str(path).strip() for path in (sent_paths_by_store.get(store, []) or []) if str(path).strip()])
            count = max(path_count, int(sent_count_by_store.get(store, 0) or 0))
            if count < 0:
                count = 0
            sent_count_by_store[store] = count
            resend_count = int(resend_count_by_store.get(store, 0) or 0)
            resend_count_by_store[store] = min(max(resend_count, 0), max(count - 1, 0))
            stage = str(delivery_stage_by_store.get(store, "") or "").strip()
            inferred_stage = "delivered_closed" if count >= 2 else "delivered_once" if count >= 1 else "not_delivered"
            if stage not in {"not_delivered", "delivered_once", "delivered_closed"}:
                stage = inferred_stage
            elif inferred_stage == "delivered_closed":
                stage = "delivered_closed"
            elif inferred_stage == "delivered_once" and stage == "not_delivered":
                stage = "delivered_once"
            delivery_stage_by_store[store] = stage
            if count > 0:
                total_address_count += count

        state["sent_address_stores"] = sorted(sent_stores)
        state["address_image_sent_count_by_store"] = sent_count_by_store
        state["address_image_resend_count_by_store"] = resend_count_by_store
        state["address_delivery_stage_by_store"] = delivery_stage_by_store
        if total_address_count > int(state.get("address_image_sent_count", 0) or 0):
            state["address_image_sent_count"] = total_address_count

    def _fill_user_defaults(self, state: Dict[str, Any], user_hash: str) -> None:
        now = datetime.now().isoformat()
        normalized_user_hash = self._normalize_user_hash(user_hash)
        state.setdefault("user_hash", normalized_user_hash)
        state.setdefault("first_seen_at", now)
        state.setdefault("updated_at", now)
        state.setdefault("video_armed", False)
        state.setdefault("video_sent", False)
        state.setdefault("post_contact_reply_count", 0)
        state.setdefault("recent_reply_hashes", [])
        state.setdefault("reply_timestamps", {})
        if not isinstance(state.get("recent_reply_hashes"), list):
            state["recent_reply_hashes"] = []
        if not isinstance(state.get("reply_timestamps"), dict):
            state["reply_timestamps"] = {}
