import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService


class DummyLLMService:
    def __init__(self, reply_text: str = "姐姐这个问题我给您详细说明下哈🌹"):
        self.reply_text = reply_text
        self.reply_queue = []
        self.calls = 0
        self.prompt = ""

    def set_system_prompt(self, prompt: str):
        self.prompt = prompt

    def generate_reply_sync(self, user_message: str, conversation_history=None):
        self.calls += 1
        if self.reply_queue:
            return True, self.reply_queue.pop(0)
        return True, self.reply_text

    def get_current_model_name(self) -> str:
        return "DummyLLM"


class RuleEngineTestCase(unittest.TestCase):
    def _build_agent(
        self,
        temp_dir: Path,
        whitelist_sessions=None,
        address_image_files=None,
        store_targets=None,
        include_local_video: bool = True,
    ):
        whitelist_sessions = whitelist_sessions or []
        address_image_files = address_image_files or ["北京地址.jpg"]
        store_targets = store_targets or {}

        images_dir = temp_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / "contact.jpg").write_text("x", encoding="utf-8")
        if include_local_video:
            (images_dir / "video.mp4").write_text("x", encoding="utf-8")
        for address_name in address_image_files:
            (images_dir / address_name).write_text("x", encoding="utf-8")

        image_categories_path = temp_dir / "image_categories.json"
        image_categories_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "categories": ["联系方式", "店铺地址", "视频素材"],
                    "images": {
                        "联系方式": ["contact.jpg"],
                        "店铺地址": list(address_image_files),
                        "视频素材": ["video.mp4"],
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
        media_whitelist_path.write_text(
            json.dumps({"version": 1, "session_ids": whitelist_sessions}, ensure_ascii=False),
            encoding="utf-8",
        )
        conversation_log_dir = temp_dir / "conversations"
        conversation_log_dir.mkdir(parents=True, exist_ok=True)

        system_prompt = temp_dir / "system_prompt.md"
        playbook = temp_dir / "playbook.md"
        system_prompt.write_text("你是客服助手。", encoding="utf-8")
        playbook.write_text("语气友好。", encoding="utf-8")

        kb_file = temp_dir / "knowledge.json"
        kb_file.write_text("[]", encoding="utf-8")

        memory_path = temp_dir / "memory.json"
        route_alias_path = temp_dir / "shanghai_route_aliases.json"

        repository = KnowledgeRepository(kb_file)
        knowledge_service = KnowledgeService(
            repository,
            address_config_path=Path("config") / "address.json",
            shanghai_route_alias_path=route_alias_path,
        )
        llm_service = DummyLLMService()
        memory_store = MemoryStore(memory_path)

        agent = CustomerServiceAgent(
            knowledge_service=knowledge_service,
            llm_service=llm_service,
            memory_store=memory_store,
            images_dir=images_dir,
            image_categories_path=image_categories_path,
            system_prompt_doc_path=system_prompt,
            playbook_doc_path=playbook,
            reply_templates_path=reply_templates_path,
            media_whitelist_path=media_whitelist_path,
            conversation_log_dir=conversation_log_dir,
        )
        return agent, knowledge_service, repository, llm_service

    def _append_media_success_log(
        self,
        conversations_dir: Path,
        session_id: str,
        media_type: str,
        media_path: str,
        ts: str,
        user_id_hash: str,
        trigger_source: str = "",
    ) -> None:
        log_file = conversations_dir / f"{session_id}.jsonl"
        records = []
        if log_file.exists():
            existing = [x for x in log_file.read_text(encoding="utf-8").splitlines() if x.strip()]
            for line in existing:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
        records.extend(
            [
                {
                    "timestamp": ts,
                    "session_id": session_id,
                    "user_id_hash": user_id_hash,
                    "event_type": "media_attempt",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {
                        "type": media_type,
                        "path": media_path,
                        "trigger_source": trigger_source,
                    },
                },
                {
                    "timestamp": ts,
                    "session_id": session_id,
                    "user_id_hash": user_id_hash,
                    "event_type": "media_result",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {
                        "type": media_type,
                        "success": True,
                        "result": {"ok": True},
                        "trigger_source": trigger_source,
                    },
                },
            ]
        )
        log_file.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in records) + "\n", encoding="utf-8")

    def _append_assistant_reply_log(
        self,
        conversations_dir: Path,
        session_id: str,
        user_id_hash: str,
        ts: str,
        text: str = "收到",
    ) -> None:
        log_file = conversations_dir / f"{session_id}.jsonl"
        records = []
        if log_file.exists():
            existing = [x for x in log_file.read_text(encoding="utf-8").splitlines() if x.strip()]
            for line in existing:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
        records.append(
            {
                "timestamp": ts,
                "session_id": session_id,
                "user_id_hash": user_id_hash,
                "event_type": "assistant_reply",
                "reply_source": "rule",
                "rule_id": "DUMMY",
                "model_name": "",
                "payload": {"text": text, "round_media_sent_types": []},
            }
        )
        log_file.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in records) + "\n", encoding="utf-8")

    def test_region_route_precedence(self):
        with tempfile.TemporaryDirectory() as td:
            kb_file = Path(td) / "knowledge.json"
            kb_file.write_text("[]", encoding="utf-8")
            repository = KnowledgeRepository(kb_file)
            service = KnowledgeService(
                repository,
                address_config_path=Path("config") / "address.json",
                shanghai_route_alias_path=Path(td) / "shanghai_route_aliases.json",
            )

            hebei_route = service.resolve_store_recommendation("我在河北")
            self.assertEqual(hebei_route.get("target_store"), "beijing_chaoyang")

            sh_route = service.resolve_store_recommendation("我在上海徐汇")
            self.assertEqual(sh_route.get("target_store"), "sh_xuhui")
            sh_landmark_route = service.resolve_store_recommendation("我在上海徐家汇")
            self.assertEqual(sh_landmark_route.get("target_store"), "sh_xuhui")
            self.assertEqual(sh_landmark_route.get("reason"), "sh_district_map:徐家汇")

            shijiazhuang_route = service.resolve_store_recommendation("石家庄有吗")
            self.assertEqual(shijiazhuang_route.get("target_store"), "beijing_chaoyang")
            self.assertEqual(shijiazhuang_route.get("reason"), "north_fallback_beijing")

            non_cov_route = service.resolve_store_recommendation("我在黑龙江")
            self.assertEqual(non_cov_route.get("reason"), "out_of_coverage")

            neg_sh_only = service.resolve_store_recommendation("我不在上海")
            self.assertEqual(neg_sh_only.get("reason"), "out_of_coverage")
            self.assertEqual(neg_sh_only.get("route_type"), "non_coverage")
            self.assertEqual(neg_sh_only.get("detected_region"), "非上海地区")

            neg_bj_only = service.resolve_store_recommendation("我不在北京")
            self.assertEqual(neg_bj_only.get("reason"), "out_of_coverage")
            self.assertEqual(neg_bj_only.get("route_type"), "non_coverage")
            self.assertEqual(neg_bj_only.get("detected_region"), "非北京地区")

            neg_both = service.resolve_store_recommendation("我不在北京和上海")
            self.assertEqual(neg_both.get("reason"), "out_of_coverage")
            self.assertEqual(neg_both.get("route_type"), "non_coverage")
            self.assertEqual(neg_both.get("detected_region"), "非沪京地区")

            normal_price_route = service.resolve_store_recommendation("不同价格有什么区别啊？")
            self.assertEqual(normal_price_route.get("reason"), "unknown")

            route_alias_xuhui = service.resolve_store_recommendation("常德路地址能发一下吗？")
            self.assertEqual(route_alias_xuhui.get("target_store"), "sh_xuhui")
            self.assertEqual(route_alias_xuhui.get("reason"), "sh_route_scored:sh_xuhui")
            self.assertEqual(route_alias_xuhui.get("confidence"), "high")

            route_alias_jingan = service.resolve_store_recommendation("长寿路地址能发一下")
            self.assertEqual(route_alias_jingan.get("target_store"), "sh_jingan")
            self.assertEqual(route_alias_jingan.get("reason"), "sh_route_scored:sh_jingan")

            route_alias_renmin = service.resolve_store_recommendation("外滩地址发一下")
            self.assertEqual(route_alias_renmin.get("target_store"), "sh_renmin")
            self.assertEqual(route_alias_renmin.get("reason"), "sh_route_scored:sh_renmin")
            self.assertEqual(route_alias_renmin.get("confidence"), "high")

            renmin_variant_route = service.resolve_store_recommendation("人民廣場地址发一下")
            self.assertEqual(renmin_variant_route.get("target_store"), "sh_renmin")
            self.assertEqual(renmin_variant_route.get("reason"), "sh_route_scored:sh_renmin")

            yangpu_bridge_route = service.resolve_store_recommendation("杨浦大桥怎么走")
            self.assertEqual(yangpu_bridge_route.get("target_store"), "sh_wujiaochang")
            self.assertEqual(yangpu_bridge_route.get("reason"), "sh_route_scored:sh_wujiaochang")

            huaihai_route = service.resolve_store_recommendation("淮海中路地址发一下")
            self.assertEqual(huaihai_route.get("target_store"), "sh_xuhui")
            self.assertEqual(huaihai_route.get("reason"), "sh_route_scored:sh_xuhui")

            ruijin_route = service.resolve_store_recommendation("瑞金二路地址发一下")
            self.assertEqual(ruijin_route.get("target_store"), "sh_xuhui")
            self.assertEqual(ruijin_route.get("reason"), "sh_route_scored:sh_xuhui")

            service.save_shanghai_route_alias_rows(
                [{"keyword": "北京西路", "target_store": "sh_jingan", "note": "静安高频"}]
            )
            beijing_road_route = service.resolve_store_recommendation("北京西路地址发一下")
            self.assertEqual(beijing_road_route.get("target_store"), "sh_jingan")
            self.assertEqual(beijing_road_route.get("reason"), "sh_route_scored:sh_jingan")
            self.assertEqual(beijing_road_route.get("confidence"), "high")

            hongqiao_station_route = service.resolve_store_recommendation("上海虹桥站附近有店吗")
            self.assertEqual(hongqiao_station_route.get("target_store"), "sh_renmin")
            self.assertEqual(hongqiao_station_route.get("reason"), "sh_route_scored:sh_renmin")

            hongqiao_route = service.resolve_store_recommendation("虹桥")
            self.assertEqual(hongqiao_route.get("target_store"), "sh_xuhui")
            self.assertEqual(hongqiao_route.get("reason"), "sh_route_scored:sh_xuhui")

            south_station_route = service.resolve_store_recommendation("上海南站附近地址发一下")
            self.assertEqual(south_station_route.get("target_store"), "sh_xuhui")
            self.assertEqual(south_station_route.get("reason"), "sh_route_scored:sh_xuhui")

            west_station_route = service.resolve_store_recommendation("上海西站")
            self.assertEqual(west_station_route.get("target_store"), "sh_hongkou")
            self.assertEqual(west_station_route.get("reason"), "sh_route_scored:sh_hongkou")

            route_alias_low_conf = service.resolve_store_recommendation("长寿路南京路地址哪个近")
            self.assertEqual(route_alias_low_conf.get("reason"), "sh_route_need_clarify")
            self.assertEqual(route_alias_low_conf.get("route_type"), "need_clarify")
            self.assertEqual(route_alias_low_conf.get("confidence"), "low")

            sh_need_district = service.resolve_store_recommendation("我在上海")
            self.assertEqual(sh_need_district.get("reason"), "shanghai_need_district")

            coming_to_shanghai = service.resolve_store_recommendation("我从外地来上海 去那个店")
            self.assertEqual(coming_to_shanghai.get("reason"), "shanghai_need_arrival_point")
            self.assertEqual(coming_to_shanghai.get("route_type"), "need_district")

            mixed_region_route = service.resolve_store_recommendation("哦你们在上海，我们在绍兴，什么时候过来来做一个，都很好看")
            self.assertEqual(mixed_region_route.get("target_store"), "sh_renmin")
            self.assertEqual(mixed_region_route.get("reason"), "jiangzhe_to_sh_renmin")


    def test_not_in_shanghai_or_beijing_should_not_fallback_to_llm(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, llm = self._build_agent(temp_dir)
            user_name = "用户负向城市"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_neg_city",
                user_id_hash=user_hash,
                ts="2026-02-27T09:35:00",
            )

            d1 = agent.decide("chat_not_in_sh", user_name, "不在上海怎么做？", [])
            self.assertNotEqual(d1.reply_source, "llm")
            self.assertNotEqual(d1.rule_id, "LLM_GENERAL")
            self.assertEqual(d1.route_reason, "out_of_coverage")

            d2 = agent.decide("chat_not_in_bj", user_name, "不在北京怎么做？", [])
            self.assertNotEqual(d2.reply_source, "llm")
            self.assertNotEqual(d2.rule_id, "LLM_GENERAL")
            self.assertEqual(d2.route_reason, "out_of_coverage")
            self.assertEqual(llm.calls, 0)

    def test_geo_followup_cycle_two_plus_one(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))
            session_id = "chat_cycle"
            user_name = "用户A"

            d1 = agent.decide(session_id, user_name, "怎么买", [])
            self.assertEqual(d1.rule_id, "ADDR_ASK_REGION_R1")

            d2 = agent.decide(session_id, user_name, "怎么买呀", [])
            self.assertEqual(d2.rule_id, "ADDR_ASK_REGION_R2")

            d3 = agent.decide(session_id, user_name, "怎么买啊", [])
            self.assertEqual(d3.rule_id, "ADDR_ASK_REGION_CHOICE")

            d4 = agent.decide(session_id, user_name, "我想买", [])
            self.assertEqual(d4.rule_id, "ADDR_ASK_REGION_R1_RESET")

    def test_geo_followup_reply_with_waidi_routes_contact_image(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))
            session_id = "chat_waidi"
            user_name = "用户外地"

            d1 = agent.decide(session_id, user_name, "具体位置", [])
            self.assertEqual(d1.rule_id, "ADDR_ASK_REGION_R1")

            d2 = agent.decide(session_id, user_name, "我在外地呢", [])
            self.assertEqual(d2.rule_id, "ADDR_OUT_OF_COVERAGE")
            self.assertEqual(d2.route_reason, "out_of_coverage")
            self.assertEqual(d2.media_plan, "contact_image")
            self.assertTrue(d2.media_items)

    def test_address_after_image_uses_text_once_then_falls_back_to_llm(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, llm = self._build_agent(temp_dir)
            session_id = "chat_addr_repeat"
            user_name = "用户重复地址"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_addr_repeat",
                user_id_hash=user_hash,
                ts="2026-02-27T09:35:00",
            )

            d1 = agent.decide(session_id, user_name, "北京店具体位置", [])
            self.assertEqual(d1.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d1.media_plan, "address_image")
            self.assertTrue(d1.media_items)
            agent.mark_media_sent(session_id, user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=d1.media_items[0]["path"],
                ts="2026-02-27T10:00:00",
                user_id_hash=user_hash,
            )

            d2 = agent.decide(session_id, user_name, "北京店具体位置", [])
            self.assertEqual(d2.rule_id, "ADDR_TEXT_AFTER_IMAGE")
            self.assertEqual(d2.reply_source, "rule")
            self.assertEqual(d2.media_plan, "address_image")
            self.assertTrue(d2.media_items)
            self.assertNotIn("朝阳区建外SOHO东区", d2.reply_text)

            d3 = agent.decide(session_id, user_name, "北京店具体位置", [])
            self.assertEqual(d3.reply_source, "rule")
            self.assertEqual(d3.rule_id, "ADDR_CONTACT_AFTER_TEXT")

    def test_address_followup_accepts_house_number_phrases_after_image(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_addr_house_number"
            user_name = "用户门牌号"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_addr_house_number",
                user_id_hash=user_hash,
                ts="2026-02-27T09:35:00",
            )

            d1 = agent.decide(session_id, user_name, "北京店具体位置", [])
            self.assertEqual(d1.rule_id, "ADDR_STORE_RECOMMEND")
            agent.mark_media_sent(session_id, user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=d1.media_items[0]["path"],
                ts="2026-02-27T10:00:00",
                user_id_hash=user_hash,
            )

            d2 = agent.decide(session_id, user_name, "多少号", [])
            self.assertEqual(d2.rule_id, "ADDR_TEXT_AFTER_IMAGE")
            self.assertEqual(d2.media_plan, "address_image")
            self.assertTrue(d2.media_items)
            self.assertNotIn("朝阳区建外SOHO东区", d2.reply_text)

            d3 = agent.decide(session_id, user_name, "几号", [])
            self.assertEqual(d3.rule_id, "ADDR_CONTACT_AFTER_TEXT")

    def test_address_query_shanghai_asks_district(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_detail_sh", "用户地址1", "你们上海店的地址在哪", [])
            self.assertEqual(d.rule_id, "ADDR_ASK_DISTRICT_R1")
            self.assertEqual(d.media_plan, "none")
            self.assertNotIn("门店地址：", d.reply_text)

    def test_address_query_shanghai_landmark_routes_store(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_detail_sh_landmark", "用户地址地标", "上海徐家汇", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.route_reason, "sh_district_map:徐家汇")

    def test_shanghai_route_scoring_low_confidence_asks_clarify(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_sh_route_clarify", "用户上海路线", "长寿路南京路地址哪个近", [])
            self.assertEqual(d.rule_id, "ADDR_SH_ROUTE_NEED_CLARIFY")
            self.assertEqual(d.route_reason, "need_clarify")
            self.assertEqual(d.media_plan, "none")
            self.assertIn("哪条路附近", d.reply_text)

    def test_coming_to_shanghai_from_out_of_town_asks_shanghai_district(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_come_to_sh", "用户外地来沪", "我从外地来上海 去那个店？", [])
            self.assertEqual(d.rule_id, "ADDR_ASK_ARRIVAL_POINT")
            self.assertEqual(d.route_reason, "need_arrival_point")
            self.assertEqual(d.media_plan, "none")
            self.assertIn("哪个站下车", d.reply_text)

    def test_shanghai_district_followup_with_unfamiliar_route_recovers_to_arrival_point(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d1 = agent.decide("chat_sh_unfamiliar", "用户上海不熟", "上海地址", [])
            self.assertEqual(d1.rule_id, "ADDR_ASK_DISTRICT_R1")

            d2 = agent.decide("chat_sh_unfamiliar", "用户上海不熟", "我外地来的不熟悉", [])
            self.assertEqual(d2.rule_id, "ADDR_ASK_ARRIVAL_POINT")
            self.assertEqual(d2.route_reason, "need_arrival_point")
            self.assertEqual(d2.media_plan, "none")
            self.assertIn("哪个站下车", d2.reply_text)

    def test_shanghai_route_alias_short_phrase_is_treated_as_address(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_sh_route_short", "用户纯地点", "中百一店", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.intent, "address")
            self.assertEqual(d.route_reason, "sh_route_scored:sh_wujiaochang")
            self.assertIn("上海五角场门店", d.reply_text)

    def test_shanghai_route_short_phrase_after_image_uses_address_followup(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(
                temp_dir,
                address_image_files=["上海人广地址.jpg"],
                store_targets={"上海人广地址.jpg": "sh_renmin"},
            )
            session_id = "chat_sh_route_followup"
            user_name = "用户上海追问"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_sh_route_followup",
                user_id_hash=user_hash,
                ts="2026-02-27T09:35:00",
            )
            agent.mark_media_sent(
                session_id,
                user_name,
                {
                    "type": "address_image",
                    "target_store": "sh_renmin",
                    "path": str(temp_dir / "images" / "上海人广地址.jpg"),
                },
                success=True,
            )
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=str(temp_dir / "images" / "上海人广地址.jpg"),
                ts="2026-02-27T10:00:00",
                user_id_hash=user_hash,
            )

            d2 = agent.decide(session_id, user_name, "南京路", [])
            self.assertEqual(d2.rule_id, "ADDR_TEXT_AFTER_IMAGE")
            self.assertEqual(d2.media_plan, "address_image")
            self.assertTrue(d2.media_items)
            self.assertNotIn("汉口路650号亚洲大厦", d2.reply_text)

    def test_ambiguous_short_fragment_asks_back_instead_of_llm(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐，北京朝阳门店具体位置是：朝阳区建外SOHO东区。"

            d = agent.decide("chat_ambiguous_short", "用户残句", "址", [])
            self.assertEqual(d.rule_id, "ADDR_AMBIGUOUS_SHORT_FRAGMENT")
            self.assertEqual(d.reply_source, "rule")
            self.assertEqual(d.media_plan, "none")
            self.assertIn("门店地址", d.reply_text)

    def test_non_price_sentence_with_earn_money_does_not_trigger_price_priority(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐，这段话我收到了呀。"

            d = agent.decide(
                "chat_non_price_money",
                "用户非价格",
                "马老师天天赚大钱，身体棒棒的，希望生意兴隆",
                [],
            )
            self.assertNotIn(d.rule_id, {"PRICE_PRIORITY", "PRICE_PRIORITY_FALLBACK", "PRICE_PRIORITY_PRIVATE_GUIDE"})

    def test_direct_price_question_still_triggers_price_priority(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_direct_price", "用户价格", "多少钱", [])
            self.assertIn(d.rule_id, {"PRICE_PRIORITY", "PRICE_PRIORITY_FALLBACK"})

    def test_lifespan_query_uses_knowledge_priority_not_llm(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, repository, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐，一般正常佩戴可以用35年左右。"
            repository.add(
                question="假发一般能用多久？",
                answer="姐姐，一般正常佩戴可以用3～5年左右，保养得好时间会更久哦🤍",
                intent="general",
                tags=["使用寿命"],
                answers=[
                    "姐姐，一般正常佩戴可以用3～5年左右，保养得好时间会更久哦🤍"
                ],
            )
            repository.save()

            d = agent.decide("chat_lifespan", "用户寿命", "一般能用多久", [])
            self.assertEqual(d.rule_id, "LIFESPAN_PRIORITY")
            self.assertEqual(d.reply_source, "knowledge")
            self.assertIn("3～5年", d.reply_text)

    def test_service_hours_short_query_does_not_get_treated_as_follow_up(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, repository, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐，我们全年都营业，每天上午。😘"
            repository.add(
                question="你们上班时间是几点？营业时间？",
                answer="姐姐我们是全年无休，营业时间是上午9:30～下午6:00哦🤍",
                intent="service_hours",
                tags=["服务", "营业时间", "咨询"],
                answers=[
                    "姐姐我们是全年无休，营业时间是上午9:30～下午6:00哦🤍",
                    "姐姐营业时间是上午9:30～下午6:00🤍",
                ],
            )
            repository.save()

            d = agent.decide("chat_service_hours_short", "用户营业时间", "营业时间", [])

            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "KB_MATCH")
            self.assertIn("9:30", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_service_hours_medium_confidence_match_still_returns_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, repository, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐我们是全年无休，营业时间是上午。🌺"
            repository.add(
                question="你们上班时间是几点？营业时间？",
                answer="姐姐我们是全年无休，营业时间是上午9:30～下午6:00哦🤍",
                intent="service_hours",
                tags=["服务", "营业时间", "咨询"],
                answers=[
                    "姐姐我们是全年无休，营业时间是上午9:30～下午6:00哦🤍",
                    "姐姐全年都在营业，上午9:30～下午6:00,放心来咨询哦🤍",
                ],
            )
            repository.save()

            d = agent.decide("chat_service_hours_medium", "用户营业时间", "你们营业时间是？", [])

            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "KB_MATCH")
            self.assertIn("9:30", d.reply_text)
            self.assertGreater(d.kb_match_score, 0.5)
            self.assertEqual(llm.calls, 0)

    def test_address_index_prefers_store_targets_metadata_even_without_district_filename(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            address_name = "门店图A.jpg"
            agent, _, _, _ = self._build_agent(
                temp_dir,
                address_image_files=[address_name],
                store_targets={address_name: "sh_xuhui"},
            )
            user_name = "用户元数据"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_store_targets_meta",
                user_id_hash=user_hash,
                ts="2026-02-27T09:35:00",
            )

            d = agent.decide("chat_store_targets_meta", user_name, "我在上海徐汇", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.media_plan, "address_image")
            self.assertTrue(d.media_items)
            self.assertEqual(d.media_items[0].get("target_store"), "sh_xuhui")
            self.assertEqual(Path(d.media_items[0].get("path", "")).name, address_name)

    def test_address_index_fallback_to_filename_when_store_targets_missing(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            address_name = "徐汇兜底图.jpg"
            agent, _, _, _ = self._build_agent(
                temp_dir,
                address_image_files=[address_name],
                store_targets={},
            )
            user_name = "用户文件名兜底"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_store_targets_fallback",
                user_id_hash=user_hash,
                ts="2026-02-27T09:36:00",
            )

            d = agent.decide("chat_store_targets_fallback", user_name, "上海徐汇", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.media_plan, "address_image")
            self.assertTrue(d.media_items)
            self.assertEqual(d.media_items[0].get("target_store"), "sh_xuhui")
            self.assertEqual(Path(d.media_items[0].get("path", "")).name, address_name)

    def test_shanghai_store_routes_media_target_consistent(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            store_to_file = {
                "sh_jingan": "A.jpg",
                "sh_renmin": "B.jpg",
                "sh_wujiaochang": "C.jpg",
                "sh_hongkou": "D.jpg",
                "sh_xuhui": "E.jpg",
            }
            file_to_store = {name: store for store, name in store_to_file.items()}
            agent, _, _, _ = self._build_agent(
                temp_dir,
                address_image_files=list(file_to_store.keys()),
                store_targets=file_to_store,
            )
            user_name = "用户上海五区"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_shanghai_routes_consistent",
                user_id_hash=user_hash,
                ts="2026-02-27T09:37:00",
            )

            cases = [
                ("我在上海静安", "sh_jingan"),
                ("我在上海人广", "sh_renmin"),
                ("我在上海五角场", "sh_wujiaochang"),
                ("我在上海虹口", "sh_hongkou"),
                ("我在上海徐汇", "sh_xuhui"),
            ]
            for idx, (query, expected_store) in enumerate(cases):
                d = agent.decide(f"chat_shanghai_route_{idx}", user_name, query, [])
                self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
                self.assertEqual(d.media_plan, "address_image")
                self.assertTrue(d.media_items)
                self.assertEqual(d.media_items[0].get("target_store"), expected_store)
                self.assertEqual(Path(d.media_items[0].get("path", "")).name, store_to_file[expected_store])

    def test_address_query_city_only_routes_north_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_detail_city_only", "用户地址城市", "石家庄有吗", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.route_reason, "north_fallback_beijing")

    def test_mixed_shanghai_and_shaoxing_phrase_prefers_jiangzhe_route(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td), address_image_files=["上海人广地址.jpg"])

            d = agent.decide("chat_shaoxing_route", "用户江浙沪", "哦你们在上海，我们在绍兴，什么时候过来来做一个，都很好看!", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.route_reason, "jiangzhe_to_sh_renmin")
            self.assertEqual(d.media_plan, "address_image")
            self.assertIn("上海人民广场门店", d.reply_text)
            self.assertIn("如果找不到可以留个☎️", d.reply_text)

    def test_generic_address_after_known_region_uses_real_text_then_contact_then_llm(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, llm = self._build_agent(temp_dir)
            session_id = "chat_generic_addr_after_region"
            user_name = "用户泛地址追问"
            user_hash = agent._hash_user(user_name)

            d1 = agent.decide(session_id, user_name, "具体地址在哪？", [])
            self.assertEqual(d1.rule_id, "ADDR_ASK_REGION_R1")

            d2 = agent.decide(session_id, user_name, "北京", [])
            self.assertEqual(d2.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d2.media_plan, "address_image")
            self.assertTrue(d2.media_items)
            agent.mark_media_sent(session_id, user_name, d2.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=d2.media_items[0]["path"],
                ts="2026-03-11T15:16:01",
                user_id_hash=user_hash,
            )

            d3 = agent.decide(session_id, user_name, "具体地址", [])
            self.assertEqual(d3.rule_id, "ADDR_TEXT_AFTER_IMAGE")
            self.assertEqual(d3.media_plan, "address_image")
            self.assertTrue(d3.media_items)
            self.assertNotIn("朝阳区建外SOHO东区", d3.reply_text)

            d4 = agent.decide(session_id, user_name, "具体地址", [])
            self.assertEqual(d4.rule_id, "ADDR_CONTACT_AFTER_TEXT")
            self.assertIn("您发个☎️", d4.reply_text)

            llm.reply_text = "姐姐，北京店就在朝阳，您导航建外SOHO东区就行🌹"
            d5 = agent.decide(session_id, user_name, "具体地址", [])
            self.assertEqual(d5.reply_source, "llm")
            self.assertEqual(d5.rule_id, "LLM_FOLLOW_UP")

    def test_address_query_cityless_asks_region(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_detail_both", "用户地址2", "具体地址在哪", [])
            self.assertEqual(d.rule_id, "ADDR_ASK_REGION_R1")
            self.assertEqual(d.media_plan, "none")
            self.assertNotIn("上海店详细地址", d.reply_text)
            self.assertNotIn("北京店详细地址", d.reply_text)

    def test_address_query_out_of_coverage_still_rule(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_detail_out", "用户地址4", "黑龙江门店具体地址在哪", [])
            self.assertEqual(d.rule_id, "ADDR_OUT_OF_COVERAGE")

    def test_address_query_known_store_still_recommend(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))

            d = agent.decide("chat_detail_known", "用户地址5", "我在门头沟，地址在哪", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")

    def test_not_in_beijing_and_shanghai_routes_out_of_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户地址6"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_addr6",
                user_id_hash=user_hash,
                ts="2026-02-27T09:36:00",
            )

            d = agent.decide("chat_not_bj_sh", user_name, "我不在北京和上海", [])
            self.assertEqual(d.rule_id, "ADDR_OUT_OF_COVERAGE")
            self.assertEqual(d.media_plan, "contact_image")
            self.assertTrue(d.media_items)

    def test_not_in_beijing_and_shanghai_after_address_query_not_loop(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户地址7"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_addr7",
                user_id_hash=user_hash,
                ts="2026-02-27T09:37:00",
            )

            d1 = agent.decide("chat_addr_loop_break", user_name, "地址在哪", [])
            self.assertIn(d1.rule_id, ("ADDR_ASK_REGION_R1", "ADDR_ASK_DISTRICT_R1"))

            d2 = agent.decide("chat_addr_loop_break", user_name, "我不在北京和上海", [])
            self.assertEqual(d2.rule_id, "ADDR_OUT_OF_COVERAGE")
            self.assertEqual(d2.media_plan, "contact_image")

    def test_kb_first_then_llm(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, repository, llm = self._build_agent(Path(td))
            repository.add("透气吗", "姐姐，我们这款透气性很好🌹", intent="wearing", tags=["佩戴体验"])

            d1 = agent.decide("chat_kb", "用户B", "透气吗", [])
            self.assertEqual(d1.reply_source, "knowledge")
            self.assertEqual(llm.calls, 0)

            d2 = agent.decide("chat_kb", "用户B", "你们售后多久", [])
            self.assertEqual(d2.reply_source, "llm")
            self.assertEqual(llm.calls, 1)

    def test_repository_match_detail_returns_tags_and_item_id(self):
        with tempfile.TemporaryDirectory() as td:
            kb_file = Path(td) / "knowledge.json"
            kb_file.write_text("[]", encoding="utf-8")
            repository = KnowledgeRepository(kb_file)
            item = repository.add("好的谢谢", "不客气姐姐🌹", intent="general", tags=["礼貌", "结束语"])

            detail = repository.find_best_match_detail("好的谢谢", threshold=0.6)
            self.assertTrue(detail.get("matched"))
            self.assertIn("tags", detail)
            self.assertIn("item_id", detail)
            self.assertEqual(detail.get("item_id"), item.id)
            self.assertIn("礼貌", detail.get("tags", []))
            self.assertEqual(detail.get("answers"), ["不客气姐姐🌹"])

    def test_repository_legacy_answer_backfills_answers(self):
        with tempfile.TemporaryDirectory() as td:
            kb_file = Path(td) / "knowledge.json"
            kb_file.write_text(
                json.dumps(
                    [
                        {
                            "intent": "wearing",
                            "question": "会掉吗",
                            "answer": "不会掉，佩戴很稳。",
                            "tags": ["佩戴体验"],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            repository = KnowledgeRepository(kb_file)
            detail = repository.find_best_match_detail("会掉吗", threshold=0.6)
            self.assertTrue(detail.get("matched"))
            self.assertEqual(detail.get("answer"), "不会掉，佩戴很稳。")
            self.assertEqual(detail.get("answers"), ["不会掉，佩戴很稳。"])

    def test_polite_closing_kb_requires_exact_match(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, repository, llm = self._build_agent(Path(td))
            repository.add("好的谢谢", "不客气姐姐🌹", intent="general", tags=["礼貌", "结束语"])

            d1 = agent.decide("chat_polite_exact", "用户礼貌1", "好的谢谢", [])
            self.assertEqual(d1.reply_source, "knowledge")
            self.assertEqual(d1.reply_text, "不客气姐姐🌹")
            self.assertFalse(d1.kb_blocked_by_polite_guard)
            self.assertEqual(d1.kb_polite_guard_reason, "")

            d2 = agent.decide("chat_polite_mixed", "用户礼貌2", "好的，但是我还想再了解一下", [])
            self.assertEqual(d2.reply_source, "llm")
            self.assertTrue(d2.kb_blocked_by_polite_guard)
            self.assertEqual(d2.kb_polite_guard_reason, "polite_not_exact")
            self.assertNotEqual(d2.reply_text, "不客气姐姐🌹")
            self.assertGreaterEqual(llm.calls, 1)

            d3 = agent.decide("chat_polite_mixed_region", "用户礼貌4", "好的，但是我不在上海怎么办啊？", [])
            self.assertNotEqual(d3.reply_source, "knowledge")
            self.assertTrue(d3.kb_blocked_by_polite_guard)
            self.assertEqual(d3.kb_polite_guard_reason, "polite_mixed_query")

    def test_polite_closing_blocked_in_intent_hint_path(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, repository, llm = self._build_agent(Path(td))
            repository.add("嗯", "好的姐姐，有任何问题随时问我哦，我一直都在呢🌷", intent="general", tags=["礼貌", "结束语"])

            d = agent.decide("chat_polite_hint", "用户礼貌3", "嗯嗯", [])
            self.assertEqual(d.reply_source, "llm")
            self.assertTrue(d.kb_blocked_by_polite_guard)
            self.assertEqual(d.kb_polite_guard_reason, "polite_not_exact")
            self.assertGreaterEqual(llm.calls, 1)

    def test_kb_variant_rotation_then_fallback_to_llm(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "会掉吗头发？会掉吗？",
                "非常牢固，我们有客户戴着做过山车都没问题！🎢",
                answers=[
                    "非常牢固，我们有客户戴着做过山车都没问题！🎢",
                    "结论先说：佩戴很稳，日常活动基本不会掉发。",
                    "您放心，这款固定性很好，正常活动不容易掉。",
                    "核心结论是不容易掉，贴合后稳定性很高。",
                    "简单说就是很牢固，佩戴后不容易松动或掉发。",
                ],
                intent="wearing",
                tags=["佩戴体验"],
            )

            user_name = "用户KB"
            session_id = "chat_kb_exact"
            seen = []
            for _ in range(5):
                d = agent.decide(session_id, user_name, "会掉吗？", [])
                self.assertEqual(d.reply_source, "knowledge")
                self.assertEqual(d.kb_variant_total, 5)
                self.assertGreaterEqual(d.kb_variant_selected_index, 0)
                self.assertFalse(d.kb_variant_fallback_llm)
                seen.append(d.reply_text)
                agent.mark_reply_sent(session_id, user_name, d.reply_text)

            self.assertEqual(len(set(seen)), 5)
            self.assertEqual(llm.calls, 0)

            llm.reply_text = "结论先说：佩戴很稳，正常活动不会掉发。"
            d6 = agent.decide(session_id, user_name, "会掉吗？", [])
            self.assertEqual(d6.reply_source, "llm")
            self.assertEqual(d6.rule_id, "LLM_KB_VARIANT_FALLBACK")
            self.assertTrue(d6.kb_variant_fallback_llm)
            self.assertEqual(d6.kb_variant_total, 5)
            self.assertGreaterEqual(llm.calls, 1)

    def test_llm_normalize_only_single_trailing_emoji(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))
            normalized = agent._normalize_reply_text("放心戴🌹蹦迪跳舞都不掉哦～💃🌹")
            self.assertTrue(normalized.endswith("。🌹"))
            self.assertEqual(normalized.count("🌹"), 1)
            self.assertNotIn("💃", normalized)
            self.assertNotIn("～", normalized)

    def test_llm_normalize_enforces_brevity_limit(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, _ = self._build_agent(Path(td))
            normalized = agent._normalize_reply_text(
                "姐姐我们目前门店在北京朝阳和上海5家店（静安、人广、虹口、五角场、徐汇），外地暂时没有门店；如果您方便来店，我可以帮您安排试戴和购买流程。"
            )
            self.assertTrue(normalized.endswith("。🌹"))
            self.assertLessEqual(len(normalized) - 1, 33)

    def test_shipping_terms_hard_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐我们全国包邮到家呢～📦"

            d = agent.decide("chat_shipping_block", "用户物流", "物流怎么发", [])
            self.assertEqual(d.reply_source, "llm")
            self.assertEqual(d.reply_text, "姐姐我们是到店定制哦。🌹")

    def test_north_fallback_purchase_recommends_beijing_when_no_contact_sent(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_north_beijing"
            user_name = "北方用户A"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_north_a",
                user_id_hash=user_hash,
                ts="2026-02-27T10:00:00",
            )

            d = agent.decide(session_id, user_name, "我在内蒙古怎么买？", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.route_reason, "north_fallback_beijing")
            self.assertEqual(d.media_plan, "address_image")
            self.assertTrue(d.media_items)
            self.assertIn("北京朝阳门店", d.reply_text)

    def test_north_fallback_purchase_after_contact_sent_uses_circle_remind(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_north_contact_sent"
            user_name = "北方用户B"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_north_b",
                user_id_hash=user_hash,
                ts="2026-02-27T10:00:00",
            )
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=str(temp_dir / "images" / "contact.jpg"),
                ts="2026-02-27T10:01:00",
                user_id_hash=user_hash,
            )

            d = agent.decide(session_id, user_name, "我在内蒙古怎么买？", [])
            self.assertEqual(d.rule_id, "PURCHASE_REMOTE_CONTACT_REMIND_ONLY")
            self.assertEqual(d.route_reason, "north_fallback_beijing")
            self.assertEqual(d.media_plan, "none")
            self.assertFalse(d.media_items)
            self.assertIn("画圈", d.reply_text)

    def test_first_turn_purchase_unknown_routes_to_addr_ask_region(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)

            d = agent.decide("chat_first_purchase_unknown", "用户首轮购买", "姐姐你好，我想买假发", [])
            self.assertEqual(d.rule_id, "ADDR_ASK_REGION_R1")
            self.assertTrue(d.is_first_turn_global)
            self.assertEqual(d.media_plan, "none")
            self.assertFalse(d.media_items)

    def test_first_turn_global_prepares_contact_image_and_video(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)
            agent.set_options(
                use_knowledge_first=agent.use_knowledge_first,
                knowledge_threshold=agent.knowledge_threshold,
                first_reply_video_enabled=True,
            )

            d = agent.decide("chat_first_contact", "用户首轮", "我在门头沟怎么买", [])
            self.assertEqual(d.rule_id, "PURCHASE_CONTACT_FROM_KNOWN_GEO")
            self.assertTrue(d.is_first_turn_global)
            self.assertFalse(d.first_turn_media_guard_applied)
            self.assertEqual(d.media_plan, "contact_image")
            self.assertTrue(d.media_items)
            self.assertEqual(len(d.first_turn_image_items), 1)
            self.assertEqual(d.first_turn_image_items[0].get("type"), "contact_image")
            self.assertEqual(len(d.first_turn_video_items), 1)
            self.assertEqual(d.first_turn_video_items[0].get("type"), "delayed_video")

    def test_first_turn_global_prepares_address_image_and_video(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)
            agent.set_options(
                use_knowledge_first=agent.use_knowledge_first,
                knowledge_threshold=agent.knowledge_threshold,
                first_reply_video_enabled=True,
            )

            d = agent.decide("chat_first_address", "用户首轮地址", "我在门头沟", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertTrue(d.is_first_turn_global)
            self.assertFalse(d.first_turn_media_guard_applied)
            self.assertEqual(d.media_plan, "address_image")
            self.assertTrue(d.media_items)
            self.assertEqual(len(d.first_turn_image_items), 1)
            self.assertEqual(d.first_turn_image_items[0].get("type"), "address_image")
            self.assertEqual(len(d.first_turn_video_items), 1)
            self.assertEqual(d.first_turn_video_items[0].get("type"), "delayed_video")

    def test_after_first_turn_allows_media_across_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户跨会话"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_cross",
                user_id_hash=user_hash,
                ts="2026-02-27T09:00:00",
            )

            d = agent.decide("chat_next_session", user_name, "我在门头沟怎么买", [])
            self.assertFalse(d.is_first_turn_global)
            self.assertFalse(d.first_turn_media_guard_applied)
            self.assertEqual(d.rule_id, "PURCHASE_CONTACT_FROM_KNOWN_GEO")
            self.assertEqual(d.media_plan, "contact_image")
            self.assertTrue(d.media_items)

    def test_user_message_log_alone_already_breaks_global_first_turn(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户仅消息"
            user_hash = agent._hash_user(user_name)

            (conversations_dir / "seed_user_only_message.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-02-27T09:00:00",
                        "session_id": "seed_user_only_message",
                        "user_id_hash": user_hash,
                        "event_type": "user_message",
                        "reply_source": "",
                        "rule_id": "",
                        "model_name": "",
                        "payload": {"text": "你好"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            d = agent.decide("chat_next_session_only_message", user_name, "静安寺地址", [])
            self.assertFalse(d.is_first_turn_global)

    def test_first_turn_override_preserves_first_turn_media_plan(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户首轮覆盖"
            user_hash = agent._hash_user(user_name)

            (conversations_dir / "seed_override.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-02-27T09:00:00",
                        "session_id": "seed_override",
                        "user_id_hash": user_hash,
                        "event_type": "user_message",
                        "reply_source": "",
                        "rule_id": "",
                        "model_name": "",
                        "payload": {"text": "你好"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            agent.set_options(
                use_knowledge_first=agent.use_knowledge_first,
                knowledge_threshold=agent.knowledge_threshold,
                first_reply_video_enabled=True,
            )
            d = agent.decide(
                "chat_override_first_turn",
                user_name,
                "我在门头沟",
                [],
                first_turn_global_override=True,
            )
            self.assertTrue(d.is_first_turn_global)
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(len(d.first_turn_image_items), 1)
            self.assertEqual(len(d.first_turn_video_items), 1)

    def test_contact_image_frequency_and_whitelist(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            white_session = "chat_white"
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir, whitelist_sessions=[white_session])
            user_name = "用户C"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_c",
                user_id_hash=user_hash,
                ts="2026-02-27T09:30:00",
            )

            s1 = "chat_normal"
            d1 = agent.decide(s1, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d1.media_plan, "contact_image")
            self.assertTrue(d1.media_items)
            agent.mark_media_sent(s1, user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=s1,
                media_type="contact_image",
                media_path=d1.media_items[0]["path"],
                ts="2999-01-01T00:00:00",
                user_id_hash=user_hash,
            )

            d2 = agent.decide(s1, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d2.media_plan, "contact_image")
            self.assertTrue(d2.media_items)
            agent.mark_media_sent(s1, user_name, d2.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=s1,
                media_type="contact_image",
                media_path=d2.media_items[0]["path"],
                ts="2999-01-01T00:00:30",
                user_id_hash=user_hash,
            )

            d2b = agent.decide(s1, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d2b.media_plan, "contact_image")
            self.assertTrue(d2b.media_items)
            agent.mark_media_sent(s1, user_name, d2b.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=s1,
                media_type="contact_image",
                media_path=d2b.media_items[0]["path"],
                ts="2999-01-01T00:00:45",
                user_id_hash=user_hash,
            )

            d2c = agent.decide(s1, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d2c.media_plan, "none")
            self.assertFalse(d2c.media_items)

            d3 = agent.decide(white_session, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d3.media_plan, "contact_image")
            self.assertTrue(d3.media_items)
            agent.mark_media_sent(white_session, user_name, d3.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=white_session,
                media_type="contact_image",
                media_path=d3.media_items[0]["path"],
                ts="2999-01-01T00:01:00",
                user_id_hash=user_hash,
            )

            d4 = agent.decide(white_session, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d4.media_plan, "contact_image")
            self.assertTrue(d4.media_items)

    def test_shipping_kb_match_appends_contact_image_with_3x_limit(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, repository, _ = self._build_agent(temp_dir)
            repository.add(
                "那我怎么购买呢？可以寄吗？可以邮寄吗？快递可以吗？寄快递",
                "姐姐，我们是假发私人定制的，您可以加我，我远程给您定制😊",
                intent="purchase",
                tags=["邮寄"],
                answers=[
                    "姐姐，我们是假发私人定制的，您可以加我，我远程给您定制😊",
                    "姐姐可以寄的，不过需要先定制，您加我我给您详细对接一下😊",
                ],
            )

            user_name = "用户邮寄"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_shipping_user",
                user_id_hash=user_hash,
                ts="2026-02-27T10:20:00",
            )
            session_id = "chat_shipping_kb"

            d1 = agent.decide(session_id, user_name, "不同价格有什么区别，可以邮寄吗", [])
            self.assertEqual(d1.reply_source, "knowledge")
            self.assertEqual(d1.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d1.reply_text, "姐姐，我们是假发私人定制的，您可以加我，我远程给您定制😊")
            self.assertEqual(d1.media_plan, "contact_image")
            self.assertTrue(d1.media_items)
            agent.mark_media_sent(session_id, user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=d1.media_items[0]["path"],
                ts="2999-01-01T00:10:00",
                user_id_hash=user_hash,
            )

            d2 = agent.decide(session_id, user_name, "不同价格有什么区别，可以邮寄吗", [])
            self.assertEqual(d2.reply_source, "knowledge")
            self.assertEqual(d2.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d2.media_plan, "contact_image")
            self.assertTrue(d2.media_items)
            agent.mark_media_sent(session_id, user_name, d2.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=d2.media_items[0]["path"],
                ts="2999-01-01T00:10:30",
                user_id_hash=user_hash,
            )

            d3 = agent.decide(session_id, user_name, "不同价格有什么区别，可以邮寄吗", [])
            self.assertEqual(d3.reply_source, "knowledge")
            self.assertEqual(d3.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d3.media_plan, "contact_image")
            self.assertTrue(d3.media_items)
            agent.mark_media_sent(session_id, user_name, d3.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=d3.media_items[0]["path"],
                ts="2999-01-01T00:11:00",
                user_id_hash=user_hash,
            )

            d4 = agent.decide(session_id, user_name, "不同价格有什么区别，可以邮寄吗", [])
            self.assertEqual(d4.reply_source, "knowledge")
            self.assertEqual(d4.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d4.media_plan, "none")
            self.assertFalse(d4.media_items)
            self.assertEqual(d4.media_skip_reason, "contact_image_already_sent")

    def test_appointment_kb_priority_over_purchase_rule(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, repository, _ = self._build_agent(temp_dir)
            repository.add(
                "怎么预约？如何预约？需要预约吗？",
                "姐姐，我们是预约制的呢，避免您跑空您看看图上红框框加我预约🌷",
                intent="appointment",
                tags=["预约"],
                answers=[
                    "姐姐我们这边是预约制的～您可以看看红框内容加我预约🌷",
                ],
            )

            user_name = "用户预约优先"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_appoint_priority",
                user_id_hash=user_hash,
                ts="2026-02-27T10:40:00",
            )

            d = agent.decide("chat_appoint_priority", user_name, "怎么预约？", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d.media_plan, "contact_image")
            self.assertTrue(d.media_items)

    def test_appointment_kb_contact_image_limit_3(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, repository, _ = self._build_agent(temp_dir)
            repository.add(
                "怎么预约？如何预约？需要预约吗？",
                "姐姐，我们是预约制的呢，避免您跑空您看看图上红框框加我预约🌷",
                intent="appointment",
                tags=["预约"],
                answers=[
                    "姐姐我们这边是预约制的～您可以看看红框内容加我预约🌷",
                    "需要预约的姐姐～您什么时间方便？您可以看看红框内容+我😊",
                ],
            )

            user_name = "用户预约上限"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_appoint_limit",
                user_id_hash=user_hash,
                ts="2026-02-27T10:45:00",
            )
            session_id = "chat_appoint_limit"

            for idx, ts in enumerate(("2999-01-01T00:20:00", "2999-01-01T00:20:30", "2999-01-01T00:21:00"), start=1):
                d = agent.decide(session_id, user_name, "需要预约吗？", [])
                self.assertEqual(d.reply_source, "knowledge")
                self.assertEqual(d.rule_id, "KB_MATCH_CONTACT_IMAGE")
                self.assertEqual(d.media_plan, "contact_image")
                self.assertTrue(d.media_items)
                agent.mark_media_sent(session_id, user_name, d.media_items[0], success=True)
                self._append_media_success_log(
                    conversations_dir=conversations_dir,
                    session_id=session_id,
                    media_type="contact_image",
                    media_path=d.media_items[0]["path"],
                    ts=ts,
                    user_id_hash=user_hash,
                )

            d4 = agent.decide(session_id, user_name, "需要预约吗？", [])
            self.assertEqual(d4.reply_source, "knowledge")
            self.assertEqual(d4.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d4.media_plan, "none")
            self.assertFalse(d4.media_items)
            self.assertEqual(d4.media_skip_reason, "contact_image_already_sent")

    def test_appointment_first_turn_prepares_contact_image_and_video(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, _ = self._build_agent(temp_dir)
            agent.set_options(
                use_knowledge_first=agent.use_knowledge_first,
                knowledge_threshold=agent.knowledge_threshold,
                first_reply_video_enabled=True,
            )
            repository.add(
                "怎么预约？如何预约？需要预约吗？",
                "姐姐，我们是预约制的呢，避免您跑空您看看图上红框框加我预约🌷",
                intent="appointment",
                tags=["预约"],
            )

            d = agent.decide("chat_appoint_first_turn", "用户预约首轮", "怎么预约？", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d.media_plan, "contact_image")
            self.assertTrue(d.is_first_turn_global)
            self.assertFalse(d.first_turn_media_guard_applied)
            self.assertTrue(d.media_items)
            self.assertEqual(len(d.first_turn_image_items), 1)
            self.assertEqual(len(d.first_turn_video_items), 1)

    def test_kb_match_without_shipping_keeps_media_none(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, repository, _ = self._build_agent(temp_dir)
            repository.add(
                "价格是多少",
                "姐姐，主要看发质和工艺，价格区间我可以给您详细讲解😊",
                intent="price",
                tags=["价格"],
            )

            user_name = "用户普通KB"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_normal_kb",
                user_id_hash=user_hash,
                ts="2026-02-27T10:30:00",
            )

            d = agent.decide("chat_normal_kb", user_name, "价格是多少", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d.media_plan, "none")
            self.assertFalse(d.media_items)

    def test_price_query_uses_price_priority_even_with_beijing_context(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "这款多少钱？图片上多少钱？第二款多少钱？",
                "姐姐这款不是固定价格，价格在3000到6000之间，需要根据头围脸型设计定价🌷",
                intent="price",
                tags=["价格", "咨询", "定制"],
            )

            user_name = "价格用户"
            user_hash = agent._hash_user(user_name)
            agent.memory_store.update_session_state(
                "chat_price_beijing",
                {
                    "last_target_store": "beijing_chaoyang",
                    "last_detected_region": "北京",
                },
                user_hash=user_hash,
            )

            d = agent.decide("chat_price_beijing", user_name, "第二款假发多少钱", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d.media_plan, "none")
            self.assertFalse(d.media_items)
            self.assertIn("3000", d.reply_text)
            self.assertNotIn("北京朝阳门店", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_price_plus_store_question_answers_price_then_store_distribution(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "这款多少钱？图片上多少钱？第二款多少钱？",
                "姐姐这款不是固定价格，价格在3000到6000之间，需要根据头围脸型设计定价🌷",
                intent="price",
                tags=["价格", "咨询", "定制"],
            )

            d = agent.decide("chat_price_store", "价格门店用户", "这款多少钱，在哪个店能看？", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d.media_plan, "none")
            self.assertIn("3000", d.reply_text)
            self.assertIn("北京朝阳1家", d.reply_text)
            self.assertIn("上海5家", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_price_plus_appointment_answers_price_then_appointment_fact_without_media(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "价格多少？多少钱？",
                "姐姐价格这块主要看材质和您想要的效果，通常在3000到6000之间😊",
                intent="price",
                tags=["价格"],
            )

            d = agent.decide("chat_price_appoint", "价格预约用户", "这款多少钱，需要预约吗？", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d.media_plan, "none")
            self.assertIn("3000", d.reply_text)
            self.assertIn("预约制", d.reply_text)
            self.assertFalse(d.media_items)
            self.assertEqual(llm.calls, 0)

    def test_price_plus_same_day_duration_answers_duration_then_price(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "价格多少？多少钱？",
                "姐姐价格这块主要看材质和您想要的效果，通常在3000到6000之间😊",
                intent="price",
                tags=["价格"],
            )

            d = agent.decide("chat_price_duration", "价格时效用户", "到上海来一天能完成吗?大概多少钱?", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d.media_plan, "none")
            self.assertIn("3000", d.reply_text)
            self.assertIn("当天一般做不完", d.reply_text)
            self.assertNotIn("上海5家", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_price_plus_store_question_still_answers_store_distribution(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "价格多少？多少钱？",
                "姐姐价格这块主要看材质和您想要的效果，通常在3000到6000之间😊",
                intent="price",
                tags=["价格"],
            )

            d = agent.decide("chat_price_store_2", "价格门店用户2", "到上海看大概多少钱，在哪个店能看？", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "PRICE_PRIORITY")
            self.assertIn("3000", d.reply_text)
            self.assertIn("上海5家", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_price_priority_rotates_variants_for_same_user(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, _ = self._build_agent(temp_dir)
            repository.add(
                "价格多少？多少钱？价格多少钱？什么价位？",
                "姐姐，我们是私人定制的假发，根据不同的材质，正常3000、4000、5000、6000都有，具体要看您的头围、脸型和需求方案💗",
                intent="price",
                tags=["价格", "预算"],
                answers=[
                    "姐姐价格这块主要看材质和您想要的效果～通常在3000、4000、5000、6000都有区间，得结合头围、脸型再定方案😊",
                    "姐姐我们是按定制方案走的，不同材质价格不一样，大概3000、4000、5000、6000都有，具体要看您适合哪一款🌷",
                ],
            )

            user_name = "价格轮换用户"
            d1 = agent.decide("chat_price_rotate", user_name, "价格呢", [])
            d2 = agent.decide("chat_price_rotate", user_name, "第二款价格是多少", [])

            self.assertEqual(d1.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d2.rule_id, "PRICE_PRIORITY")
            self.assertNotEqual(d1.reply_text, d2.reply_text)
            self.assertIn("3000", d1.reply_text)
            self.assertIn("4000", d1.reply_text)
            self.assertIn("3000", d2.reply_text)
            self.assertIn("4000", d2.reply_text)

    def test_price_priority_third_time_guides_to_private_then_returns_to_price(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "价格多少？多少钱？价格多少钱？什么价位？",
                "姐姐，我们是私人定制的假发，根据不同的材质，正常3000、4000、5000、6000都有，具体要看您的头围、脸型和需求方案💗",
                intent="price",
                tags=["价格", "预算"],
                answers=[
                    "姐姐价格这块主要看材质和您想要的效果～通常在3000、4000、5000、6000都有区间，得结合头围、脸型再定方案😊",
                    "姐姐我们是按定制方案走的，不同材质价格不一样，大概3000、4000、5000、6000都有，具体要看您适合哪一款🌷",
                    "姐姐先给您个范围：一般3000、4000、5000、6000都有左右～您把需求跟我说下（长度/发量/风格），我帮您更精准估价😘",
                ],
            )

            session_id = "chat_price_private_guide"
            user_name = "价格引导用户"
            d1 = agent.decide(session_id, user_name, "价格是多少？", [])
            d2 = agent.decide(session_id, user_name, "价格呢？", [])
            d3 = agent.decide(session_id, user_name, "没有具体价格吗？", [])
            d4 = agent.decide(session_id, user_name, "价位一般在多少，具体一点", [])

            self.assertEqual(d1.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d2.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d3.rule_id, "PRICE_PRIORITY_PRIVATE_GUIDE")
            self.assertIn("留个☎️", d3.reply_text)
            self.assertEqual(d4.rule_id, "PRICE_PRIORITY")
            self.assertIn("3000", d4.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_process_priority_handles_single_visit_followup(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "要来几次才能做好？来几次可以？来一次可以吗？",
                "姐姐一般需要来2次会更稳妥，第一次测量设计，第二次调整佩戴，当天通常做不好哦🤍",
                intent="process",
                tags=["流程", "到店", "次数"],
                answers=[
                    "姐姐一般需要来2次会更稳妥哦🤍",
                    "姐姐第一次测量设计，第二次调整佩戴，会更合适一些🤍",
                ],
            )

            d = agent.decide("chat_process_once", "流程用户", "来一次可以吗？", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertEqual(d.rule_id, "PROCESS_PRIORITY")
            self.assertIn("2次", d.reply_text)
            self.assertNotIn("一次就可以完成", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_franchise_query_is_not_misclassified_as_out_of_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, repository, llm = self._build_agent(temp_dir)
            repository.add(
                "可以加盟吗？",
                "姐姐，目前我们这边暂时不考虑加盟哦，谢谢理解～🤍",
                intent="franchise",
                tags=["加盟", "合作"],
            )

            d = agent.decide("chat_franchise", "加盟用户", "可以加盟你们吗？", [])
            self.assertEqual(d.reply_source, "knowledge")
            self.assertIn("暂时不考虑加盟", d.reply_text)
            self.assertNotEqual(d.rule_id, "ADDR_OUT_OF_COVERAGE_REMIND_ONLY")
            self.assertEqual(llm.calls, 0)

    def test_address_followup_keeps_true_address_residual_question(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_addr_residual"
            user_name = "用户地址残句"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_addr_residual",
                user_id_hash=user_hash,
                ts="2026-03-11T15:15:00",
            )

            d1 = agent.decide(session_id, user_name, "具体地址在哪？", [])
            self.assertEqual(d1.rule_id, "ADDR_ASK_REGION_R1")

            d2 = agent.decide(session_id, user_name, "北京", [])
            self.assertEqual(d2.rule_id, "ADDR_STORE_RECOMMEND")
            agent.mark_media_sent(session_id, user_name, d2.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=d2.media_items[0]["path"],
                ts="2026-03-11T15:16:01",
                user_id_hash=user_hash,
            )

            d3 = agent.decide(session_id, user_name, "北在哪？", [])
            self.assertEqual(d3.rule_id, "ADDR_TEXT_AFTER_IMAGE")
            self.assertEqual(d3.media_plan, "address_image")
            self.assertTrue(d3.media_items)
            self.assertNotIn("朝阳区建外SOHO东区", d3.reply_text)

    def test_address_followup_does_not_hijack_price_question_after_address_context(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, repository, llm = self._build_agent(temp_dir)
            session_id = "chat_addr_then_price"
            user_name = "用户地址后价格"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_addr_then_price",
                user_id_hash=user_hash,
                ts="2026-03-11T15:15:00",
            )
            repository.add(
                "这款多少钱？图片上多少钱？第二款多少钱？",
                "姐姐这款不是固定价格，价格在3000到6000之间，需要根据头围脸型设计定价🌷",
                intent="price",
                tags=["价格", "咨询", "定制"],
            )

            d1 = agent.decide(session_id, user_name, "具体地址在哪？", [])
            self.assertEqual(d1.rule_id, "ADDR_ASK_REGION_R1")

            d2 = agent.decide(session_id, user_name, "北京", [])
            self.assertEqual(d2.rule_id, "ADDR_STORE_RECOMMEND")
            agent.mark_media_sent(session_id, user_name, d2.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=d2.media_items[0]["path"],
                ts="2026-03-11T15:16:01",
                user_id_hash=user_hash,
            )

            d3 = agent.decide(session_id, user_name, "第二款的短发多少钱", [])
            self.assertEqual(d3.rule_id, "PRICE_PRIORITY")
            self.assertEqual(d3.reply_source, "knowledge")
            self.assertIn("3000", d3.reply_text)
            self.assertNotIn("朝阳区建外SOHO东区", d3.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_llm_low_price_reply_is_overridden_by_fixed_price_levels(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐这个款式2000就可以做呢🌹"

            d = agent._decide_llm_reply(
                latest_user_text="你们价格多少？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertEqual(d.reply_source, "llm")
            self.assertIn("3000、4000、5000、6000不同档位", d.reply_text)

    def test_llm_non_low_price_reply_is_sent_as_is(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐这个价格要看具体设计方案呢🌹"

            d = agent._decide_llm_reply(
                latest_user_text="你们价格多少？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertEqual(d.reply_source, "llm")
            self.assertIn("姐姐这个价格要看具体设计方案呢。", d.reply_text)

    def test_llm_price_reply_with_hundreds_is_overridden_by_price_guardrail(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐，假发价格根据款式、长度、材质不同，从几百到上千不等💗"

            d = agent._decide_llm_reply(
                latest_user_text="视频的假发价格",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            self.assertEqual(llm.calls, 1)
            self.assertIn("3000、4000、5000、6000", d.reply_text)
            self.assertNotIn("几百", d.reply_text)

    def test_llm_price_reply_with_social_channel_is_overridden_by_price_guardrail(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐您可以去小红书搜索我们下单，价格会更清楚一些🌹"

            d = agent._decide_llm_reply(
                latest_user_text="你们价格多少？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            self.assertEqual(llm.calls, 1)
            self.assertIn("3000、4000、5000、6000", d.reply_text)
            self.assertNotIn("小红书", d.reply_text)
            self.assertNotIn("下单", d.reply_text)

    def test_llm_address_reply_is_overridden_by_canonical_store_address(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐在南京西路附近，您导航一下就好🌹"

            d = agent._decide_llm_reply(
                latest_user_text="静安店地址在哪里？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertEqual(d.reply_source, "llm")
            self.assertIn("上海静安门店", d.reply_text)
            self.assertIn("圈圈的位置", d.reply_text)
            self.assertNotIn("静安区愚园路172号环球世界大厦A座", d.reply_text)
            self.assertNotIn("南京西路", d.reply_text)

    def test_llm_contact_reply_is_overridden_by_fixed_contact_phrase(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "好的姐姐，我加您微信详细说下🌹"

            d = agent._decide_llm_reply(
                latest_user_text="13916008878",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertIn("您留个☎️", d.reply_text)
            self.assertIn("主动跟您介绍", d.reply_text)

    def test_llm_address_detail_reply_is_overridden_by_fixed_address_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "好的姐姐帮您问了，门店在静安区南京西路1818号国际广场2楼🌹"

            d = agent._decide_llm_reply(
                latest_user_text="在几楼啊？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                session_state={"last_target_store": "sh_jingan"},
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertIn("圈圈的位置", d.reply_text)
            self.assertNotIn("具体地址", d.reply_text)
            self.assertNotIn("南京西路", d.reply_text)

    def test_llm_phone_leak_reply_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "姐姐，您直接拨打客服热线19521462613就能获取详细地址和导航啦🌹"

            d = agent._decide_llm_reply(
                latest_user_text="北京店怎么联系？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertEqual(
                d.reply_text,
                "姐姐，您提供电话，我来联系您，可以给您具体的介绍假发价格，款式，地址位置，坐车导航路线，以及预约事项。❤️",
            )

    def test_llm_ma_teacher_hair_service_claim_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "可以的姐姐，假发修剪造型我们这边没问题。您到时过来，马老师帮您弄。💗"

            d = agent._decide_llm_reply(
                latest_user_text="你们店里也可以剪发的吧？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertIn("假发修剪造型我们这边没问题", d.reply_text)
            self.assertNotIn("马老师帮您弄", d.reply_text)

    def test_llm_ma_teacher_direct_query_keeps_identity_reply(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            llm.reply_text = "可以的姐姐，马老师帮您弄。💗"

            d = agent._decide_llm_reply(
                latest_user_text="我找马老师做可以吗？",
                intent="general",
                route_reason="unknown",
                conversation_history=[],
                rule_id="LLM_GENERAL",
            )

            print(f"LLM输出：{llm.reply_text}")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 1)
            self.assertEqual(d.reply_text, "姐姐，马老师是做短视频拍摄的，暂时无法安排🥰")

    def test_user_phone_submission_uses_fixed_rule_reply(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))

            d = agent.decide(
                "chat_phone_submit",
                "留电话用户",
                "13916008878",
                [],
            )

            print("LLM输出：<未调用LLM，命中手机号硬规则>")
            print(f"实际发出：{d.reply_text}")
            self.assertEqual(llm.calls, 0)
            self.assertEqual(d.reply_source, "rule")
            self.assertEqual(d.rule_id, "CONTACT_PHONE_SUBMITTED")
            self.assertEqual(d.reply_text, "收到啦姐姐，我稍后加您好友，具体跟你详细介绍❤️")

    def test_video_session_once_with_log_driven_state(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户D"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_d",
                user_id_hash=user_hash,
                ts="2026-02-27T09:40:00",
            )

            d1 = agent.decide("chat_a", user_name, "我在黑龙江怎么买", [])
            agent.mark_media_sent("chat_a", user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id="chat_a",
                media_type="contact_image",
                media_path=d1.media_items[0]["path"],
                ts="2026-02-27T10:00:00",
                user_id_hash=user_hash,
            )
            # 联系方式图之后的第1条用户消息，不触发视频
            (conversations_dir / "chat_a.jsonl").write_text(
                (conversations_dir / "chat_a.jsonl").read_text(encoding="utf-8")
                + json.dumps(
                    {
                        "timestamp": "2026-02-27T10:00:01",
                        "session_id": "chat_a",
                        "user_id_hash": user_hash,
                        "event_type": "user_message",
                        "reply_source": "",
                        "rule_id": "",
                        "model_name": "",
                        "payload": {"text": "好的"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertIsNone(agent.mark_reply_sent("chat_a", user_name, "第一轮回复"))

            # 联系方式图之后第2条用户消息，触发视频
            (conversations_dir / "chat_a.jsonl").write_text(
                (conversations_dir / "chat_a.jsonl").read_text(encoding="utf-8")
                + json.dumps(
                    {
                        "timestamp": "2026-02-27T10:00:03",
                        "session_id": "chat_a",
                        "user_id_hash": user_hash,
                        "event_type": "user_message",
                        "reply_source": "",
                        "rule_id": "",
                        "model_name": "",
                        "payload": {"text": "我再问下"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            video_item = agent.mark_reply_sent("chat_a", user_name, "第二轮回复")
            self.assertIsNotNone(video_item)
            self.assertEqual(video_item.get("type"), "delayed_video")
            agent.mark_media_sent("chat_a", user_name, video_item, success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id="chat_a",
                media_type="delayed_video",
                media_path=str(temp_dir / "images" / "video.mp4"),
                ts="2026-02-27T10:00:10",
                user_id_hash=user_hash,
                trigger_source="contact_followup",
            )

            d2 = agent.decide("chat_b", user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d2.media_plan, "contact_image")
            self.assertTrue(d2.media_items)
            self.assertIsNone(agent.mark_reply_sent("chat_a", user_name, "再追问一次"))

    def test_first_reply_video_toggle_off_does_not_trigger(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户首轮关闭"

            agent.set_options(
                use_knowledge_first=agent.use_knowledge_first,
                knowledge_threshold=agent.knowledge_threshold,
                first_reply_video_enabled=False,
            )

            d = agent.decide("chat_first_reply_off", user_name, "价格多少", [])
            self.assertTrue(d.is_first_turn_global)
            self.assertFalse(d.first_turn_video_items)

    def test_first_reply_and_contact_followup_videos_can_both_send(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            user_name = "用户双视频"
            user_hash = agent._hash_user(user_name)

            agent.set_options(
                use_knowledge_first=agent.use_knowledge_first,
                knowledge_threshold=agent.knowledge_threshold,
                first_reply_video_enabled=True,
            )

            d0 = agent.decide("chat_dual_video", user_name, "价格多少", [])
            first_video = d0.first_turn_video_items[0] if d0.first_turn_video_items else None
            self.assertIsNotNone(first_video)
            self.assertEqual(first_video.get("type"), "delayed_video")
            self.assertEqual(first_video.get("trigger_source"), "first_reply")

            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id="chat_dual_video",
                media_type="delayed_video",
                media_path=str(first_video.get("path", "")),
                ts="2026-02-27T10:00:00",
                user_id_hash=user_hash,
                trigger_source="first_reply",
            )

            d1 = agent.decide("chat_dual_video", user_name, "我在黑龙江怎么买", [])
            agent.mark_media_sent("chat_dual_video", user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id="chat_dual_video",
                media_type="contact_image",
                media_path=d1.media_items[0]["path"],
                ts="2026-02-27T10:00:10",
                user_id_hash=user_hash,
            )

            log_file = conversations_dir / "chat_dual_video.jsonl"
            existing = log_file.read_text(encoding="utf-8")
            existing += json.dumps(
                {
                    "timestamp": "2026-02-27T10:00:11",
                    "session_id": "chat_dual_video",
                    "user_id_hash": user_hash,
                    "event_type": "user_message",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {"text": "好的"},
                },
                ensure_ascii=False,
            ) + "\n"
            existing += json.dumps(
                {
                    "timestamp": "2026-02-27T10:00:12",
                    "session_id": "chat_dual_video",
                    "user_id_hash": user_hash,
                    "event_type": "user_message",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {"text": "我再问下"},
                },
                ensure_ascii=False,
            ) + "\n"
            log_file.write_text(existing, encoding="utf-8")

            second_video = agent.mark_reply_sent(
                "chat_dual_video",
                user_name,
                "联系方式后第二轮回复",
                is_first_turn_global=False,
            )
            self.assertIsNotNone(second_video)
            self.assertEqual(second_video.get("trigger_source"), "contact_followup")

            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id="chat_dual_video",
                media_type="delayed_video",
                media_path=str(second_video.get("path", "")),
                ts="2026-02-27T10:00:20",
                user_id_hash=user_hash,
                trigger_source="contact_followup",
            )

            self.assertIsNone(
                agent.mark_reply_sent(
                    "chat_dual_video",
                    user_name,
                    "再次回复",
                    is_first_turn_global=False,
                )
            )

    def test_video_media_fallback_when_config_name_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)

            bad_config = {
                "version": 1,
                "categories": ["联系方式", "店铺地址", "视频素材"],
                "images": {
                    "联系方式": ["contact.jpg"],
                    "店铺地址": ["北京地址.jpg"],
                    "视频素材": ["配置里不存在的视频名.mp4"],
                },
            }
            (temp_dir / "image_categories.json").write_text(
                json.dumps(bad_config, ensure_ascii=False),
                encoding="utf-8",
            )
            agent.reload_media_library()
            status = agent.get_status()
            self.assertGreater(status.get("video_media_count", 0), 0)
            self.assertTrue(agent._pick_video_media())

    def test_purchase_known_geo_contact_then_remind(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_geo"
            user_name = "用户E"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_e",
                user_id_hash=user_hash,
                ts="2026-02-27T09:50:00",
            )

            d0 = agent.decide(session_id, user_name, "我在长宁", [])
            self.assertEqual(d0.rule_id, "ADDR_STORE_RECOMMEND")

            d1 = agent.decide(session_id, user_name, "怎么买啊", [])
            self.assertEqual(d1.rule_id, "PURCHASE_CONTACT_FROM_KNOWN_GEO")
            self.assertEqual(d1.media_plan, "contact_image")
            self.assertTrue(d1.media_items)
            agent.mark_media_sent(session_id, user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=d1.media_items[0]["path"],
                ts="2999-01-01T00:02:00",
                user_id_hash=user_hash,
            )

            d2 = agent.decide(session_id, user_name, "怎么预约", [])
            self.assertEqual(d2.rule_id, "PURCHASE_CONTACT_REMIND_ONLY")
            self.assertEqual(d2.media_plan, "none")
            self.assertFalse(d2.media_items)

    def test_not_in_shanghai_purchase_sends_contact_if_not_sent(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_not_in_sh"
            user_name = "用户E2"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_e2",
                user_id_hash=user_hash,
                ts="2026-02-27T09:51:00",
            )

            d0 = agent.decide(session_id, user_name, "我在长宁", [])
            self.assertEqual(d0.rule_id, "ADDR_STORE_RECOMMEND")

            d1 = agent.decide(session_id, user_name, "不在上海怎么买？", [])
            self.assertEqual(d1.rule_id, "PURCHASE_REMOTE_CONTACT_IMAGE")
            self.assertEqual(d1.media_plan, "contact_image")
            self.assertTrue(d1.media_items)

    def test_not_in_shanghai_purchase_remind_if_contact_already_sent(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_not_in_sh_sent"
            user_name = "用户E3"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_e3",
                user_id_hash=user_hash,
                ts="2026-02-27T09:52:00",
            )

            d0 = agent.decide(session_id, user_name, "我在长宁", [])
            self.assertEqual(d0.rule_id, "ADDR_STORE_RECOMMEND")

            d1 = agent.decide(session_id, user_name, "怎么预约？", [])
            self.assertEqual(d1.rule_id, "PURCHASE_CONTACT_FROM_KNOWN_GEO")
            self.assertEqual(d1.media_plan, "contact_image")
            self.assertTrue(d1.media_items)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=d1.media_items[0]["path"],
                ts="2026-02-27T10:02:00",
                user_id_hash=user_hash,
            )

            d2 = agent.decide(session_id, user_name, "不在上海怎么买？", [])
            self.assertEqual(d2.rule_id, "PURCHASE_REMOTE_CONTACT_REMIND_ONLY")
            self.assertEqual(d2.media_plan, "none")
            self.assertIn("远程定制", d2.reply_text)

    def test_purchase_known_geo_not_blocked_by_legacy_contact_count(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_geo_legacy"
            user_name = "用户G"

            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_g",
                user_id_hash=user_hash,
                ts="2026-02-27T09:55:00",
            )
            agent.memory_store.update_session_state(
                session_id,
                {
                    "contact_image_sent_count": 1,
                    "contact_image_last_sent_at": "",
                },
                user_hash=user_hash,
            )

            d0 = agent.decide(session_id, user_name, "我在长宁", [])
            self.assertEqual(d0.rule_id, "ADDR_STORE_RECOMMEND")

            d1 = agent.decide(session_id, user_name, "需要预约吗？", [])
            self.assertEqual(d1.rule_id, "PURCHASE_CONTACT_FROM_KNOWN_GEO")
            self.assertEqual(d1.media_plan, "contact_image")
            self.assertTrue(d1.media_items)

    def test_address_image_cooldown_24h(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_addr"
            user_name = "用户F"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_f",
                user_id_hash=user_hash,
                ts="2026-02-27T09:58:00",
            )

            d1 = agent.decide(session_id, user_name, "我在门头沟", [])
            self.assertEqual(d1.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d1.media_plan, "address_image")
            self.assertTrue(d1.media_items)
            agent.mark_media_sent(session_id, user_name, d1.media_items[0], success=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=d1.media_items[0]["path"],
                ts=datetime.now().isoformat(timespec="seconds"),
                user_id_hash=user_hash,
            )

            d2 = agent.decide(session_id, user_name, "我在门头沟", [])
            self.assertEqual(d2.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d2.media_plan, "address_image")
            self.assertTrue(d2.media_items)

            (conversations_dir / f"{session_id}.jsonl").unlink(missing_ok=True)
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=d1.media_items[0]["path"],
                ts="2020-01-01T00:00:00",
                user_id_hash=user_hash,
            )

            d3 = agent.decide(session_id, user_name, "我在门头沟", [])
            self.assertEqual(d3.media_plan, "address_image")
            self.assertTrue(d3.media_items)

    def test_address_image_can_still_send_after_more_than_six_history(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_addr_more_than_six"
            user_name = "用户地址超6次"
            user_hash = agent._hash_user(user_name)

            agent.memory_store.update_session_state(
                session_id,
                {
                    "address_image_sent_count": 6,
                    "last_target_store": "beijing_chaoyang",
                },
                user_hash=user_hash,
            )

            d = agent.decide(session_id, user_name, "我在门头沟", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.media_plan, "address_image")
            self.assertTrue(d.media_items)

    def test_both_images_lock_blocks_future_images(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_lock"
            user_name = "用户H"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_h",
                user_id_hash=user_hash,
                ts="2020-01-01T10:29:00",
            )

            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=str(temp_dir / "images" / "北京地址.jpg"),
                ts="2020-01-01T10:30:00",
                user_id_hash=user_hash,
            )
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=str(temp_dir / "images" / "contact.jpg"),
                ts="2020-01-01T10:31:00",
                user_id_hash=user_hash,
            )

            d = agent.decide(session_id, user_name, "我在门头沟", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.media_plan, "address_image")
            self.assertTrue(d.media_items)

    def test_both_images_strong_intent_first_fixed_then_llm(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, llm = self._build_agent(temp_dir)
            session_id = "chat_lock_purchase"
            user_name = "用户I"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_i",
                user_id_hash=user_hash,
                ts="2026-02-27T10:39:00",
            )

            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=str(temp_dir / "images" / "北京地址.jpg"),
                ts="2026-02-27T10:40:00",
                user_id_hash=user_hash,
            )
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=str(temp_dir / "images" / "contact.jpg"),
                ts="2026-02-27T10:41:00",
                user_id_hash=user_hash,
            )
            agent.memory_store.update_session_state(
                session_id,
                {"last_target_store": "beijing_chaoyang"},
                user_hash=user_hash,
            )

            d1 = agent.decide(session_id, user_name, "怎么预约", [])
            self.assertEqual(d1.rule_id, "PURCHASE_AFTER_BOTH_FIRST_HINT")
            self.assertEqual(d1.media_plan, "none")
            self.assertIn("画圈圈", d1.reply_text)

            llm.reply_text = "姐姐我这边帮您安排，您告诉我方便到店时间哈🌹"
            d2 = agent.decide(session_id, user_name, "我想买", [])
            self.assertIn(d2.reply_source, ("llm", "knowledge"))
            self.assertEqual(d2.media_plan, "none")

    def test_both_images_first_hint_ignores_legacy_strong_count_and_second_hits_kb(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, repository, _ = self._build_agent(temp_dir)
            session_id = "chat_lock_purchase_legacy_count"
            user_name = "用户Legacy"
            user_hash = agent._hash_user(user_name)

            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_legacy",
                user_id_hash=user_hash,
                ts="2026-02-27T10:39:00",
            )
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="address_image",
                media_path=str(temp_dir / "images" / "北京地址.jpg"),
                ts="2026-02-27T10:40:00",
                user_id_hash=user_hash,
            )
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=str(temp_dir / "images" / "contact.jpg"),
                ts="2026-02-27T10:41:00",
                user_id_hash=user_hash,
            )
            agent.memory_store.update_session_state(
                session_id,
                {
                    "last_target_store": "beijing_chaoyang",
                    "strong_intent_after_both_count": 18,
                    "purchase_both_first_hint_sent": False,
                },
                user_hash=user_hash,
            )
            repository.add(
                "怎么预约",
                "结论先说：可以预约到店，我现在就帮您安排。",
                answers=[
                    "结论先说：可以预约到店，我现在就帮您安排。",
                    "可以预约的姐姐，您告诉我方便时间我来登记。",
                    "您这边可以直接预约到店，我帮您对接门店时间。",
                    "没问题，预约到店这边可以安排，您说下时间偏好。",
                    "支持预约到店，我这边马上给您走预约流程。",
                ],
                intent="purchase",
                tags=["预约"],
            )

            d1 = agent.decide(session_id, user_name, "怎么预约", [])
            self.assertEqual(d1.reply_source, "knowledge")
            self.assertEqual(d1.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d1.media_plan, "contact_image")
            self.assertFalse(d1.kb_variant_fallback_llm)

            d2 = agent.decide(session_id, user_name, "怎么预约", [])
            self.assertEqual(d2.reply_source, "knowledge")
            self.assertEqual(d2.rule_id, "KB_MATCH_CONTACT_IMAGE")
            self.assertEqual(d2.media_plan, "contact_image")
            self.assertFalse(d2.kb_variant_fallback_llm)

    def test_repeat_rewrite_fallback_to_pool(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            session_id = "chat_repeat"
            user_name = "用户J"
            repeated = "姐姐我来帮您安排～🌹"
            normalized = agent._normalize_for_dedupe(repeated)

            user_hash = agent._hash_user(user_name)
            user_state = agent.memory_store.get_user_state(user_hash)
            user_state["recent_reply_hashes"] = [normalized]
            agent.memory_store.update_user_state(user_hash, user_state)

            llm.reply_text = repeated
            llm.reply_queue = [repeated, repeated]  # 触发两次改写仍重复，最终落去重池

            d = agent.decide(session_id, user_name, "售后多久", [])
            self.assertNotEqual(agent._normalize_for_dedupe(d.reply_text), normalized)
            self.assertIn(d.reply_text, agent._dedupe_reply_pool)

    def test_log_deleted_resets_stale_media_state(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_reset_by_log_delete"
            user_name = "用户K"
            conversations_dir = temp_dir / "conversations"

            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_k",
                user_id_hash=user_hash,
                ts="2026-02-27T10:10:00",
            )
            agent.memory_store.update_session_state(
                session_id,
                {
                    "address_image_sent_count": 3,
                    "contact_image_sent_count": 2,
                    "address_image_last_sent_at_by_store": {"beijing_chaoyang": "2026-01-01T00:00:00"},
                    "contact_image_last_sent_at": "2026-01-01T00:00:00",
                },
                user_hash=user_hash,
            )

            # 未生成会话日志时，应回放为空并清掉“已发图”状态
            d = agent.decide(session_id, user_name, "我在门头沟", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.media_plan, "address_image")
            self.assertFalse(d.media_skip_reason)
            self.assertTrue(d.media_items)

    def test_log_deleted_resets_video_state(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            conversations_dir = temp_dir / "conversations"
            agent, _, _, _ = self._build_agent(temp_dir, whitelist_sessions=["chat_video_reset"])
            session_id = "chat_video_reset"
            user_name = "用户V"
            user_hash = agent._hash_user(user_name)
            self._append_assistant_reply_log(
                conversations_dir=conversations_dir,
                session_id="seed_user_v",
                user_id_hash=user_hash,
                ts="2026-02-27T09:59:00",
            )

            d1 = agent.decide(session_id, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d1.media_plan, "contact_image")
            self._append_media_success_log(
                conversations_dir=conversations_dir,
                session_id=session_id,
                media_type="contact_image",
                media_path=d1.media_items[0]["path"],
                ts="2026-02-27T10:00:00",
                user_id_hash=user_hash,
            )
            (conversations_dir / f"{session_id}.jsonl").write_text(
                (conversations_dir / f"{session_id}.jsonl").read_text(encoding="utf-8")
                + json.dumps(
                    {
                        "timestamp": "2026-02-27T10:00:01",
                        "session_id": session_id,
                        "user_id_hash": user_hash,
                        "event_type": "user_message",
                        "reply_source": "",
                        "rule_id": "",
                        "model_name": "",
                        "payload": {"text": "收到"},
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-02-27T10:00:03",
                        "session_id": session_id,
                        "user_id_hash": user_hash,
                        "event_type": "user_message",
                        "reply_source": "",
                        "rule_id": "",
                        "model_name": "",
                        "payload": {"text": "再问一次"},
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-02-27T10:00:04",
                        "session_id": session_id,
                        "user_id_hash": user_hash,
                        "event_type": "assistant_reply",
                        "reply_source": "rule",
                        "rule_id": "DUMMY",
                        "model_name": "",
                        "payload": {"text": "收到", "round_media_sent_types": []},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertIsNotNone(agent.mark_reply_sent(session_id, user_name, "第二轮"))

            (conversations_dir / f"{session_id}.jsonl").unlink(missing_ok=True)

            d2 = agent.decide(session_id, user_name, "我在黑龙江怎么买", [])
            self.assertEqual(d2.media_plan, "contact_image")

    def test_media_state_recovers_from_conversation_log(self):
        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            agent, _, _, _ = self._build_agent(temp_dir)
            session_id = "chat_log_recover"
            user_name = "用户L"

            log_file = (temp_dir / "conversations") / f"{session_id}.jsonl"
            records = [
                {
                    "timestamp": "2020-01-01T10:00:00",
                    "session_id": session_id,
                    "user_id_hash": agent._hash_user(user_name),
                    "event_type": "media_attempt",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {"type": "address_image", "path": str(temp_dir / "images" / "北京地址.jpg")},
                },
                {
                    "timestamp": "2020-01-01T10:00:01",
                    "session_id": session_id,
                    "user_id_hash": agent._hash_user(user_name),
                    "event_type": "media_result",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {"type": "address_image", "success": True, "result": {"ok": True}},
                },
                {
                    "timestamp": "2020-01-01T10:00:10",
                    "session_id": session_id,
                    "user_id_hash": agent._hash_user(user_name),
                    "event_type": "media_attempt",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {"type": "contact_image", "path": str(temp_dir / "images" / "contact.jpg")},
                },
                {
                    "timestamp": "2020-01-01T10:00:11",
                    "session_id": session_id,
                    "user_id_hash": agent._hash_user(user_name),
                    "event_type": "media_result",
                    "reply_source": "",
                    "rule_id": "",
                    "model_name": "",
                    "payload": {"type": "contact_image", "success": True, "result": {"ok": True}},
                },
                {
                    "timestamp": "2020-01-01T10:00:12",
                    "session_id": session_id,
                    "user_id_hash": agent._hash_user(user_name),
                    "event_type": "assistant_reply",
                    "reply_source": "rule",
                    "rule_id": "DUMMY",
                    "model_name": "",
                    "payload": {"text": "收到", "round_media_sent_types": []},
                },
            ]
            log_file.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in records) + "\n", encoding="utf-8")

            user_hash = agent._hash_user(user_name)
            agent.memory_store.update_session_state(
                session_id,
                {
                    "address_image_sent_count": 0,
                    "contact_image_sent_count": 0,
                    "last_target_store": "beijing_chaoyang",
                },
                user_hash=user_hash,
            )

            d = agent.decide(session_id, user_name, "我在门头沟", [])
            self.assertEqual(d.rule_id, "ADDR_STORE_RECOMMEND")
            self.assertEqual(d.media_plan, "address_image")
            self.assertTrue(d.media_items)

    def test_media_image_placeholder_uses_fixed_price_reply_pool(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            d = agent.decide("chat_media_image", "媒体图片用户", "[图片]", [])
            self.assertEqual(d.rule_id, "MEDIA_IMAGE_REPLY")
            self.assertEqual(d.reply_source, "knowledge")
            self.assertIn("3000～6000元", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_media_video_placeholder_uses_fixed_price_reply_pool(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            d = agent.decide("chat_media_video", "媒体视频用户", "[视频]", [])
            self.assertEqual(d.rule_id, "MEDIA_VIDEO_REPLY")
            self.assertEqual(d.reply_source, "knowledge")
            self.assertIn("3000～6000元", d.reply_text)
            self.assertEqual(llm.calls, 0)

    def test_media_emoji_placeholder_uses_fixed_reply(self):
        with tempfile.TemporaryDirectory() as td:
            agent, _, _, llm = self._build_agent(Path(td))
            d = agent.decide("chat_media_emoji", "媒体表情用户", "[表情]", [])
            self.assertEqual(d.rule_id, "MEDIA_EMOJI_REPLY")
            self.assertEqual(d.reply_source, "knowledge")
            self.assertIn(
                d.reply_text,
                {
                    "姐姐，关于假发的问题，您可以随时问我🌹",
                    "姐姐，假发这块您有任何想了解的都可以直接问我呀❤️",
                    "姐姐，您要是想了解假发的价格、款式或者到店问题，都可以随时问我哦🌷",
                    "姐姐，关于假发这边您尽管问我，我一直都在呢💐",
                    "姐姐，假发有什么想咨询的，您直接跟我说就可以啦🥰",
                },
            )
            self.assertEqual(llm.calls, 0)


if __name__ == "__main__":
    unittest.main()
