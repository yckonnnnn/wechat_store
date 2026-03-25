"""
去重检查模块

多维度去重：媒体发送、回复内容、追问轮数、时间冷却
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import hashlib


class DeduplicationChecker:
    """去重检查器"""

    def __init__(self, memory_store):
        """
        Args:
            memory_store: MemoryStore 实例
        """
        self.memory = memory_store

    def check_media_sent(
        self,
        session_id: str,
        user_hash: str,
        media_type: str,
        target_id: str = "",
    ) -> bool:
        """
        检查媒体是否已发送

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希
            media_type: 媒体类型（address_image, contact_image）
            target_id: 目标 ID（门店 ID，可选）

        Returns:
            True 表示已发送（应去重），False 表示未发送
        """
        state = self.memory.get_session_state(session_id, user_hash)

        if media_type == "address_image":
            # 检查是否已发送过地址图
            sent_count = state.get("address_image_sent_count", 0)
            if sent_count > 0:
                # 检查是否是同一门店
                last_store = state.get("last_target_store", "")
                if target_id and last_store == target_id:
                    return True
                # 不同门店，允许发送
                return False

        elif media_type == "contact_image":
            sent_count = state.get("contact_image_sent_count", 0)
            if sent_count > 0:
                return True

        return False

    def check_reply_sent(
        self,
        session_id: str,
        user_hash: str,
        content: str,
        window_seconds: int = 600,
    ) -> bool:
        """
        检查回复内容是否在时间窗口内已发送

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希
            content: 回复内容
            window_seconds: 时间窗口（秒），默认 10 分钟

        Returns:
            True 表示已发送（应去重），False 表示未发送
        """
        content_hash = hashlib.md5(content.encode()).hexdigest()

        # 使用 UserStore 存储回复哈希和时间戳（用户维度去重）
        user_state = self.memory.get_user_state(user_hash)
        recent_hashes = user_state.get("recent_reply_hashes", [])
        reply_times = user_state.get("reply_timestamps", {})

        # 清理过期记录
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        valid_hashes = []
        for h in recent_hashes:
            ts_str = reply_times.get(h, "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                if ts >= cutoff:
                    valid_hashes.append(h)

        # 检查是否重复
        is_duplicate = content_hash in valid_hashes

        # 更新记录
        if not is_duplicate:
            valid_hashes.append(content_hash)
            reply_times[content_hash] = datetime.now().isoformat()
            # 限制记录数量
            if len(valid_hashes) > 100:
                valid_hashes = valid_hashes[-100:]
            # 使用 UserStore 存储回复哈希和时间戳（用户维度去重）
            self.memory.update_user_state(
                user_hash,
                {
                    "recent_reply_hashes": valid_hashes,
                    "reply_timestamps": reply_times,
                },
            )

        return is_duplicate

    def check_followup_round(
        self,
        session_id: str,
        user_hash: str,
        question_type: str,
        max_rounds: int = 2,
    ) -> bool:
        """
        检查追问是否超过最大轮数

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希
            question_type: 问题类型（geo, price, appointment）
            max_rounds: 最大追问轮数

        Returns:
            True 表示已达到最大轮数（应停止追问），False 表示可以继续
        """
        state = self.memory.get_session_state(session_id, user_hash)

        if question_type == "geo":
            current_round = state.get("geo_followup_round", 0)
            return current_round >= max_rounds

        # 其他问题类型可扩展
        return False

    def check_time_cooldown(
        self,
        session_id: str,
        user_hash: str,
        event_type: str,
        cooldown_seconds: int = 300,
    ) -> bool:
        """
        检查是否在冷却时间内

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希
            event_type: 事件类型（contact_prompt, address_prompt）
            cooldown_seconds: 冷却时间（秒），默认 5 分钟

        Returns:
            True 表示在冷却中（应等待），False 表示可以执行
        """
        state = self.memory.get_session_state(session_id, user_hash)

        last_time_str = state.get(f"last_{event_type}_time", "")
        if not last_time_str:
            return False

        last_time = datetime.fromisoformat(last_time_str)
        cutoff = datetime.now() - timedelta(seconds=cooldown_seconds)

        return last_time >= cutoff

    def record_event(
        self,
        session_id: str,
        user_hash: str,
        event_type: str,
    ) -> None:
        """
        记录事件时间

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希
            event_type: 事件类型
        """
        self.memory.update_session_state(
            session_id,
            {f"last_{event_type}_time": datetime.now().isoformat()},
            user_hash=user_hash,
        )

    def increment_followup_round(
        self,
        session_id: str,
        user_hash: str,
        question_type: str,
    ) -> int:
        """
        增加追问轮数

        Args:
            session_id: 会话 ID
            user_hash: 用户哈希
            question_type: 问题类型

        Returns:
            当前轮数
        """
        state = self.memory.get_session_state(session_id, user_hash)

        if question_type == "geo":
            current = state.get("geo_followup_round", 0)
            new_value = current + 1
            self.memory.update_session_state(
                session_id,
                {"geo_followup_round": new_value},
                user_hash=user_hash,
            )
            return new_value

        return 0
