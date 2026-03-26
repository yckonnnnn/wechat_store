import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Signal, QTimer

from src.core.message_processor import MessageProcessor
from src.core.private_cs_agent import AgentDecision, CustomerServiceAgent
from src.core.session_manager import SessionManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.conversation_logger import ConversationLogger
from src.services.knowledge_service import KnowledgeService


class DummyLLMService:
    def set_system_prompt(self, prompt: str):
        del prompt

    def generate_reply_sync(self, user_message: str, conversation_history=None):
        del user_message, conversation_history
        return True, "姐姐我在呢🌹"

    def get_current_model_name(self) -> str:
        return "DummyLLM"


def build_real_agent(
    temp_dir: Path,
    *,
    contact_image_files=None,
    address_image_files=None,
    store_targets=None,
) -> CustomerServiceAgent:
    contact_image_files = contact_image_files or ["contact.jpg"]
    address_image_files = address_image_files or ["徐汇地址1.jpg"]
    store_targets = store_targets or {}

    images_dir = temp_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for name in contact_image_files:
        (images_dir / name).write_text("x", encoding="utf-8")
    for name in address_image_files:
        (images_dir / name).write_text("x", encoding="utf-8")

    image_categories_path = temp_dir / "image_categories.json"
    image_categories_path.write_text(
        json.dumps(
            {
                "version": 1,
                "categories": ["联系方式", "店铺地址"],
                "images": {
                    "联系方式": list(contact_image_files),
                    "店铺地址": list(address_image_files),
                },
                "store_targets": dict(store_targets),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reply_templates_path = temp_dir / "reply_templates.json"
    reply_templates_path.write_text("{}", encoding="utf-8")
    media_whitelist_path = temp_dir / "media_whitelist.json"
    media_whitelist_path.write_text(json.dumps({"version": 1, "session_ids": []}, ensure_ascii=False), encoding="utf-8")
    system_prompt = temp_dir / "system_prompt.md"
    playbook = temp_dir / "playbook.md"
    system_prompt.write_text("你是客服助手。", encoding="utf-8")
    playbook.write_text("语气友好。", encoding="utf-8")
    kb_file = temp_dir / "knowledge.json"
    kb_file.write_text("[]", encoding="utf-8")

    repository = KnowledgeRepository(kb_file)
    knowledge_service = KnowledgeService(
        repository,
        address_config_path=Path("config") / "address.json",
        shanghai_route_alias_path=temp_dir / "shanghai_route_aliases.json",
    )
    memory_store = MemoryStore(temp_dir / "memory.json")

    agent = CustomerServiceAgent(
        knowledge_service=knowledge_service,
        llm_service=DummyLLMService(),
        memory_store=memory_store,
        images_dir=images_dir,
        image_categories_path=image_categories_path,
        system_prompt_doc_path=system_prompt,
        playbook_doc_path=playbook,
        reply_templates_path=reply_templates_path,
        media_whitelist_path=media_whitelist_path,
        conversation_log_dir=temp_dir / "conversations",
    )
    return agent


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


class DummyBrowserImageNeverStarts(QObject):
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
        del media_path, callback
        self.image_send_calls += 1

    def send_video_from_material_library(self, callback):
        del callback


class DummyBrowserImageSequence(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self, image_results):
        super().__init__()
        self.image_results = list(image_results)
        self.image_send_calls = 0
        self.sent_image_paths = []

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
        self.image_send_calls += 1
        self.sent_image_paths.append(media_path)
        payload = self.image_results.pop(0) if self.image_results else {"ok": True}
        if isinstance(payload, dict) and payload.get("ok") is True:
            callback(True, payload)
            return
        callback(False, payload)

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


class DummyBrowserNoUnreadButCurrentChat(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.grab_calls = 0

    def find_and_click_first_unread(self, callback):
        callback(True, {"found": False, "clicked": False})

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names
        callback(True, {"found": False, "clicked": False})

    def grab_chat_data(self, callback):
        self.grab_calls += 1
        callback(
            True,
            {
                "user_name": "当前会话用户",
                "chat_session_key": "",
                "chat_session_fingerprint": "fp_current_chat_probe",
                "messages": [
                    {"text": "姐姐您好", "is_user": False},
                    {"text": "你们营业时间是？", "is_user": True},
                ],
            },
        )

    def send_message(self, text, callback):
        del text
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
        self.decide_calls = 0

    def reload_media_library(self):
        return None

    def reload_rule_configs(self):
        return None

    def reload_prompt_docs(self):
        return True

    def decide(self, session_id: str, user_name: str, latest_user_text: str, conversation_history=None, first_turn_global_override=None):
        self.decide_calls += 1
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
    def build_first_turn_video_items(self, session_id: str):
        del session_id
        return [
            {
                "type": "delayed_video",
                "path": "video.mp4",
                "trigger_source": "first_reply",
            }
        ]


class DummyAgentFlowFirstTurnImageAndVideo(DummyAgentFlow):
    def build_first_turn_video_items(self, session_id: str):
        del session_id
        return [
            {
                "type": "delayed_video",
                "path": "video.mp4",
                "trigger_source": "first_reply",
            }
        ]


class DummyBrowserFirstTurnSequence(QObject):
    page_loaded = Signal(bool)
    url_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.sequence = []
        self.sent_texts = []

    def find_and_click_first_unread(self, callback):
        del callback

    def find_and_click_unread_by_usernames(self, user_names, callback):
        del user_names, callback

    def grab_chat_data(self, callback):
        del callback

    def send_message(self, text, callback):
        self.sequence.append("text")
        self.sent_texts.append(text)
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
    def _make_real_agent_decision(
        self,
        agent: CustomerServiceAgent,
        session_id: str,
        user_name: str,
        *,
        media_plan: str,
        route: dict,
        latest_user_text: str = "怎么预约？",
        intent: str = "purchase",
        reply_text: str = "姐姐我马上帮您安排～🌹",
    ) -> AgentDecision:
        user_hash = agent._hash_user(user_name)
        session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
        user_state = agent.memory_store.get_user_state(user_hash)
        media_items, skip_reason = agent._plan_media_items(
            session_id=session_id,
            text=latest_user_text,
            intent=intent,
            route=route,
            route_reason=str(route.get("reason", "") or "unknown"),
            media_plan=media_plan,
            session_state=session_state,
            user_state=user_state,
            force_contact_image=(media_plan == "contact_image"),
        )
        return AgentDecision(
            reply_text=reply_text,
            intent=intent,
            route_reason=str(route.get("reason", "") or "unknown"),
            reply_goal="推进",
            media_plan=media_plan if media_items else "none",
            media_items=media_items,
            reply_source="rule",
            rule_id="TEST_DECISION",
            media_skip_reason=skip_reason,
        )

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
            processor._detect_user_first_turn_global = lambda user_hash: False

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
            self.assertFalse(user_payload.get("is_first_turn_global"))

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
            processor._detect_user_first_turn_global = lambda user_hash: False

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
            processor._detect_user_first_turn_global = lambda user_hash: False

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
            processor._detect_user_first_turn_global = lambda user_hash: False

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
            processor._detect_user_first_turn_global = lambda user_hash: False

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
            processor._detect_user_first_turn_global = lambda user_hash: False

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

    def test_planned_required_media_is_persisted_before_image_send(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent = build_real_agent(temp_dir)
            browser = DummyBrowserImageNeverStarts()
            sessions = SessionManager()
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(temp_dir / "conversations")
            processor._detect_user_first_turn_global = lambda user_hash: False

            route = {"target_store": "sh_xuhui", "reason": "sh_district_map:徐汇", "detected_region": "徐汇"}
            decision = self._make_real_agent_decision(
                agent,
                session_id="user_planned_media",
                user_name="计划用户",
                media_plan="contact_image",
                route=route,
            )
            agent.decide = lambda *args, **kwargs: decision

            payload = {
                "user_name": "计划用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_planned_media",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "怎么预约？", "is_user": True},
                ],
            }

            processor._on_chat_data(True, payload, auto_reply=True)

            session_id = processor._build_session_id("计划用户", "", "fp_planned_media")
            session_state = agent.memory_store.get_session_state(session_id, user_hash=agent._hash_user("计划用户"))
            self.assertEqual(browser.image_send_calls, 1)
            self.assertTrue(session_state.get("planned_required_media"))
            self.assertEqual(session_state["planned_required_media"][0].get("type"), "contact_image")
            self.assertFalse(session_state.get("pending_required_media"))

    def test_address_image_failure_retries_next_round_with_new_store_image(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent = build_real_agent(
                temp_dir,
                address_image_files=["徐汇地址1.jpg", "徐汇地址2.jpg"],
                store_targets={"徐汇地址1.jpg": "sh_xuhui", "徐汇地址2.jpg": "sh_xuhui"},
            )
            browser = DummyBrowserImageSequence(
                [
                    {
                        "error": "上传失败",
                        "step": "upload_failed",
                        "failure_code": "upload_failed",
                    },
                    {"ok": True},
                ]
            )
            sessions = SessionManager()
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(temp_dir / "conversations")
            processor._detect_user_first_turn_global = lambda user_hash: False

            first_decision = self._make_real_agent_decision(
                agent,
                session_id="user_addr_retry",
                user_name="地址补发用户",
                media_plan="address_image",
                route={"target_store": "sh_xuhui", "reason": "sh_district_map:徐汇", "detected_region": "徐汇"},
                latest_user_text="我在徐汇",
                intent="address",
            )
            second_decision = AgentDecision(
                reply_text="姐姐我继续帮您看着呢🌹",
                intent="general",
                route_reason="unknown",
                reply_goal="解答",
                media_plan="none",
                media_items=[],
                reply_source="rule",
                rule_id="TEST_EMPTY",
            )
            decisions = [first_decision, second_decision]
            agent.decide = lambda *args, **kwargs: decisions.pop(0)

            first_payload = {
                "user_name": "地址补发用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_addr_retry",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "我在徐汇", "is_user": True},
                ],
            }
            processor._on_chat_data(True, first_payload, auto_reply=True)

            session_id = processor._build_session_id("地址补发用户", "", "fp_addr_retry")
            session_state = agent.memory_store.get_session_state(session_id, user_hash=agent._hash_user("地址补发用户"))
            self.assertTrue(session_state.get("pending_required_media"))

            second_payload = {
                "user_name": "地址补发用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_addr_retry",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "还有别的图吗", "is_user": True},
                ],
            }
            processor._on_chat_data(True, second_payload, auto_reply=True)

            self.assertEqual(browser.image_send_calls, 2)
            self.assertNotEqual(browser.sent_image_paths[0], browser.sent_image_paths[1])
            session_state = agent.memory_store.get_session_state(session_id, user_hash=agent._hash_user("地址补发用户"))
            self.assertFalse(session_state.get("pending_required_media"))
            self.assertFalse(session_state.get("planned_required_media"))

    def test_contact_image_failure_retries_next_round_with_new_contact_image(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent = build_real_agent(
                temp_dir,
                contact_image_files=["contact1.jpg", "contact2.jpg"],
            )
            browser = DummyBrowserImageSequence(
                [
                    {
                        "error": "上传失败",
                        "step": "upload_failed",
                        "failure_code": "upload_failed",
                    },
                    {"ok": True},
                ]
            )
            sessions = SessionManager()
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(temp_dir / "conversations")
            processor._detect_user_first_turn_global = lambda user_hash: False

            first_decision = self._make_real_agent_decision(
                agent,
                session_id="user_contact_retry",
                user_name="联系补发用户",
                media_plan="contact_image",
                route={"target_store": "sh_xuhui", "reason": "sh_district_map:徐汇", "detected_region": "徐汇"},
            )
            second_decision = AgentDecision(
                reply_text="姐姐我继续帮您看着呢🌹",
                intent="general",
                route_reason="unknown",
                reply_goal="解答",
                media_plan="none",
                media_items=[],
                reply_source="rule",
                rule_id="TEST_EMPTY",
            )
            decisions = [first_decision, second_decision]
            agent.decide = lambda *args, **kwargs: decisions.pop(0)

            payload = {
                "user_name": "联系补发用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_contact_retry",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "怎么预约？", "is_user": True},
                ],
            }
            processor._on_chat_data(True, payload, auto_reply=True)
            payload_retry = dict(payload)
            payload_retry["messages"] = [
                {"text": "历史客服", "is_user": False},
                {"text": "我再确认一下怎么预约", "is_user": True},
            ]
            processor._on_chat_data(True, payload_retry, auto_reply=True)

            self.assertEqual(browser.image_send_calls, 2)
            self.assertNotEqual(browser.sent_image_paths[0], browser.sent_image_paths[1])

    def test_unattempted_planned_media_is_replayed_next_round(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent = build_real_agent(temp_dir)
            browser = DummyBrowserImageNeverStarts()
            sessions = SessionManager()
            processor = MessageProcessor(browser, sessions, agent)
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(temp_dir / "conversations")
            processor._detect_user_first_turn_global = lambda user_hash: False

            first_decision = self._make_real_agent_decision(
                agent,
                session_id="user_replay_planned",
                user_name="计划补发用户",
                media_plan="contact_image",
                route={"target_store": "sh_xuhui", "reason": "sh_district_map:徐汇", "detected_region": "徐汇"},
            )
            second_decision = AgentDecision(
                reply_text="姐姐我继续帮您看着呢🌹",
                intent="general",
                route_reason="unknown",
                reply_goal="解答",
                media_plan="none",
                media_items=[],
                reply_source="rule",
                rule_id="TEST_EMPTY",
            )
            decisions = [first_decision, second_decision]
            agent.decide = lambda *args, **kwargs: decisions.pop(0)

            payload = {
                "user_name": "计划补发用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_replay_planned",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "怎么预约？", "is_user": True},
                ],
            }
            processor._on_chat_data(True, payload, auto_reply=True)

            session_id = processor._build_session_id("计划补发用户", "", "fp_replay_planned")
            session_state = agent.memory_store.get_session_state(session_id, user_hash=agent._hash_user("计划补发用户"))
            self.assertTrue(session_state.get("planned_required_media"))

            browser2 = DummyBrowserFlow()
            processor2 = MessageProcessor(browser2, sessions, agent)
            processor2._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor2._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor2.conversation_logger = ConversationLogger(temp_dir / "conversations")
            processor2._detect_user_first_turn_global = lambda user_hash: False
            agent.decide = lambda *args, **kwargs: second_decision

            processor2._on_chat_data(True, payload, auto_reply=True)
            session_state = agent.memory_store.get_session_state(session_id, user_hash=agent._hash_user("计划补发用户"))
            self.assertFalse(session_state.get("planned_required_media"))

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
            processor._detect_user_first_turn_global = lambda user_hash: False
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
            processor._detect_user_first_turn_global = lambda user_hash: False

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

    def test_first_turn_skips_decide_and_second_turn_starts_calling_it(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFlow()
            sessions = SessionManager()
            agent = DummyAgentFlowFirstReplyVideo(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._FIRST_TURN_VIDEO_CONTINUE_DELAY_MS = 0
            processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS = 0
            processor._VIDEO_SEND_AFTER_TEXT_EXTRA_DELAY_MS = 0
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")
            first_turn_states = [True, False]
            processor._detect_user_first_turn_global = lambda user_hash: first_turn_states.pop(0)

            first_payload = {
                "user_name": "首轮转二轮用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_first_then_second",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "你好啊～", "is_user": True},
                ],
            }
            processor._on_chat_data(True, first_payload, auto_reply=True)
            self.assertEqual(agent.decide_calls, 0)

            second_payload = {
                "user_name": "首轮转二轮用户",
                "chat_session_key": "",
                "chat_session_method": "fallback",
                "chat_session_fingerprint": "fp_first_then_second",
                "messages": [
                    {"text": "历史客服", "is_user": False},
                    {"text": "你好啊～", "is_user": True},
                    {"text": "价格多少", "is_user": True},
                ],
            }
            processor._on_chat_data(True, second_payload, auto_reply=True)
            self.assertEqual(agent.decide_calls, 1)

    def test_first_reply_video_flows_through_material_library_sender(self):
        app = QCoreApplication.instance() or QCoreApplication([])

        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserVideoRoute()
            sessions = SessionManager()
            agent = DummyAgentFlowFirstReplyVideo(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._FIRST_TURN_VIDEO_CONTINUE_DELAY_MS = 0
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
            self.assertEqual(browser.image_send_calls, 0)
            self.assertEqual(browser.sent_messages, [processor._FIRST_TURN_AUTO_REPLY_TEXT])
            self.assertEqual(agent.decide_calls, 0)

    def test_first_turn_image_text_video_sequence_is_ordered(self):
        app = QCoreApplication.instance() or QCoreApplication([])

        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserFirstTurnSequence()
            sessions = SessionManager()
            agent = DummyAgentFlowFirstTurnImageAndVideo(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor._FIRST_TURN_VIDEO_CONTINUE_DELAY_MS = 0
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

            self.assertEqual(browser.sequence, ["text", "video"])
            self.assertEqual(browser.sent_texts, [processor._FIRST_TURN_AUTO_REPLY_TEXT])
            self.assertEqual(agent.decide_calls, 0)

    def test_first_turn_greeting_plan_still_attaches_video(self):
        agent = CustomerServiceAgent.__new__(CustomerServiceAgent)
        agent.first_reply_video_enabled = False
        agent.summarize_session_video_from_log = lambda session_id: {"first_reply_video_sent": False}
        agent._build_video_media_item = lambda trigger_source: {
            "type": "delayed_video",
            "path": "video.mp4",
            "trigger_source": trigger_source,
        }

        decision = AgentDecision(
            reply_text="你好呀姐姐，有什么可以帮您？💕",
            intent="general",
            route_reason="unknown",
            reply_goal="解答",
            media_plan="none",
            media_items=[],
            reply_source="llm",
            rule_id="LLM_FOLLOW_UP",
            rule_applied=False,
            is_first_turn_global=True,
        )

        agent._populate_first_turn_media_plan("user_f4279bcac8", "胃不疼", decision)

        self.assertEqual(len(decision.first_turn_video_items), 1)
        self.assertEqual(decision.first_turn_video_items[0]["type"], "delayed_video")
        self.assertEqual(decision.first_turn_video_items[0]["trigger_source"], "first_reply")
        self.assertTrue(decision.first_turn_video_items[0]["first_turn_media"])

    def test_delayed_video_uses_material_library_sender(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserVideoRoute()
            sessions = SessionManager()
            agent = DummyAgentFlow(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")
            processor._detect_user_first_turn_global = lambda user_hash: False

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
            processor._detect_user_first_turn_global = lambda user_hash: False

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

    def test_no_unread_probes_current_chat_and_processes_new_message(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserNoUnreadButCurrentChat()
            sessions = SessionManager()
            agent = DummyAgent(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            captured = []
            stale_called = []

            def fake_on_chat_data(success, result, auto_reply):
                captured.append((success, auto_reply, result))
                processor._reset_cycle()

            processor._on_chat_data = fake_on_chat_data
            processor._check_stale_replied_sessions = lambda: stale_called.append(True)
            processor._check_unread_and_enter()

            self.assertEqual(browser.grab_calls, 1)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0][0], True)
            self.assertEqual(captured[0][1], True)
            self.assertFalse(stale_called)

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

    def test_stale_followup_uses_one_minute_threshold_and_new_text(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserStaleFollowup("超时用户")
            sessions = SessionManager()
            agent = DummyAgent(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            user_hash = processor._build_user_hash("超时用户", "user_timeout")
            log_path = processor.conversation_logger._session_file("user_timeout", user_name="超时用户")
            record = {
                "timestamp": (datetime.now() - timedelta(seconds=90)).isoformat(),
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
            self.assertEqual(processor._STALE_FOLLOWUP_AFTER_SECONDS, 60)
            self.assertEqual(
                processor._STALE_FOLLOWUP_TEXT,
                "姐姐，记得请添加我好友哦，我会发详细定位还有乘车路线以及预约/价格方面事项给到您~❤️",
            )

    def test_stale_followup_skips_nameless_test_log_and_uses_real_user(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserStaleFollowup("超时用户")
            sessions = SessionManager()
            agent = DummyAgent(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            conversations_dir = Path(td) / "conversations"
            conversations_dir.mkdir(parents=True, exist_ok=True)

            nameless_log = conversations_dir / "test_session_002.jsonl"
            nameless_log.write_text(
                json.dumps(
                    {
                        "timestamp": (datetime.now() - timedelta(minutes=3)).isoformat(),
                        "session_id": "test_session_002",
                        "user_id_hash": "test_user_hash",
                        "event_type": "assistant_reply",
                        "reply_source": "rule",
                        "rule_id": "TEST",
                        "model_name": "",
                        "payload": {"text": "测试回复"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            user_hash = processor._build_user_hash("超时用户", "user_timeout")
            real_log = processor.conversation_logger._session_file("user_timeout", user_name="超时用户")
            real_log.write_text(
                json.dumps(
                    {
                        "timestamp": (datetime.now() - timedelta(seconds=90)).isoformat(),
                        "session_id": "user_timeout",
                        "user_id_hash": user_hash,
                        "event_type": "assistant_reply",
                        "reply_source": "rule",
                        "rule_id": "TEST",
                        "model_name": "",
                        "payload": {"text": "上一轮回复", "user_name": "超时用户"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            candidate, reason = processor._find_stale_followup_candidate()

            self.assertEqual(reason, "")
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate["user_hash"], user_hash)
            self.assertEqual(candidate["user_name"], "超时用户")

    def test_stale_followup_sends_text_then_contact_image(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent = build_real_agent(temp_dir, contact_image_files=["contact.jpg"])
            browser = DummyBrowserFirstTurnSequence()
            sessions = SessionManager()
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(temp_dir / "conversations")
            original_single_shot = QTimer.singleShot

            def fake_single_shot(delay_ms, callback):
                del delay_ms
                callback()

            QTimer.singleShot = staticmethod(fake_single_shot)
            try:
                processor._send_stale_followup_message(
                    session_id="stale_followup_media",
                    user_name="超时用户",
                    user_hash=processor._build_user_hash("超时用户", "stale_followup_media"),
                )
            finally:
                QTimer.singleShot = original_single_shot

            self.assertEqual(browser.sequence, ["text", "image"])

    def test_stale_followup_waits_before_contact_image(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent = build_real_agent(temp_dir, contact_image_files=["contact.jpg"])
            browser = DummyBrowserFirstTurnSequence()
            sessions = SessionManager()
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(temp_dir / "conversations")

            scheduled = []
            original_single_shot = QTimer.singleShot

            def fake_single_shot(delay_ms, callback):
                scheduled.append(delay_ms)
                callback()

            QTimer.singleShot = staticmethod(fake_single_shot)
            try:
                processor._send_stale_followup_message(
                    session_id="stale_followup_media_delay",
                    user_name="超时用户",
                    user_hash=processor._build_user_hash("超时用户", "stale_followup_media_delay"),
                )
            finally:
                QTimer.singleShot = original_single_shot

            self.assertIn(processor._MEDIA_SEND_AFTER_TEXT_DELAY_MS, scheduled)

    def test_stale_followup_not_found_enters_retry_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            memory_store = MemoryStore(Path(td) / "memory.json")
            browser = DummyBrowserStaleFollowup("别的用户")
            sessions = SessionManager()
            agent = DummyAgent(memory_store)
            processor = MessageProcessor(browser, sessions, agent)
            processor.conversation_logger = ConversationLogger(Path(td) / "conversations")

            user_hash = processor._build_user_hash("超时用户", "user_timeout")
            log_path = processor.conversation_logger._session_file("user_timeout", user_name="超时用户")
            record = {
                "timestamp": (datetime.now() - timedelta(seconds=90)).isoformat(),
                "session_id": "user_timeout",
                "user_id_hash": user_hash,
                "event_type": "assistant_reply",
                "reply_source": "rule",
                "rule_id": "TEST",
                "model_name": "",
                "payload": {"text": "上一轮回复", "user_name": "超时用户"},
            }
            log_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

            processor._check_stale_replied_sessions()
            candidate, _ = processor._find_stale_followup_candidate()

            self.assertIsNone(candidate)
            self.assertIn(user_hash, processor._stale_followup_skip_until)


if __name__ == "__main__":
    unittest.main()
