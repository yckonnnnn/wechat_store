"""
意图识别增强模块

多层意图识别：状态确认 → 上下文追问 → 关键词匹配
"""

from typing import Any, Dict, List, Optional


class IntentDetector:
    """增强意图识别器"""

    # 状态确认关键词
    STATUS_CONFIRM_KEYWORDS = {
        "address": ("地址发了吗", "地址发过吗", "地址有吗", "地址收到了吗", "看到地址吗", "发了吗", "发过吗", "收到了", "看到吗", "发我了吗"),
        "contact": ("微信有吗", "电话有吗", "联系方式有吗", "有微信吗", "有电话吗", "有联系方式吗"),
        "price": ("价格说了吗", "多少钱说了吗", "说过价格", "价格说了"),
    }

    # 追问承接关键词
    FOLLOWUP_KEYWORDS = ("那这", "那家", "这家", "这个", "那怎么", "那家店", "这家店")

    # 预约意图关键词
    APPOINTMENT_KEYWORDS = ("预约", "约一下", "约时间", "排期", "时间安排", "什么时候来", "怎么约", "预约制", "需要预约", "要预约")

    # 邮寄查询关键词
    SHIPPING_KEYWORDS = ("快递", "邮寄", "寄过去", "包邮", "物流", "到家", "可以快递", "能邮寄")

    # 地址意图关键词（保留原有逻辑）
    ADDRESS_KEYWORDS = ("地址", "在哪", "位置", "门店", "店在哪", "怎么去", "路线", "定位")

    # 联系方式意图关键词
    CONTACT_KEYWORDS = (
        "微信", "联系方式", "电话", "手机号", "QQ", "怎么加", "如何联系",
        "怎么联系", "联系", "联系你", "联系你们",
        "留个", "加你", "加好友", "专属客服"
    )

    def detect(
        self,
        text: str,
        conversation_history: List[Dict[str, str]],
        state: Dict[str, Any],
    ) -> str:
        """
        多层意图识别

        Args:
            text: 用户消息
            conversation_history: 对话历史
            state: 统一状态

        Returns:
            意图字符串
        """
        # 1. 检查是否是状态确认
        intent = self._detect_status_confirm(text)
        if intent:
            return intent

        # 2. 检查是否是预约意图
        if self._is_appointment_intent(text):
            return "appointment"

        # 3. 检查是否是邮寄查询
        if self._is_shipping_query(text):
            return "shipping_query"

        # 4. 原有逻辑（关键词匹配）
        keyword_intent = self._detect_by_keywords(text)
        if keyword_intent != "general":
            return keyword_intent

        # 5. 最后再识别“延续同一家店的追问”，避免抢走明确问题类型
        if self._is_followup(text, conversation_history, state):
            return "followup"

        return "general"

    def _detect_status_confirm(self, text: str) -> Optional[str]:
        """检测是否是状态确认"""
        normalized = str(text or "").strip()
        if not normalized:
            return None

        explicit_resend_texts = {
            "地址发我",
            "把地址发我",
            "地址发我下",
            "地址发我一下",
            "再发一下地址",
            "重新发下地址",
            "重发下地址",
            "给我发地址",
        }
        resend_address_tokens = ("再发", "重新发", "重发", "给我发")
        if "地址" in normalized and (
            normalized in explicit_resend_texts
            or any(token in normalized for token in resend_address_tokens)
        ):
            return "address"

        # 先检查地址确认（因为"地址"这个词比较具体）
        if "地址" in normalized:
            for intent_type, keywords in self.STATUS_CONFIRM_KEYWORDS.items():
                if intent_type == "address":
                    if any(k in normalized for k in keywords):
                        return f"status_confirm_{intent_type}"
            return "address"  # 有"地址"但不是确认，返回 address 意图

        # 检查价格确认
        for intent_type, keywords in self.STATUS_CONFIRM_KEYWORDS.items():
            if intent_type == "price":
                if any(k in normalized for k in keywords):
                    return f"status_confirm_{intent_type}"

        # 检查联系方式确认
        for intent_type, keywords in self.STATUS_CONFIRM_KEYWORDS.items():
            if intent_type == "contact":
                if any(k in normalized for k in keywords):
                    return f"status_confirm_{intent_type}"

        return None

    def _is_followup(
        self,
        text: str,
        conversation_history: List[Dict[str, str]],
        state: Dict[str, Any],
    ) -> bool:
        """检测是否是追问承接"""
        # 有已确认的门店，且用户提到"这/那"
        if state.get("last_target_store") and state.get("last_target_store") != "unknown":
            if any(k in text for k in self.FOLLOWUP_KEYWORDS):
                return True

        # 上一轮是地址回复，这一轮是简短承接
        if conversation_history:
            last_turn = conversation_history[-1]
            if last_turn.get("role") == "assistant":
                last_content = last_turn.get("content", "")
                if "地址" in last_content or "门店" in last_content or "位置" in last_content:
                    if len(text) <= 15 and any(k in text for k in self.FOLLOWUP_KEYWORDS):
                        return True
        return False

    def _is_appointment_intent(self, text: str) -> bool:
        """检测是否是预约意图"""
        normalized = str(text or "").strip()
        if not normalized:
            return False
        return any(k in normalized for k in self.APPOINTMENT_KEYWORDS)

    def _is_shipping_query(self, text: str) -> bool:
        """检测是否是邮寄查询"""
        normalized = str(text or "").strip()
        if not normalized:
            return False
        return any(k in normalized for k in self.SHIPPING_KEYWORDS)

    def _detect_by_keywords(self, text: str) -> str:
        """原有逻辑：关键词匹配"""
        # 地址意图
        if any(k in text for k in self.ADDRESS_KEYWORDS):
            return "address"

        # 联系方式意图
        if any(k in text for k in self.CONTACT_KEYWORDS):
            return "contact"

        # 购买意图
        if any(k in text for k in ("买", "购买", "定制", "价格", "多少钱", "费用")):
            return "purchase"

        return "general"

    def get_status_confirm_type(self, intent: str) -> Optional[str]:
        """从状态确认意图中提取类型"""
        if intent.startswith("status_confirm_"):
            return intent.replace("status_confirm_", "")
        return None
