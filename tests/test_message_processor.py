import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from src.core.message_processor import MessageProcessor
from src.core.private_cs_agent import AgentDecision
from src.core.session_manager import SessionManager
from src.data.memory_store import MemoryStore
from src.services.conversation_logger import ConversationLogger


class DummyBrowser(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def find_and_click_first_unread(self, callback):
        del callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text, callback

    def send_image(self, media_path, callback):
        del media_path, callback


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

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        del text
        callback(True, {"ok": True})

    def send_image(self, media_path, callback):
        del media_path
        callback(True, {"ok": True})


class DummyBrowserFlowRetry(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.image_send_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

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


class DummyAgentFlow:
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store

    def reload_media_library(self):
        return None

    def reload_rule_configs(self):
        return None

    def reload_prompt_docs(self):
        return True

    def decide(self, session_id: str, user_name: str, latest_user_text: str, conversation_history=None):
        del session_id, user_name, latest_user_text, conversation_history
        return AgentDecision(
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

    def is_user_first_turn_global(self, user_id_hash: str) -> bool:
        del user_id_hash
        return True

    def mark_reply_sent(self, session_id: str, user_name: str, reply_text: str):
        del session_id, user_name, reply_text
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


class DummyBrowserFlowCompensation(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.image_send_calls = 0

    def find_and_click_first_unread(self, callback):
        del callback

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


class MessageProcessorSessionIdTestCase(unittest.TestCase):
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
            processor._send_pending_decision()

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

    def test_retry_contact_image_when_verify_timeout_without_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlowRetry()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
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
            processor._send_pending_decision()

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
            processor._send_pending_decision()

            self.assertEqual(browser.image_send_calls, 3)
            session_id = processor._build_session_id("补偿用户", "", "fp_comp")
            log_path = processor.conversation_logger._session_file(session_id, user_name="补偿用户")
            lines = [json.loads(x) for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertTrue(any(x.get("event_type") == "contact_image_send_pending_compensation" for x in lines))
            result_payloads = [x.get("payload", {}) for x in lines if x.get("event_type") == "media_result"]
            self.assertTrue(any(bool(p.get("compensation_enqueued")) for p in result_payloads))


if __name__ == "__main__":
    unittest.main()
