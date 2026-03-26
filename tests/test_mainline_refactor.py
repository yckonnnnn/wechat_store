import tempfile
import unittest
from pathlib import Path

from src.data.memory_store import MemoryStore

import test_rule_engine as rule_engine_tests


class MainlineRefactorTestCase(unittest.TestCase):
    def test_memory_store_migrates_delivery_stages(self):
        with tempfile.TemporaryDirectory() as td:
            memory = MemoryStore(Path(td) / "memory.json")
            state = memory.get_session_state("s1", user_hash="u1")
            state.update(
                {
                    "contact_image_sent_count": 2,
                    "address_image_sent_paths_by_store": {
                        "beijing_chaoyang": ["a.jpg", "b.jpg"],
                        "sh_hongkou": ["c.jpg"],
                    },
                    "sent_address_stores": ["beijing_chaoyang", "sh_hongkou"],
                }
            )
            memory.update_session_state("s1", state, user_hash="u1")
            migrated = memory.get_session_state("s1", user_hash="u1")
            self.assertEqual(migrated.get("contact_delivery_stage"), "delivered_once")
            self.assertEqual(migrated.get("address_delivery_stage_by_store", {}).get("beijing_chaoyang"), "delivered_closed")
            self.assertEqual(migrated.get("address_delivery_stage_by_store", {}).get("sh_hongkou"), "delivered_once")

    def test_address_delivery_only_resends_on_explicit_request(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = helper._build_agent(
                Path(td),
                address_image_files=["北京地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang"},
            )

            first = agent.decide("s1", "u1", "北京地址给我", [])
            self.assertEqual(first.rule_id, "ADDRESS_DELIVERY_FIRST")
            self.assertTrue(any(item.get("type") == "address_image" for item in first.media_items))
            agent.mark_media_sent("s1", "u1", first.media_items[0], True)

            second = agent.decide("s1", "u1", "你推荐哪家", [{"role": "assistant", "content": first.reply_text}])
            self.assertNotEqual(second.rule_id, "ADDRESS_DELIVERY_RESEND")
            self.assertFalse(any(item.get("type") == "address_image" for item in second.media_items))

            third = agent.decide("s1", "u1", "再发一下位置图", [{"role": "assistant", "content": first.reply_text}])
            self.assertEqual(third.rule_id, "ADDRESS_DELIVERY_RESEND")
            self.assertTrue(any(item.get("type") == "address_image" for item in third.media_items))

    def test_address_resend_needs_unique_store(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = helper._build_agent(
                Path(td),
                address_image_files=["北京地址.jpg", "虹口地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang", "虹口地址.jpg": "sh_hongkou"},
            )
            first = agent.decide("s1", "u1", "北京地址给我", [])
            second = agent.decide("s1", "u1", "虹口地址给我", [{"role": "assistant", "content": first.reply_text}])
            agent.mark_media_sent("s1", "u1", first.media_items[0], True)
            agent.mark_media_sent("s1", "u1", second.media_items[0], True)

            third = agent.decide("s1", "u1", "再发一下位置图", [{"role": "assistant", "content": second.reply_text}])
            self.assertEqual(third.rule_id, "ADDRESS_RESEND_NEED_STORE")
            self.assertEqual(third.media_plan, "none")

    def test_contact_delivery_stops_after_phone_capture(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = helper._build_agent(Path(td))
            first = agent.decide("s1", "u1", "13812345678", [])
            self.assertEqual(first.rule_id, "CONTACT_PHONE_SUBMITTED")

            second = agent.decide(
                "s1",
                "u1",
                "怎么联系",
                [{"role": "user", "content": "13812345678"}, {"role": "assistant", "content": first.reply_text}],
            )
            self.assertEqual(second.rule_id, "LLM_CONTACT_CAPTURED")
            self.assertFalse(any(item.get("type") == "contact_image" for item in second.media_items))

    def test_conversation_repair_has_priority_and_no_media(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = helper._build_agent(Path(td))
            llm.reply_text = "姐姐，刚刚是我没说清楚，您这轮主要是想确认门店安排，我直接继续跟您说清楚🌹"
            decision = agent.decide("s1", "u1", "你没听懂我的意思", [])
            self.assertEqual(decision.rule_id, "LLM_CONVERSATION_REPAIR")
            self.assertEqual(decision.media_plan, "none")
            self.assertEqual(decision.media_items, [])

    def test_position_preference_does_not_trigger_address_delivery(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = helper._build_agent(Path(td))
            llm.reply_text = "姐姐，位置远一点也没关系，我按您要认真、做得漂亮这个要求给您选设计师。🌹"

            decision = agent.decide(
                "s1",
                "u1",
                "位置远点儿，我可以克服困难。我主要想找一个做事认真、做的漂亮的设计师",
                [],
            )

            self.assertNotEqual(decision.rule_id, "ADDRESS_DELIVERY_FIRST")
            self.assertFalse(any(item.get("type") == "address_image" for item in decision.media_items))

    def test_store_confirmation_does_not_reopen_address_delivery(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = helper._build_agent(
                Path(td),
                address_image_files=["北京地址.jpg", "上海人广地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang", "上海人广地址.jpg": "sh_renmin"},
            )
            llm.reply_text = "姐姐，我是在按您的要求帮您判断适合的门店，不是直接把您往人民广场推。🌹"

            first = agent.decide("s1", "u1", "北京地址给我", [])
            agent.mark_media_sent("s1", "u1", first.media_items[0], True)

            decision = agent.decide(
                "s1",
                "u1",
                "我主要想问，您是按照我的要求选一个好的门店告诉我，还是你确定让我在人民广场店",
                [{"role": "assistant", "content": first.reply_text}],
            )

            self.assertNotEqual(decision.rule_id, "ADDRESS_DELIVERY_FIRST")
            self.assertFalse(any(item.get("type") == "address_image" for item in decision.media_items))

    def test_store_recommendation_rule_only_handles_explicit_recommend_request(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = helper._build_agent(Path(td))
            llm.reply_text = "姐姐，我是在按您的要求帮您判断门店，不是直接把您往人民广场推。🌹"

            decision = agent.decide(
                "s1",
                "u1",
                "您的意思是，还是让我去人民广场，对不对",
                [],
            )

            self.assertNotEqual(decision.rule_id, "STORE_RECOMMENDATION")
            self.assertEqual(decision.reply_source, "llm")

    def test_store_recommendation_rule_retires_after_address_delivery(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = helper._build_agent(
                Path(td),
                address_image_files=["上海人广地址.jpg"],
                store_targets={"上海人广地址.jpg": "sh_renmin"},
            )
            first = agent.decide("s1", "u1", "人民广场地址给我", [])
            self.assertEqual(first.rule_id, "ADDRESS_DELIVERY_FIRST")
            agent.mark_media_sent("s1", "u1", first.media_items[0], True)

            llm.reply_text = "姐姐，您这轮是在确认我是不是在硬推门店，我直接把这个点跟您说清楚。🌹"
            second = agent.decide(
                "s1",
                "u1",
                "你是不是确定让我去人民广场店",
                [{"role": "assistant", "content": first.reply_text}],
            )

            self.assertNotEqual(second.rule_id, "STORE_RECOMMENDATION")
            self.assertEqual(second.reply_source, "llm")


if __name__ == "__main__":
    unittest.main()
