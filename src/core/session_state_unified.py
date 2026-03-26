"""
统一会话状态管理模块

所有状态读取都通过 UnifiedSessionState.get_state() 获取，
确保各模块读取到一致、最新的状态。

状态优先级：Logger 最新事件 > MemoryStore > SessionManager
"""

from typing import Any, Dict, List
from datetime import datetime


class UnifiedSessionState:
    """统一会话状态管理"""

    def __init__(self, memory_store, session_manager, conversation_logger):
        """
        Args:
            memory_store: MemoryStore 实例
            session_manager: SessionManager 实例
            conversation_logger: ConversationLogger 实例
        """
        self.memory = memory_store
        self.session = session_manager
        self.logger = conversation_logger

    def get_state(self, session_id: str, user_hash: str) -> Dict[str, Any]:
        """
        获取统一会话状态

        优先级：Logger 最新事件 > MemoryStore > SessionManager

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希

        Returns:
            统一状态字典，包含所有已确认的事实和状态
        """
        # 1. 读取 MemoryStore
        memory_state = self.memory.get_session_state(session_id, user_hash)

        # 2. 读取 SessionManager
        session_obj = self.session.get_session(session_id) if self.session is not None else None
        session_state = session_obj.context if session_obj else {}

        # 3. 读取 ConversationLogger（最近 20 条事件）
        logger_events = self.logger.get_recent_events(session_id, limit=20)
        logger_state = self._extract_state_from_logger(logger_events)

        # 4. 按优先级合并状态
        merged_state = {
            **session_state,      # 优先级最低
            **memory_state,       # 优先级中
            **logger_state,       # 优先级最高
            "_merged_at": datetime.now().isoformat(),
            "_source_session_id": session_id,
            "_source_user_hash": user_hash,
        }
        self._hydrate_media_flags(merged_state)

        return merged_state

    def _extract_state_from_logger(self, events: List[Dict]) -> Dict[str, Any]:
        """
        从日志事件中提取状态

        从新到旧遍历，提取最新的状态信息

        Args:
            events: 日志事件列表

        Returns:
            从日志中提取的状态字典
        """
        state = {}

        for event in events:
            event_type = event.get("event_type")
            payload = event.get("payload", {})

            # 媒体发送事件
            if event_type == "media_sent":
                media_type = payload.get("media_type")
                if media_type == "address_image":
                    if "last_target_store" not in state:
                        state["last_target_store"] = payload.get("target_store")
                    state["address_image_sent"] = True
                    state["address_image_sent_at"] = payload.get("sent_at")

                elif media_type == "contact_image":
                    state["contact_image_sent"] = True
                    state["contact_image_sent_at"] = payload.get("sent_at")

            # 助手回复事件
            elif event_type == "assistant_reply":
                del payload

            # 用户消息事件（用于推断）
            elif event_type == "user_message":
                text = payload.get("text", "")
                if "北京" in text or "朝阳" in text:
                    state.setdefault("inferred_city", "北京")
                elif "上海" in text:
                    state.setdefault("inferred_city", "上海")

        return state

    def _hydrate_media_flags(self, state: Dict[str, Any]) -> None:
        """根据持久化计数补全布尔状态，避免 prompt 和规则误判。"""
        if int(state.get("address_image_sent_count", 0) or 0) > 0:
            state["address_image_sent"] = True
        else:
            state.setdefault("address_image_sent", False)

        if int(state.get("contact_image_sent_count", 0) or 0) > 0:
            state["contact_image_sent"] = True
        else:
            state.setdefault("contact_image_sent", False)
        state.setdefault("contact_captured", False)
        state.setdefault("contact_image_resend_count", 0)

    def get_confirmed_facts(self, session_id: str, user_hash: str) -> Dict[str, Any]:
        """
        获取已确认的事实（用于注入 LLM prompt）

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希

        Returns:
            已确认事实字典
        """
        state = self.get_state(session_id, user_hash)

        return {
            "city_confirmed": state.get("conversation_facts", {}).get("city", "未知"),
            "store_confirmed": state.get("last_target_store", "未知"),
            "address_image_sent": bool(
                state.get("address_image_sent", False)
                or int(state.get("address_image_sent_count", 0) or 0) > 0
            ),
            "contact_image_sent": bool(
                state.get("contact_image_sent", False)
                or int(state.get("contact_image_sent_count", 0) or 0) > 0
            ),
            "contact_captured": bool(state.get("contact_captured", False)),
            "contact_image_resend_count": int(state.get("contact_image_resend_count", 0) or 0),
            "geo_followup_round": state.get("geo_followup_round", 0),
            "geo_followup_exhausted": state.get("geo_followup_exhausted", False),
        }
