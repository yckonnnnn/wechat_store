from __future__ import annotations

from typing import Any, Dict, List, Tuple


STORE_NAME_MAP = {
    "sh_renmin": "人民广场店",
    "sh_jingan": "静安店",
    "sh_hongkou": "虹口店",
    "sh_wujiaochang": "五角场店",
    "sh_xuhui": "徐汇店",
    "beijing_chaoyang": "北京朝阳店",
}


def _build_confirmed_facts_block(confirmed_facts: Dict[str, Any]) -> str:
    return (
        "【现场信息】\n"
        f"- 门店：{confirmed_facts.get('store_confirmed', '未知')}；候选：{confirmed_facts.get('store_candidates', '无')}；地址权限：{confirmed_facts.get('store_delivery_authority', '无')}\n"
        f"- 主线：{confirmed_facts.get('current_mainline', 'business_answer')}；地址：{confirmed_facts.get('address_stage', 'not_delivered')}；联系方式：{confirmed_facts.get('contact_stage', 'not_delivered')}\n"
        f"- 电话已收到：{confirmed_facts.get('contact_captured', False)}；地区追问：{confirmed_facts.get('geo_followup_round', 0)}轮；耗尽：{confirmed_facts.get('geo_followup_exhausted', False)}\n"
        "【红线】\n"
        "- 不该回地址时别回地址，不该推联系方式时别推联系方式。\n"
        "- 电话已收到后别再要联系方式；用户改问别的问题，就直接答新问题。\n"
        "- 如果电话已收到，不要再让用户留电话、留方式、加好友。\n\n"
    )


def _build_enterprise_guard_summary(enterprise_guard_text: str) -> str:
    if not enterprise_guard_text.strip():
        return "（企业知识约束文档缺失，请按已有品牌口径稳妥回复）"
    return (
        "- 只能按企业已知信息回复，不能编地址、路线、价格、活动和定位。\n"
        "- 门店只有北京朝阳1家、上海5家；价格只在3000到6000区间内表达。\n"
        "- 导航、地铁口、停车等未知细节先承认不确定，不要乱答；不要要求用户发图，也不要乱承诺。"
    )


def _build_faq_priority_block(
    standard_reply_question: str,
    standard_reply_answer: str,
    standard_reply_confidence: str,
) -> str:
    if not standard_reply_answer:
        return "（当前无高置信标准话术命中）"
    return (
        f"- {standard_reply_question or '未知'}\n"
        f"- {standard_reply_answer}\n"
        f"- 置信度：{standard_reply_confidence or 'unknown'}，当前问题高度一致时优先沿用。"
    )


def _build_faq_block(faq_examples: List[Tuple[str, str]]) -> str:
    if not faq_examples:
        return "（当前无高相关标准话术）"
    question, answer = faq_examples[0]
    return f"- {question} -> {answer}"


def _build_brand_block(brand_snippets: List[str]) -> str:
    if not brand_snippets:
        return "（当前无高相关品牌知识片段）"
    compact = " ".join(str(brand_snippets[0]).split())
    return f"- {compact[:220]}"


def _build_conversation_state_block(conversation_state: Dict[str, str]) -> str:
    return (
        "【最近对话状态】\n"
        f"- 城市：{conversation_state.get('city_confirmed', '未知')}；门店：{conversation_state.get('store_confirmed', '未知')}；到店：{conversation_state.get('visit_status', '未说明')}\n"
        f"- 上轮：{conversation_state.get('last_answer_type', '未知')}；本轮目标：{conversation_state.get('reply_goal', '自然承接并回答当前问题')}；别重复：{conversation_state.get('avoid_repeat', '无')}"
    )


