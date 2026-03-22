from __future__ import annotations

from typing import Any, Dict, List, Tuple


def build_general_llm_prompt(agent: Any, latest_user_text: str) -> Tuple[str, Dict[str, Any]]:
    normalized_text = agent.knowledge_service.normalize_user_text(latest_user_text)
    faq_detail = agent.knowledge_service.find_answer_detail(normalized_text, threshold=agent.knowledge_threshold)
    faq_examples = agent._top_kb_examples(normalized_text, limit=3)
    faq_block = "\n".join([f"- 问：{q}\n  答：{a}" for q, a in faq_examples]) or "（当前无高相关标准话术）"
    enterprise_guard = agent._enterprise_guard_doc_text or "（企业知识约束文档缺失，请按已有品牌口径稳妥回复）"
    store_fact_block = (
        "【门店事实】\n"
        "- 北京只有 1 家门店，位于朝阳区。\n"
        "- 上海共有 5 家门店：静安、人民广场、虹口、五角场、徐汇。\n"
        "- 如果用户没有明确所在城市或区域，请自然追问，不要生硬套模板。\n"
        "- 不要编造路线、出口、导航、楼层、停车等不确定细节。"
    )
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
        faq_priority_block = (
            f"问题：{standard_reply_question or '未知'}\n"
            f"建议答案：{standard_reply_answer}\n"
            f"置信度：{standard_reply_confidence or 'unknown'}\n"
            "要求：如果用户问题与这条标准话术高度一致，优先遵循核心结论，再自然润色。"
        )
    brand_snippets = agent._top_brand_knowledge_snippets(normalized_text, limit=3)
    brand_block = "\n\n".join(brand_snippets) if brand_snippets else "（当前无高相关品牌知识片段）"
    conversation_state = agent._summarize_llm_conversation_state(
        latest_user_text=latest_user_text,
        conversation_history=getattr(agent, "_current_prompt_conversation_history", []) or [],
        standard_reply_intent=standard_reply_intent,
    )
    conversation_state_block = (
        "【最近对话状态】\n"
        f"- 已确认城市：{conversation_state.get('city_confirmed', '未知')}\n"
        f"- 已确认门店：{conversation_state.get('store_confirmed', '未知')}\n"
        f"- 到店条件：{conversation_state.get('visit_status', '未说明')}\n"
        f"- 上一轮已回答：{conversation_state.get('last_answer_type', '未知')}\n"
        f"- 当前阶段：{conversation_state.get('current_stage', '信息确认')}\n"
        f"- 本轮回复目标：{conversation_state.get('reply_goal', '自然承接并回答当前问题')}\n"
        f"- 避免重复：{conversation_state.get('avoid_repeat', '无')}"
    )
    prompt = (
        "你是艾耐儿假发客服助理。\n"
        "语气自然、亲切、有耐心，接地气，拟人化口语，像真人客服。\n"
        "硬规则：结论先行；尽量1句话完成回复，不拖拉，不啰嗦，且必须是完整句；末尾只保留1个emoji表情。\n"
        "禁止主动索要电话、微信或其他联系方式，除非用户明确在问怎么联系；即使如此也不要输出具体联系方式。\n"
        "涉及价格区间、营业时间、使用年限、预约、远程定制等明确事实时，优先保留标准话术和品牌知识库里的核心数字与结论，不要省略或改写错。\n"
        "人物事实硬规则：马老师只负责短视频拍摄，不做假发、不做头发、不剪头、不加好友、不负责修剪造型，禁止把这些服务归给马老师。\n"
        "超出标准话术和品牌知识库可常规发挥，但必须围绕企业知识口径；禁止编造活动承诺、禁止要求对方发图、联系方式或超出事实的信息。\n"
        "若信息不确定，给稳妥结论并自然引导用户补充。\n\n"
        "多轮对话时，优先判断用户是在确认已有信息、推进下一步还是提出新问题。\n"
        "如果上一轮已经明确回答过地址、本店信息或预约信息，本轮不要原样重复；除非用户明确要求再说一遍。\n"
        "如果用户表达“知道了”“可以去”“那就这个店”“那我过去”等，视为已经确认门店，应推进到预约、营业时间、到店安排等下一步。\n"
        "如果用户只是简短承接，不要把整段标准话术或整段地址重新说一遍，优先接着往下聊。\n\n"
        "如果用户提到受伤、生病、不方便出门、摔跤、腿脚不方便等情况，先简短安慰或共情，再继续给方案。\n"
        "如果用户上一轮已经知道需要预约，这一轮再问“怎么预约”，应直接说明预约操作或下一步，不要重复“我们是预约制的呢”。\n\n"
        f"{store_fact_block}\n\n"
        f"{conversation_state_block}\n\n"
        f"【高置信标准话术命中】\n{faq_priority_block}\n\n"
        f"【企业知识约束】\n{enterprise_guard}\n\n"
        f"【相关标准话术参考】\n{faq_block}\n\n"
        f"【品牌知识库参考】\n{brand_block}\n\n"
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
    combined_text = " ".join(str(item.get("content", "") or "") for item in history[-6:])
    current_text = f"{combined_text} {latest_user_text}".strip()
    normalized = agent.knowledge_service.normalize_user_text(current_text)

    city_confirmed = "未知"
    if "北京" in normalized or "朝阳" in normalized:
        city_confirmed = "北京"
    if "上海" in normalized or any(token in normalized for token in ("静安", "人民广场", "人广", "虹口", "五角场", "徐汇")):
        city_confirmed = "上海"

    store_confirmed = "未知"
    if any(token in normalized for token in ("人民广场", "人广", "黄埔", "汉口路")):
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

    empathy_need = "无"
    if any(token in normalized for token in ("摔了", "摔跤", "受伤", "腿伤", "腿现在", "不方便出门", "生病", "腿脚不方便")):
        empathy_need = "需要先安慰共情"

    last_answer_type = "未知"
    if history:
        last_assistant = ""
        for item in reversed(history):
            if str(item.get("role", "")) == "assistant":
                last_assistant = str(item.get("content", "") or "")
                break
        last_answer_type = agent._infer_answer_type(last_assistant)

    latest_norm = agent.knowledge_service.normalize_user_text(latest_user_text)
    reply_goal = "自然承接并回答当前问题"
    avoid_repeat = "无"
    if empathy_need != "无":
        reply_goal = "先简短安慰共情，再给可行方案"
        avoid_repeat = "不要一上来就直接索要联系方式"
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
    if visit_status == "不方便到店":
        current_stage = "远程定制引导"
    elif agent._looks_like_appointment_query(latest_norm):
        current_stage = "预约引导"
    elif store_confirmed != "未知" and visit_status == "可以到店":
        current_stage = "门店已确认，推进预约"
    elif store_confirmed != "未知":
        current_stage = "门店已确认"
    elif city_confirmed != "未知":
        current_stage = "城市已确认，待确认门店"

    if last_answer_type == "store_address" and "地址" not in latest_norm and store_confirmed != "未知":
        avoid_repeat = "上一轮已回答地址，本轮优先推进下一步"
        if current_stage == "门店已确认":
            current_stage = "门店已确认，等待推进"
    if agent._looks_like_appointment_query(latest_norm) and last_answer_type == "appointment":
        reply_goal = "直接说明预约操作或具体下一步，不要重复预约定义"
        avoid_repeat = "不要重复“我们是预约制的呢”"

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
