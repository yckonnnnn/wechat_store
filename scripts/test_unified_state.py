"""
统一状态管理测试脚本

测试场景：
1. 状态合并逻辑
2. 从日志提取状态
3. 已确认事实获取
"""

import sys
import json
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.memory_store import MemoryStore
from src.core.session_manager import SessionManager
from src.services.conversation_logger import ConversationLogger
from src.core.session_state_unified import UnifiedSessionState


def create_mock_components():
    """创建模拟组件用于测试"""
    temp_root = Path(tempfile.mkdtemp(prefix="unified_state_test_"))
    memory_store = MemoryStore(temp_root / "agent_memory.json")
    session_manager = SessionManager()
    conversation_logger = ConversationLogger(temp_root / "conversations")
    return memory_store, session_manager, conversation_logger


def test_state_merge():
    """测试状态合并逻辑"""
    print("=" * 60)
    print("测试 1: 状态合并逻辑")
    print("=" * 60)

    memory_store, session_manager, conversation_logger = create_mock_components()
    unified_state = UnifiedSessionState(memory_store, session_manager, conversation_logger)

    session_id = "test_session_001"
    user_hash = "test_user_hash"

    # 设置 MemoryStore 状态
    memory_store.update_session_state(session_id, {"last_target_store": "beijing_chaoyang", "address_image_sent_count": 1}, user_hash)

    # 获取统一状态
    state = unified_state.get_state(session_id, user_hash)

    print(f"last_target_store: {state.get('last_target_store')}")
    print(f"address_image_sent: {state.get('address_image_sent')}")
    print(f"_merged_at: {state.get('_merged_at')}")

    assert state.get("last_target_store") == "beijing_chaoyang", "应正确读取 MemoryStore 状态"
    print("✅ 测试通过：状态合并逻辑正确")
    print()


def test_logger_extraction():
    """测试从日志提取最新地址状态，不回放旧追问计数"""
    print("=" * 60)
    print("测试 2: 从日志提取状态")
    print("=" * 60)

    memory_store, session_manager, conversation_logger = create_mock_components()
    unified_state = UnifiedSessionState(memory_store, session_manager, conversation_logger)

    session_id = "test_session_002"
    user_hash = "test_user_hash"

    # 模拟日志事件
    from datetime import datetime
    events = [
        {
            "event_type": "user_message",
            "payload": {"text": "我在北京", "timestamp": datetime.now().isoformat()}
        },
        {
            "event_type": "assistant_reply",
            "payload": {"rule_id": "ADDR_ASK_DISTRICT_R1", "timestamp": datetime.now().isoformat()}
        },
        {
            "event_type": "media_sent",
            "payload": {
                "media_type": "address_image",
                "target_store": "beijing_chaoyang",
                "sent_at": datetime.now().isoformat()
            }
        },
        {
            "event_type": "media_sent",
            "payload": {
                "media_type": "address_image",
                "target_store": "sh_jingan",
                "sent_at": datetime.now().isoformat()
            }
        }
    ]

    # 手动写入日志
    for event in events:
        conversation_logger.append_event(
            session_id=session_id,
            user_id_hash=user_hash,
            event_type=event["event_type"],
            payload=event["payload"],
        )

    # 获取统一状态
    state = unified_state.get_state(session_id, user_hash)

    print(f"last_target_store: {state.get('last_target_store')}")
    print(f"address_image_sent: {state.get('address_image_sent')}")
    print(f"geo_followup_round: {state.get('geo_followup_round')}")

    assert state.get("address_image_sent") == True, "应正确提取地址图已发送状态"
    assert state.get("last_target_store") == "sh_jingan", "应保留最近一次发送地址图对应的门店"
    assert state.get("geo_followup_round", 0) == 0, "不应从历史日志回放旧的追问轮数"
    print("✅ 测试通过：从日志提取状态正确")
    print()


