"""
会话日志落盘服务
用于沉淀训练数据（JSONL）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class ConversationLogger:
    """将会话事件按 session 追加写入 JSONL。"""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def append_event(
        self,
        session_id: str,
        user_id_hash: str,
        event_type: str,
        payload: Dict[str, Any],
        user_name: str = "",
        reply_source: str = "",
        rule_id: str = "",
        model_name: str = "",
    ) -> None:
        try:
            effective_user_name = user_name or str((payload or {}).get("user_name", "") or "")
            path = self._session_file(session_id=session_id, user_name=effective_user_name)
            record = {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "user_id_hash": user_id_hash,
                "event_type": event_type,
                "reply_source": reply_source or "",
                "rule_id": rule_id or "",
                "model_name": model_name or "",
                "payload": payload or {},
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # 日志沉淀不影响主链路
            return

    def _session_file(self, session_id: str, user_name: str = "", dt: datetime | None = None) -> Path:
        safe_session = re.sub(r"[^0-9A-Za-z_\-]", "_", session_id or "unknown")
        display_name = self._sanitize_user_name(user_name)
        if not display_name:
            return self.root_dir / f"{safe_session}.jsonl"
        current_dt = dt or datetime.now()
        return self.root_dir / f"{display_name}_{current_dt.strftime('%Y-%m-%d')}.jsonl"

    def build_log_filename(self, user_name: str, dt: datetime | None = None) -> str:
        display_name = self._sanitize_user_name(user_name) or "未知用户"
        current_dt = dt or datetime.now()
        return f"{display_name}_{current_dt.strftime('%Y-%m-%d')}.jsonl"

    def _sanitize_user_name(self, user_name: str) -> str:
        text = str(user_name or "").strip()
        if not text:
            return ""
        text = re.sub(r'[\\/:*?"<>|]+', "_", text)
        text = re.sub(r"\s+", "_", text)
        text = re.sub(r"_+", "_", text).strip("._")
        return text or "未知用户"

    def get_recent_events(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取指定 session 的最近 N 条事件

        Args:
            session_id: 会话 ID
            limit: 返回事件数量限制

        Returns:
            事件列表，按时间从新到旧排序
        """
        events = []
        files = [str(path) for path in self.root_dir.glob("*.jsonl") if path.is_file()]

        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            record = json.loads(line)
                            if str(record.get("session_id", "") or "") != str(session_id or ""):
                                continue
                            events.append(record)
            except Exception:
                # 日志读取失败不影响主链路
                continue

        # 按时间戳排序，从新到旧
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return events[:limit]
