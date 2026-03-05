"""
消息处理器
单一编排链路：未读检测 -> 点击进入 -> 抓取聊天记录 -> Agent 决策 -> 发送文字/媒体。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, QTimer

from .private_cs_agent import AgentDecision, CustomerServiceAgent
from .session_manager import SessionManager
from ..services.browser_service import BrowserService
from ..services.conversation_logger import ConversationLogger


class MessageProcessor(QObject):
    """消息编排器"""

    status_changed = Signal(str)
    log_message = Signal(str)
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

        self._running = False
        self._page_ready = False
        self._poll_inflight = False
        self._processing_reply = False

        self._last_processed_marker = ""
        self._pending_send: Optional[Dict[str, Any]] = None

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_cycle)

        self.browser.page_loaded.connect(self._on_page_loaded)
        self.browser.url_changed.connect(self._on_url_changed)

    def start(self, interval_ms: int = 4000):
        if self._running:
            return
        if not self._page_ready:
            self.log_message.emit("⚠️ 页面未就绪，等待加载完成")
            return

        self._running = True
        self._poll_timer.start(interval_ms)
        self.status_changed.emit("running")
        self.log_message.emit("🚀 AI客服已启动")

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._poll_timer.stop()
        self._poll_inflight = False
        self._processing_reply = False
        self._pending_send = None
        self.status_changed.emit("stopped")
        self.log_message.emit("🛑 AI客服已停止")

    def is_running(self) -> bool:
        return self._running

    def force_check(self):
        if not self._poll_inflight:
            self._poll_cycle()

    def reload_media_config(self):
        """重载 Agent 媒体库索引"""
        self.agent.reload_media_library()
        self.agent.reload_rule_configs()
        self.log_message.emit("✅ 已重载媒体素材索引")

    def reload_keyword_config(self):
        """兼容旧入口：转发到媒体重载。"""
        self.reload_media_config()

    def reload_prompt_docs(self):
        success = self.agent.reload_prompt_docs()
        self.agent.reload_rule_configs()
        if success:
            self.log_message.emit("✅ 已重载系统 Prompt 与 Playbook 文档")
        else:
            self.log_message.emit("⚠️ Prompt 文档缺失，已使用默认兜底")

    def _on_page_loaded(self, success: bool):
        self._page_ready = success
        if success:
            self.status_changed.emit("ready")
            self.log_message.emit("✅ 页面加载完成")
        else:
            self.status_changed.emit("error")
            self.log_message.emit("❌ 页面加载失败")

    def _on_url_changed(self, url: str):
        self.log_message.emit(f"🌐 页面地址变化: {url}")

    def _poll_cycle(self):
        if not self._running or not self._page_ready or self._poll_inflight or self._processing_reply:
            return
        self._poll_inflight = True
        self._check_unread_and_enter()

    def _check_unread_and_enter(self):
        def on_result(success, result):
            if not success:
                self.log_message.emit("⚠️ 检查未读失败")
                self._reset_cycle()
                return

            payload = self._parse_js_payload(result)
            if payload.get("found") and payload.get("clicked"):
                self.log_message.emit(f"🔔 发现未读({payload.get('badgeText', 'dot')})，已点击进入")
                QTimer.singleShot(1000, self._grab_and_reply_active_chat)
                return

            self._reset_cycle()

        self.browser.find_and_click_first_unread(on_result)

    def _grab_and_reply_active_chat(self):
        if not self._running:
            self._reset_cycle()
            return

        self.browser.grab_chat_data(lambda success, result: self._on_chat_data(success, result, auto_reply=True))

    def grab_and_display_chat_history(self, auto_reply: bool = True):
        """手动抓取聊天记录（抓取测试按钮使用）"""
        self.browser.grab_chat_data(lambda success, result: self._on_chat_data(success, result, auto_reply=auto_reply))

    def _on_chat_data(self, success: bool, result: Any, auto_reply: bool):
        if not success:
            self.log_message.emit("❌ 抓取聊天记录失败")
            self._reset_cycle()
            return

        data = self._parse_js_payload(result)
        messages = data.get("messages", []) or []
        user_name = (data.get("user_name") or "未知用户").strip() or "未知用户"
        chat_session_key = (data.get("chat_session_key") or "").strip()
        chat_session_method = (data.get("chat_session_method") or "").strip()
        chat_session_fingerprint = (data.get("chat_session_fingerprint") or "").strip()

        if not messages:
            self.log_message.emit(f"⚠️ 用户 {user_name} 暂无可读消息")
            self._reset_cycle()
            return

        self._log_chat_history(user_name, messages)
        if not auto_reply:
            self._reset_cycle()
            return

        latest_user_message = self._latest_user_text(messages)
        if not latest_user_message:
            self.log_message.emit("⏸️ 最后一条不是用户消息，跳过自动回复")
            self._reset_cycle()
            return

        marker = self._build_message_marker(user_name, latest_user_message, messages)
        if marker == self._last_processed_marker:
            self.log_message.emit("⏸️ 检测到重复消息，跳过")
            self._reset_cycle()
            return

        self._last_processed_marker = marker
        self.message_received.emit({"user_name": user_name, "text": latest_user_message})

        session_id = self._build_session_id(
            user_name=user_name,
            chat_session_key=chat_session_key,
            chat_session_fingerprint=chat_session_fingerprint,
        )
        user_hash = self._build_user_hash(user_name=user_name, session_id=session_id)
        is_first_turn_global = self._detect_user_first_turn_global(user_hash=user_hash)
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
            payload={
                "text": latest_user_message,
                "user_name": user_name,
                "chat_session_key": chat_session_key,
                "chat_session_method": chat_session_method,
                "chat_session_fingerprint": chat_session_fingerprint,
                "is_first_turn_global": bool(is_first_turn_global),
            },
        )

        history = self._convert_history(messages)
        decision = self.agent.decide(
            session_id=session_id,
            user_name=user_name,
            latest_user_text=latest_user_message,
            conversation_history=history,
        )

        self.decision_ready.emit(
            {
                "session_id": session_id,
                "user_name": user_name,
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

        self.log_message.emit(
            f"🤖 Agent决策: source={decision.reply_source}, intent={decision.intent}, "
            f"route={decision.route_reason}, media={decision.media_plan}, rule={decision.rule_id or '-'}"
        )
        if decision.media_skip_reason == "first_turn_global_no_media":
            self.log_message.emit("ℹ️ 首轮媒体保护生效：本轮只发送文本，后续轮次满足条件会自动发图")
        self._append_training_event(
            session_id=session_id,
            user_id_hash=user_hash,
            event_type="decision_snapshot",
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
                "kb_repeat_rewritten": bool(decision.kb_repeat_rewritten),
                "purchase_both_first_hint_sent": bool(decision.purchase_both_first_hint_sent),
                "video_trigger_user_count": int(decision.video_trigger_user_count or 0),
            },
        )

        self._processing_reply = True
        self._pending_send = {
            "session_id": session_id,
            "user_name": user_name,
            "decision": decision,
        }

        self.log_message.emit("⏳ 等待3秒后发送回复...")
        QTimer.singleShot(3000, self._send_pending_decision)

    def _send_pending_decision(self):
        payload = self._pending_send
        if not payload:
            self._reset_cycle()
            return

        session_id = payload["session_id"]
        user_name = payload["user_name"]
        decision: AgentDecision = payload["decision"]

        def on_text_sent(success, result):
            if not success:
                self.log_message.emit("❌ 文本发送失败")
                self.error_occurred.emit("发送文本失败")
                self._reset_cycle()
                return

            self.log_message.emit(f"✅ 文本回复已发送: {decision.reply_text[:80]}")
            self.sessions.add_message(session_id, decision.reply_text, is_user=False)
            self.sessions.record_reply(session_id)
            self.reply_sent.emit(session_id, decision.reply_text)

            extra_video = self.agent.mark_reply_sent(session_id, user_name, decision.reply_text)
            media_queue = list(decision.media_items)
            if extra_video:
                media_queue.append(extra_video)

            media_summary = {"sent_types": [], "failed_types": [], "sent_details": [], "failed_details": []}
            self._send_media_queue(session_id, user_name, media_queue, decision=decision, media_summary=media_summary)

        self.browser.send_message(decision.reply_text, on_text_sent)

    def _send_media_queue(
        self,
        session_id: str,
        user_name: str,
        media_queue: List[Dict[str, Any]],
        decision: Optional[AgentDecision] = None,
        media_summary: Optional[Dict[str, List[str]]] = None,
    ):
        if not media_queue:
            if decision is not None:
                self._append_training_event(
                    session_id=session_id,
                    user_id_hash=self._build_user_hash(user_name=user_name, session_id=session_id),
                    event_type="assistant_reply",
                    reply_source=decision.reply_source,
                    rule_id=decision.rule_id,
                    model_name=decision.llm_model,
                    payload={
                        "text": decision.reply_text,
                        "intent": decision.intent,
                        "route_reason": decision.route_reason,
                        "llm_fallback_reason": decision.llm_fallback_reason,
                        "round_media_sent": bool((media_summary or {}).get("sent_types")),
                        "round_media_sent_types": list((media_summary or {}).get("sent_types", [])),
                        "round_media_failed_types": list((media_summary or {}).get("failed_types", [])),
                        "round_media_sent_details": list((media_summary or {}).get("sent_details", [])),
                        "is_first_turn_global": bool(decision.is_first_turn_global),
                        "first_turn_media_guard_applied": bool(decision.first_turn_media_guard_applied),
                        "kb_repeat_rewritten": bool(decision.kb_repeat_rewritten),
                        "purchase_both_first_hint_sent": bool(decision.purchase_both_first_hint_sent),
                        "kb_variant_total": int(decision.kb_variant_total or 0),
                        "kb_variant_selected_index": int(
                            decision.kb_variant_selected_index
                            if decision.kb_variant_selected_index is not None
                            else -1
                        ),
                        "kb_variant_fallback_llm": bool(decision.kb_variant_fallback_llm),
                        "force_contact_image": bool(decision.force_contact_image),
                        "kb_contact_trigger_type": str(decision.kb_contact_trigger_type or ""),
                    },
                )
            self._reset_cycle()
            return

        item = media_queue.pop(0)
        media_type = item.get("type", "unknown")
        media_path = item.get("path", "")
        if not media_path:
            self._send_media_queue(
                session_id,
                user_name,
                media_queue,
                decision=decision,
                media_summary=media_summary,
            )
            return

        self.log_message.emit(f"🖼️ 准备发送媒体: type={media_type}")
        self._append_training_event(
            session_id=session_id,
            user_id_hash=self._build_user_hash(user_name=user_name, session_id=session_id),
            event_type="media_attempt",
            payload={
                "type": media_type,
                "path": media_path,
                "target_store": item.get("target_store", ""),
                "store_name": item.get("store_name", ""),
                "store_address": item.get("store_address", ""),
                "detected_region": item.get("detected_region", ""),
                "route_reason": item.get("route_reason", ""),
            },
        )

        def on_media_sent(success, result):
            retry_count = int(item.get("_retry_count", 0) or 0)
            if not success and self._should_retry_media_send(
                media_type=media_type,
                result=result,
                retry_count=retry_count,
            ):
                self.log_message.emit(f"⚠️ 媒体发送未确认，准备重试: type={media_type}")
                self._append_training_event(
                    session_id=session_id,
                    user_id_hash=self._build_user_hash(user_name=user_name, session_id=session_id),
                    event_type="media_result",
                    payload={
                        "type": media_type,
                        "path": media_path,
                        "target_store": item.get("target_store", ""),
                        "store_name": item.get("store_name", ""),
                        "store_address": item.get("store_address", ""),
                        "detected_region": item.get("detected_region", ""),
                        "route_reason": item.get("route_reason", ""),
                        "success": False,
                        "retry_scheduled": True,
                        "retry_attempt": retry_count + 1,
                        "result": result if isinstance(result, (dict, str, int, float, bool, type(None))) else str(result),
                    },
                )
                retry_item = dict(item)
                retry_item["_retry_count"] = retry_count + 1
                self._send_media_queue(
                    session_id=session_id,
                    user_name=user_name,
                    media_queue=[retry_item] + list(media_queue),
                    decision=decision,
                    media_summary=media_summary,
                )
                return

            if success:
                self.log_message.emit(f"✅ 媒体发送成功: type={media_type}")
                if media_summary is not None:
                    media_summary.setdefault("sent_types", []).append(media_type)
                    media_summary.setdefault("sent_details", []).append(
                        {
                            "type": media_type,
                            "path": media_path,
                            "target_store": item.get("target_store", ""),
                            "store_name": item.get("store_name", ""),
                            "store_address": item.get("store_address", ""),
                            "detected_region": item.get("detected_region", ""),
                            "route_reason": item.get("route_reason", ""),
                        }
                    )
            else:
                detail = ""
                if isinstance(result, dict):
                    detail = result.get("error") or result.get("detail") or ""
                elif isinstance(result, str):
                    detail = result
                if detail:
                    self.log_message.emit(f"❌ 媒体发送失败: type={media_type}, detail={detail}")
                else:
                    self.log_message.emit(f"❌ 媒体发送失败: type={media_type}")
                if media_summary is not None:
                    media_summary.setdefault("failed_types", []).append(media_type)
                    media_summary.setdefault("failed_details", []).append(
                        {
                            "type": media_type,
                            "path": media_path,
                            "target_store": item.get("target_store", ""),
                            "store_name": item.get("store_name", ""),
                            "store_address": item.get("store_address", ""),
                            "detected_region": item.get("detected_region", ""),
                            "route_reason": item.get("route_reason", ""),
                        }
                    )
            self._append_training_event(
                session_id=session_id,
                user_id_hash=self._build_user_hash(user_name=user_name, session_id=session_id),
                event_type="media_result",
                payload={
                    "type": media_type,
                    "path": media_path,
                    "target_store": item.get("target_store", ""),
                    "store_name": item.get("store_name", ""),
                    "store_address": item.get("store_address", ""),
                    "detected_region": item.get("detected_region", ""),
                    "route_reason": item.get("route_reason", ""),
                    "success": bool(success),
                    "retry_scheduled": False,
                    "retry_attempt": retry_count,
                    "result": result if isinstance(result, (dict, str, int, float, bool, type(None))) else str(result),
                },
            )
            self.agent.mark_media_sent(session_id, user_name, item, success=bool(success))

            if media_queue:
                QTimer.singleShot(
                    1200,
                    lambda: self._send_media_queue(
                        session_id,
                        user_name,
                        media_queue,
                        decision=decision,
                        media_summary=media_summary,
                    ),
                )
            else:
                self._send_media_queue(
                    session_id,
                    user_name,
                    media_queue,
                    decision=decision,
                    media_summary=media_summary,
                )

        self.browser.send_image(media_path, on_media_sent)

    def _should_retry_media_send(self, media_type: str, result: Any, retry_count: int) -> bool:
        if media_type not in ("contact_image", "address_image"):
            return False
        if retry_count >= 1:
            return False

        if isinstance(result, dict):
            error_text = str(result.get("error") or result.get("detail") or "")
            step = str(result.get("step") or "")
            confirm_clicked = bool(result.get("confirmClicked", False))
            saw_pending_or_dialog = bool(result.get("sawPendingOrDialog", False))
            return (
                step == "verify_timeout"
                and "图片未检测到实际发送结果" in error_text
                and not confirm_clicked
                and not saw_pending_or_dialog
            )

        if isinstance(result, str):
            return "图片未检测到实际发送结果" in result
        return False

    def test_grab(self, callback: Callable = None):
        def on_data(success, data):
            if callback:
                callback(success, data)
                return
            if success:
                self.log_message.emit(f"测试抓取成功: {str(data)[:180]}")
            else:
                self.log_message.emit("测试抓取失败")

        self.browser.grab_chat_data(on_data)

    def _reset_cycle(self):
        self._poll_inflight = False
        self._processing_reply = False
        self._pending_send = None

    def _parse_js_payload(self, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        return {}

    def _latest_user_text(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return ""
        if not messages[-1].get("is_user", False):
            return ""
        return (messages[-1].get("text") or "").strip()

    def _build_message_marker(self, user_name: str, latest_user_text: str, messages: List[Dict[str, Any]]) -> str:
        user_count = len([m for m in messages if m.get("is_user")])
        raw = f"{user_name}|{latest_user_text}|{user_count}"
        return self._hash_id(raw)

    def _convert_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        history: List[Dict[str, str]] = []
        source = messages[:-1] if messages and messages[-1].get("is_user", False) else messages
        for msg in source[-12:]:
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            role = "user" if msg.get("is_user") else "assistant"
            history.append({"role": role, "content": text})
        return history

    def _hash_id(self, text: str) -> str:
        return hashlib.md5((text or "").encode("utf-8", errors="ignore")).hexdigest()[:10]

    def _build_session_id(self, user_name: str, chat_session_key: str, chat_session_fingerprint: str = "") -> str:
        key = (chat_session_key or "").strip()
        if key:
            return f"chat_{self._hash_id(key)}"
        user_key = f"user_{self._hash_id(user_name)}"
        fingerprint = (chat_session_fingerprint or "").strip()
        if not fingerprint:
            return user_key

        existing = self.agent.memory_store.get_existing_session_state(user_key)
        existing_fp = (existing or {}).get("session_fingerprint", "") if isinstance(existing, dict) else ""
        if not existing_fp or existing_fp == fingerprint:
            return user_key

        return f"{user_key}_{self._hash_id(fingerprint)[:6]}"

    def _build_user_hash(self, user_name: str, session_id: str) -> str:
        base = (user_name or "").strip() or session_id
        return self._hash_id(base)

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
        reply_source: str = "",
        rule_id: str = "",
        model_name: str = "",
    ) -> None:
        self.conversation_logger.append_event(
            session_id=session_id,
            user_id_hash=user_id_hash,
            event_type=event_type,
            payload=payload,
            reply_source=reply_source,
            rule_id=rule_id,
            model_name=model_name,
        )

    def _log_chat_history(self, user_name: str, messages: List[Dict[str, Any]]):
        self.log_message.emit(f"📋 聊天记录: {user_name}，共 {len(messages)} 条")
        for msg in messages[-12:]:
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            role = "用户" if msg.get("is_user") else "客服"
            self.log_message.emit(f"{role}: {text}")