def test_logger_session_filtering():
    """测试同一日志文件下只读取当前 session 的事件"""
    print("=" * 60)
    print("测试 2.1: 日志按 session 精确过滤")
    print("=" * 60)

    memory_store, session_manager, conversation_logger = create_mock_components()
    unified_state = UnifiedSessionState(memory_store, session_manager, conversation_logger)

    session_id = "test_session_filter_target"
    user_hash = "test_user_hash"
    user_name = "同一用户"

    conversation_logger.append_event(
        session_id=session_id,
        user_id_hash=user_hash,
        event_type="assistant_reply",
        user_name=user_name,
        payload={"rule_id": "ADDR_ASK_DISTRICT_R1"},
    )
    conversation_logger.append_event(
        session_id="test_session_filter_other",
        user_id_hash=user_hash,
        event_type="assistant_reply",
        user_name=user_name,
        payload={"rule_id": "ADDR_ASK_DISTRICT_R2"},
    )
    conversation_logger.append_event(
        session_id="test_session_filter_other",
        user_id_hash=user_hash,
        event_type="media_sent",
        user_name=user_name,
        payload={"media_type": "address_image", "target_store": "sh_jingan", "sent_at": "2026-03-26T00:00:00"},
    )

    state = unified_state.get_state(session_id, user_hash)
    recent_events = conversation_logger.get_recent_events(session_id)

    print(f"recent_events_count: {len(recent_events)}")
    print(f"geo_followup_round: {state.get('geo_followup_round')}")
    print(f"address_image_sent: {state.get('address_image_sent')}")

    assert len(recent_events) == 1, "只应返回当前 session 的事件"
    assert state.get("geo_followup_round", 0) == 0, "不应混入其他 session 的追问轮数"
    assert state.get("address_image_sent") in {False, None}, "不应混入其他 session 的地址图状态"
    print("✅ 测试通过：日志不会串到其他会话")
    print()


def test_confirmed_facts():
    """测试已确认事实获取"""
    print("=" * 60)
    print("测试 3: 已确认事实获取")
    print("=" * 60)

    memory_store, session_manager, conversation_logger = create_mock_components()
    unified_state = UnifiedSessionState(memory_store, session_manager, conversation_logger)

    session_id = "test_session_003"
    user_hash = "test_user_hash"

    # 设置状态
    memory_store.update_session_state(session_id, {
        "last_target_store": "sh_jingan",
        "address_image_sent_count": 1,
        "contact_image_sent_count": 1,
        "geo_followup_round": 2,
    }, user_hash)

    # 获取已确认事实
    facts = unified_state.get_confirmed_facts(session_id, user_hash)

    print(f"city_confirmed: {facts.get('city_confirmed')}")
    print(f"store_confirmed: {facts.get('store_confirmed')}")
    print(f"address_image_sent: {facts.get('address_image_sent')}")
    print(f"contact_image_sent: {facts.get('contact_image_sent')}")
    print(f"geo_followup_round: {facts.get('geo_followup_round')}")

    assert facts.get("store_confirmed") == "sh_jingan", "应正确返回已确认门店"
    assert facts.get("address_image_sent") == True, "应根据计数返回地址图已发送"
    assert facts.get("contact_image_sent") == True, "应根据计数返回联系方式已发送"
    assert facts.get("geo_followup_round") == 2, "应正确返回追问轮数"
    print("✅ 测试通过：已确认事实获取正确")
    print()


def test_geo_followup_exhausted_fallback():
    """测试追问耗尽兜底逻辑"""
    print("=" * 60)
    print("测试 4: 追问耗尽兜底逻辑")
    print("=" * 60)

    from src.core.agent_rule_engine import decide_general_reply
    from src.core.agent_types import AgentDecision

    # 模拟 agent 对象
    class MockAgent:
        def __init__(self):
            self._current_unified_state = {
                "geo_followup_exhausted": True,
                "geo_followup_round": 2,
                "last_geo_pending": True,
                "contact_image_sent": False,
                "contact_image_sent_count": 0,
            }
            self.use_knowledge_first = False

        def _is_ambiguous_short_fragment(self, *args, **kwargs):
            return False

        def _is_follow_up_question(self, *args, **kwargs):
            return False

        def _decide_media_placeholder_reply(self, **kwargs):
            return None

        def _decide_lifespan_priority_reply(self, **kwargs):
            return None

    agent = MockAgent()

    decision = decide_general_reply(
        agent=agent,
        latest_user_text="地址在哪",
        intent="address",
        route={"reason": "unknown"},
        conversation_history=[],
        session_state={},
        user_state={},
        user_id_hash="test",
    )

    print(f"rule_id: {decision.rule_id}")
    print(f"intent: {decision.intent}")
    print(f"reply_goal: {decision.reply_goal}")

    assert decision.rule_id == "GEO_FOLLOWUP_EXHAUSTED", "追问耗尽应切换到联系方式"
    assert decision.intent == "contact", "意图应切换为 contact"
    print("✅ 测试通过：追问耗尽兜底逻辑正确")
    print()


