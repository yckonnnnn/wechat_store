import tempfile
import unittest
from pathlib import Path

import test_rule_engine as rule_engine_tests


class FollowupRegressionTestCase(unittest.TestCase):
    def test_weekday_appointment_followup_does_not_turn_into_service_hours(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = helper._build_agent(temp_dir)
            repository.add(
                "周一可以预约吗？怎么预约？",
                "姐姐，我们这边是预约制，您确定时间后我帮您安排。🤍",
                intent="appointment",
                tags=["预约"],
            )

            first = agent.decide("appointment_followup", "预约用户", "周一可以预约吗", [])
            agent.mark_reply_sent("appointment_followup", "预约用户", first.reply_text)
            second = agent.decide("appointment_followup", "预约用户", "那周二呢", [])

            self.assertNotIn("9:30", second.reply_text)
            self.assertNotIn("下午6:00", second.reply_text)
            self.assertNotEqual(agent.memory_store.get_session_state("appointment_followup").get("last_answer_topic"), "service_hours")
            self.assertLessEqual(llm.calls, 1)

    def test_price_fallback_third_turn_still_guides_to_private_contact(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, llm = helper._build_agent(temp_dir)

            session_id = "price_fallback_private_guide"
            user_name = "价格追问用户"
            first = agent.decide(session_id, user_name, "大概啥价位", [])
            second = agent.decide(session_id, user_name, "这个得多少钱", [])
            third = agent.decide(session_id, user_name, "预算多少呢", [])

            self.assertEqual(first.rule_id, "PRICE_PRIORITY_FALLBACK")
            self.assertEqual(second.rule_id, "PRICE_PRIORITY_FALLBACK")
            self.assertEqual(third.rule_id, "PRICE_PRIORITY_PRIVATE_GUIDE")
            self.assertIn("留个☎️", third.reply_text)
            self.assertLessEqual(llm.calls, 1)


if __name__ == "__main__":
    unittest.main()
