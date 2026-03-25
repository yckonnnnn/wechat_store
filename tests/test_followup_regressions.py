import tempfile
import unittest
from pathlib import Path

import test_rule_engine as rule_engine_tests
from src.core.agent_types import AgentDecision


class FollowupRegressionTestCase(unittest.TestCase):
    def test_first_turn_generic_address_request_does_not_send_store_media_before_city_is_confirmed(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["北京地址.jpg", "虹口地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang", "虹口地址.jpg": "sh_hongkou"},
            )

            decision = agent.decide("generic_address_first_turn", "未确认地区用户", "地址给我", [])
            media_decision = agent.judge_post_reply_media(
                session_id="generic_address_first_turn",
                user_name="未确认地区用户",
                latest_user_text="地址给我",
                reply_text=decision.reply_text,
                conversation_history=[],
                decision=decision,
            )

            self.assertEqual(decision.reply_goal, "追问地区")
            self.assertEqual(decision.rule_id, "ADDR_ASK_REGION_R1")
            self.assertTrue(decision.first_turn_media_guard_applied)
            self.assertEqual(decision.first_turn_image_items, [])
            self.assertEqual(len(decision.first_turn_video_items), 1)
            self.assertEqual(decision.first_turn_video_items[0].get("type"), "delayed_video")
            self.assertEqual(media_decision.media_items, [])

    def test_explicit_district_overrides_previous_store_memory(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, llm = helper._build_agent(
                temp_dir,
                address_image_files=["北京地址.jpg", "虹口地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang", "虹口地址.jpg": "sh_hongkou"},
            )
            agent.set_options(use_knowledge_first=True, knowledge_threshold=0.6, reply_mode="llm_direct")

            session_id = "hongkou_override"
            user_name = "改口虹口用户"
            session_state = agent.memory_store.get_session_state(session_id, user_hash=agent._hash_user(user_name))
            session_state.update(
                {
                    "last_target_store": "beijing_chaoyang",
                    "address_image_sent_count": 1,
                    "sent_address_stores": ["beijing_chaoyang"],
                    "address_info_shared": True,
                    "conversation_facts": {"recommended_store": "beijing_chaoyang"},
                }
            )
            agent.memory_store.update_session_state(session_id, session_state, user_hash=agent._hash_user(user_name))
            agent.memory_store.save()

            llm.reply_text = "姐姐，北京朝阳门店位置直接看图片就可以哦。🌹"
            history = [{"role": "assistant", "content": "姐姐，北京朝阳门店位置直接看图片就可以哦。🌹"}]

            decision = agent.decide(session_id, user_name, "虹口地址给我", history)
            media_decision = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="虹口地址给我",
                reply_text=decision.reply_text,
                conversation_history=history,
                decision=decision,
            )

            self.assertIn("虹口", decision.reply_text)
            self.assertNotIn("北京朝阳", decision.reply_text)
            self.assertTrue(any(item.get("target_store") == "sh_hongkou" for item in (media_decision.media_items or [])))
            self.assertFalse(any(item.get("target_store") == "beijing_chaoyang" for item in (media_decision.media_items or [])))

    def test_same_store_second_trigger_uses_natural_reply_without_repeating_image(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, llm = helper._build_agent(
                temp_dir,
                address_image_files=["北京地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang"},
            )
            agent.set_options(use_knowledge_first=True, knowledge_threshold=0.6, reply_mode="llm_direct")

            session_id = "same_store_second_trigger"
            user_name = "重复北京用户"
            user_hash = agent._hash_user(user_name)
            session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
            session_state.update(
                {
                    "last_target_store": "beijing_chaoyang",
                    "address_image_sent_count": 1,
                    "sent_address_stores": ["beijing_chaoyang"],
                    "conversation_facts": {"recommended_store": "beijing_chaoyang", "city": "beijing"},
                }
            )
            agent.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
            agent.memory_store.save()

            llm.reply_text = "姐姐，您到北京前跟我说一声，我提前帮您安排就好。🌹"
            second = agent.decide(
                session_id,
                user_name,
                "我在三亚，过段时间去北京找你们",
                [
                    {"role": "user", "content": "我在北京"},
                    {"role": "assistant", "content": "姐姐，推荐您去北京朝阳店，我给您发一张位置图，您直接看图片会更直观。🌹"},
                ],
            )
            second_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="我在三亚，过段时间去北京找你们",
                reply_text=second.reply_text,
                conversation_history=[
                    {"role": "user", "content": "我在北京"},
                    {"role": "assistant", "content": "姐姐，推荐您去北京朝阳店，我给您发一张位置图，您直接看图片会更直观。🌹"},
                ],
                decision=second,
            )

            self.assertNotEqual(second.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertNotIn("推荐您去北京朝阳店", second.reply_text)
            self.assertEqual(second_media.media_items, [])

    def test_address_followup_after_image_answers_naturally_without_telling_user_to_check_picture(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["北京地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang"},
            )

            session_id = "address_followup_natural_reply"
            user_name = "地址追问用户"
            first = agent.decide(session_id, user_name, "北京店具体位置", [])
            agent.mark_media_sent(session_id, user_name, first.media_items[0], success=True)

            second = agent.decide(
                session_id,
                user_name,
                "具体地址怎么样",
                [
                    {"role": "user", "content": "北京店具体位置"},
                    {"role": "assistant", "content": first.reply_text},
                ],
            )

            self.assertEqual(second.rule_id, "ADDR_TEXT_AFTER_IMAGE")
            self.assertIn("平台限制", second.reply_text)
            self.assertIn("留个☎️", second.reply_text)
            self.assertNotIn("看图片", second.reply_text)
            self.assertNotIn("位置直接看图片", second.reply_text)

    def test_empty_visible_history_clears_stale_address_and_contact_context(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["北京地址.jpg", "虹口地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang", "虹口地址.jpg": "sh_hongkou"},
            )

            session_id = "fresh_start_after_history_deleted"
            user_name = "删历史后重来用户"
            user_hash = agent._hash_user(user_name)
            session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
            session_state.update(
                {
                    "last_target_store": "beijing_chaoyang",
                    "address_image_sent_count": 1,
                    "sent_address_stores": ["beijing_chaoyang"],
                    "address_info_shared": True,
                    "contact_image_sent_count": 1,
                    "contact_image_last_sent_at": "2026-03-25T00:00:00",
                    "contact_image_sent_paths": ["contact.jpg"],
                    "conversation_facts": {
                        "recommended_store": "beijing_chaoyang",
                        "city": "beijing",
                        "appointment_ready": True,
                    },
                    "conversation_stage": "appointment_ready",
                    "active_topic": "appointment",
                    "last_geo_pending": True,
                    "last_geo_route_reason": "need_region",
                }
            )
            agent.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
            agent.memory_store.update_user_state(
                user_hash,
                {
                    "video_armed": True,
                    "video_sent": True,
                    "post_contact_reply_count": 3,
                    "recent_reply_hashes": ["old-reply"],
                },
            )
            agent.memory_store.save()

            decision = agent.decide(session_id, user_name, "地址给我", [])
            media_decision = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="地址给我",
                reply_text=decision.reply_text,
                conversation_history=[],
                decision=decision,
            )
            refreshed_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
            refreshed_user_state = agent.memory_store.get_user_state(user_hash)

            self.assertEqual(decision.rule_id, "ADDR_ASK_REGION_R1")
            self.assertEqual(media_decision.media_items, [])
            self.assertEqual(refreshed_state.get("last_target_store"), "")
            self.assertEqual(int(refreshed_state.get("address_image_sent_count", 0) or 0), 0)
            self.assertEqual(int(refreshed_state.get("contact_image_sent_count", 0) or 0), 0)
            self.assertTrue(bool(refreshed_state.get("last_geo_pending", False)))
            self.assertEqual(refreshed_state.get("last_geo_route_reason"), "need_region")
            self.assertEqual(refreshed_user_state.get("recent_reply_hashes"), [])

    def test_empty_visible_history_does_not_treat_contact_as_already_captured(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "fresh_contact_after_history_deleted"
            user_name = "删历史后联系方式用户"
            user_hash = agent._hash_user(user_name)
            session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
            session_state.update(
                {
                    "contact_image_sent_count": 1,
                    "contact_image_last_sent_at": "2026-03-25T00:00:00",
                    "contact_image_sent_paths": ["contact.jpg"],
                }
            )
            agent.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
            agent.memory_store.save()

            decision = agent.decide(session_id, user_name, "13562120968", [])

            self.assertEqual(decision.rule_id, "CONTACT_PHONE_SUBMITTED")
            self.assertNotIn("之前留的方式", decision.reply_text)

    def test_travel_plan_to_beijing_does_not_misfire_to_service_hours(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)
            agent.set_options(use_knowledge_first=True, knowledge_threshold=0.6, reply_mode="llm_direct")

            history = [
                {"role": "user", "content": "怎么卖的假发"},
                {"role": "assistant", "content": "姐姐，您提供电话，我来联系您，可以给您具体的介绍假发价格，款式，地址位置，坐车导航路线，以及预约事项。❤️"},
            ]

            decision = agent.decide("travel_plan_not_hours", "行程用户", "我在三亚呢，过段时间四月份去北京", history)

            self.assertNotEqual(decision.rule_id, "SERVICE_HOURS_PRIORITY")
            self.assertNotIn("营业时间", decision.reply_text)
            self.assertNotIn("上午9：30", decision.reply_text)

    def test_travel_schedule_statement_does_not_misfire_to_lifespan(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            decision = agent.decide("travel_plan_not_lifespan", "行程时长用户", "我多久去北京比较方便", [])

            self.assertNotEqual(decision.rule_id, "LIFESPAN_PRIORITY")
            self.assertNotIn("3到5年", decision.reply_text)

    def test_travel_schedule_statement_in_address_context_uses_natural_store_followup(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["北京地址.jpg"],
                store_targets={"北京地址.jpg": "beijing_chaoyang"},
            )

            session_id = "travel_schedule_address_context"
            user_name = "行程地址用户"
            first = agent.decide(session_id, user_name, "我在北京", [])
            agent.mark_media_sent(session_id, user_name, first.media_items[0], success=True)

            second = agent.decide(
                session_id,
                user_name,
                "我在三亚，过段时间去北京",
                [
                    {"role": "user", "content": "我在北京"},
                    {"role": "assistant", "content": first.reply_text},
                ],
            )

            self.assertEqual(second.rule_id, "ADDR_TRAVEL_SCHEDULE_FOLLOWUP")
            self.assertIn("过来前跟我说一声", second.reply_text)
            self.assertNotIn("看图片就可以哦", second.reply_text)

    def test_llm_reply_store_mention_can_drive_address_image_without_user_side_store_mapping(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(
                temp_dir,
                address_image_files=["静安地址.jpg"],
                store_targets={"静安地址.jpg": "sh_jingan"},
            )
            agent.set_options(use_knowledge_first=True, knowledge_threshold=0.6, reply_mode="llm_direct")

            session_id = "baoshan_llm_reply_drives_media"
            user_name = "宝山用户"
            decision = AgentDecision(
                reply_text="姐姐，上海静安门店位置直接看图片就可以哦。🌹",
                intent="general",
                route_reason="sh_district_map:宝山",
                reply_goal="解答",
                media_plan="none",
                reply_source="llm",
                rule_id="LLM_FOLLOW_UP",
            )
            media_decision = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="宝山有吗",
                reply_text=decision.reply_text,
                conversation_history=[
                    {"role": "user", "content": "价格是多少"},
                    {"role": "assistant", "content": "姐姐，我们是私人定制的假发，根据不同的材质，正常3000、4000、5000、6000都有。🌹"},
                ],
                decision=decision,
            )

            self.assertTrue(any(item.get("target_store") == "sh_jingan" for item in (media_decision.media_items or [])))

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

    def test_contact_followup_after_contact_image_stops_reminding_user_to_check_picture(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "contact_followup_natural_reply"
            user_name = "联系方式追问用户"
            first = agent.decide(session_id, user_name, "怎么联系你", [])

            self.assertEqual(first.rule_id, "CONTACT_SEND_IMAGE")
            agent.mark_media_sent(session_id, user_name, first.media_items[0], success=True)

            second = agent.decide(
                session_id,
                user_name,
                "联系方式怎么给你",
                [
                    {"role": "user", "content": "怎么联系你"},
                    {"role": "assistant", "content": first.reply_text},
                ],
            )

            self.assertEqual(second.rule_id, "CONTACT_FOLLOWUP")
            self.assertIn("留个☎️", second.reply_text)
            self.assertNotIn("刚发的联系方式图", second.reply_text)
            self.assertNotIn("点开就能看到", second.reply_text)

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
                helper._append_media_success_log(
                    conversations_dir=agent.conversation_log_dir,
                    session_id=session_id,
                    media_type=str(item.get("type", "") or ""),
                    media_path=str(item.get("path", "") or ""),
                    ts="2026-03-25T10:00:00",
                    user_id_hash=agent._hash_user(user_name),
                    trigger_source=str(item.get("route_reason", "") or ""),
                )
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

    def test_remote_followup_without_visible_contact_image_still_sends_contact_image(self):
        helper = rule_engine_tests.RuleEngineTestCase()
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = helper._build_agent(temp_dir)

            session_id = "remote_followup_needs_visible_contact"
            user_name = "外地补图用户"
            user_hash = agent._hash_user(user_name)
            session_state = agent.memory_store.get_session_state(session_id, user_hash=user_hash)
            session_state.update(
                {
                    "remote_flow_active": True,
                    "remote_contact_image_sent": True,
                    "contact_image_sent_count": 2,
                    "contact_image_sent_paths": ["contact.jpg"],
                }
            )
            agent.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
            agent.memory_store.save()

            history = [
                {"role": "user", "content": "我人在三亚"},
                {"role": "assistant", "content": "姐姐，外地也可以远程定制。❤️"},
            ]

            second = agent.decide(session_id, user_name, "不在上海怎么买", history)
            second_media = agent.judge_post_reply_media(
                session_id=session_id,
                user_name=user_name,
                latest_user_text="不在上海怎么买",
                reply_text=second.reply_text,
                conversation_history=history,
                decision=second,
            )

            self.assertIn(second.rule_id, {"REMOTE_FLOW_ENTRY", "REMOTE_FLOW_FOLLOWUP"})
            self.assertTrue(any(item.get("type") == "contact_image" for item in (second_media.media_items or [])))

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
                helper._append_media_success_log(
                    conversations_dir=agent.conversation_log_dir,
                    session_id=session_id,
                    media_type=str(item.get("type", "") or ""),
                    media_path=str(item.get("path", "") or ""),
                    ts="2026-03-25T10:00:00",
                    user_id_hash=agent._hash_user(user_name),
                    trigger_source=str(item.get("route_reason", "") or ""),
                )
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
                helper._append_media_success_log(
                    conversations_dir=agent.conversation_log_dir,
                    session_id=session_id,
                    media_type=str(item.get("type", "") or ""),
                    media_path=str(item.get("path", "") or ""),
                    ts="2026-03-25T10:00:00",
                    user_id_hash=agent._hash_user(user_name),
                    trigger_source=str(item.get("route_reason", "") or ""),
                )
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