def test_geo_followup_exhausted_does_not_block_other_topics():
    """测试追问次数已满时，非地区问题仍可正常回答"""
    print("=" * 60)
    print("测试 5: 追问耗尽不应拦截其他问题")
    print("=" * 60)

    from src.core.agent_rule_engine import decide_general_reply

    class MockAgent:
        def __init__(self):
            class MockKnowledgeService:
                @staticmethod
                def find_answer_detail(text, threshold=0.0):
                    if text == "营业时间呢":
                        return {
                            "matched": True,
                            "intent": "service_hours",
                            "tags": ["营业时间"],
                            "confidence": "high",
                            "score": 0.99,
                            "question": "营业时间",
                            "mode": "match",
                            "item_id": "hours_001",
                            "answer": "姐姐，我们营业时间是周一到周五 9:00-18:00❤️",
                            "answers": ["姐姐，我们营业时间是周一到周五 9:00-18:00❤️"],
                        }
                    return {"matched": False}

            self._current_unified_state = {
                "geo_followup_round": 2,
                "last_geo_pending": False,
                "contact_image_sent": False,
                "contact_image_sent_count": 0,
            }
            self.use_knowledge_first = True
            self.knowledge_threshold = 0.6
            self.knowledge_service = MockKnowledgeService()

        def _decide_media_placeholder_reply(self, **kwargs):
            return None

        def _decide_lifespan_priority_reply(self, **kwargs):
            return None

        def _looks_like_direct_contact_request(self, text):
            return False

        def _looks_like_appointment_query(self, text):
            return False

        def _looks_like_phone_submission(self, text):
            return False

        def _decide_price_priority_reply(self, **kwargs):
            return None

        def _decide_brand_priority_reply(self, **kwargs):
            return None

        def _decide_process_priority_reply(self, **kwargs):
            return None

        def _decide_address_followup_priority_reply(self, **kwargs):
            return None

        def _should_block_kb_by_polite_guard(self, **kwargs):
            return False, ""

        def _decide_store_hours_priority_reply(self, **kwargs):
            return None

        def _looks_like_travel_schedule_statement(self, text):
            return False

        def _resolve_kb_contact_trigger_type(self, **kwargs):
            return ""

        def _select_kb_variant_answer(self, answers, user_state, user_id_hash=""):
            if not answers:
                return "", -1, False
            return answers[0], 0, False

        def __getattr__(self, name):
            if name.startswith("_decide_"):
                return lambda **kwargs: None
            if name in {"_is_ambiguous_short_fragment", "_is_follow_up_question", "_looks_like_process_query"}:
                return lambda *args, **kwargs: False
            raise AttributeError(name)

    from src.core.agent_types import AgentDecision

    agent = MockAgent()
    decision = decide_general_reply(
        agent=agent,
        latest_user_text="营业时间呢",
        intent="general",
        route={"reason": "unknown"},
        conversation_history=[],
        session_state={},
        user_state={},
        user_id_hash="test",
    )

    print(f"rule_id: {decision.rule_id}")
    print(f"reply: {decision.reply_text}")

    assert decision.rule_id == "KB_MATCH", "非地区问题不应被追问耗尽兜底拦截"
    print("✅ 测试通过：其他问题不会被错误切到联系方式")
    print()


def test_state_merge_without_session_manager():
    """测试没有 SessionManager 时仍可合并状态"""
    print("=" * 60)
    print("测试 6: 缺少 SessionManager 也能读取统一状态")
    print("=" * 60)

    memory_store, _, conversation_logger = create_mock_components()
    unified_state = UnifiedSessionState(memory_store, None, conversation_logger)

    session_id = "test_session_no_manager"
    user_hash = "test_user_hash"
    memory_store.update_session_state(session_id, {"contact_image_sent_count": 1}, user_hash)

    state = unified_state.get_state(session_id, user_hash)
    print(f"contact_image_sent: {state.get('contact_image_sent')}")

    assert state.get("contact_image_sent") == True, "没有 SessionManager 时也应正常返回状态"
    print("✅ 测试通过：缺少 SessionManager 不会阻塞状态读取")
    print()


if __name__ == "__main__":
    print("\n统一状态管理测试套件")
    print("=" * 60)

    try:
        test_state_merge()
        test_logger_extraction()
        test_logger_session_filtering()
        test_confirmed_facts()
        test_geo_followup_exhausted_fallback()
        test_geo_followup_exhausted_does_not_block_other_topics()
        test_state_merge_without_session_manager()

        print("=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)

    except AssertionError as e:
        print(f"❌ 测试失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 测试异常：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