def build_general_llm_prompt(agent: Any, latest_user_text: str) -> Tuple[str, Dict[str, Any]]:
    # 【新增】获取已确认事实并注入到 prompt 最开头
    confirmed_facts_block = ""
    confirmed_facts = {}

    if hasattr(agent, '_current_unified_state') and agent._current_unified_state:
        state = agent._current_unified_state
        store_key = str(
            state.get("current_store_context", "")
            or state.get("store_delivery_authority", "")
            or ""
        ).strip()
        store_candidates = [
            STORE_NAME_MAP.get(str(item).strip(), str(item).strip())
            for item in (state.get("store_candidates", []) or [])
            if str(item).strip()
        ]
        address_stages = []
        for raw_store, raw_stage in sorted((state.get("address_delivery_stage_by_store", {}) or {}).items()):
            stage_store = STORE_NAME_MAP.get(str(raw_store).strip(), str(raw_store).strip())
            address_stages.append(f"{stage_store}:{raw_stage}")
        confirmed_facts = {
            "store_confirmed": STORE_NAME_MAP.get(store_key, store_key or "未知"),
            "address_stage": str((dict(state.get("address_delivery_stage_by_store", {}) or {})).get(store_key, "not_delivered") or "not_delivered"),
            "contact_stage": str(state.get("contact_delivery_stage", "not_delivered") or "not_delivered"),
            "current_mainline": str(state.get("current_mainline", "business_answer") or "business_answer"),
            "contact_captured": bool(state.get("contact_captured", False)),
            "geo_followup_round": state.get("geo_followup_round", 0),
            "geo_followup_exhausted": state.get("geo_followup_exhausted", False),
            "store_delivery_authority": STORE_NAME_MAP.get(
                str(state.get("store_delivery_authority", "") or "").strip(),
                str(state.get("store_delivery_authority", "") or "无").strip() or "无",
            ),
            "store_candidates": "、".join(store_candidates[:3]) if store_candidates else "无",
            "address_stages": "；".join(address_stages) if address_stages else "无",
        }

        confirmed_facts_block = _build_confirmed_facts_block(confirmed_facts)

    normalized_text = agent.knowledge_service.normalize_user_text(latest_user_text)
    faq_detail = agent.knowledge_service.find_answer_detail(normalized_text, threshold=agent.knowledge_threshold)
    faq_examples = agent._top_kb_examples(normalized_text, limit=3)
    faq_block = _build_faq_block(faq_examples)
    enterprise_guard = _build_enterprise_guard_summary(agent._enterprise_guard_doc_text or "")
    store_fact_block = "【门店范围】\n- 只推荐北京朝阳1家和上海5家；用户没说清城市或区域，就自然追问。"
    faq_priority_block = "（当前无高置信标准话术命中）"
    standard_reply_hit = False
    standard_reply_question = ""
    standard_reply_confidence = ""
    standard_reply_answer = ""
    standard_reply_intent = ""
    if faq_detail.get("matched"):
        standard_reply_hit = True
        standard_reply_question = str(faq_detail.get("question", "") or "")
        standard_reply_confidence = str(faq_detail.get("confidence", "") or "")
        standard_reply_answer = str(faq_detail.get("answer", "") or "").strip()
        standard_reply_intent = str(faq_detail.get("intent", "") or "").strip().lower()
        faq_priority_block = _build_faq_priority_block(
            standard_reply_question=standard_reply_question,
            standard_reply_answer=standard_reply_answer,
            standard_reply_confidence=standard_reply_confidence,
        )
    brand_snippets = agent._top_brand_knowledge_snippets(normalized_text, limit=3)
    brand_block = _build_brand_block(brand_snippets)
    conversation_state = agent._summarize_llm_conversation_state(
        latest_user_text=latest_user_text,
        conversation_history=getattr(agent, "_current_prompt_conversation_history", []) or [],
        standard_reply_intent=standard_reply_intent,
    )
    conversation_state_block = _build_conversation_state_block(conversation_state)
    prompt = (
        confirmed_facts_block +
        "你是艾耐儿假发客服助理。\n"
        "像真人客服一样自然、利落地回话；结论先行，尽量1句话说完整，末尾只保留1个emoji表情。\n"
        "【你要做的事】\n"
        "- 帮用户推荐合适门店，但只能推荐上海5家和北京朝阳1家。\n"
        "- 江浙沪优先人民广场店，内蒙优先北京朝阳店；上海本地按区域、便利度和需求推荐；外地不方便到店可承接远程定制。\n"
        "- 推荐是帮用户判断，不是硬推；用户质疑你为什么这么推荐时，先把原因解释清楚。\n"
        "- 需要承接联系方式时要委婉，优先引导用户发电话，不主动索要微信号；平时提渠道可以说微信，但别踩平台红线。\n"
        "\n"
        "先听懂用户这轮真正想问什么，容错错别字和口语；追问同一件事时，只回答新增部分，不要整段复读。\n"
        "多轮里优先判断用户是在确认、继续推进，还是换了新问题；已经讲过的地址、本店、预约、价格，除非用户明确要求重说，否则别原样重复。\n"
        "用户说“知道了”“可以去”“那就这个店”“那我过去”等，视为确认门店，往预约、营业时间、到店安排继续接；再问怎么预约，就直接说怎么约。\n"
        "联系方式只在用户明确问怎么联系、怎么加，或确实需要推进下一步时再委婉承接；不要频繁索要联系方式，也不要输出具体联系方式。\n"
        "价格、营业时间、使用年限、预约、远程定制这些明确事实，优先沿用标准结论；不确定就稳妥收口并自然补问，不要编造。\n"
        "用户提到受伤、生病、不方便出门、摔跤、腿脚不方便，先简短安慰再给方案。马老师只负责短视频拍摄，不做假发、不做头发、不剪头、不加好友、不负责修剪造型。\n\n"
        f"{store_fact_block}\n\n"
        f"{conversation_state_block}\n\n"
        f"【高置信标准话术命中】\n{faq_priority_block}\n\n"
        f"【企业口径】\n{enterprise_guard}\n\n"
        f"【相关话术】\n{faq_block}\n\n"
        f"【品牌补充】\n{brand_block}\n\n"
        "仅输出最终客服话术纯文本，不要输出JSON、代码块或解释。"
    )
    return prompt, {
        "standard_reply_hit": standard_reply_hit,
        "standard_reply_question": standard_reply_question,
        "standard_reply_confidence": standard_reply_confidence,
        "standard_reply_answer": standard_reply_answer,
        "standard_reply_intent": standard_reply_intent,
        "brand_knowledge_used": bool(brand_snippets),
        "conversation_state": conversation_state,
    }


