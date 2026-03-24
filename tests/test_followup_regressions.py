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
            self.assertNotIn("9：30", second.reply_text)
            self.assertNotIn("下午6:00", second.reply_text)
            self.assertNotIn("下午6：00", second.reply_text)
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

    def test_contact_added_confirmation_does_not_ask_for_phone_again(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "contact_added_confirmation"
            user_name = "联系方式用户"
            first = agent.decide(session_id, user_name, "13562120968", [])
            agent.mark_reply_sent(session_id, user_name, first.reply_text)
            second = agent.decide(
                session_id,
                user_name,
                "我刚才加你了",
                [
                    {"role": "user", "content": "13562120968"},
                    {"role": "assistant", "content": first.reply_text},
                ],
            )

            self.assertEqual(second.rule_id, "CONTACT_ALREADY_ADDED")
            self.assertNotIn("留个☎️", second.reply_text)
            self.assertNotIn("留个", second.reply_text)

    def test_contact_already_captured_does_not_repeat_contact_request(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "contact_already_captured"
            user_name = "重复留电用户"
            first = agent.decide(session_id, user_name, "13562120968", [])
            agent.mark_reply_sent(session_id, user_name, first.reply_text)
            second = agent.decide(
                session_id,
                user_name,
                "我留了两次电话了",
                [
                    {"role": "user", "content": "13562120968"},
                    {"role": "assistant", "content": first.reply_text},
                ],
            )

            self.assertEqual(second.rule_id, "CONTACT_ALREADY_CAPTURED")
            self.assertNotIn("留个☎️", second.reply_text)
            self.assertNotIn("留个", second.reply_text)

    def test_weekend_visit_followup_returns_closed_days_fact(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, _ = helper._build_agent(temp_dir)
            repository.add(
                "你们上班时间是几点？营业时间？",
                "姐姐，我们营业时间是上午9：30-下午6：00，除春节、技术培训等特殊情况外，其他时间正常上班❤️",
                intent="service_hours",
                tags=["营业时间"],
            )

            session_id = "weekend_closed_followup"
            user_name = "周末用户"
            first = agent.decide(session_id, user_name, "营业时间是几点", [])
            agent.mark_reply_sent(session_id, user_name, first.reply_text)
            second = agent.decide(
                session_id,
                user_name,
                "我想周六过去",
                [
                    {"role": "user", "content": "营业时间是几点"},
                    {"role": "assistant", "content": first.reply_text},
                ],
            )

            self.assertEqual(second.rule_id, "SERVICE_HOURS_WEEKEND_CLOSED")
            self.assertIn("除春节、技术培训等特殊情况外", second.reply_text)

    def test_address_replies_use_picture_wording_instead_of_circle_wording(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["徐汇地址.jpg"],
                store_targets={"徐汇地址.jpg": "sh_xuhui"},
            )

            decision = agent.decide("picture_wording", "看图用户", "我在上海徐汇，去哪家店比较近", [])
            self.assertIn("看图片", decision.reply_text)
            self.assertNotIn("圈圈", decision.reply_text)
            self.assertNotIn("红框", decision.reply_text)

    def test_typo_appointment_query_triggers_contact_image_before_phone_submission(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            decision = agent.decide("typo_appointment", "错别字预约用户", "需不需要预月", [])
            media_decision = agent.judge_post_reply_media(
                session_id="typo_appointment",
                user_name="错别字预约用户",
                latest_user_text="需不需要预月",
                reply_text=decision.reply_text,
                conversation_history=[],
                decision=decision,
            )

            self.assertTrue(any(item.get("type") == "contact_image" for item in (media_decision.media_items or [])))

    def test_appointment_followup_after_address_guides_to_contact_instead_of_repeating_address(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["人广地址.jpg"],
                store_targets={"人广地址.jpg": "sh_renmin"},
            )

            session_id = "appointment_after_address"
            user_name = "预约跟进用户"
            first = agent.decide(session_id, user_name, "我在上海人民广场附近", [])
            first_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="我在上海人民广场附近",
                reply_text=first.reply_text,
                conversation_history=[],
                decision=first,
            )
            for item in (first_media.media_items or []):
                agent.mark_media_sent(session_id, user_name, item, True)

            history = [
                {"role": "user", "content": "我在上海人民广场附近"},
                {"role": "assistant", "content": first.reply_text},
            ]
            second = agent.decide(session_id, user_name, "那怎么约呀", history)
            second_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="那怎么约呀",
                reply_text=second.reply_text,
                conversation_history=history,
                decision=second,
            )

            self.assertEqual(second.intent, "appointment")
            self.assertIn("专属客服", second.reply_text)
            self.assertIn("预约", second.reply_text)
            self.assertTrue(any(item.get("type") == "contact_image" for item in (second_media.media_items or [])))
            self.assertFalse(any(item.get("type") == "address_image" for item in (second_media.media_items or [])))

    def test_appointment_followup_after_contact_image_uses_text_only(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["人广地址.jpg"],
                store_targets={"人广地址.jpg": "sh_renmin"},
            )

            session_id = "appointment_followup_text_only"
            user_name = "预约继续追问用户"
            history = []

            first = agent.decide(session_id, user_name, "我在上海人民广场附近", history)
            first_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="我在上海人民广场附近",
                reply_text=first.reply_text,
                conversation_history=history,
                decision=first,
            )
            for item in (first_media.media_items or []):
                agent.mark_media_sent(session_id, user_name, item, True)
            history.extend(
                [
                    {"role": "user", "content": "我在上海人民广场附近"},
                    {"role": "assistant", "content": first.reply_text},
                ]
            )

            second = agent.decide(session_id, user_name, "需不需要预月", history)
            second_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="需不需要预月",
                reply_text=second.reply_text,
                conversation_history=history,
                decision=second,
            )
            for item in (second_media.media_items or []):
                agent.mark_media_sent(session_id, user_name, item, True)
            history.extend(
                [
                    {"role": "user", "content": "需不需要预月"},
                    {"role": "assistant", "content": second.reply_text},
                ]
            )

            third = agent.decide(session_id, user_name, "那怎么约呀", history)
            third_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="那怎么约呀",
                reply_text=third.reply_text,
                conversation_history=history,
                decision=third,
            )

            self.assertIn("专属客服", third.reply_text)
            self.assertIn("方便的时间", third.reply_text)
            self.assertFalse(third_media.media_items)

    def test_phone_submission_does_not_send_extra_contact_image(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            decision = agent.decide("phone_submission_no_extra_media", "留电用户", "13900139000", [])
            media_decision = agent.judge_post_reply_media(
                session_id="phone_submission_no_extra_media",
                user_name="留电用户",
                latest_user_text="13900139000",
                reply_text=decision.reply_text,
                conversation_history=[],
                decision=decision,
            )

            self.assertEqual(decision.rule_id, "CONTACT_PHONE_SUBMITTED")
            self.assertFalse(media_decision.media_items)

    def test_remote_out_of_town_first_turn_sends_only_contact_image(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            decision = agent.decide("remote_first_turn", "异地用户", "我不在上海 我在哈尔滨", [])
            media_decision = agent.judge_post_reply_media(
                session_id="remote_first_turn",
                user_name="异地用户",
                latest_user_text="我不在上海 我在哈尔滨",
                reply_text=decision.reply_text,
                conversation_history=[],
                decision=decision,
            )

            self.assertEqual(decision.rule_id, "REMOTE_FLOW_ENTRY")
            self.assertIn("远程定制", decision.reply_text)
            self.assertTrue(any(item.get("type") == "contact_image" for item in (media_decision.media_items or [])))
            self.assertFalse(any(item.get("type") == "address_image" for item in (media_decision.media_items or [])))

    def test_remote_followup_after_contact_image_uses_text_only(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "remote_followup_text_only"
            user_name = "异地追问用户"
            history = []

            first = agent.decide(session_id, user_name, "我不在上海 我在哈尔滨", history)
            first_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="我不在上海 我在哈尔滨",
                reply_text=first.reply_text,
                conversation_history=history,
                decision=first,
            )
            for item in (first_media.media_items or []):
                agent.mark_media_sent(session_id, user_name, item, True)
            history.extend(
                [
                    {"role": "user", "content": "我不在上海 我在哈尔滨"},
                    {"role": "assistant", "content": first.reply_text},
                ]
            )

            second = agent.decide(session_id, user_name, "快点回我", history)
            second_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="快点回我",
                reply_text=second.reply_text,
                conversation_history=history,
                decision=second,
            )

            self.assertEqual(second.rule_id, "REMOTE_FLOW_FOLLOWUP")
            self.assertIn("别着急", second.reply_text)
            self.assertFalse(second_media.media_items)

    def test_remote_shipping_followup_stays_remote_and_does_not_repeat_media(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "remote_shipping_followup"
            user_name = "异地邮寄用户"
            history = []

            first = agent.decide(session_id, user_name, "我不在上海 我在哈尔滨", history)
            first_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="我不在上海 我在哈尔滨",
                reply_text=first.reply_text,
                conversation_history=history,
                decision=first,
            )
            for item in (first_media.media_items or []):
                agent.mark_media_sent(session_id, user_name, item, True)
            history.extend(
                [
                    {"role": "user", "content": "我不在上海 我在哈尔滨"},
                    {"role": "assistant", "content": first.reply_text},
                ]
            )

            second = agent.decide(session_id, user_name, "能不能邮寄", history)
            second_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="能不能邮寄",
                reply_text=second.reply_text,
                conversation_history=history,
                decision=second,
            )

            self.assertEqual(second.rule_id, "REMOTE_FLOW_FOLLOWUP")
            self.assertIn("远程定制", second.reply_text)
            self.assertIn("寄", second.reply_text)
            self.assertFalse(second_media.media_items)

    def test_remote_flow_contact_request_after_image_does_not_repeat_media(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "remote_contact_request_after_image"
            user_name = "异地联系用户"
            history = []

            first = agent.decide(session_id, user_name, "我不在上海 我在哈尔滨", history)
            first_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="我不在上海 我在哈尔滨",
                reply_text=first.reply_text,
                conversation_history=history,
                decision=first,
            )
            for item in (first_media.media_items or []):
                agent.mark_media_sent(session_id, user_name, item, True)
            history.extend(
                [
                    {"role": "user", "content": "我不在上海 我在哈尔滨"},
                    {"role": "assistant", "content": first.reply_text},
                ]
            )

            second = agent.decide(session_id, user_name, "那你直接加我微信吧", history)
            second_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="那你直接加我微信吧",
                reply_text=second.reply_text,
                conversation_history=history,
                decision=second,
            )

            self.assertEqual(second.rule_id, "REMOTE_FLOW_FOLLOWUP")
            self.assertIn("我这就加您", second.reply_text)
            self.assertFalse(second_media.media_items)


if __name__ == "__main__":
    unittest.main()
