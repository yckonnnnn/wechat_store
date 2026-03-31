"""
消息处理器
单一编排链路：未读检测 -> 点击进入 -> 抓取聊天记录 -> Agent 决策 -> 发送文字/媒体。
"""

from __future__ import annotations

import json
import inspect
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QCoreApplication, QObject, Signal, QTimer, QThread

from .message_processor_media import MediaSendCoordinator, MediaSendHooks
from .message_processor_support import MessageProcessorSupport
from .private_cs_agent import AgentDecision, CustomerServiceAgent
from .session_manager import SessionManager
from ..services.browser_service import BrowserService
from ..services.conversation_logger import ConversationLogger
from ..services.address_interceptor import AddressInterceptor, AddressInterceptResult
from ..utils.emoji_helper import add_random_emoji


class MessageProcessor(QObject):
    """消息编排器"""

    _GRAB_CHAT_AFTER_CLICK_DELAY_MS = 3000
    _FIRST_TURN_VIDEO_CONTINUE_DELAY_MS = 3000
    _MEDIA_SEND_AFTER_TEXT_DELAY_MS = 900
    _VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 1200
    _CURRENT_CHAT_PROBE_AFTER_NO_UNREAD = True
    _STALE_FOLLOWUP_AFTER_SECONDS = 60
    _STALE_FOLLOWUP_GRAB_DELAY_MS = 800
    _STALE_FOLLOWUP_RETRY_COOLDOWN_SECONDS = 300
    _STALE_FOLLOWUP_TEXT = "姐姐，记得请添加我好友哦，我会发详细定位还有乘车路线以及预约/价格方面事项给到您~❤️"
    _FIRST_TURN_AUTO_REPLY_TEXT = "因咨询较多，我是智能助手小艾，请添加真人客服一对一详细为您解答！"
    _FIRST_TURN_VIDEO_NOTICE_TEXT = _FIRST_TURN_AUTO_REPLY_TEXT

    status_changed = Signal(str)
    log_message = Signal(str)
    log_event = Signal(dict)
    message_received = Signal(dict)
    reply_sent = Signal(str, str)
    error_occurred = Signal(str)
    decision_ready = Signal(dict)

    def __init__(self, browser_service: BrowserService, session_manager: SessionManager, agent: CustomerServiceAgent):
        super().__init__()
        self.browser = browser_service
        self.sessions = session_manager
        self.agent = agent
        self.conversation_logger = ConversationLogger(Path("data") / "conversations")
        if hasattr(self.agent, "conversation_logger"):
            self.agent.conversation_logger = self.conversation_logger
        self._support = MessageProcessorSupport(self.agent.memory_store)

        self._running = False
        self._ai_enabled = False
        self._remote_control_enabled = True
        self._remote_control_users: set[str] = set()
        self._poll_interval_ms = 4000
        self._page_ready = False
        self._poll_inflight = False
        self._processing_reply = False
        self._decision_worker: Optional[_DecisionWorker] = None

        self._last_processed_marker = ""
        self._recent_processed_media_markers: List[str] = []
        self._pending_send: Optional[Dict[str, Any]] = None
        self._pending_unread_hint: Optional[Dict[str, str]] = None
        self._pending_stale_followup: Optional[Dict[str, str]] = None
        self._last_stale_followup_status = ""
        self._stale_followup_skip_until: Dict[str, datetime] = {}
        self._active_session_context: Optional[Dict[str, str]] = None

        # 门店名称 → 地址图片文件名关键词映射（用于从文件名中匹配）
        self._store_address_keyword_map = {
            "静安店": "静安",
            "人民广场店": "人广",
            "虹口店": "虹口",
            "五角场店": "五角场",
            "徐汇店": "徐汇",
            "北京店": "北京",
        }

        # 拦截器目标门店 → 地址图片索引 key 映射
        self._interceptor_store_to_index_key = {
            "静安店": "sh_jingan",
            "人民广场店": "sh_renmin",
            "虹口店": "sh_hongkou",
            "五角场店": "sh_wujiaochang",
            "徐汇店": "sh_xuhui",
            "北京店": "beijing_chaoyang",
        }

        # 联系方式图片触发器：已触发过的 session_id 集合（进程内去重，每个会话只发一次）
        self._contact_trigger_sent_sessions: set[str] = set()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_cycle)
        self._address_interceptor = AddressInterceptor()
        self._media_delivery = MediaSendCoordinator(
            MediaSendHooks(
                send_image=self.browser.send_image,
                schedule=self._schedule_media_callback,
                emit_log=self._emit_log,
                emit_media_ui_log=self._emit_media_ui_log,
                append_training_event=self._append_training_event,
                append_media_delivery_event=self._append_media_delivery_event,
                mark_media_sent=getattr(
                    self.agent,
                    "mark_media_sent",
                    lambda session_id, user_name, media_item, success: None,
                ),
                enqueue_media_compensation=getattr(
                    self.agent,
                    "enqueue_media_compensation",
                    lambda session_id, user_name, media_item, failure_code="", failure_detail="": None,
                ),
                build_user_hash=self._build_user_hash,
                media_event_name=self._media_event_name,
                pending_media_id=self._pending_media_id,
                extract_failure_code=self._extract_failure_code,
                extract_failure_detail=self._extract_failure_detail,
                should_retry_media_send=self._should_retry_media_send,
                reset_cycle=self._reset_cycle,
                send_video_from_material_library=getattr(self.browser, "send_video_from_material_library", None),
                clear_message_input=getattr(self.browser, "clear_message_input", None),
                mark_active_session=self._mark_active_session,
            )
        )

        self.browser.page_loaded.connect(self._on_page_loaded)
        self.browser.url_changed.connect(self._on_url_changed)
        if hasattr(self.browser, "media_debug_hook"):
            self.browser.media_debug_hook = self._on_browser_media_debug

    def _emit_log(self, message: str, *, color: str = "", category: str = "", level: str = "info"):
        payload = {
            "text": str(message or ""),
            "color": color or "",
            "category": category or "",
            "level": level or "info",
        }
        self.log_message.emit(payload["text"])
        self.log_event.emit(payload)

    def _on_browser_media_debug(self, payload: Dict[str, Any]) -> None:
        media_type = str(payload.get("media_type", "") or "delayed_video")
        message = str(payload.get("message", "") or "")
        level = str(payload.get("level", "") or "info")
        if message:
            self._emit_media_ui_log(media_type, message, level=level)

    def start(self, interval_ms: int = 4000):
        self._poll_interval_ms = max(1000, int(interval_ms or self._poll_interval_ms or 4000))
        if not self._page_ready:
            self._emit_log("⚠️ 页面未就绪，等待加载完成")
            return

        if self._running and self._ai_enabled:
            return

        self._running = True
        self._ai_enabled = True
        self._poll_timer.start(self._poll_interval_ms)
        self.status_changed.emit("running")
        self._emit_log("🚀 AI客服已启动")

    def stop(self):
        if not self._running:
            return
        self._ai_enabled = False
        if not self._poll_timer.isActive():
            self._poll_timer.start(self._poll_interval_ms)
        self._poll_inflight = False
        self._processing_reply = False
        self._pending_send = None
        self._pending_unread_hint = None
        self._active_session_context = None
        self.status_changed.emit("paused_remote")
        self._emit_log("🛑 AI客服已暂停，远程监听中")

    def shutdown(self):
        self._running = False
        self._ai_enabled = False
        self._poll_timer.stop()
        self._poll_inflight = False
        self._processing_reply = False
        self._pending_send = None
        self._pending_unread_hint = None
        self._active_session_context = None
        self.status_changed.emit("stopped")
        self._emit_log("🛑 AI客服已停止")

    def is_running(self) -> bool:
        return self._running

    def is_ai_enabled(self) -> bool:
        return self._running and self._ai_enabled

    def set_remote_control_users(self, names: List[str]):
        normalized = {str(x).strip() for x in (names or []) if str(x).strip()}
        self._remote_control_users = normalized
        self._emit_log(f"🔐 已更新远程控制白名单: {', '.join(sorted(normalized)) if normalized else '未配置'}")

    def pause_ai_for_remote_control(self):
        if not self._running:
            self._running = True
        self._ai_enabled = False
        if self._page_ready and not self._poll_timer.isActive():
            self._poll_timer.start(self._poll_interval_ms)
        self.status_changed.emit("paused_remote")

    def resume_ai_from_remote_control(self):
        if not self._page_ready:
            self._emit_log("⚠️ 页面未就绪，无法恢复 AI")
            return
        self._running = True
        self._ai_enabled = True
        if not self._poll_timer.isActive():
            self._poll_timer.start(self._poll_interval_ms)
        self.status_changed.emit("running")

    def get_runtime_status(self) -> Dict[str, Any]:
        return {
            "runtime_status": "running" if self.is_ai_enabled() else "paused_remote" if self._running else "stopped",
            "remote_control_enabled": bool(self._remote_control_enabled),
            "remote_control_user_count": len(self._remote_control_users),
        }

    def force_check(self):
        if not self._poll_inflight:
            self._poll_cycle()

    def reload_media_config(self):
        """重载 Agent 媒体库索引"""
        self.agent.reload_media_library()
        self.agent.reload_rule_configs()
        self._emit_log("✅ 已重载媒体素材索引")

    def reload_keyword_config(self):
        """兼容旧入口：转发到媒体重载。"""
        self.reload_media_config()

    def reload_prompt_docs(self):
        success = self.agent.reload_prompt_docs()
        self.agent.reload_rule_configs()
        if success:
            self._emit_log("✅ 已重载系统 Prompt 与 Playbook 文档")
        else:
            self._emit_log("⚠️ Prompt 文档缺失，已使用默认兜底")

    def _on_page_loaded(self, success: bool):
        self._page_ready = success
        if success:
            self.status_changed.emit("ready")
            self._emit_log("✅ 页面加载完成")
        else:
            self.status_changed.emit("error")
            self._emit_log("❌ 页面加载失败")

    def _on_url_changed(self, url: str):
        self._emit_log(f"🌐 页面地址变化: {url}")

    def _schedule_media_callback(self, delay_ms: int, callback: Callable[[], None]) -> None:
        if delay_ms <= 0:
            callback()
            return
        if not self._running or QCoreApplication.instance() is None:
            callback()
            return
        QTimer.singleShot(delay_ms, callback)

    def _poll_cycle(self):
        if not self._running or not self._page_ready or self._poll_inflight or self._processing_reply:
            return
        self._poll_inflight = True
        if not self._ai_enabled:
            self._check_remote_control_unread()
            return
        self._check_unread_and_enter()

    def _check_remote_control_unread(self):
        if not self._remote_control_enabled:
            self._reset_cycle()
            return

        def on_result(success, result):
            if not success:
                self._emit_log("⚠️ 远程控制监听失败")
                self._reset_cycle()
                return

            payload = self._parse_js_payload(result)
            if payload.get("found") and payload.get("clicked"):
                matched_name = str(payload.get("matchedName", "") or "")
                self._emit_log(f"🛰️ 发现远程控制消息，来自: {matched_name or '白名单用户'}")
                QTimer.singleShot(600, self._grab_remote_control_chat)
                return

            self._check_stale_replied_sessions()

        self.browser.find_and_click_unread_by_usernames(sorted(self._remote_control_users), on_result)

    def _grab_remote_control_chat(self):
        if not self._running:
            self._reset_cycle()
            return
        self.browser.grab_chat_data(lambda success, result: self._on_chat_data(success, result, auto_reply=True))

    def _check_unread_and_enter(self):
        def on_result(success, result):
            if not success:
                self._emit_log("⚠️ 检查未读失败")
                self._reset_cycle()
                return

            payload = self._parse_js_payload(result)
            if payload.get("found") and payload.get("clicked"):
                self._pending_unread_hint = {
                    "preview_text": str(payload.get("previewText", "") or ""),
                    "preview_type": str(payload.get("previewType", "") or ""),
                    "session_text": str(payload.get("sessionText", "") or ""),
                    "badge_text": str(payload.get("badgeText", "") or ""),
                }
                if payload.get("activeMatched"):
                    self._emit_log(f"🔔 当前会话检测到未读({payload.get('badgeText', 'dot')})")
                else:
                    self._emit_log(f"🔔 发现未读({payload.get('badgeText', 'dot')})，已点击进入")
                if self._pending_unread_hint.get("preview_type") in {"image", "video", "emoji"}:
                    self._emit_log(
                        f"🧭 未读预览识别: {self._format_unread_preview_hint(self._pending_unread_hint)}"
                    )
                delay_ms = int(getattr(self, "_GRAB_CHAT_AFTER_CLICK_DELAY_MS", 3000) or 0)
                self._emit_log(f"⏳ 预留{max(0, delay_ms) / 1000:.0f}秒人工介入时间，再抓取聊天记录")
                QTimer.singleShot(delay_ms, self._grab_and_reply_active_chat)
                return

            self._check_current_chat_after_no_unread()

        self.browser.find_and_click_first_unread(on_result)

    def _check_current_chat_after_no_unread(self):
        if not bool(getattr(self, "_CURRENT_CHAT_PROBE_AFTER_NO_UNREAD", True)):
            self._check_stale_replied_sessions()
            return

        def on_result(success, result):
            if not success:
                self._check_stale_replied_sessions()
                return

            data = self._parse_js_payload(result)
            messages = list(data.get("messages", []) or [])
            user_name = (data.get("user_name") or "").strip()
            if not messages or not user_name:
                self._check_stale_replied_sessions()
                return

            latest_user_message = self._latest_user_text(messages)
            if not latest_user_message:
                self._check_stale_replied_sessions()
                return

            marker = self._build_message_marker(user_name, latest_user_message, messages)
            if self._is_duplicate_marker(marker, latest_user_message):
                self._check_stale_replied_sessions()
                return

            self._emit_log(f"🔎 当前会话无红点但发现新消息，直接处理: {user_name}")
            self._on_chat_data(True, result, auto_reply=True)

        self.browser.grab_chat_data(on_result)

    def _grab_and_reply_active_chat(self):
        if not self._running:
            self._reset_cycle()
            return

        self.browser.grab_chat_data(lambda success, result: self._on_chat_data(success, result, auto_reply=True))

    def grab_and_display_chat_history(self, auto_reply: bool = True):
        """手动抓取聊天记录（抓取测试按钮使用）"""
        self.browser.grab_chat_data(lambda success, result: self._on_chat_data(success, result, auto_reply=auto_reply))

    def _check_stale_replied_sessions(self):
        candidate, reason = self._find_stale_followup_candidate()
        if not candidate:
            self._emit_stale_followup_status(reason or "当前没有可触发的1分钟结尾话术候选")
            self._reset_cycle()
            return

        self._emit_stale_followup_status(f"发现1分钟结尾话术候选: {str(candidate.get('user_name', '') or '').strip()}")
        user_name = str(candidate.get("user_name", "") or "").strip()
        if not user_name:
            self._reset_cycle()
            return

        find_chat = getattr(self.browser, "find_and_click_chat_by_username", None)
        if not callable(find_chat):
            self._emit_log("⚠️ 浏览器不支持按用户名切换会话，跳过1分钟结尾话术")
            self._reset_cycle()
            return

        def on_result(success, result):
            if not success:
                self._emit_log(f"⚠️ 1分钟结尾话术切换会话失败: {user_name}")
                self._reset_cycle()
                return

            payload = self._parse_js_payload(result)
            if not payload.get("found") or not payload.get("clicked"):
                self._emit_log(f"⚠️ 未定位到超时会话: {user_name}")
                self._stale_followup_skip_until[str(candidate.get("user_hash", "") or user_name)] = (
                    datetime.now() + timedelta(seconds=int(getattr(self, "_STALE_FOLLOWUP_RETRY_COOLDOWN_SECONDS", 300) or 300))
                )
                self._reset_cycle()
                return

            self._pending_stale_followup = candidate
            self._mark_active_session(
                session_id=str(candidate.get("session_id", "") or ""),
                user_name=user_name,
                stage="stale_followup_locked",
                detail="等待抓取确认",
            )
            delay_ms = int(getattr(self, "_STALE_FOLLOWUP_GRAB_DELAY_MS", 800) or 0)
            if delay_ms <= 0:
                self._grab_stale_followup_chat()
                return
            QTimer.singleShot(delay_ms, self._grab_stale_followup_chat)

        find_chat(user_name, on_result)

    def _grab_stale_followup_chat(self):
        if not self._running:
            self._reset_cycle()
            return
        self.browser.grab_chat_data(self._on_stale_followup_chat_data)

    def _on_stale_followup_chat_data(self, success: bool, result: Any):
        candidate = dict(self._pending_stale_followup or {})
        if not success or not candidate:
            self._reset_cycle()
            return

        data = self._parse_js_payload(result)
        messages = list(data.get("messages", []) or [])
        user_name = (data.get("user_name") or candidate.get("user_name") or "").strip()
        if not user_name:
            self._reset_cycle()
            return

        latest_user_message = self._latest_user_text(messages)
        if latest_user_message:
            self._emit_log(f"⏸️ 用户 {user_name} 已有新消息，取消1分钟结尾话术")
            self._pending_stale_followup = None
            self._reset_cycle()
            return

        session_id = self._build_session_id(
            user_name=user_name,
            chat_session_key=(data.get("chat_session_key") or "").strip(),
            chat_session_fingerprint=(data.get("chat_session_fingerprint") or "").strip(),
        )
        user_hash = str(candidate.get("user_hash", "") or self._build_user_hash(user_name=user_name, session_id=session_id))
        self._send_stale_followup_message(session_id=session_id, user_name=user_name, user_hash=user_hash)

    def _send_stale_followup_message(self, session_id: str, user_name: str, user_hash: str):
        reply_text = str(getattr(self, "_STALE_FOLLOWUP_TEXT", self._STALE_FOLLOWUP_TEXT))
        if getattr(self, "agent", None) is not None and callable(getattr(self.agent, "_pick_fixed_reply", None)):
            session_state = self.agent.memory_store.get_session_state(session_id, user_hash=user_hash)
            reply_text = self.agent._pick_fixed_reply(
                session_state=session_state,
                category="stale_followup",
                replies=getattr(self.agent, "STALE_FOLLOWUP_TEXT_POOL", ()) or (),
                fallback=reply_text,
            )
            self.agent.memory_store.update_session_state(
                session_id,
                {"fixed_reply_counters": dict(session_state.get("fixed_reply_counters", {}) or {})},
                user_hash=user_hash,
            )
            self.agent.memory_store.save()
        self._processing_reply = True
        self._mark_active_session(
            session_id=session_id,
            user_name=user_name,
            stage="stale_followup_send",
            detail="发送固定结尾话术",
        )

        def on_sent(success, result):
            del result
            if not success:
                self._emit_log(f"❌ 1分钟结尾话术发送失败: {user_name}")
                self._reset_cycle()
                return

            media_summary = {
                "sent_types": [],
                "failed_types": [],
                "sent_details": [],
            }
            self.sessions.get_or_create_session(session_id=session_id, user_name=user_name)
            self.sessions.add_message(session_id, reply_text, is_user=False, user_name=user_name)
            self.sessions.record_reply(session_id)
            self.reply_sent.emit(session_id, reply_text)
            self._emit_log(f"✅ 文本回复已发送: {reply_text[:80]}")

            def finish_stale_followup() -> None:
                self._append_training_event(
                    session_id=session_id,
                    user_id_hash=user_hash,
                    event_type="stale_followup_sent",
                    user_name=user_name,
                    reply_source="stale_followup",
                    rule_id="STALE_FOLLOWUP",
                    payload={"text": reply_text, "user_name": user_name},
                )
                self._append_training_event(
                    session_id=session_id,
                    user_id_hash=user_hash,
                    event_type="assistant_reply",
                    user_name=user_name,
                    reply_source="stale_followup",
                    rule_id="STALE_FOLLOWUP",
                    payload={
                        "text": reply_text,
                        "intent": "stale_followup",
                        "route_reason": "stale_followup",
                        "round_media_sent": bool(media_summary.get("sent_types")),
                        "round_media_sent_types": list(media_summary.get("sent_types", [])),
                        "round_media_failed_types": list(media_summary.get("failed_types", [])),
                        "round_media_sent_details": list(media_summary.get("sent_details", [])),
                    },
                )
                self._emit_log(f"✅ 已发送1分钟结尾话术: {user_name}")
                self._pending_stale_followup = None
                self._reset_cycle()

            media_queue = self._build_stale_followup_media_queue(session_id=session_id, user_name=user_name)
            if media_queue:
                delay_ms = int(getattr(self, "_MEDIA_SEND_AFTER_TEXT_DELAY_MS", 900) or 0)
                send_media = lambda: self._send_media_queue(
                    session_id=session_id,
                    user_name=user_name,
                    media_queue=media_queue,
                    media_summary=media_summary,
                    on_complete=finish_stale_followup,
                    defer_retry_media_types={"contact_image"},
                )
                if delay_ms <= 0:
                    send_media()
                    return
                QTimer.singleShot(delay_ms, send_media)
                return

            finish_stale_followup()

        # 添加随机 emoji 到回复文本
        reply_text_with_emoji = add_random_emoji(
            reply_text,
            context="general",
            gender="male" if "帅哥" in reply_text else "female",
        )
        self.browser.send_message(reply_text_with_emoji, on_sent)

    def _build_stale_followup_media_queue(self, session_id: str, user_name: str) -> List[Dict[str, Any]]:
        pick_contact_image = getattr(self.agent, "_pick_contact_image_for_session", None)
        if not callable(pick_contact_image):
            return []
        user_hash = self._build_user_hash(user_name=user_name, session_id=session_id)
        session_state = dict(self.agent.memory_store.get_session_state(session_id, user_hash=user_hash) or {})
        media_path = str(pick_contact_image(session_state) or "").strip()
        if not media_path:
            return []
        return [
            {
                "type": "contact_image",
                "path": media_path,
                "trigger_source": "stale_followup",
                "route_reason": "stale_followup_contact_image",
            }
        ]

    # ── 地址图片重发（"图在哪儿"处理） ────────────────────────────────────────

    _ADDRESS_IMAGE_RETRY_PHRASES = (
        "图在哪", "图片呢", "图在哪儿", "图呢", "没看到图", "没收到图",
        "图片没收到", "没看见图", "图发了吗", "地址图呢", "图片在哪",
        "图片发了吗", "没有图", "没看到地址图", "发图", "地址图片呢",
    )
    _ADDRESS_IMAGE_RETRY_REPLY = "姐姐稍等，我再给您发一次地址图～"

    def _should_retry_address_image(self, user_text: str, session_id: str, user_hash: str) -> bool:
        """判断是否应跳过 LLM 直接重发地址图。"""
        text = str(user_text or "").strip()
        if not any(phrase in text for phrase in self._ADDRESS_IMAGE_RETRY_PHRASES):
            return False
        session_state = self.agent.memory_store.get_session_state(session_id, user_hash=user_hash)
        last_store = str(session_state.get("last_intercepted_store", "") or "").strip()
        return bool(last_store)

    def _handle_address_image_retry(
        self,
        session_id: str,
        user_name: str,
        user_hash: str,
        marker: str,
        latest_user_message: str,
    ) -> None:
        """跳过 LLM，发固定话术 + 重发上次拦截门店的地址图。"""
        session_state = self.agent.memory_store.get_session_state(session_id, user_hash=user_hash)
        last_store_name = str(session_state.get("last_intercepted_store", "") or "").strip()
        store_key = self._interceptor_store_to_index_key.get(last_store_name)
        reply_text = self._ADDRESS_IMAGE_RETRY_REPLY
        self._emit_log(f"🔁 地址图重发触发：门店={last_store_name}，跳过 LLM")

        self._processing_reply = True
        self._remember_processed_marker(marker, latest_user_message)

        def on_retry_sent(success, result):
            del result
            if not success:
                self._emit_log("❌ 地址图重发文本发送失败")
                self._reset_cycle()
                return

            self.sessions.get_or_create_session(session_id=session_id, user_name=user_name)
            self.sessions.add_message(session_id, reply_text, is_user=False, user_name=user_name)
            self.sessions.record_reply(session_id)
            self.reply_sent.emit(session_id, reply_text)
            self._emit_log(f"✅ 地址图重发话术已发送: {reply_text}")
            self._append_training_event(
                session_id=session_id,
                user_id_hash=user_hash,
                event_type="address_image_retry",
                user_name=user_name,
                payload={"text": reply_text, "store": last_store_name, "trigger": latest_user_message},
            )

            media_queue: List[Dict[str, Any]] = []
            if store_key:
                image_path = self.agent.pick_address_image(store_key, session_state=session_state)
                if image_path:
                    media_queue.append({
                        "type": "address_image",
                        "path": image_path,
                        "trigger_source": "address_image_retry",
                        "target_store": store_key,
                    })
                    self._emit_log(f"📍 重发地址图：{Path(image_path).name}")
                else:
                    self._emit_log(f"⚠️  {last_store_name} 图片库为空，无法重发")
            else:
                self._emit_log(f"⚠️  重发失败，未知门店：{last_store_name}")

            if media_queue:
                delay_ms = int(getattr(self, "_MEDIA_SEND_AFTER_TEXT_DELAY_MS", 900) or 0)
                media_summary = {"sent_types": [], "failed_types": [], "sent_details": [], "failed_details": []}
                send_media = lambda: self._send_media_queue(
                    session_id=session_id,
                    user_name=user_name,
                    media_queue=media_queue,
                    decision=None,
                    media_summary=media_summary,
                    on_complete=self._reset_cycle,
                )
                if delay_ms > 0:
                    QTimer.singleShot(delay_ms, send_media)
                else:
                    send_media()
            else:
                self._reset_cycle()

        reply_with_emoji = add_random_emoji(reply_text, context="general", gender="female")
        self.browser.send_message(reply_with_emoji, on_retry_sent)

    # ── 地址图片重发结束 ──────────────────────────────────────────────────────

    def _on_chat_data(self, success: bool, result: Any, auto_reply: bool):
        if not success:
            self._emit_log("❌ 抓取聊天记录失败")
            self._reset_cycle()
            return

        data = self._parse_js_payload(result)
        messages = list(data.get("messages", []) or [])
        debug_lines = data.get("debug", []) or []
        user_name = (data.get("user_name") or "未知用户").strip() or "未知用户"
        chat_session_key = (data.get("chat_session_key") or "").strip()
        chat_session_method = (data.get("chat_session_method") or "").strip()
        chat_session_fingerprint = (data.get("chat_session_fingerprint") or "").strip()
        messages = self._restrict_media_placeholders_to_unread_context(messages)
        messages = self._maybe_append_unread_hint_message(messages)

        if not messages:
            self._emit_log(f"⚠️ 用户 {user_name} 暂无可读消息")
            for line in debug_lines[-6:]:
                self._emit_log(f"🧭 抓取调试: {line}")
            self._reset_cycle()
            return

        self._log_chat_history(user_name, messages)
        if not auto_reply:
            self._reset_cycle()
            return

        latest_user_message = self._latest_user_text(messages)
        if not latest_user_message:
            self._emit_log("⏸️ 最后一条不是用户消息，跳过自动回复")
            for line in debug_lines[-6:]:
                self._emit_log(f"🧭 抓取调试: {line}")
            self._reset_cycle()
            return

        marker = self._build_message_marker(user_name, latest_user_message, messages)
        if self._is_duplicate_marker(marker, latest_user_message):
            self._emit_log("⏸️ 检测到重复消息，跳过")
            self._reset_cycle()
            return

        self._remember_processed_marker(marker, latest_user_message)
        self.message_received.emit({"user_name": user_name, "text": latest_user_message})

        session_id = self._build_session_id(
            user_name=user_name,
            chat_session_key=chat_session_key,
            chat_session_fingerprint=chat_session_fingerprint,
        )
        user_hash = self._build_user_hash(user_name=user_name, session_id=session_id)
        is_first_turn_global = self._detect_user_first_turn_global(user_hash=user_hash)
        self._mark_active_session(
            session_id=session_id,
            user_name=user_name,
            stage="chat_locked",
            detail=f"latest={latest_user_message[:40]}",
        )
        if chat_session_fingerprint:
            self.agent.memory_store.update_session_state(
                session_id=session_id,
                updates={"session_fingerprint": chat_session_fingerprint},
                user_hash=user_hash,
            )
        self.sessions.get_or_create_session(session_id=session_id, user_name=user_name)
        self.sessions.add_message(session_id, latest_user_message, is_user=True, user_name=user_name)
        self._append_training_event(
            session_id=session_id,
            user_id_hash=user_hash,
            event_type="user_message",
            user_name=user_name,
            payload={
                "text": latest_user_message,
                "user_name": user_name,
                "chat_session_key": chat_session_key,
                "chat_session_method": chat_session_method,
                "chat_session_fingerprint": chat_session_fingerprint,
                "is_first_turn_global": bool(is_first_turn_global),
            },
        )

        remote_command = self._normalize_remote_control_command(latest_user_message)
        if self._is_remote_control_user(user_name) and remote_command:
            self._handle_remote_control_command(
                session_id=session_id,
                user_name=user_name,
                user_hash=user_hash,
                command=remote_command,
            )
            self._remember_processed_marker(marker, latest_user_message)
            return

        # 用 Python 侧累积的干净历史替代前端抓取的全页记录
        # session.messages 包含本次 session 所有 add_message 的内容（含刚加入的当前用户消息）
        # 去掉末尾的当前用户消息，与 _convert_history 的语义保持一致（LLMService 会在末尾追加）
        _session_obj = self.sessions.get_session(session_id)
        if _session_obj and len(_session_obj.messages) > 1:
            history = [
                {"role": "user" if m["is_user"] else "assistant", "content": str(m.get("text") or "").strip()}
                for m in _session_obj.messages[:-1]
                if str(m.get("text") or "").strip()
            ]
        else:
            history = []
        # ── 地址图片重发检测（跳过 LLM） ────────────────────────────────────────
        # 用户反馈未收到地址图时（"图在哪儿"等），直接重发，不调用 LLM
        if self._should_retry_address_image(latest_user_message, session_id, user_hash):
            self._handle_address_image_retry(session_id, user_name, user_hash, marker, latest_user_message)
            return
        # ── 地址图片重发检测结束 ──────────────────────────────────────────────

        self._processing_reply = True
        self._pending_send = {
            "session_id": session_id,
            "user_name": user_name,
            "latest_user_text": latest_user_message,
            "conversation_history": history,
            "user_hash": user_hash,
        }

        decision_payload = {
            "session_id": session_id,
            "user_name": user_name,
            "latest_user_text": latest_user_message,
            "conversation_history": history,
            "is_first_turn_global": bool(is_first_turn_global),
            "user_hash": user_hash,
            "use_first_turn_opening": bool(
                is_first_turn_global and str(getattr(self.agent, "reply_mode", "")) != "llm_direct"
            ),
            "build_first_turn_opening_decision": self._build_first_turn_opening_decision,
        }
        self._emit_log("🧠 开始后台生成 LLM 回复")
        self._start_decision_worker(decision_payload)

    def _start_decision_worker(self, payload: Dict[str, Any]) -> None:
        if hasattr(self.agent, "conversation_logger"):
            self.agent.conversation_logger = self.conversation_logger
        if payload.get("use_first_turn_opening", False):
            self._emit_log("🧭 首轮命中固定承接：后台直接生成固定文本和视频")
        if not self._running:
            try:
                worker = _DecisionWorker(self.agent, payload, self.sessions, parent=self)
                decision = worker.compute_decision(self.agent, payload)
            except Exception as exc:
                self._on_decision_worker_failed(payload, str(exc))
                return
            self._on_decision_worker_ready(payload, decision)
            return
        worker = _DecisionWorker(self.agent, payload, self.sessions, parent=self)
        worker.decision_ready.connect(self._on_decision_worker_ready)
        worker.decision_failed.connect(self._on_decision_worker_failed)
        worker.finished.connect(self._clear_decision_worker)
        self._decision_worker = worker
        worker.start()

    def _on_decision_worker_ready(self, payload: Dict[str, Any], decision: AgentDecision) -> None:
        if not self._pending_send:
            self._emit_log("⏭️ 后台决策已完成，但当前会话已取消，忽略本次结果")
            return
        user_hash = str(payload.get("user_hash", "") or "")
        request_ms = int(getattr(decision, "llm_request_ms", 0) or 0)
        attempts = int(getattr(decision, "llm_attempt_count", 0) or 0)
        speed_label = "正常"
        if attempts >= 2 or request_ms > 5000:
            speed_label = "异常慢"
        elif request_ms >= 3000:
            speed_label = "偏慢"
        self.decision_ready.emit(
            {
                "session_id": payload["session_id"],
                "user_name": payload["user_name"],
                "intent": decision.intent,
                "route_reason": decision.route_reason,
                "reply_goal": decision.reply_goal,
                "media_plan": decision.media_plan,
                "reply_source": decision.reply_source,
                "source": decision.reply_source,
                "rule_id": decision.rule_id,
                "rule_applied": decision.rule_applied,
            }
        )

        self._emit_log(
            f"🤖 Agent决策: source={decision.reply_source}, intent={decision.intent}, "
            f"route={decision.route_reason}, media={decision.media_plan}, rule={decision.rule_id or '-'}"
        )
        self._emit_log(
            "⏱️ LLM耗时: "
            f"prompt={int(getattr(decision, 'prompt_build_ms', 0) or 0)}ms, "
            f"request={int(getattr(decision, 'llm_request_ms', 0) or 0)}ms, "
            f"total={int(getattr(decision, 'llm_total_ms', 0) or 0)}ms, "
            f"attempts={int(getattr(decision, 'llm_attempt_count', 0) or 0)}, "
            f"messages={int(getattr(decision, 'llm_message_count', 0) or 0)}, "
            f"prompt_chars={int(getattr(decision, 'system_prompt_chars', 0) or 0)}, "
            f"判定={speed_label}"
        )
        if str(getattr(decision, "llm_fallback_reason", "") or "").strip():
            self._emit_log(f"⚠️ Fallback原因: {decision.llm_fallback_reason}")
        self._append_training_event(
            session_id=payload["session_id"],
            user_id_hash=user_hash,
            event_type="decision_snapshot",
            user_name=payload["user_name"],
            reply_source=decision.reply_source,
            rule_id=decision.rule_id,
            model_name=decision.llm_model,
            payload={
                "intent": decision.intent,
                "route_reason": decision.route_reason,
                "reply_goal": decision.reply_goal,
                "media_plan": decision.media_plan,
                "reply_text": decision.reply_text,
                "rule_applied": decision.rule_applied,
                "geo_context_source": decision.geo_context_source,
                "media_skip_reason": decision.media_skip_reason,
                "round_media_blocked": bool(decision.media_skip_reason),
                "round_media_block_reason": decision.media_skip_reason,
                "round_media_planned_types": [str(x.get("type", "")) for x in (decision.media_items or []) if isinstance(x, dict)],
                "both_images_sent_state": bool(decision.both_images_sent_state),
                "kb_match_score": float(decision.kb_match_score or 0.0),
                "kb_match_question": str(decision.kb_match_question or ""),
                "kb_match_mode": str(decision.kb_match_mode or ""),
                "kb_item_id": str(decision.kb_item_id or ""),
                "kb_variant_total": int(decision.kb_variant_total or 0),
                "kb_variant_selected_index": int(
                    decision.kb_variant_selected_index
                    if decision.kb_variant_selected_index is not None
                    else -1
                ),
                "kb_variant_fallback_llm": bool(decision.kb_variant_fallback_llm),
                "kb_confident": bool(decision.kb_confident),
                "kb_blocked_by_polite_guard": bool(decision.kb_blocked_by_polite_guard),
                "kb_polite_guard_reason": str(decision.kb_polite_guard_reason or ""),
                "force_contact_image": bool(decision.force_contact_image),
                "kb_contact_trigger_type": str(decision.kb_contact_trigger_type or ""),
                "is_first_turn_global": bool(decision.is_first_turn_global),
                "first_turn_media_guard_applied": bool(decision.first_turn_media_guard_applied),
                "first_turn_image_types": [
                    str(x.get("type", ""))
                    for x in (decision.first_turn_image_items or [])
                    if isinstance(x, dict)
                ],
                "first_turn_video_types": [
                    str(x.get("type", ""))
                    for x in (decision.first_turn_video_items or [])
                    if isinstance(x, dict)
                ],
                "first_turn_text_required": bool(decision.first_turn_text_required),
                "first_turn_retry_policy": dict(decision.first_turn_retry_policy or {}),
                "kb_repeat_rewritten": bool(decision.kb_repeat_rewritten),
                "purchase_both_first_hint_sent": bool(decision.purchase_both_first_hint_sent),
                "video_trigger_user_count": int(decision.video_trigger_user_count or 0),
                "reply_mode": str(getattr(decision, "reply_mode", "") or ""),
                "standard_reply_hit": bool(getattr(decision, "standard_reply_hit", False)),
                "standard_reply_question": str(getattr(decision, "standard_reply_question", "") or ""),
                "standard_reply_confidence": str(getattr(decision, "standard_reply_confidence", "") or ""),
                "brand_knowledge_used": bool(getattr(decision, "brand_knowledge_used", False)),
                "prompt_build_ms": int(getattr(decision, "prompt_build_ms", 0) or 0),
                "llm_request_ms": int(getattr(decision, "llm_request_ms", 0) or 0),
                "llm_total_ms": int(getattr(decision, "llm_total_ms", 0) or 0),
                "llm_attempt_count": int(getattr(decision, "llm_attempt_count", 0) or 0),
                "llm_message_count": int(getattr(decision, "llm_message_count", 0) or 0),
                "system_prompt_chars": int(getattr(decision, "system_prompt_chars", 0) or 0),
            },
        )

        if self._pending_send:
            self._pending_send["decision"] = decision
        self._emit_log("✉️ 开始发送回复")
        self._send_pending_decision()

    def _on_decision_worker_failed(self, payload: Dict[str, Any], error_text: str) -> None:
        if not self._pending_send:
            return
        self._emit_log(f"❌ Agent后台决策失败: {error_text}")
        self.error_occurred.emit("后台生成回复失败")
        self._append_training_event(
            session_id=str(payload.get("session_id", "") or ""),
            user_id_hash=str(payload.get("user_hash", "") or ""),
            event_type="decision_failed",
            user_name=str(payload.get("user_name", "") or ""),
            payload={"error": str(error_text or "")},
        )
        self._reset_cycle()

    def _clear_decision_worker(self) -> None:
        worker = self._decision_worker
        if worker is None:
            return
        if worker.isRunning():
            return
        worker.deleteLater()
        self._decision_worker = None

    def _send_pending_decision(self):
        payload = self._pending_send
        if not payload:
            self._reset_cycle()
            return

        session_id = payload["session_id"]
        user_name = payload["user_name"]
        decision: AgentDecision = payload["decision"]
        latest_user_text = str(payload.get("latest_user_text", "") or "")
        conversation_history = list(payload.get("conversation_history", []) or [])
        self._mark_active_session(
            session_id=session_id,
            user_name=user_name,
            stage="send_pending",
            detail=f"media={decision.media_plan or 'none'}",
        )

        media_summary = {"sent_types": [], "failed_types": [], "sent_details": [], "failed_details": []}
        first_turn_image_items = [dict(x) for x in (decision.first_turn_image_items or []) if isinstance(x, dict)]
        first_turn_video_items = [dict(x) for x in (decision.first_turn_video_items or []) if isinstance(x, dict)]
        deferred_media_items: List[Dict[str, Any]] = []

        def send_text_and_remaining_media(planned_media_items_after_text: Optional[List[Dict[str, Any]]] = None):
            planned_media_items = list(planned_media_items_after_text or [])

            def on_text_sent(success, result):
                if not success:
                    self._emit_log("❌ 文本发送失败")
                    self.error_occurred.emit("发送文本失败")
                    self._reset_cycle()
                    return

                self._emit_log(f"✅ 文本回复已发送: {decision.reply_text[:80]}")
                self.sessions.add_message(session_id, decision.reply_text, is_user=False)
                self.sessions.record_reply(session_id)
                self.reply_sent.emit(session_id, decision.reply_text)

                extra_video = self.agent.mark_reply_sent(
                    session_id,
                    user_name,
                    decision.reply_text,
                    is_first_turn_global=bool(decision.is_first_turn_global),
                )
                extra_medias = [extra_video] if extra_video else []
                post_reply_media_items: List[Dict[str, Any]] = []
                post_reply_media_decision = None
                if str(getattr(decision, "reply_mode", "") or "") == "llm_direct":
                    try:
                        post_reply_media_decision = self.agent.judge_post_reply_media(
                            session_id=session_id,
                            user_name=user_name,
                            latest_user_text=latest_user_text,
                            reply_text=decision.reply_text,
                            conversation_history=conversation_history,
                            decision=decision,
                        )
                        post_reply_media_items = list(getattr(post_reply_media_decision, "media_items", []) or [])
                    except Exception as exc:
                        self._emit_log(f"⚠️ 媒体裁判执行失败，不影响文本发送: {exc}")
                        post_reply_media_items = []
                post_text_extra_items = [*first_turn_video_items, *extra_medias, *deferred_media_items]
                media_queue = self.agent.build_post_text_media_queue(
                    session_id=session_id,
                    user_name=user_name,
                    planned_media_items=[*planned_media_items, *post_reply_media_items],
                    extra_media_items=post_text_extra_items,
                )

                if media_queue:
                    self._record_planned_required_media(session_id, user_name, media_queue)
                    self._mark_active_session(
                        session_id=session_id,
                        user_name=user_name,
                        stage="text_sent_wait_media",
                        detail=f"queued_media={len(media_queue)}",
                    )
                    delay_ms = int(getattr(self, "_MEDIA_SEND_AFTER_TEXT_DELAY_MS", 900) or 0)
                    has_delayed_video = any(
                        isinstance(item, dict) and str(item.get("type", "") or "") == "delayed_video"
                        for item in media_queue
                    )
                    if has_delayed_video:
                        delay_ms += int(getattr(self, "_VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS", 1200) or 0)
                    send_media = lambda: self._send_media_queue(
                            session_id,
                            user_name,
                            media_queue,
                            decision=decision,
                            media_summary=media_summary,
                        )
                    if delay_ms <= 0:
                        send_media()
                        return

                    QTimer.singleShot(delay_ms, send_media)
                    return

                self._send_media_queue(session_id, user_name, media_queue, decision=decision, media_summary=media_summary)

            # ── 地址拦截器：检测单门店地址并替换 ──────────────────────────────────────
            # 1. 调用拦截器检测 decision.reply_text 是否包含单门店地址
            # 2. 如果拦截：替换为"地址看图片中的位置"，并触发对应门店的地址图片
            # 3. 日志记录的是原始 decision.reply_text（由上层 decision_snapshot 记录）
            intercept_result = self._address_interceptor.intercept(decision.reply_text)

            try:
                if intercept_result.is_intercepted:
                    store_names_str = "、".join(intercept_result.target_stores)
                    self._emit_log(
                        f"🎯 地址拦截器命中 {intercept_result.match_count} 家门店：{store_names_str}"
                    )
                    reply_text_to_send = intercept_result.processed_text

                    # 获取 session_state 用于图片避重 + 记录 last_intercepted_store
                    _intercept_user_hash = self._build_user_hash(user_name=user_name, session_id=session_id)
                    session_state = self.agent.memory_store.get_session_state(session_id, user_hash=_intercept_user_hash)

                    # 记录第一家门店，供"图在哪儿"重发时使用
                    self.agent.memory_store.update_session_field(
                        session_id,
                        _intercept_user_hash,
                        "last_intercepted_store",
                        intercept_result.target_store or "",
                    )

                    # 决定触发哪些门店的图片：1-2 家各发 1 张，3 家及以上只发第 1 家
                    stores_to_send = (
                        intercept_result.target_stores[:2]
                        if intercept_result.match_count <= 2
                        else intercept_result.target_stores[:1]
                    )
                    for store_name in stores_to_send:
                        store_key = self._interceptor_store_to_index_key.get(store_name)
                        if store_key:
                            image_path = self.agent.pick_address_image(store_key, session_state=session_state)
                            if image_path:
                                planned_media_items.insert(0, {
                                    "type": "address_image",
                                    "path": image_path,
                                    "trigger_source": "address_interceptor",
                                    "target_store": store_key,
                                })
                                self._emit_log(f"📍 触发 {store_name} 地址图片 ({Path(image_path).name})")
                            else:
                                self._emit_log(f"⚠️  {store_name} 地址图片库为空")
                        else:
                            self._emit_log(f"⚠️  未知门店 {store_name}，无法映射地址图片索引")

                    if intercept_result.match_count > 2:
                        self._emit_log(
                            f"ℹ️  {intercept_result.match_count} 家门店地址，仅触发第 1 家图片（{intercept_result.target_stores[0]}）"
                        )
                else:
                    reply_text_to_send = decision.reply_text
            except Exception as _intercept_exc:
                self._emit_log(f"⚠️ 地址拦截器异常，回退到原始文本: {_intercept_exc}")
                reply_text_to_send = decision.reply_text
            # ── 地址拦截器结束 ──────────────────────────────────────────────────────

            # ── 联系方式图片触发器 ─────────────────────────────────────────────────
            # 检测规则：
            # 1. LLM 输出含"索取联系方式"话术（如"您留个电话"），说明 agent 在要用户联系方式
            # 2. 用户消息含"远程定制"（明确预约意图，LLM 回复中也会提及）
            # 触发动作：补发一张联系方式图片，每个 session 只发一次，与 1 分钟兜底逻辑独立
            _CONTACT_TRIGGER_LLM_PHRASES = (
                "留个电话", "留下电话", "留下您的电话",
                "留个联系方式", "留下联系方式", "留下您的联系方式",
                "留个微信", "留下微信", "方便留个", "方便留下",
                "您的手机号", "手机号发给我", "手机号给我",
                "留个号码", "留下号码", "联系到您",
                "联系方式给我", "联系方式发给我",
            )
            _CONTACT_TRIGGER_USER_PHRASES = (
                "远程定制",
            )
            try:
                if session_id not in self._contact_trigger_sent_sessions:
                    llm_text = str(decision.reply_text or "")
                    user_text = str(latest_user_text or "")
                    contact_triggered = (
                        any(p in llm_text for p in _CONTACT_TRIGGER_LLM_PHRASES)
                        or any(p in user_text for p in _CONTACT_TRIGGER_USER_PHRASES)
                    )
                    if contact_triggered:
                        pick_contact_image = getattr(self.agent, "_pick_contact_image_for_session", None)
                        if callable(pick_contact_image):
                            _user_hash = self._build_user_hash(user_name=user_name, session_id=session_id)
                            _session_state = self.agent.memory_store.get_session_state(session_id, user_hash=_user_hash)
                            contact_image_path = str(pick_contact_image(_session_state) or "").strip()
                            if contact_image_path:
                                planned_media_items.append({
                                    "type": "contact_image",
                                    "path": contact_image_path,
                                    "trigger_source": "contact_trigger",
                                    "route_reason": "llm_contact_ask",
                                })
                                self._contact_trigger_sent_sessions.add(session_id)
                                self._emit_log("📞 联系方式触发器命中，补发联系方式图片（本 session 仅此一次）")
            except Exception as _contact_exc:
                self._emit_log(f"⚠️ 联系方式触发器异常，跳过: {_contact_exc}")
            # ── 联系方式图片触发器结束 ──────────────────────────────────────────────

            # 添加随机 emoji 到回复文本
            reply_text_with_emoji = add_random_emoji(
                reply_text_to_send,
                context=str(getattr(decision, "intent", "general") or "general"),
                gender="male" if "帅哥" in reply_text_to_send else "female",
            )
            self.browser.send_message(reply_text_with_emoji, on_text_sent)

        if decision.rule_id == "FIRST_TURN_AUTO_REPLY":
            send_text_and_remaining_media([])
            return

        # Phase 1: 首轮视频优先发送
        if decision.is_first_turn_global and first_turn_video_items:
            self._mark_active_session(
                session_id=session_id,
                user_name=user_name,
                stage="first_turn_send_video",
                detail=f"queued_media={len(first_turn_video_items)}",
            )
            self._emit_log("🎬 首轮优先发送视频")

            def on_video_complete():
                self._emit_log("✅ 首轮视频发送完成，等待 3 秒后继续发送图片")
                self._mark_active_session(
                    session_id=session_id,
                    user_name=user_name,
                    stage="first_turn_video_wait_continue",
                    detail="waiting_3s",
                )

                def continue_with_images():
                    self._emit_log("⏭️ 继续发送图片和文本")
                    # 清空 first_turn_video_items，避免重复发送
                    first_turn_video_items.clear()

                    # 继续发送图片（如果有）
                    if first_turn_image_items:
                        self._mark_active_session(
                            session_id=session_id,
                            user_name=user_name,
                            stage="first_turn_send_image",
                            detail=f"queued_media={len(first_turn_image_items)}",
                        )
                        self._send_media_queue(
                            session_id,
                            user_name,
                            first_turn_image_items,
                            decision=None,
                            media_summary=media_summary,
                            on_complete=lambda: send_text_and_remaining_media([]),
                            defer_retry_media_types={"address_image", "contact_image"},
                            deferred_retry_items=deferred_media_items,
                        )
                    else:
                        # 没有图片，直接发送文本
                        send_text_and_remaining_media([])

                delay_ms = int(getattr(self, "_FIRST_TURN_VIDEO_CONTINUE_DELAY_MS", 3000) or 0)
                if delay_ms > 0:
                    QTimer.singleShot(delay_ms, continue_with_images)
                    return
                continue_with_images()

            self._send_media_queue(
                session_id,
                user_name,
                first_turn_video_items,
                decision=None,
                media_summary=media_summary,
                on_complete=on_video_complete,
            )
            return

        if decision.is_first_turn_global and first_turn_image_items:
            self._mark_active_session(
                session_id=session_id,
                user_name=user_name,
                stage="first_turn_send_image",
                detail=f"queued_media={len(first_turn_image_items)}",
            )
            self._send_media_queue(
                session_id,
                user_name,
                first_turn_image_items,
                decision=None,
                media_summary=media_summary,
                on_complete=lambda: send_text_and_remaining_media([]),
                defer_retry_media_types={"address_image", "contact_image"},
                deferred_retry_items=deferred_media_items,
            )
            return

        planned_items_after_text = [] if decision.is_first_turn_global else list(decision.media_items)
        send_text_and_remaining_media(planned_items_after_text)

    def _build_first_turn_opening_decision(self, session_id: str, user_name: str) -> AgentDecision:
        del user_name
        video_items: List[Dict[str, Any]] = []
        build_video_items = getattr(self.agent, "build_first_turn_video_items", None)
        if callable(build_video_items):
            try:
                video_items = [dict(x) for x in (build_video_items(session_id) or []) if isinstance(x, dict)]
            except Exception:
                video_items = []

        decision = AgentDecision(
            reply_text=str(getattr(self, "_FIRST_TURN_AUTO_REPLY_TEXT", "") or "").strip(),
            intent="first_turn_auto",
            route_reason="first_turn_auto_reply",
            reply_goal="首轮承接",
            media_plan="delayed_video" if video_items else "none",
            media_items=[],
            reply_source="system",
            rule_id="FIRST_TURN_AUTO_REPLY",
            rule_applied=True,
        )
        decision.is_first_turn_global = True
        decision.first_turn_text_required = True
        decision.first_turn_video_items = video_items
        decision.first_turn_retry_policy = {
            "image_retry_once_deferred": True,
            "video_retry_once_inline": True,
        }
        return decision

    def _send_media_queue(
        self,
        session_id: str,
        user_name: str,
        media_queue: List[Dict[str, Any]],
        decision: Optional[AgentDecision] = None,
        media_summary: Optional[Dict[str, List[str]]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        defer_retry_media_types: Optional[set[str]] = None,
        deferred_retry_items: Optional[List[Dict[str, Any]]] = None,
    ):
        self._media_delivery.send_media_queue(
            session_id=session_id,
            user_name=user_name,
            media_queue=media_queue,
            decision=decision,
            media_summary=media_summary,
            on_complete=on_complete,
            defer_retry_media_types=defer_retry_media_types,
            deferred_retry_items=deferred_retry_items,
        )

    def _should_retry_media_send(self, media_type: str, result: Any, retry_count: int) -> bool:
        failure_code = self._extract_failure_code(result)
        if media_type in ("contact_image", "address_image"):
            if retry_count >= 2:
                return False
            return failure_code in {
                "locate_image_button_failed",
                "native_click_image_button_failed",
                "confirm_click_failed",
                "confirm_click_after_enter_failed",
                "verify_timeout",
                "verified_soft_timeout",
                "unknown_media_failure",
            }
        if media_type == "delayed_video":
            if retry_count >= 2:
                return False
            return failure_code in {
                "locate_material_library_failed",
                "locate_video_tab_failed",
                "locate_video_item_failed",
                "click_video_send_button_failed",
                "drag_video_to_chat_failed",
                "confirm_click_failed",
                "video_verify_timeout",
                "unknown_media_failure",
            }
        return False

    def test_grab(self, callback: Callable = None):
        def on_data(success, data):
            if callback:
                callback(success, data)
                return
            if success:
                self._emit_log(f"测试抓取成功: {str(data)[:180]}")
            else:
                self._emit_log("测试抓取失败")

        self.browser.grab_chat_data(on_data)

    def _reset_cycle(self):
        self._emit_active_session_release()
        self._poll_inflight = False
        self._processing_reply = False
        self._pending_send = None
        self._pending_unread_hint = None
        self._pending_stale_followup = None
        self._active_session_context = None

    def _parse_js_payload(self, payload: Any) -> Dict[str, Any]:
        return self._support.parse_js_payload(payload)

    def _latest_user_text(self, messages: List[Dict[str, Any]]) -> str:
        return self._support.latest_user_text(messages)

    def _maybe_append_unread_hint_message(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        updated_messages, log_message = self._support.maybe_append_unread_hint_message(
            messages,
            self._pending_unread_hint,
        )
        if log_message:
            self._emit_log(log_message)
        return updated_messages

    def _restrict_media_placeholders_to_unread_context(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self._support.restrict_media_placeholders_to_unread_context(messages, self._pending_unread_hint)

    def _format_unread_preview_hint(self, hint: Dict[str, str]) -> str:
        return self._support.format_unread_preview_hint(hint)

    def _build_message_marker(self, user_name: str, latest_user_text: str, messages: List[Dict[str, Any]]) -> str:
        return self._support.build_message_marker(
            user_name,
            latest_user_text,
            messages,
            self._pending_unread_hint,
        )

    def _build_media_message_marker(self, user_name: str, latest_user_text: str) -> str:
        return self._support.build_media_message_marker(
            user_name,
            latest_user_text,
            self._pending_unread_hint,
        )

    def _is_duplicate_marker(self, marker: str, latest_user_text: str) -> bool:
        return self._support.is_duplicate_marker(
            marker,
            latest_user_text,
            last_processed_marker=self._last_processed_marker,
            recent_processed_media_markers=self._recent_processed_media_markers,
        )

    def _remember_processed_marker(self, marker: str, latest_user_text: str) -> None:
        self._last_processed_marker, self._recent_processed_media_markers = self._support.remember_processed_marker(
            marker,
            latest_user_text,
            last_processed_marker=self._last_processed_marker,
            recent_processed_media_markers=self._recent_processed_media_markers,
        )

    def _convert_history(self, messages: List[Dict[str, Any]], latest_user_text_override: str = None) -> List[Dict[str, str]]:
        return self._support.convert_history(messages, latest_user_text_override)

    def _mark_active_session(self, session_id: str, user_name: str, stage: str, detail: str = "") -> None:
        stage_text = str(stage or "").strip() or "unknown"
        context = {
            "session_id": str(session_id or ""),
            "user_name": str(user_name or ""),
            "stage": stage_text,
            "detail": str(detail or ""),
        }
        self._active_session_context = context

        stage_labels = {
            "chat_locked": "锁定当前会话",
            "send_pending": "进入发送阶段",
            "text_sent_wait_media": "文本已发，等待媒体",
            "sending_media": "正在发送媒体",
        }
        label = stage_labels.get(stage_text, stage_text)
        suffix = f"，{context['detail']}" if context["detail"] else ""
        self._emit_log(
            f"🔒 会话处理锁: {label}，用户={context['user_name'] or '-'}，session={context['session_id'] or '-'}{suffix}"
        )

    def _emit_active_session_release(self) -> None:
        context = self._active_session_context or {}
        session_id = str(context.get("session_id", "") or "")
        user_name = str(context.get("user_name", "") or "")
        stage = str(context.get("stage", "") or "")
        if not session_id and not user_name:
            return
        detail = f"，last_stage={stage}" if stage else ""
        self._emit_log(
            f"🔓 会话处理完成: 用户={user_name or '-'}，session={session_id or '-'}{detail}，准备轮询下一个未读"
        )

    def _hash_id(self, text: str) -> str:
        return self._support.hash_id(text)

    def _build_session_id(self, user_name: str, chat_session_key: str, chat_session_fingerprint: str = "") -> str:
        return self._support.build_session_id(user_name, chat_session_key, chat_session_fingerprint)

    def _build_user_hash(self, user_name: str, session_id: str) -> str:
        return self._support.build_user_hash(user_name, session_id)

    def _emit_stale_followup_status(self, message: str) -> None:
        text = str(message or "").strip()
        if not text or text == self._last_stale_followup_status:
            return
        self._last_stale_followup_status = text
        self._emit_log(f"🕒 {text}")

    def _find_stale_followup_candidate(self) -> tuple[Optional[Dict[str, str]], str]:
        root_dir = getattr(self.conversation_logger, "root_dir", None)
        if not isinstance(root_dir, Path) or not root_dir.exists():
            return None, "暂无会话日志，跳过1分钟结尾话术"

        now = datetime.now()
        by_user: Dict[str, Dict[str, Any]] = {}
        for log_path in sorted(root_dir.glob("*.jsonl")):
            try:
                rows = [x for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
            except Exception:
                continue

            for row in rows:
                try:
                    record = json.loads(row)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue

                event_type = str(record.get("event_type", "") or "")
                if event_type not in {"user_message", "assistant_reply", "stale_followup_sent"}:
                    continue

                user_hash = str(record.get("user_id_hash", "") or "").strip()
                if not user_hash:
                    continue

                timestamp = self._parse_iso_ts(str(record.get("timestamp", "") or ""))
                if timestamp is None:
                    continue

                payload = record.get("payload", {}) if isinstance(record.get("payload", {}), dict) else {}
                user_name = str(payload.get("user_name", "") or "").strip()
                session_id = str(record.get("session_id", "") or "")
                summary = by_user.setdefault(
                    user_hash,
                    {
                        "user_hash": user_hash,
                        "user_name": user_name,
                        "session_id": session_id,
                        "last_event_type": "",
                        "last_event_at": None,
                        "last_assistant_at": None,
                        "last_assistant_session_id": "",
                        "has_stale_followup": False,
                    },
                )
                if user_name:
                    summary["user_name"] = user_name
                if session_id:
                    summary["session_id"] = session_id
                if event_type == "stale_followup_sent" or str(record.get("rule_id", "") or "") == "STALE_FOLLOWUP":
                    summary["has_stale_followup"] = True
                if summary["last_event_at"] is None or timestamp > summary["last_event_at"]:
                    summary["last_event_at"] = timestamp
                    summary["last_event_type"] = event_type
                    summary["session_id"] = session_id or str(summary.get("session_id", "") or "")
                if event_type == "assistant_reply":
                    if summary["last_assistant_at"] is None or timestamp > summary["last_assistant_at"]:
                        summary["last_assistant_at"] = timestamp
                        summary["last_assistant_session_id"] = session_id

        eligible: List[Dict[str, Any]] = []
        blocked_by_log: List[str] = []
        waiting_for_timeout: List[str] = []
        waiting_for_reply_end: List[str] = []
        invalid_candidates: List[str] = []
        for summary in by_user.values():
            raw_user_name = str(summary.get("user_name", "") or "").strip()
            user_name = raw_user_name or "未知用户"
            cooldown_key = str(summary.get("user_hash", "") or user_name)
            skip_until = self._stale_followup_skip_until.get(cooldown_key)
            if isinstance(skip_until, datetime) and now < skip_until:
                continue
            if bool(summary.get("has_stale_followup", False)):
                blocked_by_log.append(user_name)
                continue
            if str(summary.get("last_event_type", "") or "") != "assistant_reply":
                waiting_for_reply_end.append(user_name)
                continue
            last_assistant_at = summary.get("last_assistant_at")
            if last_assistant_at is None:
                continue
            timeout_seconds = int(getattr(self, "_STALE_FOLLOWUP_AFTER_SECONDS", 60) or 60)
            if now - last_assistant_at < timedelta(seconds=timeout_seconds):
                waiting_for_timeout.append(user_name)
                continue
            if not raw_user_name:
                invalid_candidates.append(str(summary.get("session_id", "") or user_name))
                continue
            eligible.append(summary)

        if not eligible:
            if blocked_by_log:
                return None, f"跳过1分钟结尾话术：日志中已存在发送记录（{blocked_by_log[0]}）"
            if waiting_for_timeout:
                return None, f"跳过1分钟结尾话术：距离上次回复不足1分钟（{waiting_for_timeout[0]}）"
            if waiting_for_reply_end:
                return None, f"跳过1分钟结尾话术：最后一条不是客服回复（{waiting_for_reply_end[0]}）"
            if invalid_candidates:
                return None, f"跳过1分钟结尾话术：存在缺少用户名的历史记录（{invalid_candidates[0]}）"
            return None, "当前没有可触发的1分钟结尾话术候选"

        eligible.sort(key=lambda item: item.get("last_assistant_at") or now)
        chosen = eligible[0]
        return (
            {
                "user_hash": str(chosen.get("user_hash", "") or ""),
                "user_name": str(chosen.get("user_name", "") or ""),
                "session_id": str(chosen.get("last_assistant_session_id", "") or chosen.get("session_id", "") or ""),
            },
            "",
        )

    def _parse_iso_ts(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _detect_user_first_turn_global(self, user_hash: str) -> bool:
        if not user_hash:
            return False
        try:
            if hasattr(self.agent, "is_user_first_turn_global"):
                return bool(self.agent.is_user_first_turn_global(user_id_hash=user_hash))
            if hasattr(self.agent, "summarize_user_turns_from_logs"):
                turns = self.agent.summarize_user_turns_from_logs(user_id_hash=user_hash)
                return int((turns or {}).get("assistant_reply_count", 0) or 0) == 0
        except Exception:
            return False
        return False

    def _append_training_event(
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
        self.conversation_logger.append_event(
            session_id=session_id,
            user_id_hash=user_id_hash,
            event_type=event_type,
            payload=payload,
            user_name=user_name,
            reply_source=reply_source,
            rule_id=rule_id,
            model_name=model_name,
        )

    def _normalize_remote_control_command(self, text: str) -> str:
        normalized = str(text or "").strip().lower()
        return normalized if normalized in {"start", "stop"} else ""

    def _is_remote_control_user(self, user_name: str) -> bool:
        return str(user_name or "").strip() in self._remote_control_users

    def _handle_remote_control_command(self, session_id: str, user_name: str, user_hash: str, command: str) -> None:
        applied = False
        if command == "stop":
            applied = self.is_ai_enabled()
            self.pause_ai_for_remote_control()
            reply_text = "姐姐你好，已经关闭❤️"
            event_type = "remote_control_stop_applied" if applied else "remote_control_stop_noop"
            self._emit_log(f"🛰️ 远程 stop 命中: {user_name}")
        else:
            applied = not self.is_ai_enabled()
            self.resume_ai_from_remote_control()
            reply_text = "姐姐你好，已经启动🏃"
            event_type = "remote_control_start_applied" if applied else "remote_control_start_noop"
            self._emit_log(f"🛰️ 远程 start 命中: {user_name}")

        self._append_training_event(
            session_id=session_id,
            user_id_hash=user_hash,
            event_type=event_type,
            user_name=user_name,
            payload={
                "command": command,
                "applied": bool(applied),
                "user_name": user_name,
                "runtime_status": self.get_runtime_status().get("runtime_status", ""),
            },
        )

        def on_sent(success, result):
            if success:
                self.sessions.add_message(session_id, reply_text, is_user=False)
                self.sessions.record_reply(session_id)
                self.reply_sent.emit(session_id, reply_text)
                self._append_training_event(
                    session_id=session_id,
                    user_id_hash=user_hash,
                    event_type="assistant_reply",
                    user_name=user_name,
                    reply_source="remote_control",
                    rule_id=event_type,
                    payload={
                        "text": reply_text,
                        "intent": "remote_control",
                        "route_reason": "remote_control",
                        "round_media_sent": False,
                        "round_media_sent_types": [],
                        "round_media_failed_types": [],
                        "round_media_sent_details": [],
                    },
                )
            else:
                self._emit_log("❌ 远程控制反馈发送失败")
            self._reset_cycle()

        # 添加随机 emoji 到回复文本
        reply_text_with_emoji = add_random_emoji(
            reply_text,
            context="general",
            gender="male" if "帅哥" in reply_text else "female",
        )
        self.browser.send_message(reply_text_with_emoji, on_sent)

    def _log_chat_history(self, user_name: str, messages: List[Dict[str, Any]]):
        self._emit_log(f"📋 聊天记录: {user_name}，共 {len(messages)} 条")
        for msg in messages[-12:]:
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            role = "用户" if msg.get("is_user") else "客服"
            self._emit_log(f"{role}: {self._format_log_message_text(msg)}")

    def _format_log_message_text(self, msg: Dict[str, Any]) -> str:
        return self._support.format_log_message_text(msg)

    def _append_media_delivery_event(
        self,
        session_id: str,
        user_name: str,
        event_type: str,
        item: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        media_payload = {
            "media_type": str(item.get("type", "") or ""),
            "path": str(item.get("path", "") or ""),
            "target_store": str(item.get("target_store", "") or ""),
            "store_name": str(item.get("store_name", "") or ""),
            "store_address": str(item.get("store_address", "") or ""),
            "route_reason": str(item.get("route_reason", "") or ""),
            "failure_code": str(payload.get("failure_code", "") or ""),
            "retry_attempt": int(payload.get("retry_attempt", 0) or 0),
            "compensation_enqueued": bool(payload.get("compensation_enqueued", False)),
            "pending_media_id": str(payload.get("pending_media_id", "") or ""),
            "delivery_stage": str(payload.get("delivery_stage", "") or ""),
        }
        self._append_training_event(
            session_id=session_id,
            user_id_hash=self._build_user_hash(user_name=user_name, session_id=session_id),
            event_type=event_type,
            user_name=user_name,
            payload=media_payload,
        )

    def _media_event_name(self, media_type: str, stage: str) -> str:
        return self._support.media_event_name(media_type, stage)

    def _pending_media_id(self, item: Dict[str, Any]) -> str:
        return self._support.pending_media_id(item)

    def _extract_failure_code(self, result: Any) -> str:
        return self._support.extract_failure_code(result)

    def _extract_failure_detail(self, result: Any) -> str:
        return self._support.extract_failure_detail(result)

    def _emit_media_ui_log(self, media_type: str, message: str, level: str = "info") -> None:
        if media_type == "address_image":
            prefix = "[ADDR]"
        elif media_type == "contact_image":
            prefix = "[CONTACT]"
        else:
            prefix = "[MEDIA]"
        self._emit_log(f"{prefix} {message}", color="#ef4444", category="media", level=level)

    def _record_planned_required_media(
        self,
        session_id: str,
        user_name: str,
        media_queue: List[Dict[str, Any]],
    ) -> None:
        register = getattr(self.agent, "register_planned_required_media", None)
        if not callable(register):
            return
        try:
            planned_items = list(register(session_id=session_id, user_name=user_name, media_items=media_queue) or [])
        except Exception as exc:
            self._emit_log(f"⚠️ 必达媒体计划落盘失败，不影响发送: {exc}")
            return
        for item in planned_items:
            if not isinstance(item, dict):
                continue
            media_type = str(item.get("type", "") or "")
            pending_media_id = str(item.get("pending_media_id", "") or self._pending_media_id(item))
            self._append_media_delivery_event(
                session_id=session_id,
                user_name=user_name,
                event_type=self._media_event_name(media_type, "planned"),
                item=item,
                payload={
                    "media_type": media_type,
                    "delivery_stage": "planned",
                    "pending_media_id": pending_media_id,
                    "retry_attempt": 0,
                    "compensation_enqueued": False,
                    "failure_code": "",
                },
            )

    def _record_required_media_terminal_failure(
        self,
        session_id: str,
        user_name: str,
        item: Dict[str, Any],
        media_summary: Optional[Dict[str, List[str]]],
        failure_code: str,
        detail: str,
    ) -> None:
        media_type = str(item.get("type", "") or "")
        pending_media_id = str(item.get("pending_media_id", "") or self._pending_media_id(item))
        if media_summary is not None:
            media_summary.setdefault("failed_types", []).append(media_type)
        self._emit_media_ui_log(media_type, f"媒体发送失败: type={media_type}, detail={detail}", level="error")
        self._append_media_delivery_event(
            session_id=session_id,
            user_name=user_name,
            event_type=self._media_event_name(media_type, "failed"),
            item=item,
            payload={
                "media_type": media_type,
                "delivery_stage": "failed_terminal",
                "pending_media_id": pending_media_id,
                "retry_attempt": int(item.get("_retry_count", 0) or 0),
                "compensation_enqueued": False,
                "failure_code": failure_code,
            },
        )


class _DecisionWorker(QThread):
    """在后台线程里执行 Agent 决策，避免阻塞 UI 主线程。"""

    decision_ready = Signal(dict, object)
    decision_failed = Signal(dict, str)

    def __init__(
        self,
        agent: CustomerServiceAgent,
        payload: Dict[str, Any],
        session_manager: Optional[SessionManager] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._agent = agent
        self._payload = dict(payload or {})
        self._session_manager = session_manager

    def compute_decision(self, agent: CustomerServiceAgent, payload: Dict[str, Any]) -> AgentDecision:
        if payload.get("use_first_turn_opening", False):
            return payload["build_first_turn_opening_decision"](
                session_id=payload["session_id"],
                user_name=payload["user_name"],
            )
        decide_kwargs = {
            "session_id": payload["session_id"],
            "user_name": payload["user_name"],
            "latest_user_text": payload["latest_user_text"],
            "conversation_history": list(payload.get("conversation_history", []) or []),
            "first_turn_global_override": bool(payload.get("is_first_turn_global", False)),
        }
        try:
            signature = inspect.signature(agent.decide)
        except (TypeError, ValueError):
            signature = None
        if signature is None or "session_manager" in signature.parameters:
            decide_kwargs["session_manager"] = self._session_manager
        decision = agent.decide(**decide_kwargs)

        # 首轮视频注入：llm_direct 模式下 decide() 不会设置首轮视频，需在此补充
        if bool(payload.get("is_first_turn_global", False)) and not decision.first_turn_video_items:
            build_video_items = getattr(agent, "build_first_turn_video_items", None)
            if callable(build_video_items):
                try:
                    video_items = [
                        dict(x)
                        for x in (build_video_items(payload["session_id"]) or [])
                        if isinstance(x, dict)
                    ]
                    if video_items:
                        decision.is_first_turn_global = True
                        decision.first_turn_video_items = video_items
                except Exception:
                    pass

        return decision

    def run(self):
        try:
            decision = self.compute_decision(self._agent, self._payload)
            self.decision_ready.emit(dict(self._payload), decision)
        except Exception as exc:
            self.decision_failed.emit(dict(self._payload), str(exc))
