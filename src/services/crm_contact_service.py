"""
CRM 联系方式提取与状态管理服务。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?(1[3-9]\d{9})(?!\d)")
WECHAT_WITH_PREFIX_PATTERN = re.compile(
    r"(?:微信号?|vx|wx)\s*(?:[:：是为=]\s*|\s+)([A-Za-z][A-Za-z0-9_-]{5,19})(?![A-Za-z0-9_-])",
    flags=re.IGNORECASE,
)


@dataclass
class CRMContactRecord:
    record_key: str
    user_name: str
    contact_type: str
    contact_value: str
    contact_display: str
    session_id: str
    first_seen_at: str
    last_seen_at: str
    followed_up: bool = False


class CRMContactService:
    """从对话 JSONL 中提取 CRM 联系方式并维护跟进状态。"""

    def __init__(self, conversation_dir: Path, followup_file: Path):
        self.conversation_dir = conversation_dir
        self.followup_file = followup_file
        self._status_map = self._load_status_map()

    def refresh(self) -> List[CRMContactRecord]:
        return self.load_records()

    def load_records(self) -> List[CRMContactRecord]:
        records: Dict[str, CRMContactRecord] = {}

        if not self.conversation_dir.exists():
            return []

        for log_path in sorted(self.conversation_dir.glob("*.jsonl")):
            self._consume_log_file(log_path, records)

        for record in records.values():
            record.followed_up = bool(self._status_map.get(record.record_key, False))

        return sorted(records.values(), key=self._record_sort_key, reverse=True)

    def set_followup(self, record_key: str, followed_up: bool) -> None:
        self._status_map[str(record_key)] = bool(followed_up)
        self._save_status_map()

    def toggle_followup(self, record_key: str) -> bool:
        new_value = not bool(self._status_map.get(record_key, False))
        self._status_map[str(record_key)] = new_value
        self._save_status_map()
        return new_value

    def _consume_log_file(self, log_path: Path, records: Dict[str, CRMContactRecord]) -> None:
        try:
            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    self._consume_log_line(line=line, records=records)
        except Exception:
            return

    def _consume_log_line(self, line: str, records: Dict[str, CRMContactRecord]) -> None:
        raw = line.strip()
        if not raw:
            return
        try:
            record = json.loads(raw)
        except Exception:
            return

        if str(record.get("event_type", "") or "") != "user_message":
            return

        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            return

        text = str(payload.get("text", "") or "").strip()
        if not text:
            return

        session_id = str(record.get("session_id", "") or "").strip() or "unknown_session"
        user_name = str(payload.get("user_name", "") or "").strip() or session_id
        ts = str(record.get("timestamp", "") or "").strip()

        contacts = self._extract_contacts(text)
        for contact_type, contact_value in contacts:
            record_key = self._build_record_key(user_name, contact_type, contact_value)
            contact_display = f"手机号：{contact_value}" if contact_type == "phone" else f"微信：{contact_value}"
            current = records.get(record_key)
            if current is None:
                records[record_key] = CRMContactRecord(
                    record_key=record_key,
                    user_name=user_name,
                    contact_type=contact_type,
                    contact_value=contact_value,
                    contact_display=contact_display,
                    session_id=session_id,
                    first_seen_at=ts,
                    last_seen_at=ts,
                    followed_up=bool(self._status_map.get(record_key, False)),
                )
                continue

            if self._is_earlier(ts, current.first_seen_at):
                current.first_seen_at = ts
            if self._is_later(ts, current.last_seen_at):
                current.last_seen_at = ts
            if not current.session_id and session_id:
                current.session_id = session_id

    def _extract_contacts(self, text: str) -> List[Tuple[str, str]]:
        hits: List[Tuple[str, str]] = []
        seen = set()

        for match in PHONE_PATTERN.finditer(text):
            normalized = match.group(1)
            key = ("phone", normalized)
            if key in seen:
                continue
            seen.add(key)
            hits.append(key)

        for match in WECHAT_WITH_PREFIX_PATTERN.finditer(text):
            normalized = match.group(1)
            key = ("wechat", normalized)
            if key in seen:
                continue
            seen.add(key)
            hits.append(key)

        return hits

    def _build_record_key(self, user_name: str, contact_type: str, contact_value: str) -> str:
        raw = f"{user_name}|{contact_type}|{contact_value}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:20]

    def _record_sort_key(self, record: CRMContactRecord):
        return (self._parse_ts(record.last_seen_at), record.user_name, record.contact_type, record.contact_value)

    def _load_status_map(self) -> Dict[str, bool]:
        if not self.followup_file.exists():
            return {}
        try:
            with self.followup_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            status_map = data.get("status_map", {})
            if not isinstance(status_map, dict):
                return {}
            return {str(k): bool(v) for k, v in status_map.items()}
        except Exception:
            return {}

    def _save_status_map(self) -> None:
        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "status_map": self._status_map,
        }
        self.followup_file.parent.mkdir(parents=True, exist_ok=True)
        with self.followup_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _is_later(self, left: str, right: str) -> bool:
        return self._parse_ts(left) > self._parse_ts(right)

    def _is_earlier(self, left: str, right: str) -> bool:
        return self._parse_ts(left) < self._parse_ts(right)

    def _parse_ts(self, value: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            return datetime.min
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except Exception:
            return datetime.min