def summarize_llm_conversation_state(
    agent: Any,
    latest_user_text: str,
    conversation_history: List[Dict[str, str]],
    standard_reply_intent: str = "",
) -> Dict[str, str]:
    history = conversation_history or []
    # 优先使用统一状态
    if hasattr(agent, '_current_unified_state') and agent._current_unified_state:
        state = agent._current_unified_state
    else:
        state = dict(getattr(agent, "_current_prompt_session_state", {}) or {})

    conversation_facts = dict(state.get("conversation_facts", {}) or {})
    latest_norm = agent.knowledge_service.normalize_user_text(latest_user_text)
    combined_text = " ".join(str(item.get("content", "") or "") for item in history)
    current_text = f"{combined_text} {latest_user_text}".strip()
    normalized = agent.knowledge_service.normalize_user_text(current_text)

    latest_city = ""
    if "北京" in latest_norm or "朝阳" in latest_norm:
        latest_city = "北京"
    if "上海" in latest_norm or any(token in latest_norm for token in ("静安", "人民广场", "人广", "虹口", "五角场", "徐汇")):
        latest_city = "上海"

    recommended_store = str(
        state.get("current_store_context", "")
        or conversation_facts.get("recommended_store", "")
        or state.get("store_delivery_authority", "")
        or state.get("last_target_store", "")
        or ""
    ).strip()
    city_from_store = ""
    if recommended_store.startswith("sh_"):
        city_from_store = "上海"
    elif recommended_store == "beijing_chaoyang":
        city_from_store = "北京"

    city_confirmed = latest_city or str(conversation_facts.get("city", "") or "").strip() or city_from_store or "未知"
    if city_confirmed == "未知":
        if "北京" in normalized or "朝阳" in normalized:
            city_confirmed = "北京"
        if "上海" in normalized or any(token in normalized for token in ("静安", "人民广场", "人广", "虹口", "五角场", "徐汇")):
            city_confirmed = "上海"

    store_confirmed = "未知"
    if any(token in latest_norm for token in ("人民广场", "人广", "黄埔", "汉口路")):
        store_confirmed = "人民广场店"
    elif any(token in latest_norm for token in ("静安", "愚园路")):
        store_confirmed = "静安店"
    elif any(token in latest_norm for token in ("虹口", "花园路")):
        store_confirmed = "虹口店"
    elif any(token in latest_norm for token in ("五角场", "政通路", "万达广场")):
        store_confirmed = "五角场店"
    elif any(token in latest_norm for token in ("徐汇", "漕溪北路", "中航德必")):
        store_confirmed = "徐汇店"
    elif any(token in latest_norm for token in ("朝阳", "建外soho")):
        store_confirmed = "北京朝阳店"
    elif str(state.get("current_store_context", "") or "").strip() in STORE_NAME_MAP:
        store_confirmed = STORE_NAME_MAP[str(state.get("current_store_context", "") or "").strip()]
    elif recommended_store and recommended_store in STORE_NAME_MAP:
        store_confirmed = STORE_NAME_MAP[recommended_store]
    elif any(token in normalized for token in ("人民广场", "人广", "黄埔", "汉口路")):
        store_confirmed = "人民广场店"
    elif any(token in normalized for token in ("静安", "愚园路")):
        store_confirmed = "静安店"
    elif any(token in normalized for token in ("虹口", "花园路")):
        store_confirmed = "虹口店"
    elif any(token in normalized for token in ("五角场", "政通路", "万达广场")):
        store_confirmed = "五角场店"
    elif any(token in normalized for token in ("徐汇", "漕溪北路", "中航德必")):
        store_confirmed = "徐汇店"
    elif any(token in normalized for token in ("朝阳", "建外soho")):
        store_confirmed = "北京朝阳店"

    visit_status = "未说明"
    if any(token in normalized for token in ("不方便去", "不能去", "不去上海", "外地", "远程")):
        visit_status = "不方便到店"
    elif any(token in normalized for token in ("可以去", "过去", "到店", "去店里", "能过去")):
        visit_status = "可以到店"
    elif str(state.get("conversation_stage", "") or "") in {"store_recommended", "address_image_sent", "appointment_ready"}:
        visit_status = "可以到店"

    empathy_need = "无"
    if any(token in normalized for token in ("摔了", "摔跤", "受伤", "腿伤", "腿现在", "不方便出门", "生病", "腿脚不方便")):
        empathy_need = "需要先安慰共情"

    last_answer_type = str(state.get("last_answer_topic", "") or "").strip() or "未知"
    if last_answer_type == "store_recommendation":
        last_answer_type = "store_address"
    elif last_answer_type == "service_hours":
        last_answer_type = "service_hours"
    elif last_answer_type == "lifespan":
        last_answer_type = "lifespan"
    elif last_answer_type == "appointment":
        last_answer_type = "appointment"
    elif last_answer_type == "price":
        last_answer_type = "price"
    elif history and last_answer_type == "未知":
        last_assistant = ""
        for item in reversed(history):
            if str(item.get("role", "")) == "assistant":
                last_assistant = str(item.get("content", "") or "")
                break
        last_answer_type = agent._infer_answer_type(last_assistant)

    current_turn_action = str(state.get("current_turn_action", "") or "").strip()
    conversation_stage = str(state.get("conversation_stage", "") or "").strip()
    active_topic = str(state.get("active_topic", "") or "").strip()
    reply_goal = "自然承接并回答当前问题"
    avoid_repeat = "无"
    if empathy_need != "无":
        reply_goal = "先简短安慰共情，再给可行方案"
        avoid_repeat = "不要一上来就直接索要联系方式"
    elif current_turn_action == "advance_to_next_step" and store_confirmed != "未知":
        reply_goal = "直接承接用户下一步问题，推进到预约或到店安排"
        avoid_repeat = "不要回头重新问城市或再报完整门店列表"
    elif current_turn_action == "revisit_previous_info" and store_confirmed != "未知":
        reply_goal = "继续承接已发过的位置信息，直接回答位置图或地址追问"
        avoid_repeat = "不要跳去联系方式，也不要回头追问城市"
    elif current_turn_action == "confirm_previous_fact" and active_topic == "price":
        reply_goal = "基于已经说过的价格事实，直接回答这次确认、比较或贵不贵的问题"
        avoid_repeat = "不要把完整价格模板原样重复"
    elif agent._looks_like_appointment_query(latest_norm):
        reply_goal = "回答预约方式，并推进到预约时间安排"
        avoid_repeat = "不要重复完整地址或门店列表"
    elif any(token in latest_norm for token in ("可以去", "知道", "那就", "就去", "过去")) and store_confirmed != "未知":
        reply_goal = "承接用户已确认门店，推进到预约或到店安排"
        avoid_repeat = "不要重复完整地址，除非用户明确要求重说"
    elif any(token in latest_norm for token in ("地址", "在哪", "位置")):
        if store_confirmed != "未知":
            reply_goal = "直接回答已确认门店地址"
            avoid_repeat = "不要重复整段上海5店列表"
        else:
            reply_goal = "回答门店分布，并自然确认城市或区域"
            avoid_repeat = "不要直接索要联系方式"
    elif standard_reply_intent == "service_hours":
        reply_goal = "准确回答营业时间"
    elif standard_reply_intent == "lifespan":
        reply_goal = "准确回答使用年限"

    current_stage = "信息确认"
    stage_display_map = {
        "store_recommended": "门店已确认",
        "address_image_sent": "位置图已发送",
        "price_answered": "价格已说明",
        "service_hours_answered": "营业时间已说明",
        "lifespan_answered": "使用寿命已说明",
        "appointment_ready": "预约推进中",
    }
    if conversation_stage in stage_display_map:
        current_stage = stage_display_map[conversation_stage]
    elif visit_status == "不方便到店":
        current_stage = "远程定制引导"
    elif agent._looks_like_appointment_query(latest_norm):
        current_stage = "预约引导"
    elif store_confirmed != "未知" and visit_status == "可以到店":
        current_stage = "门店已确认，推进预约"
    elif store_confirmed != "未知":
        current_stage = "门店已确认"
    elif city_confirmed != "未知":
        current_stage = "城市已确认，待确认门店"

    if (
        last_answer_type == "store_address"
        and "地址" not in latest_norm
        and store_confirmed != "未知"
        and current_turn_action != "revisit_previous_info"
    ):
        avoid_repeat = "上一轮已回答地址，本轮优先推进下一步"
        if current_stage == "门店已确认":
            current_stage = "门店已确认，等待推进"
    if agent._looks_like_appointment_query(latest_norm) and last_answer_type == "appointment":
        reply_goal = "直接说明预约操作或具体下一步，不要重复预约定义"
        avoid_repeat = "不要重复“我们是预约制的呢”"
    if current_turn_action == "revisit_previous_info" and store_confirmed != "未知":
        current_stage = "位置图已发送"
    if current_turn_action == "advance_to_next_step" and store_confirmed != "未知":
        current_stage = "预约推进中"

    return {
        "city_confirmed": city_confirmed,
        "store_confirmed": store_confirmed,
        "visit_status": visit_status,
        "last_answer_type": last_answer_type,
        "current_stage": current_stage,
        "reply_goal": reply_goal,
        "avoid_repeat": avoid_repeat,
        "empathy_need": empathy_need,
    }
