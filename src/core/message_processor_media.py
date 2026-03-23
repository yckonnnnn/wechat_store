"""
Media delivery coordinator for message processing.

This module extracts the queue draining, retry, compensation, and logging
behavior from MessageProcessor._send_media_queue into a standalone collaborator
that is wired entirely through injected callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from .private_cs_agent import AgentDecision

MediaItem = Dict[str, Any]
MediaSummary = Dict[str, List[str]]
ScheduleCallback = Callable[[int, Callable[[], None]], None]
SendResultCallback = Callable[[bool, Any], None]
SendImageCallback = Callable[[str, SendResultCallback], None]
SendVideoCallback = Callable[[SendResultCallback], None]
ClearInputCallback = Callable[[SendResultCallback], None]


@dataclass(frozen=True)
class MediaSendHooks:
    """Injected side effects used by the media queue coordinator."""

    send_image: SendImageCallback
    schedule: ScheduleCallback
    emit_log: Callable[[str], None]
    emit_media_ui_log: Callable[[str, str, str], None]
    append_training_event: Callable[..., None]
    append_media_delivery_event: Callable[[str, str, str, MediaItem, Dict[str, Any]], None]
    mark_media_sent: Callable[[str, str, MediaItem, bool], None]
    enqueue_media_compensation: Callable[[str, str, MediaItem, str, str], Optional[MediaItem]]
    build_user_hash: Callable[[str, str], str]
    media_event_name: Callable[[str, str], str]
    pending_media_id: Callable[[MediaItem], str]
    extract_failure_code: Callable[[Any], str]
    extract_failure_detail: Callable[[Any], str]
    should_retry_media_send: Callable[[str, Any, int], bool]
    reset_cycle: Callable[[], None]
    send_video_from_material_library: Optional[SendVideoCallback] = None
    clear_message_input: Optional[ClearInputCallback] = None
    mark_active_session: Optional[Callable[[str, str, str, str], None]] = None


class MediaSendCoordinator:
    """Drain a media queue while preserving the existing delivery semantics."""

    _RETRY_DELAY_MS = 1500
    _BETWEEN_ITEMS_DELAY_MS = 1200
    _DEFERRED_RETRY_DELAY_MS = 1200

    def __init__(self, hooks: MediaSendHooks):
        self._hooks = hooks

    def send_media_queue(
        self,
        session_id: str,
        user_name: str,
        media_queue: List[MediaItem],
        decision: Optional[AgentDecision] = None,
        media_summary: Optional[MediaSummary] = None,
        on_complete: Optional[Callable[[], None]] = None,
        defer_retry_media_types: Optional[Set[str]] = None,
        deferred_retry_items: Optional[List[MediaItem]] = None,
    ) -> None:
        self._drain_queue(
            session_id=session_id,
            user_name=user_name,
            media_queue=media_queue,
            decision=decision,
            media_summary=media_summary,
            on_complete=on_complete,
            defer_retry_media_types=set(defer_retry_media_types or set()),
            deferred_retry_items=deferred_retry_items,
        )

    def _drain_queue(
        self,
        session_id: str,
        user_name: str,
        media_queue: List[MediaItem],
        decision: Optional[AgentDecision],
        media_summary: Optional[MediaSummary],
        on_complete: Optional[Callable[[], None]],
        defer_retry_media_types: Set[str],
        deferred_retry_items: Optional[List[MediaItem]],
    ) -> None:
        if not media_queue:
            self._finalize_queue(
                session_id=session_id,
                user_name=user_name,
                decision=decision,
                media_summary=media_summary,
                on_complete=on_complete,
            )
            return

        item = media_queue.pop(0)
        media_type = str(item.get("type", "") or "unknown")
        media_path = str(item.get("path", "") or "")
        pending_media_id = str(item.get("pending_media_id", "") or self._hooks.pending_media_id(item))
        item["pending_media_id"] = pending_media_id

        if not media_path:
            self._record_required_media_terminal_failure(
                session_id=session_id,
                user_name=user_name,
                item=item,
                media_summary=media_summary,
                failure_code="missing_media_path",
                detail="媒体路径缺失",
            )
            self._drain_queue(
                session_id=session_id,
                user_name=user_name,
                media_queue=media_queue,
                decision=decision,
                media_summary=media_summary,
                on_complete=on_complete,
                defer_retry_media_types=defer_retry_media_types,
                deferred_retry_items=deferred_retry_items,
            )
            return

        self._mark_active_session(
            session_id=session_id,
            user_name=user_name,
            stage="sending_media",
            detail=f"type={media_type}",
        )
        self._emit_media_start_log(media_type, item)
        self._emit_media_prepare_log(media_type)
        self._append_media_planned_events(
            session_id=session_id,
            user_name=user_name,
            media_type=media_type,
            item=item,
            pending_media_id=pending_media_id,
        )

        def on_media_sent(success: bool, result: Any) -> None:
            self._handle_media_sent(
                session_id=session_id,
                user_name=user_name,
                media_queue=media_queue,
                item=item,
                media_type=media_type,
                media_path=media_path,
                pending_media_id=pending_media_id,
                success=success,
                result=result,
                decision=decision,
                media_summary=media_summary,
                on_complete=on_complete,
                defer_retry_media_types=defer_retry_media_types,
                deferred_retry_items=deferred_retry_items,
            )

        def send_media_after_clear() -> None:
            if media_type == "delayed_video":
                send_video = self._hooks.send_video_from_material_library
                if callable(send_video):
                    send_video(on_media_sent)
                    return
            self._hooks.send_image(media_path, on_media_sent)

        clear_input = self._hooks.clear_message_input
        if callable(clear_input):

            def on_input_cleared(success: bool, result: Any) -> None:
                if not success:
                    self._hooks.emit_media_ui_log(
                        media_type,
                        f"发送媒体前清空输入框失败: {result}，继续尝试发送",
                        level="warning",
                    )
                send_media_after_clear()

            clear_input(on_input_cleared)
            return

        send_media_after_clear()

    def _handle_media_sent(
        self,
        session_id: str,
        user_name: str,
        media_queue: List[MediaItem],
        item: MediaItem,
        media_type: str,
        media_path: str,
        pending_media_id: str,
        success: bool,
        result: Any,
        decision: Optional[AgentDecision],
        media_summary: Optional[MediaSummary],
        on_complete: Optional[Callable[[], None]],
        defer_retry_media_types: Set[str],
        deferred_retry_items: Optional[List[MediaItem]],
    ) -> None:
        retry_count = int(item.get("_retry_count", 0) or 0)
        failure_code = self._hooks.extract_failure_code(result)
        detail = self._hooks.extract_failure_detail(result)
        compensation_enqueued = False

        if not success and self._hooks.should_retry_media_send(media_type=media_type, result=result, retry_count=retry_count):
            retry_item = dict(item)
            retry_item["_retry_count"] = retry_count + 1

            if media_type in defer_retry_media_types and deferred_retry_items is not None:
                self._emit_retry_log(media_type, item, retry_count, failure_code, deferred=True)
                deferred_retry_items.append(retry_item)
                self._append_training_event(
                    session_id=session_id,
                    user_name=user_name,
                    user_id_hash=self._hooks.build_user_hash(user_name=user_name, session_id=session_id),
                    event_type="media_result",
                    payload=self._build_media_result_payload(
                        item=item,
                        media_type=media_type,
                        media_path=media_path,
                        success=False,
                        retry_scheduled=True,
                        retry_attempt=retry_count + 1,
                        delivery_stage="retry_deferred",
                        failure_code=failure_code,
                        compensation_enqueued=False,
                        pending_media_id=pending_media_id,
                        result=result,
                    ),
                )
                self._schedule_next(
                    self._DEFERRED_RETRY_DELAY_MS,
                    lambda: self._drain_queue(
                        session_id=session_id,
                        user_name=user_name,
                        media_queue=media_queue,
                        decision=decision,
                        media_summary=media_summary,
                        on_complete=on_complete,
                        defer_retry_media_types=defer_retry_media_types,
                        deferred_retry_items=deferred_retry_items,
                    ),
                )
                return

            self._append_training_event(
                session_id=session_id,
                user_name=user_name,
                user_id_hash=self._hooks.build_user_hash(user_name=user_name, session_id=session_id),
                event_type="media_result",
                payload=self._build_media_result_payload(
                    item=item,
                    media_type=media_type,
                    media_path=media_path,
                    success=False,
                    retry_scheduled=True,
                    retry_attempt=retry_count + 1,
                    delivery_stage="retrying",
                    failure_code=failure_code,
                    compensation_enqueued=False,
                    pending_media_id=pending_media_id,
                    result=result,
                ),
            )
            self._hooks.append_media_delivery_event(
                session_id,
                user_name,
                self._hooks.media_event_name(media_type, "retry"),
                item,
                {
                    "media_type": media_type,
                    "delivery_stage": "retrying",
                    "pending_media_id": pending_media_id,
                    "retry_attempt": retry_count + 1,
                    "compensation_enqueued": False,
                    "failure_code": failure_code,
                },
            )
            self._schedule_next(
                self._RETRY_DELAY_MS,
                lambda: self._drain_queue(
                    session_id=session_id,
                    user_name=user_name,
                    media_queue=[retry_item, *list(media_queue)],
                    decision=decision,
                    media_summary=media_summary,
                    on_complete=on_complete,
                    defer_retry_media_types=defer_retry_media_types,
                    deferred_retry_items=deferred_retry_items,
                ),
            )
            return

        if success:
            self._hooks.emit_media_ui_log(media_type, f"媒体发送成功: type={media_type}", level="success")
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
                        "trigger_source": item.get("trigger_source", ""),
                    }
                )
            self._hooks.append_media_delivery_event(
                session_id,
                user_name,
                self._hooks.media_event_name(media_type, "success"),
                item,
                {
                    "media_type": media_type,
                    "delivery_stage": "sent",
                    "pending_media_id": pending_media_id,
                    "retry_attempt": retry_count,
                    "compensation_enqueued": False,
                    "failure_code": "",
                },
            )
        else:
            self._emit_media_failure_log(media_type=media_type, result=result, detail=detail)
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
                        "trigger_source": item.get("trigger_source", ""),
                    }
                )
            if not bool(item.get("disable_compensation", False)):
                pending_item = self._hooks.enqueue_media_compensation(
                    session_id=session_id,
                    user_name=user_name,
                    media_item=item,
                    failure_code=failure_code,
                    failure_detail=detail,
                )
                compensation_enqueued = bool(pending_item)
                if compensation_enqueued:
                    self._hooks.emit_media_ui_log(
                        media_type,
                        f"媒体进入待补发队列: type={media_type}, failure={failure_code or 'unknown'}",
                        level="warning",
                    )
                    self._hooks.append_media_delivery_event(
                        session_id,
                        user_name,
                        self._hooks.media_event_name(media_type, "pending_compensation"),
                        pending_item,
                        {
                            "media_type": media_type,
                            "delivery_stage": "pending_compensation",
                            "pending_media_id": str(pending_item.get("pending_media_id", "") or pending_media_id),
                            "retry_attempt": retry_count,
                            "compensation_enqueued": True,
                            "failure_code": failure_code,
                        },
                    )
                else:
                    self._hooks.append_media_delivery_event(
                        session_id,
                        user_name,
                        self._hooks.media_event_name(media_type, "failed"),
                        item,
                        {
                            "media_type": media_type,
                            "delivery_stage": "failed_terminal",
                            "pending_media_id": pending_media_id,
                            "retry_attempt": retry_count,
                            "compensation_enqueued": False,
                            "failure_code": failure_code,
                        },
                    )
            else:
                self._hooks.append_media_delivery_event(
                    session_id,
                    user_name,
                    self._hooks.media_event_name(media_type, "failed"),
                    item,
                    {
                        "media_type": media_type,
                        "delivery_stage": "failed_terminal",
                        "pending_media_id": pending_media_id,
                        "retry_attempt": retry_count,
                        "compensation_enqueued": False,
                        "failure_code": failure_code,
                    },
                )

        self._append_training_event(
            session_id=session_id,
            user_name=user_name,
            user_id_hash=self._hooks.build_user_hash(user_name=user_name, session_id=session_id),
            event_type="media_result",
            payload=self._build_media_result_payload(
                item=item,
                media_type=media_type,
                media_path=media_path,
                success=bool(success),
                retry_scheduled=False,
                retry_attempt=retry_count,
                delivery_stage="sent" if success else ("pending_compensation" if compensation_enqueued else "failed_terminal"),
                failure_code="" if success else failure_code,
                compensation_enqueued=compensation_enqueued,
                pending_media_id=pending_media_id,
                result=result,
            ),
        )
        self._hooks.mark_media_sent(session_id, user_name, item, bool(success))

        if media_queue:
            self._schedule_next(
                self._BETWEEN_ITEMS_DELAY_MS,
                lambda: self._drain_queue(
                    session_id=session_id,
                    user_name=user_name,
                    media_queue=media_queue,
                    decision=decision,
                    media_summary=media_summary,
                    on_complete=on_complete,
                    defer_retry_media_types=defer_retry_media_types,
                    deferred_retry_items=deferred_retry_items,
                ),
            )
            return

        self._drain_queue(
            session_id=session_id,
            user_name=user_name,
            media_queue=media_queue,
            decision=decision,
            media_summary=media_summary,
            on_complete=on_complete,
            defer_retry_media_types=defer_retry_media_types,
            deferred_retry_items=deferred_retry_items,
        )

    def _finalize_queue(
        self,
        session_id: str,
        user_name: str,
        decision: Optional[AgentDecision],
        media_summary: Optional[MediaSummary],
        on_complete: Optional[Callable[[], None]],
    ) -> None:
        if decision is not None:
            self._append_assistant_reply_event(session_id, user_name, decision, media_summary)
        if on_complete is not None:
            on_complete()
            return
        self._hooks.reset_cycle()

    def _append_assistant_reply_event(
        self,
        session_id: str,
        user_name: str,
        decision: AgentDecision,
        media_summary: Optional[MediaSummary],
    ) -> None:
        self._hooks.append_training_event(
            session_id=session_id,
            user_id_hash=self._hooks.build_user_hash(user_name=user_name, session_id=session_id),
            event_type="assistant_reply",
            user_name=user_name,
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
                    decision.kb_variant_selected_index if decision.kb_variant_selected_index is not None else -1
                ),
                "kb_variant_fallback_llm": bool(decision.kb_variant_fallback_llm),
                "force_contact_image": bool(decision.force_contact_image),
                "kb_contact_trigger_type": str(decision.kb_contact_trigger_type or ""),
            },
        )

    def _build_media_result_payload(
        self,
        item: MediaItem,
        media_type: str,
        media_path: str,
        success: bool,
        retry_scheduled: bool,
        retry_attempt: int,
        delivery_stage: str,
        failure_code: str,
        compensation_enqueued: bool,
        pending_media_id: str,
        result: Any,
    ) -> Dict[str, Any]:
        return {
            "type": media_type,
            "path": media_path,
            "target_store": item.get("target_store", ""),
            "store_name": item.get("store_name", ""),
            "store_address": item.get("store_address", ""),
            "detected_region": item.get("detected_region", ""),
            "route_reason": item.get("route_reason", ""),
            "trigger_source": item.get("trigger_source", ""),
            "success": bool(success),
            "retry_scheduled": bool(retry_scheduled),
            "retry_attempt": int(retry_attempt),
            "delivery_stage": delivery_stage,
            "failure_code": failure_code if not success else "",
            "compensation_enqueued": bool(compensation_enqueued),
            "pending_media_id": pending_media_id,
            "result": self._serialize_result(result),
        }

    def _append_training_event(self, **kwargs: Any) -> None:
        self._hooks.append_training_event(**kwargs)

    def _mark_active_session(self, session_id: str, user_name: str, stage: str, detail: str) -> None:
        if callable(self._hooks.mark_active_session):
            self._hooks.mark_active_session(session_id, user_name, stage, detail)

    def _schedule_next(self, delay_ms: int, callback: Callable[[], None]) -> None:
        if delay_ms <= 0:
            callback()
            return
        self._hooks.schedule(delay_ms, callback)

    def _emit_media_start_log(self, media_type: str, item: MediaItem) -> None:
        if media_type == "delayed_video":
            trigger_source = str(item.get("trigger_source", "") or "")
            retry_count = int(item.get("_retry_count", 0) or 0)
            if trigger_source == "first_reply":
                self._hooks.emit_media_ui_log(
                    media_type,
                    f"开始触发首轮视频发送 (重试次数: {retry_count}/2)",
                    level="info",
                )
            elif trigger_source:
                self._hooks.emit_media_ui_log(
                    media_type,
                    f"开始触发视频发送: source={trigger_source} (重试次数: {retry_count}/2)",
                    level="info",
                )
            else:
                self._hooks.emit_media_ui_log(
                    media_type,
                    f"开始触发视频发送 (重试次数: {retry_count}/2)",
                    level="info",
                )

    def _emit_media_prepare_log(self, media_type: str) -> None:
        self._hooks.emit_media_ui_log(media_type, f"准备发送媒体: type={media_type}", level="info")

    def _append_media_planned_events(
        self,
        session_id: str,
        user_name: str,
        media_type: str,
        item: MediaItem,
        pending_media_id: str,
    ) -> None:
        self._append_training_event(
            session_id=session_id,
            user_id_hash=self._hooks.build_user_hash(user_name=user_name, session_id=session_id),
            event_type="media_attempt",
            user_name=user_name,
            payload={
                "type": media_type,
                "media_type": media_type,
                "path": str(item.get("path", "") or ""),
                "target_store": item.get("target_store", ""),
                "store_name": item.get("store_name", ""),
                "store_address": item.get("store_address", ""),
                "detected_region": item.get("detected_region", ""),
                "route_reason": item.get("route_reason", ""),
                "trigger_source": item.get("trigger_source", ""),
                "delivery_stage": "attempting",
                "failure_code": "",
                "retry_attempt": int(item.get("_retry_count", 0) or 0),
                "compensation_enqueued": False,
                "pending_media_id": pending_media_id,
            },
        )
        self._hooks.append_media_delivery_event(
            session_id,
            user_name,
            self._hooks.media_event_name(media_type, "attempt"),
            item,
            {
                "media_type": media_type,
                "delivery_stage": "attempting",
                "pending_media_id": pending_media_id,
                "retry_attempt": int(item.get("_retry_count", 0) or 0),
                "compensation_enqueued": False,
                "failure_code": "",
            },
        )

    def _emit_retry_log(self, media_type: str, item: MediaItem, retry_count: int, failure_code: str, deferred: bool) -> None:
        if media_type == "delayed_video":
            trigger_source = str(item.get("trigger_source", "") or "")
            if trigger_source == "first_reply":
                prefix = "首轮视频发送失败"
            else:
                prefix = "视频发送失败"
            if deferred:
                self._hooks.emit_media_ui_log(
                    media_type,
                    f"⚠️ {prefix}，先继续后续流程，尾部重试一次 ({retry_count + 1}/2): failure={failure_code or 'unknown'}",
                    level="warning",
                )
            else:
                self._hooks.emit_media_ui_log(
                    media_type,
                    f"⚠️ {prefix}，立即重试 ({retry_count + 1}/2): failure={failure_code or 'unknown'}",
                    level="warning",
                )
            return

        if media_type in ("address_image", "contact_image"):
            if deferred:
                self._hooks.emit_media_ui_log(
                    media_type,
                    f"⚠️ 图片发送未确认，先继续后续流程，尾部重试一次 ({retry_count + 1}/2): type={media_type}, failure={failure_code or 'unknown'}",
                    level="warning",
                )
            else:
                self._hooks.emit_media_ui_log(
                    media_type,
                    f"⚠️ 图片发送失败，立即重试 ({retry_count + 1}/2): type={media_type}, failure={failure_code or 'unknown'}",
                    level="warning",
                )
            return

        if deferred:
            self._hooks.emit_media_ui_log(
                media_type,
                f"媒体发送未确认，先继续后续流程，尾部重试一次: type={media_type}, failure={failure_code or 'unknown'}",
                level="warning",
            )
        else:
            self._hooks.emit_media_ui_log(
                media_type,
                f"媒体发送未确认，准备重试: type={media_type}, failure={failure_code or 'unknown'}",
                level="warning",
            )

    def _emit_media_failure_log(self, media_type: str, result: Any, detail: str) -> None:
        failure_code = self._hooks.extract_failure_code(result)
        step = str((result or {}).get("step", "") or "") if isinstance(result, dict) else ""
        if detail:
            self._hooks.emit_media_ui_log(
                media_type,
                f"媒体发送失败: type={media_type}, detail={detail}, failure={failure_code or 'unknown'}, step={step}",
                level="error",
            )
        else:
            self._hooks.emit_media_ui_log(
                media_type,
                f"媒体发送失败: type={media_type}, failure={failure_code or 'unknown'}, step={step}",
                level="error",
            )

    def _record_required_media_terminal_failure(
        self,
        session_id: str,
        user_name: str,
        item: MediaItem,
        media_summary: Optional[MediaSummary],
        failure_code: str,
        detail: str,
    ) -> None:
        media_type = str(item.get("type", "") or "")
        pending_media_id = str(item.get("pending_media_id", "") or self._hooks.pending_media_id(item))
        if media_summary is not None:
            media_summary.setdefault("failed_types", []).append(media_type)
        self._hooks.emit_media_ui_log(media_type, f"媒体发送失败: type={media_type}, detail={detail}", level="error")
        self._hooks.append_media_delivery_event(
            session_id,
            user_name,
            self._hooks.media_event_name(media_type, "failed"),
            item,
            {
                "media_type": media_type,
                "delivery_stage": "failed_terminal",
                "pending_media_id": pending_media_id,
                "retry_attempt": int(item.get("_retry_count", 0) or 0),
                "compensation_enqueued": False,
                "failure_code": failure_code,
            },
        )

    def _serialize_result(self, result: Any) -> Any:
        if isinstance(result, (dict, str, int, float, bool)) or result is None:
            return result
        return str(result)
