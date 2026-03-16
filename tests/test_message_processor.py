import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Signal, QTimer

from src.core.message_processor import MessageProcessor
from src.core.private_cs_agent import AgentDecision, CustomerServiceAgent
from src.core.session_manager import SessionManager
from src.data.memory_store import MemoryStore
from src.services.conversation_logger import ConversationLogger


class DummyBrowser(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text, callback

    def send_image(self, media_path, callback):
        del media_path, callback

    def send_video_from_material_library(self, callback):
        del callback


class DummyAgent:
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store

    def reload_media_library(self):
        return None

    def reload_rule_configs(self):
        return None

    def reload_prompt_docs(self):
        return True

    def build_post_text_media_queue(self, session_id: str, user_name: str, planned_media_items, extra_media_items=None):
        del session_id, user_name
        queue = list(planned_media_items or [])
        queue.extend(list(extra_media_items or []))
        return queue


class DummyBrowserFlow(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        callback(True, {"ok": True})


class DummyBrowserStaleFollowup(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self, user_name: str):
        super().__init__()
        self.user_name = user_name
        self.sent_messages = []

    def find_and_click_first_unread(self, callback):
        callback(True, {"found": False, "clicked": False})

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names
        callback(True, {"found": False, "clicked": False})

    def find_and_click_chat_by_username(self, user_name, callback):
        callback(True, {"found": user_name == self.user_name, "clicked": user_name == self.user_name})

    def grab_chat_data(self, callback):
        callback(
            True,
            {
                "user_name": self.user_name,
                "chat_session_key": "",
                "chat_session_fingerprint": f"name:{self.user_name}",
                "messages": [{"text": "历史客服", "is_user": False}],
            },
        )

    def send_message(self, text, callback):
        self.sent_messages.append(text)
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        callback(True, {"ok": True})


class DummyBrowserFlowRetry(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.image_send_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        self.image_send_calls += 1
        if self.image_send_calls == 1:
            callback(
                False,
                {
                    "error": "图片未检测到实际发送结果",
                    "step": "verify_timeout",
                    "confirmClicked": False,
                    "sawPendingOrDialog": False,
                },
            )
            return
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        callback(True, {"ok": True})


class DummyAgentFlow:
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store
        self.mark_reply_sent_calls = []

    def reload_media_library(self):
        return None

    def reload_rule_configs(self):
        return None

    def reload_prompt_docs(self):
        return True

    def decide(self, session_id: str, user_name: str, latest_user_text: str, conversation_history=None, first_turn_global_override=None):
        del session_id, user_name, latest_user_text, conversation_history, first_turn_global_override
        decision = AgentDecision(
            reply_text="姐姐我马上帮您安排～🌹",
            intent="purchase",
            route_reason="known_geo_context",
            reply_goal="推进购买意图",
            media_plan="contact_image",
            media_items=[
                {
                    "type": "contact_image",
                    "path": "dummy.jpg",
                    "target_store": "sh_xuhui",
                    "store_name": "上海徐汇门店",
                    "store_address": "徐汇区漕溪北路45号中航德必大厦",
                    "detected_region": "闵行",
                    "route_reason": "sh_district_map:闵行",
                }
            ],
            reply_source="rule",
            rule_id="PURCHASE_TEST",
            rule_applied=True,
            geo_context_source="session_last_target_store",
            media_skip_reason="",
            both_images_sent_state=True,
            kb_blocked_by_polite_guard=True,
            kb_polite_guard_reason="polite_mixed_query",
            is_first_turn_global=True,
            first_turn_media_guard_applied=False,
            kb_repeat_rewritten=True,
            purchase_both_first_hint_sent=True,
            video_trigger_user_count=2,
        )
        decision.first_turn_image_items = [dict(x) for x in decision.media_items]
        decision.first_turn_text_required = True
        return decision

    def is_user_first_turn_global(self, user_id_hash: str) -> bool:
        del user_id_hash
        return True

    def mark_reply_sent(self, session_id: str, user_name: str, reply_text: str, *, is_first_turn_global: bool = False):
        self.mark_reply_sent_calls.append(
            {
                "session_id": session_id,
                "user_name": user_name,
                "reply_text": reply_text,
                "is_first_turn_global": is_first_turn_global,
            }
        )
        return None

    def build_post_text_media_queue(self, session_id: str, user_name: str, planned_media_items, extra_media_items=None):
        del session_id, user_name
        queue = list(planned_media_items or [])
        queue.extend(list(extra_media_items or []))
        return queue

    def mark_media_sent(self, session_id: str, user_name: str, media_item, success: bool):
        del session_id, user_name, media_item, success
        return None

    def enqueue_media_compensation(self, session_id: str, user_name: str, media_item, failure_code: str = "", failure_detail: str = ""):
        del session_id, user_name, failure_code, failure_detail
        queued = dict(media_item)
        queued["pending_media_id"] = "contact_image"
        return queued


class DummyAgentFlowFirstReplyVideo(DummyAgentFlow):
    def decide(self, session_id: str, user_name: str, latest_user_text: str, conversation_history=None, first_turn_global_override=None):
        decision = super().decide(session_id, user_name, latest_user_text, conversation_history, first_turn_global_override)
        decision.first_turn_image_items = [dict(x) for x in decision.media_items]
        decision.first_turn_video_items = [
            {
                "type": "delayed_video",
                "path": "video.mp4",
                "trigger_source": "first_reply",
            }
        ]
        return decision


class DummyAgentFlowFirstTurnImageAndVideo(DummyAgentFlow):
    def decide(self, session_id: str, user_name: str, latest_user_text: str, conversation_history=None, first_turn_global_override=None):
        decision = super().decide(session_id, user_name, latest_user_text, conversation_history, first_turn_global_override)
        decision.first_turn_image_items = [dict(x) for x in decision.media_items]
        decision.first_turn_video_items = [
            {
                "type": "delayed_video",
                "path": "video.mp4",
                "trigger_source": "first_reply",
            }
        ]
        return decision


class DummyBrowserFirstTurnSequence(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.sequence = []

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        self.sequence.append("text")
        del text
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        self.sequence.append("image")
        del media_path
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        self.sequence.append("video")
        callback(True, {"ok": True})


class DummyKnowledgeServiceNoMatch:
    def is_address_query(self, text: str) -> bool:
        del text
        return False

    def is_purchase_intent(self, text: str) -> bool:
        del text
        return False


class DummyBrowserFlowCompensation(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.image_send_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        self.image_send_calls += 1
        callback(
            False,
            {
                "error": "点击图片按钮失败",
                "step": "native_click_image_button",
                "failure_code": "native_click_image_button_failed",
            },
        )

    def send_video_from_material_library(self, callback):
        callback(
            False,
            {
                "error": "点击视频发送按钮失败",
                "step": "click_video_send_button",
                "failure_code": "click_video_send_button_failed",
            },
        )


class DummyBrowserDuplicateOnImage(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.composer_text = ""
        self.sent_messages = []
        self.clear_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        self.composer_text = text
        self.sent_messages.append(text)
        callback(True, {"ok": True})

    def clear_message_input(self, callback):
        self.clear_calls += 1
        self.composer_text = ""
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        if self.composer_text:
            self.sent_messages.append(self.composer_text)
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        if self.composer_text:
            self.sent_messages.append(self.composer_text)
        callback(True, {"ok": True})


class DummyBrowserUnreadClick(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def find_and_click_first_unread(self, callback):
        callback(True, {"found": True, "clicked": True, "badgeText": "1"})

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text, callback

    def send_image(self, media_path, callback):
        del media_path, callback

    def send_video_from_material_library(self, callback):
        del callback


class DummyBrowserDelayedTextThenImage(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.pending_text = ""
        self.sent_messages = []
        self.clear_calls = 0
        self.image_send_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        self.pending_text = text

        def commit_text():
            if self.pending_text:
                self.sent_messages.append(self.pending_text)
                self.pending_text = ""

        QTimer.singleShot(300, commit_text)
        callback(True, {"ok": True})

    def clear_message_input(self, callback):
        self.clear_calls += 1
        self.pending_text = ""
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        self.image_send_calls += 1
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        callback(True, {"ok": True})


class DummyBrowserVideoRoute(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.media_debug_hook = None
        self.clear_calls = 0
        self.image_send_calls = 0
        self.video_send_calls = 0
        self.sent_messages = []

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        self.sent_messages.append(text)
        callback(True, {"ok": True})

    def clear_message_input(self, callback):
        self.clear_calls += 1
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        self.image_send_calls += 1
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        self.video_send_calls += 1
        callback(True, {"ok": True})


class DummyBrowserVideoRouteWithDebug(DummyBrowserVideoRoute):
    def send_video_from_material_library(self, callback):
        self.video_send_calls += 1
        if callable(self.media_debug_hook):
            self.media_debug_hook(
                {
                    "media_type": "delayed_video",
                    "message": "素材库Tab点击成功",
                    "level": "info",
                    "step": "material_tab_clicked",
                }
            )
            self.media_debug_hook(
                {
                    "media_type": "delayed_video",
                    "message": "视频Tab点击成功",
                    "level": "info",
                    "step": "video_tab_clicked",
                }
            )
        callback(True, {"ok": True})


class DummyBrowserVideoRouteRetry(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.clear_calls = 0
        self.image_send_calls = 0
        self.video_send_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text
        callback(True, {"ok": True})

    def clear_message_input(self, callback):
        self.clear_calls += 1
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        self.image_send_calls += 1
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        self.video_send_calls += 1
        if self.video_send_calls == 1:
            callback(
                False,
                {
                    "error": "视频未检测到实际发送结果",
                    "step": "verify_timeout",
                    "failure_code": "video_verify_timeout",
                },
            )
            return
        callback(True, {"ok": True})


class DummyBrowserVideoDragRetry(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.clear_calls = 0
        self.image_send_calls = 0
        self.video_send_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text
        callback(True, {"ok": True})

    def clear_message_input(self, callback):
        self.clear_calls += 1
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        self.image_send_calls += 1
        callback(True, {"ok": True})

    def send_video_from_material_library(self, callback):
        self.video_send_calls += 1
        if self.video_send_calls == 1:
            callback(
                False,
                {
                    "error": "拖拽后未出现发送确认框",
                    "step": "drag_video_to_chat",
                    "failure_code": "drag_video_to_chat_failed",
                },
            )
            return
        callback(True, {"ok": True})


class MessageProcessorSessionIdTestCase(unittest.TestCase):
    def test_contact_request_phrases_detect_as_contact_intent(self):
        agent = CustomerServiceAgent.__new__(CustomerServiceAgent)
        agent.knowledge_service = DummyKnowledgeServiceNoMatch()

        self.assertEqual(agent._detect_intent("怎么加你们？"), "contact")
        self.assertEqual(agent._detect_intent("你的联系方式"), "contact")
        self.assertTrue(agent._looks_like_direct_contact_request("如何添加你们微信"))

    def test_conversation_logger_uses_user_name_and_date_filename(self):
        with tempfile.TemporaryDirectory() as td:
            logger = ConversationLogger(Path(td) / "conversations")
            log_path = logger._session_file("user_abc123", user_name=' 张 三 /:*? ')
            self.assertEqual(log_path.name, f"张_三_{datetime.now().strftime('%Y-%m-%d')}.jsonl")

            fallback_path = logger._session_file("user_abc123")
            self.assertEqual(fallback_path.name, "user_abc123.jsonl")

    def test_fallback_session_id_splits_by_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowser()
            sessions = SessionManager()
            agent = DummyAgent(memory_store)
            processor = MessageProcessor(browser, sessions, agent)

            user_name = "同名用户"

            base_session = processor._build_session_id(
                user_name=user_name,
                chat_session_key="",
                chat_session_fingerprint="fp_a",
            )
            self.assertTrue(base_session.startswith("user_"))

            user_hash = processor._build_user_hash(user_name=user_name, session_id=base_session)
            memory_store.update_session_state(
                session_id=base_session,
                updates={"session_fingerprint": "fp_a"},
                user_hash=user_hash,
            )

            same_fp_session = processor._build_session_id(
                user_name=user_name,
                chat_session_key="",
                chat_session_fingerprint="fp_a",
            )
            self.assertEqual(same_fp_session, base_session)

            split_session = processor._build_session_id(
                user_name=user_name,
                chat_session_key="",
                chat_session_fingerprint="fp_b",
            )
            self.assertNotEqual(split_session, base_session)
            self.assertTrue(split_session.startswith(base_session + "_"))

            keyed_session = processor._build_session_id(
                user_name=user_name,
                chat_session_key="real_session_key",
                chat_session_fingerprint="fp_b",
            )
            self.assertTrue(keyed_session.startswith("chat_"))

    def test_decision_and_assistant_log_media_aggregates(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlow()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "日志用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_log",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "需要预约吗？", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            session_id = processor._build_session_id("日志用户", "", "fp_log")
            log_path = processor.conversation_logger._session_file(session_id, user_name="日志用户")
            lines = [json.loads(x) for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]

            decision_events = [x for x in lines if x.get("event_type") == "decision_snapshot"]
            assistant_events = [x for x in lines if x.get("event_type") == "assistant_reply"]
            user_events = [x for x in lines if x.get("event_type") == "user_message"]
            self.assertTrue(decision_events)
            self.assertTrue(assistant_events)
            self.assertTrue(user_events)

            user_payload = user_events[-1].get("payload", {})
            self.assertIn("is_first_turn_global", user_payload)
            self.assertTrue(user_payload.get("is_first_turn_global"))

            decision_payload = decision_events[-1].get("payload", {})
            self.assertIn("round_media_blocked", decision_payload)
            self.assertIn("round_media_block_reason", decision_payload)
            self.assertIn("round_media_planned_types", decision_payload)
            self.assertIn("both_images_sent_state", decision_payload)
            self.assertIn("kb_match_score", decision_payload)
            self.assertIn("kb_match_question", decision_payload)
            self.assertIn("kb_match_mode", decision_payload)
            self.assertIn("kb_item_id", decision_payload)
            self.assertIn("kb_variant_total", decision_payload)
            self.assertIn("kb_variant_selected_index", decision_payload)
            self.assertIn("kb_variant_fallback_llm", decision_payload)
            self.assertIn("kb_confident", decision_payload)
            self.assertIn("kb_blocked_by_polite_guard", decision_payload)
            self.assertIn("kb_polite_guard_reason", decision_payload)
            self.assertIn("is_first_turn_global", decision_payload)
            self.assertIn("first_turn_media_guard_applied", decision_payload)
            self.assertIn("kb_repeat_rewritten", decision_payload)
            self.assertIn("purchase_both_first_hint_sent", decision_payload)
            self.assertIn("video_trigger_user_count", decision_payload)
            self.assertTrue(decision_payload.get("kb_blocked_by_polite_guard"))
            self.assertEqual(decision_payload.get("kb_polite_guard_reason"), "polite_mixed_query")
            self.assertTrue(decision_payload.get("purchase_both_first_hint_sent"))

            assistant_payload = assistant_events[-1].get("payload", {})
            self.assertIn("round_media_sent", assistant_payload)
            self.assertIn("round_media_sent_types", assistant_payload)
            self.assertIn("round_media_failed_types", assistant_payload)
            self.assertIn("round_media_sent_details", assistant_payload)
            self.assertIn("is_first_turn_global", assistant_payload)
            self.assertIn("first_turn_media_guard_applied", assistant_payload)
            self.assertIn("kb_repeat_rewritten", assistant_payload)
            self.assertIn("purchase_both_first_hint_sent", assistant_payload)
            self.assertIn("kb_variant_total", assistant_payload)
            self.assertIn("kb_variant_selected_index", assistant_payload)
            self.assertIn("kb_variant_fallback_llm", assistant_payload)
            self.assertTrue(assistant_payload.get("round_media_sent"))
            self.assertIn("contact_image", assistant_payload.get("round_media_sent_types", []))
            self.assertTrue(assistant_payload.get("round_media_sent_details"))
            self.assertTrue(assistant_payload.get("purchase_both_first_hint_sent"))

            media_attempt_events = [x for x in lines if x.get("event_type") == "media_attempt"]
            media_result_events = [x for x in lines if x.get("event_type") == "media_result"]
            self.assertTrue(media_attempt_events)
            self.assertTrue(media_result_events)
            attempt_payload = media_attempt_events[-1].get("payload", {})
            result_payload = media_result_events[-1].get("payload", {})
            for key in ("target_store", "store_name", "store_address", "detected_region", "route_reason"):
                self.assertIn(key, attempt_payload)
                self.assertIn(key, result_payload)

    def test_media_placeholder_user_message_still_triggers_auto_reply(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlow()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0

            payload = {
                "user_name": "媒体用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_media_placeholder",
                "messages": [
                    {"text": "姐姐给您发个视频", "is_user": False, "message_type": "text"},
                    {"text": "[视频]", "is_user": True, "message_type": "video"},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            session_id = processor._build_session_id("媒体用户", "", "fp_media_placeholder")
            session = sessions.get_session(session_id)
            self.assertIsNone(session)
            self.assertFalse(agent.mark_reply_sent_calls)

    def test_unread_preview_image_hint_can_patch_missing_last_user_message(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlow()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor._pending_unread_hint = {
                "preview_text": "[图片]",
                "preview_type": "image",
                "session_text": "胃不疼 [图片]",
            }

            payload = {
                "user_name": "媒体用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_unread_preview_image",
                "messages": [
                    {"text": "姐姐，定制假发的价格在3000到6000元之间", "is_user": False, "message_type": "text"},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            session_id = processor._build_session_id("媒体用户", "", "fp_unread_preview_image")
            session = sessions.get_session(session_id)
            self.assertIsNotNone(session)
            self.assertTrue(session.messages)
            self.assertEqual(session.messages[0]["text"], "[图片]")
            self.assertTrue(agent.mark_reply_sent_calls)
            self.assertEqual(agent.mark_reply_sent_calls[-1]["session_id"], session_id)

    def test_unread_preview_same_image_marker_still_dedupes(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlow()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0

            payload = {
                "user_name": "媒体用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_unread_preview_image_repeat",
                "messages": [
                    {"text": "历史客服", "is_user": False, "message_type": "text"},
                ],
            }

            processor._pending_unread_hint = {
                "preview_text": "[图片]",
                "preview_type": "image",
                "session_text": "胃不疼 [图片]",
                "badge_text": "1",
            }
            processor._on_chat_data(True, payload, auto_reply=True)
            first_calls = len(agent.mark_reply_sent_calls)

            processor._pending_unread_hint = {
                "preview_text": "[图片]",
                "preview_type": "image",
                "session_text": "胃不疼 [图片]",
                "badge_text": "1",
            }
            processor._on_chat_data(True, payload, auto_reply=True)
            self.assertEqual(len(agent.mark_reply_sent_calls), first_calls)

    def test_unread_preview_different_image_marker_does_not_get_swallowed(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlow()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0

            payload = {
                "user_name": "媒体用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_unread_preview_image_repeat",
                "messages": [
                    {"text": "历史客服", "is_user": False, "message_type": "text"},
                ],
            }

            processor._pending_unread_hint = {
                "preview_text": "[图片]",
                "preview_type": "image",
                "session_text": "胃不疼 [图片]",
                "badge_text": "1",
            }
            processor._on_chat_data(True, payload, auto_reply=True)
            first_calls = len(agent.mark_reply_sent_calls)

            processor._pending_unread_hint = {
                "preview_text": "[图片]",
                "preview_type": "image",
                "session_text": "胃不疼 [图片] 15:44",
                "badge_text": "1",
            }
            processor._on_chat_data(True, payload, auto_reply=True)
            self.assertEqual(len(agent.mark_reply_sent_calls), first_calls + 1)

    def test_retry_contact_image_when_verify_timeout_without_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlowRetry()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "重试用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_retry",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "怎么预约？", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            self.assertEqual(browser.image_send_calls, 2)
            session_id = processor._build_session_id("重试用户", "", "fp_retry")
            log_path = processor.conversation_logger._session_file(session_id, user_name="重试用户")
            lines = [json.loads(x) for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
            media_result_events = [x for x in lines if x.get("event_type") == "media_result"]
            self.assertGreaterEqual(len(media_result_events), 2)
            self.assertTrue(any(bool(e.get("payload", {}).get("retry_scheduled")) for e in media_result_events))
            self.assertTrue(any(bool(e.get("payload", {}).get("success")) for e in media_result_events))

    def test_enqueue_compensation_after_three_required_media_failures(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlowCompensation()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "补偿用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_comp",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "怎么预约？", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            self.assertEqual(browser.image_send_calls, 2)
            session_id = processor._build_session_id("补偿用户", "", "fp_comp")
            log_path = processor.conversation_logger._session_file(session_id, user_name="补偿用户")
            lines = [json.loads(x) for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertTrue(any(x.get("event_type") == "contact_image_send_pending_compensation" for x in lines))
            result_payloads = [x.get("payload", {}) for x in lines if x.get("event_type") == "media_result"]
            self.assertTrue(any(bool(p.get("compensation_enqueued")) for p in result_payloads))

    def test_remote_control_stop_and_start_from_whitelist_user(self):
        class DummyBrowserRemote(QObject):
            page_loaded = Signal(bool)
            url_changed = Signal(str)

            def __init__(self):
                super().__init__()
                self.sent_messages = []

            def find_and_click_first_unread(self, callback):
                del callback

            def find_and_click_unread_by_usernames(self, user_names, callback):
                del user_names, callback

            def grab_chat_data(self, callback):
                del callback

            def send_message(self, text, callback):
                self.sent_messages.append(text)
                callback(True, {"ok": True})

            def send_image(self, media_path, callback):
                del media_path, callback

            def send_video_from_material_library(self, callback):
                del callback

        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserRemote()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")
            processor._page_ready = True
            processor.set_remote_control_users(["控制用户"])
            processor.start()

            stop_payload = {
                "user_name": "控制用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_remote",
                "messages": [{"text": "stop", "is_user": True}],
            }
            processor._on_chat_data(True, stop_payload, auto_reply=True)
            self.assertFalse(processor.is_ai_enabled())
            self.assertEqual(browser.sent_messages[-1], "姐姐你好，已经关闭❤️")

            start_payload = {
                "user_name": "控制用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_remote",
                "messages": [{"text": " start ", "is_user": True}],
            }
            processor._on_chat_data(True, start_payload, auto_reply=True)
            self.assertTrue(processor.is_ai_enabled())
            self.assertEqual(browser.sent_messages[-1], "姐姐你好，已经启动🏃")

    def test_clear_input_before_sending_media_to_avoid_duplicate_text(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserDuplicateOnImage()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "去重用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_no_dup",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "发我地址图吧", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            self.assertGreaterEqual(browser.clear_calls, 1)
            self.assertEqual(browser.sent_messages.count("姐姐我马上帮您安排～🌹"), 1)

    def test_mark_reply_sent_receives_first_turn_flag(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlow()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "首轮透传用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_first_turn",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "我想买假发", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            self.assertTrue(agent.mark_reply_sent_calls)
            self.assertTrue(agent.mark_reply_sent_calls[-1]["is_first_turn_global"])

    def test_first_reply_video_flows_through_material_library_sender(self):
        app = QCoreApplication.instance() or QCoreApplication([])

        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserVideoRoute()
            sessions = SessionManager()
            agent = DummyAgentFlowFirstReplyVideo(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "首轮视频用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_first_video",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "我想买假发", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            loop = QEventLoop()
            QTimer.singleShot(1400, loop.quit)
            loop.exec()

            self.assertEqual(browser.video_send_calls, 1)
            self.assertEqual(browser.image_send_calls, 1)

    def test_first_turn_image_text_video_sequence_is_ordered(self):
        app = QCoreApplication.instance() or QCoreApplication([])

        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFirstTurnSequence()
            sessions = SessionManager()
            agent = DummyAgentFlowFirstTurnImageAndVideo(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "首轮图文视频用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_first_image_video",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "静安寺地址", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            loop = QEventLoop()
            QTimer.singleShot(1400, loop.quit)
            loop.exec()

            self.assertEqual(browser.sequence, ["image", "text", "video"])

    def test_delayed_video_uses_material_library_sender(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserVideoRoute()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            processor._send_media_queue(
                session_id="chat_video_route",
                user_name="视频用户",
                media_queue=[{"type": "delayed_video", "path": "dummy.mp4"}],
                decision=None,
                media_summary={"sent_types": [], "failed_types": [], "sent_details": [], "failed_details": []},
            )

            self.assertEqual(browser.video_send_calls, 1)
            self.assertEqual(browser.image_send_calls, 0)

    def test_delayed_video_emits_step_logs_from_browser_hook(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserVideoRouteWithDebug()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            captured = []
            processor.log_event.connect(captured.append)

            processor._send_media_queue(
                session_id="chat_video_debug",
                user_name="视频日志用户",
                media_queue=[{"type": "delayed_video", "path": "dummy.mp4", "trigger_source": "first_reply"}],
                decision=None,
                media_summary={"sent_types": [], "failed_types": [], "sent_details": [], "failed_details": []},
            )

            texts = [str(item.get("text", "") or "") for item in captured if isinstance(item, dict)]
            self.assertTrue(any("开始触发首轮视频发送" in text for text in texts))
            self.assertTrue(any("素材库Tab点击成功" in text for text in texts))
            self.assertTrue(any("视频Tab点击成功" in text for text in texts))

    def test_delayed_video_retries_once_after_failure(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserVideoRouteRetry()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            processor._send_media_queue(
                session_id="chat_video_retry",
                user_name="视频重试用户",
                media_queue=[{"type": "delayed_video", "path": "dummy.mp4"}],
                decision=None,
                media_summary={"sent_types": [], "failed_types": [], "sent_details": [], "failed_details": []},
            )

            self.assertEqual(browser.video_send_calls, 2)
            self.assertEqual(browser.image_send_calls, 0)

    def test_delayed_video_drag_failure_retries_once(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserVideoDragRetry()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            processor._send_media_queue(
                session_id="chat_video_drag_retry",
                user_name="视频拖拽重试用户",
                media_queue=[{"type": "delayed_video", "path": "dummy.mp4"}],
                decision=None,
                media_summary={"sent_types": [], "failed_types": [], "sent_details": [], "failed_details": []},
            )

            self.assertEqual(browser.video_send_calls, 2)
            self.assertEqual(browser.image_send_calls, 0)

    def test_delay_media_until_text_send_settles(self):
        app = QCoreApplication.instance() or QCoreApplication([])

        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserDelayedTextThenImage()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            payload = {
                "user_name": "落稳用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_text_delay",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "天津有门店吗？", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            loop = QEventLoop()
            QTimer.singleShot(1400, loop.quit)
            loop.exec()

            self.assertEqual(browser.sent_messages.count("姐姐我马上帮您安排～🌹"), 1)
            self.assertEqual(browser.image_send_calls, 1)
            self.assertGreaterEqual(browser.clear_calls, 1)

    def test_click_unread_waits_three_seconds_before_grabbing_chat(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserUnreadClick()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            scheduled = []
            original_single_shot = QTimer.singleShot

            def fake_single_shot(delay_ms, callback):
                scheduled.append(delay_ms)
                del callback

            QTimer.singleShot = staticmethod(fake_single_shot)
            try:
                processor._check_unread_and_enter()
            finally:
                QTimer.singleShot = original_single_shot

            self.assertIn(3000, scheduled)

    def test_stale_followup_candidate_ignores_memory_flag_and_uses_log_only(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserStaleFollowup("超时用户")
            sessions = SessionManager()
            agent = DummyAgent(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            user_hash = processor._build_user_hash("超时用户", "user_timeout")
            memory_store.update_user_state(
                user_hash,
                {
                    "stale_followup_sent": True,
                    "stale_followup_sent_at": datetime.now().isoformat(),
                },
            )
            memory_store.save()

            log_path = processor.conversation_logger._session_file("user_timeout", user_name="超时用户")
            record = {
                "timestamp": (datetime.now() - timedelta(minutes=3)).isoformat(),
                "session_id": "user_timeout",
                "user_id_hash": user_hash,
                "event_type": "assistant_reply",
                "reply_source": "rule",
                "rule_id": "TEST",
                "model_name": "",
                "payload": {"text": "上一轮回复", "user_name": "超时用户"},
            }
            log_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

            candidate, reason = processor._find_stale_followup_candidate()

            self.assertIsNotNone(candidate)
            self.assertEqual(reason, "")
            self.assertEqual(candidate["user_hash"], user_hash)
            self.assertEqual(candidate["user_name"], "超时用户")

    def test_stale_followup_candidate_blocks_once_log_contains_sent_event(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserStaleFollowup("超时用户")
            sessions = SessionManager()
            agent = DummyAgent(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            user_hash = processor._build_user_hash("超时用户", "user_timeout")
            log_path = processor.conversation_logger._session_file("user_timeout", user_name="超时用户")
            records = [
                {
                    "timestamp": (datetime.now() - timedelta(minutes=4)).isoformat(),
                    "session_id": "user_timeout",
                    "user_id_hash": user_hash,
                    "event_type": "assistant_reply",
                    "reply_source": "rule",
                    "rule_id": "TEST",
                    "model_name": "",
                    "payload": {"text": "上一轮回复", "user_name": "超时用户"},
                },
                {
                    "timestamp": (datetime.now() - timedelta(minutes=3)).isoformat(),
                    "session_id": "user_timeout",
                    "user_id_hash": user_hash,
                    "event_type": "stale_followup_sent",
                    "reply_source": "stale_followup",
                    "rule_id": "STALE_FOLLOWUP",
                    "model_name": "",
                    "payload": {"text": "结尾话术", "user_name": "超时用户"},
                },
            ]
            log_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n",
                encoding="utf-8",
            )

            candidate, reason = processor._find_stale_followup_candidate()

            self.assertIsNone(candidate)
            self.assertIn("日志中已存在发送记录", reason)


if __name__ == "__main__":
    unittest.main()
