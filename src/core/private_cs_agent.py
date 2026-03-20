"""
私人客服 Agent
统一负责：强规则决策、知识库命中、LLM规则外补全、媒体决策、记忆更新。
"""

from __future__ import annotations

import hashlib
import copy
import json
import random
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..data.memory_store import MemoryStore
from ..services.knowledge_service import KnowledgeService
from ..services.llm_service import LLMService
from ..utils.constants import BRAND_KNOWLEDGE_FILE


CONTACT_INTENT_KEYWORDS = (
    "微信",
    "微信号",
    "联系方式",
    "联系方法",
    "联系信息",
    "联系电话",
    "电话",
    "手机号",
    "qq",
    "QQ",
    "二维码",
    "外链",
    "邮箱",
    "怎么加",
    "如何加",
    "加你",
    "加你们",
    "怎么添加",
    "如何添加",
    "怎么加微信",
    "如何加微信",
    "怎么关注",
    "如何关注",
    "关注客服",
    "联系客服",
    "怎么联系",
    "如何联系",
)

CONTACT_COMPLIANCE_BLOCK_KEYWORDS = (
    "微信",
    "微信号",
    "联系电话",
    "电话",
    "手机号",
    "qq",
    "QQ",
    "二维码",
    "外链",
    "邮箱",
)

NEG_SHANGHAI_HINT_KEYWORDS = (
    "不在上海",
    "不是上海",
    "不去上海",
)

SHIPPING_BLOCK_KEYWORDS = (
    "包邮",
    "快递",
    "邮寄",
    "到家",
)
SHIPPING_BLOCK_REPLACEMENT = "姐姐我们是到店定制哦"
ADDRESS_UNSUPPORTED_FALLBACK = "姐姐，门店位置您可以看图里圈圈的位置哦，需要的话我也可以继续帮您安排"
MATERIAL_LIBRARY_VIDEO_SENTINEL = "__material_library_video__"
ADDRESS_FACT_FALLBACK = "姐姐，门店位置您可以看图里圈圈的位置哦，我这边也可以继续帮您安排"
ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK = "您发个☎️，我来加您好友，具体给您介绍怎么走，位置在哪里"
PRICE_FACT_FALLBACK = "姐姐，具体的价格，设计，您可以留个☎️，我来添加您，专门给您详细介绍"
PRICE_GUARDRAIL_SAFE_REPLY = "姐姐，我们的价格有3000、4000、5000、6000不同档位，具体要根据材质、款式、头围、脸型和需求方案来定。"
CONTACT_FACT_FALLBACK = "姐姐，您留个☎️，我来主动跟您介绍"
PHONE_LEAK_BLOCK_FALLBACK = "姐姐，您提供电话，我来联系您，可以给您具体的介绍假发价格，款式，地址位置，坐车导航路线，以及预约事项。❤️"
REMOTE_SUPPORT_FACT_FALLBACK = "姐姐，外地也支持远程定制，不过精准度会比到店稍低一些哦。❤️"
EMPATHY_REMOTE_SUPPORT_FALLBACK = "姐姐那您先注意休息，身体要紧，不方便来上海的话我们也可以先远程帮您看看。❤️"
USER_PHONE_SUBMITTED_REPLY = "收到啦姐姐，我稍后加您好友，具体跟你详细介绍❤️"
MA_TEACHER_ROLE_FALLBACK = "姐姐，马老师是做短视频拍摄的，暂时不负责做头发、剪头和假发处理哦。🥰"
MA_TEACHER_DIRECT_QUERY_FALLBACK = "姐姐，马老师是做短视频拍摄的，暂时无法安排🥰"
IMAGE_MEDIA_REPLY_POOL = (
    "姐姐，图片上的这款发型价位大概在3000～6000元不等，具体呢需要根据头围进行定制，所以价格会有不同❤️",
    "姐姐，图片里这款一般是在3000～6000元这个区间哦，具体还是要结合您的头围和定制需求来看❤️",
    "姐姐，您发的图片这款大概是3000～6000元不等，具体价格要按头围和定制方案来定哦❤️",
    "姐姐，图片上的这款发型通常在3000～6000元之间，具体会根据头围和想做的效果有所不同❤️",
    "姐姐，图片里这一款大概是在3000～6000元不等，具体还要根据头围和定制细节来定呢❤️",
)
VIDEO_MEDIA_REPLY_POOL = (
    "姐姐，视频上的这款发型价位大概在3000～6000元不等，具体呢需要根据头围进行定制，所以价格会有不同❤️",
    "姐姐，视频里这款一般是在3000～6000元这个区间哦，具体还是要结合您的头围和定制需求来看❤️",
    "姐姐，您发的视频这款大概是3000～6000元不等，具体价格要按头围和定制方案来定哦❤️",
    "姐姐，视频上的这款发型通常在3000～6000元之间，具体会根据头围和想做的效果有所不同❤️",
    "姐姐，视频里这一款大概是在3000～6000元不等，具体还要根据头围和定制细节来定呢❤️",
)
EMOJI_MEDIA_REPLY_POOL = (
    "姐姐，关于假发的问题，您可以随时问我🌹",
    "姐姐，假发这块您有任何想了解的都可以直接问我呀❤️",
    "姐姐，您要是想了解假发的价格、款式或者到店问题，都可以随时问我哦🌷",
    "姐姐，关于假发这边您尽管问我，我一直都在呢💐",
    "姐姐，假发有什么想咨询的，您直接跟我说就可以啦🥰",
)
SERVICE_HOURS_PRIORITY_KEYWORDS = (
    "服务时间",
    "营业时间",
    "上班时间",
    "上班几点",
    "几点营业",
    "几点上班",
    "营业到几点",
    "几点下班",
    "开门时间",
    "关门时间",
)
ADDRESS_UNSUPPORTED_QUERY_KEYWORDS = (
    "怎么去",
    "怎么走",
    "怎么过去",
    "如何去",
    "如何过去",
    "坐什么车",
    "怎么坐车",
    "坐几号线",
    "哪一站",
    "哪个站",
    "哪个出口",
    "几号出口",
    "定位",
    "导航",
    "路线",
    "停车",
    "怎么到",
    "几楼",
    "楼层",
)
ADDRESS_FACT_QUERY_KEYWORDS = (
    "地址",
    "具体地址",
    "位置",
    "具体位置",
    "多少号",
    "几号",
    "门店",
    "店铺",
    "在哪",
    "在哪里",
    "哪儿",
    "几楼",
    "楼层",
    "导航",
    "路线",
    "怎么去",
    "怎么走",
    "坐什么车",
    "哪一站",
    "哪个出口",
)
ADDRESS_FOLLOWUP_EXPLICIT_KEYWORDS = (
    "地址",
    "具体地址",
    "位置",
    "具体位置",
    "多少号",
    "几号",
    "门店地址",
    "店铺地址",
    "在哪",
    "在哪里",
    "哪儿",
    "位置在哪",
    "怎么走",
    "怎么去",
    "怎么过去",
    "如何去",
    "如何过去",
    "导航",
    "路线",
    "怎么导航",
    "导航怎么导",
    "坐车",
    "坐什么车",
    "地铁",
    "几号线",
    "哪一站",
    "哪个站",
    "哪个出口",
    "几号出口",
    "开车怎么去",
    "打车到哪里",
    "几楼",
    "楼层",
    "在哪层",
    "哪栋",
    "哪一栋",
    "哪个门",
    "从哪进",
    "停车",
    "停车方便吗",
)
ADDRESS_FOLLOWUP_PRIORITY_KEYWORDS = (
    "多少号",
    "几号",
    "具体位置",
    "具体地址",
    "哪一栋",
    "哪栋",
    "几楼",
    "在哪一栋",
    "哪个门",
    "从哪进",
    "哪个出口",
    "几号出口",
)
ADDRESS_FOLLOWUP_RESIDUAL_KEYWORDS = (
    "北在哪",
    "店在哪",
    "具体呢",
    "哪里呢",
    "位置呢",
)
SHANGHAI_ROUTE_HELP_KEYWORDS = (
    "外地来的",
    "外地来",
    "不熟悉",
    "不认识路",
    "不熟路",
    "不熟悉上海",
    "不知道哪个区",
    "不太清楚",
    "第一次来上海",
)
ADDRESS_FOLLOWUP_BLOCK_KEYWORDS = (
    "多少钱",
    "价格",
    "价位",
    "多少",
    "报价",
    "费用",
    "收费",
    "预算",
    "贵",
    "便宜",
    "预约",
    "怎么预约",
    "需要预约",
    "能约吗",
    "材质",
    "真人发",
    "短发",
    "长发",
    "这款",
    "第二款",
    "第三款",
    "自然吗",
    "热吗",
    "闷吗",
    "好打理吗",
    "会掉吗",
    "清洗",
    "保养",
    "护理",
    "售后",
)
PRICE_FACT_QUERY_KEYWORDS = (
    "价格",
    "多少钱",
    "价位",
    "报价",
    "收费",
    "预算",
    "贵",
    "便宜",
)
PRICE_FACT_SPECIFIC_KEYWORDS = (
    "具体价格",
    "具体多少钱",
    "设计",
    "设计费",
    "费用",
    "收费",
    "报价",
    "方案",
    "定制费",
)
ADDRESS_PRIORITY_OVER_PRICE_KEYWORDS = (
    "多少号",
    "几号",
)
PRICE_LOW_RISK_PHRASES = (
    "几百",
    "上千",
    "一千",
    "两千",
    "2000",
    "2000多",
    "不到3000",
    "两三千",
    "几千左右",
    "几百到上千",
)
INVALID_PRICE_CHANNEL_KEYWORDS = (
    "小红书",
    "抖音",
    "淘宝",
    "拼多多",
    "京东",
    "下单",
    "拍下",
    "购物车",
    "搜索购买",
    "链接购买",
    "店铺搜",
    "线上购买",
)
ADDRESS_REPLY_RISK_KEYWORDS = (
    "区",
    "路",
    "号",
    "大厦",
    "广场",
    "soho",
    "楼",
    "层",
)
PRICE_REPLY_RISK_KEYWORDS = (
    "价格",
    "价位",
    "元",
    "块",
    "w",
    "万",
)
PRICE_PRIORITY_KEYWORDS = (
    "多少钱",
    "价格",
    "价位",
    "多少",
    "报价",
    "费用",
    "收费",
    "预算",
    "贵",
    "便宜",
    "什么价",
    "什么价格",
    "大概多少",
    "大概多少钱",
    "多少米",
)
PRICE_FACT_FOLLOWUP_APPOINTMENT = "我们这边是预约制的，您定好时间我可以帮您安排。"
PRICE_FACT_FOLLOWUP_STORE_DISTRIBUTION = "门店目前是北京朝阳1家，上海5家（静安、人广、虹口、五角场、徐汇）。"
PRICE_FACT_FOLLOWUP_SHANGHAI_DISTRICT = "姐姐，您在上海具体位置告诉我，我给您推荐～"
PRICE_FACT_FOLLOWUP_SAME_DAY_DURATION = "如果是到店定制，当天一般做不完哦，我们是私人定制，需要时间制作。"
PRICE_FACT_FOLLOWUP_GENERAL_DURATION = "正常定制一般需要7到10天，门店周边城市通常2到3天能安排，外地也可以加急。"
PRICE_FACT_FOLLOWUP_PROCESS = "我们是一对一定制，通常会先看脸型头围，再定材质、长度和款式。"
PRICE_FACT_FOLLOWUP_PRICING_BASIS = "具体价格主要看材质、款式、头围和想要的效果。"
STORE_CONVENIENCE_QUERY_KEYWORDS = (
    "哪个店",
    "哪家店",
    "哪个门店",
    "哪家门店",
    "去哪个店",
    "去哪个门店",
    "去哪家店",
    "去哪家门店",
    "哪个近",
    "哪家近",
    "哪个门店近",
    "哪家门店近",
    "比较方便",
    "更方便",
    "方便一些",
    "哪里方便",
    "哪边方便",
)
MA_TEACHER_INVALID_SERVICE_KEYWORDS = (
    "做头发",
    "做假发",
    "剪头",
    "剪发",
    "烫发",
    "修剪",
    "造型",
    "帮您弄",
    "给您弄",
    "帮您做",
)
DEFAULT_REPLY_EMOJI = "🌹"
# 适合中老年客户的emoji表情池
REPLY_EMOJI_POOL = ["🌹", "💗", "😘", "🥰", "🌷", "❤️", "😊", "💕", "🌸", "💐", "🌺", "😄"]
ENTERPRISE_GUARD_DOC_PATH = Path("config") / "llm_enterprise_knowledge_guard_v1.md"
CONTACT_IMAGE_MAX_SEND = 3
CONTACT_TRIGGER_KEYWORDS = (
    "邮寄",
    "寄快递",
    "快递",
    "可以寄吗",
    "能寄吗",
    "寄",
    "预约",
    "怎么预约",
    "如何预约",
    "需要预约吗",
    "要预约吗",
)
CONTACT_TRIGGER_TAGS = (
    "邮寄",
    "快递",
    "预约",
)
CONTACT_TRIGGER_INTENTS = ("appointment",)
APPOINTMENT_PRIORITY_KEYWORDS = (
    "预约",
    "怎么预约",
    "如何预约",
    "需要预约",
    "要预约",
)
PROCESS_PRIORITY_KEYWORDS = (
    "来一次",
    "一次可以",
    "一次能",
    "一次行吗",
    "1次",
    "一趟",
    "跑一趟",
    "来几次",
    "几次",
)
BUSINESS_BLOCK_PRIORITY_KEYWORDS = (
    "加盟",
    "拿货",
    "代理",
    "进货",
    "工厂",
    "供应商",
    "培训",
    "学习",
)
LIFESPAN_PRIORITY_KEYWORDS = (
    "能用多久",
    "用多久",
    "多久换",
    "使用寿命",
    "寿命",
    "能戴多久",
    "可以戴多久",
    "耐用吗",
)
REQUIRED_MEDIA_TYPES = ("address_image", "contact_image", "delayed_video")
REPLY_MODE_LEGACY = "legacy"
REPLY_MODE_LLM_DIRECT = "llm_direct"


DEFAULT_REPLY_TEMPLATES: Dict[str, Any] = {
    "ask_region_r1": "姐姐，您在什么城市/区域呀？方便告诉我吗？我可以帮您针对性推荐门店，我们目前北京朝阳1家、上海5家（静安、人广、虹口、五角场、徐汇）🌹",
    "ask_region_r2": "姐姐，我再帮您确认一下，您现在在哪个城市或区域呀？我按距离给您匹配最近门店～🌹",
    "ask_region_choice": "姐姐您在上海吗？不确定也没关系，告诉我个地标我也能帮您匹配～🌹",
    "ask_region_r1_reset": "姐姐我再帮您快速确认下，您在什么城市或区域呀？我马上按距离给您匹配最近门店～🌹",
    "ask_sh_district_r1": "姐姐您在上海哪个区呀？我帮您匹配最近门店～🌹",
    "ask_sh_district_r2": "姐姐再确认下，您在上海哪个区或附近地标呢？我马上给您对门店～🌹",
    "ask_sh_district_choice": "姐姐您方便告诉我个位置？不确定也没关系，告诉我个地标我也能帮您匹配～🌹",
    "ask_sh_district_r1_reset": "姐姐我再确认下，您在上海哪个区呀？我这边马上帮您匹配最近门店～🌹",
    "ask_sh_arrival_point": "姐姐，您到上海后一般在哪个站下车呀？像虹桥站、上海站、浦东机场这些都可以告诉我，我帮您针对性推荐门店🌹",
    "ask_sh_route_clarify": "姐姐，您说的是上海哪条路附近呀？我帮您匹配最近门店🌹",
    "ask_ambiguous_short_fragment": "姐姐，您是想问门店地址吗？您告诉我大概在哪个区域，我帮您匹配最近门店🌹",
    "store_recommend": "姐姐，推荐您去{store_name}，我给您发一张位置图，您跟着图中圈圈的位置会更直观，如果找不到可以留个☎️，我来具体给你发路线～",
    "non_coverage_contact": "姐姐，{region}暂时没有我们的门店，目前假发是需要根据头围和脸型进行私人定制的，您可以看看下面图中画圈圈的地方，会有专门的老师跟您远程鉴定～💗",
    "contact_intro": "姐姐可以看下红框框的内容，您按图添加后我这边一对一继续跟进您呀😊",
    "purchase_contact_intro": "姐姐可以看看图中画框框的地方，会有专门的老师给您介绍～❤️",
    "purchase_contact_remind_only": "姐姐，请注意一下上面图中的圈圈位置哦，可以详细给您介绍怎么买～💗",
    "purchase_contact_remote_remind_only": "姐姐，您可以往上看看图中画圈的地方，我让老师一对一跟您远程定制❤️",
    "strong_intent_after_both_first": "姐姐，您可以看上面的画圈圈地方，我让老师跟您预约～💗",
    "contact_followup_1": "姐姐您看下我刚发的联系方式图，按图添加后跟我说一声，我马上接着帮您安排😊",
    "contact_followup_2": "姐姐刚刚那张联系方式图您点开就能看到，添加后回我一句，我立刻继续帮您跟进😊",
    "llm_fallback": "姐姐抱歉，系统现在有点忙，您稍后再发我马上跟进您哦🌹",
    "general_empty": "姐姐我在呢，您告诉我最关心的是价格、佩戴体验还是门店位置呀🌹",
    "repeat_pool": [
        "姐姐我在，您可以继续说下最关心的问题呀🌹",
        "姐姐收到，我帮您一步步梳理最合适的方案呀🌹",
        "姐姐明白，我先把关键点给您讲清楚呀🌹",
    ],
}

ADDRESS_IMAGE_COOLDOWN_HOURS = 24


@dataclass
class AgentDecision:
    reply_text: str
    intent: str
    route_reason: str
    reply_goal: str
    media_plan: str
    media_items: List[Dict[str, Any]] = field(default_factory=list)
    reply_source: str = "rule"
    rule_id: str = ""
    rule_applied: bool = False
    llm_model: str = ""
    llm_fallback_reason: str = ""
    geo_context_source: str = ""
    media_skip_reason: str = ""
    both_images_sent_state: bool = False
    kb_match_score: float = 0.0
    kb_match_question: str = ""
    kb_match_mode: str = ""
    kb_item_id: str = ""
    kb_variant_total: int = 0
    kb_variant_selected_index: int = -1
    kb_variant_fallback_llm: bool = False
    kb_confident: bool = False
    kb_blocked_by_polite_guard: bool = False
    kb_polite_guard_reason: str = ""
    is_first_turn_global: bool = False
    first_turn_media_guard_applied: bool = False
    first_turn_image_items: List[Dict[str, Any]] = field(default_factory=list)
    first_turn_video_items: List[Dict[str, Any]] = field(default_factory=list)
    first_turn_text_required: bool = False
    first_turn_retry_policy: Dict[str, Any] = field(default_factory=dict)
    kb_repeat_rewritten: bool = False
    purchase_both_first_hint_sent: bool = False
    video_trigger_user_count: int = 0
    force_contact_image: bool = False
    kb_contact_trigger_type: str = ""
    reply_mode: str = REPLY_MODE_LEGACY
    standard_reply_hit: bool = False
    standard_reply_question: str = ""
    standard_reply_confidence: str = ""
    standard_reply_intent: str = ""
    brand_knowledge_used: bool = False


@dataclass
class MediaJudgeDecision:
    send_contact_image: bool = False
    send_address_image: bool = False
    send_delayed_video: bool = False
    reason: str = ""
    reminder_only: bool = False
    skip_reason: str = ""
    media_items: List[Dict[str, Any]] = field(default_factory=list)


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


class CustomerServiceAgent:
    """客服 Agent 主决策器（规则优先，LLM仅规则外回复）。"""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        llm_service: LLMService,
        memory_store: MemoryStore,
        images_dir: Path,
        image_categories_path: Path,
        system_prompt_doc_path: Path,
        playbook_doc_path: Path,
        brand_knowledge_doc_path: Optional[Path] = None,
        reply_templates_path: Optional[Path] = None,
        media_whitelist_path: Optional[Path] = None,
        conversation_log_dir: Optional[Path] = None,
    ):
        self.knowledge_service = knowledge_service
        self.llm_service = llm_service
        self.memory_store = memory_store

        self.images_dir = images_dir
        self.image_categories_path = image_categories_path
        self.system_prompt_doc_path = system_prompt_doc_path
        self.playbook_doc_path = playbook_doc_path
        self.brand_knowledge_doc_path = brand_knowledge_doc_path or BRAND_KNOWLEDGE_FILE
        self.enterprise_guard_doc_path = ENTERPRISE_GUARD_DOC_PATH
        self.reply_templates_path = reply_templates_path or (Path("config") / "reply_templates.json")
        self.media_whitelist_path = media_whitelist_path or (Path("config") / "media_whitelist.json")
        self.conversation_log_dir = conversation_log_dir or (Path("data") / "conversations")

        self.use_knowledge_first = True
        self.knowledge_threshold = 0.6
        self.memory_ttl_days = 30
        self.first_reply_video_enabled = False
        self.reply_mode = REPLY_MODE_LLM_DIRECT

        self._address_index: Dict[str, List[str]] = {
            "beijing_chaoyang": [],
            "sh_xuhui": [],
            "sh_jingan": [],
            "sh_hongkou": [],
            "sh_wujiaochang": [],
            "sh_renmin": [],
        }
        self._contact_images: List[str] = []
        self._video_medias: List[str] = []

        self._system_prompt_doc_text = ""
        self._playbook_doc_text = ""
        self._enterprise_guard_doc_text = ""
        self._brand_knowledge_doc_text = ""
        self._reply_templates: Dict[str, Any] = dict(DEFAULT_REPLY_TEMPLATES)
        self._media_whitelist_sessions: set[str] = set()
        self._current_prompt_conversation_history: List[Dict[str, str]] = []

        self._dedupe_reply_pool = list(DEFAULT_REPLY_TEMPLATES.get("repeat_pool", []))

        self.reload_prompt_docs()
        self.reload_media_library()
        self.reload_rule_configs()

    def reload_prompt_docs(self) -> bool:
        """重载 system prompt 与 playbook 文档"""
        self._system_prompt_doc_text = self._read_text(self.system_prompt_doc_path)
        self._playbook_doc_text = self._read_text(self.playbook_doc_path)
        self._enterprise_guard_doc_text = self._read_text(self.enterprise_guard_doc_path)
        self._brand_knowledge_doc_text = self._read_text(self.brand_knowledge_doc_path)
        return bool(self._system_prompt_doc_text)

    def reload_media_library(self) -> None:
        """重建地址/联系方式/视频素材索引"""
        for key in self._address_index:
            self._address_index[key] = []
        self._contact_images = []
        self._video_medias = []

        if not self.image_categories_path.exists():
            return

        try:
            data = json.loads(self.image_categories_path.read_text(encoding="utf-8"))
        except Exception:
            return

        images_data = data.get("images", {}) or {}
        store_targets = data.get("store_targets", {}) or {}

        for raw_name in images_data.get("联系方式", []):
            filename = Path(raw_name).name
            path = self.images_dir / filename
            if path.exists():
                self._contact_images.append(str(path.resolve()))

        for raw_name in images_data.get("视频素材", []):
            filename = Path(raw_name).name
            path = self.images_dir / filename
            if path.exists():
                self._video_medias.append(str(path.resolve()))

        # 视频素材兜底：配置文件名变更时按目录模糊匹配，再回退到任意视频文件。
        if not self._video_medias and self.images_dir.exists():
            all_files = [p for p in self.images_dir.iterdir() if p.is_file()]
            preferred = [
                p for p in all_files
                if p.suffix.lower() in (".mp4", ".mov", ".m4v") and ("预约" in p.name or "视频" in p.name)
            ]
            if not preferred:
                preferred = [p for p in all_files if p.suffix.lower() in (".mp4", ".mov", ".m4v")]
            self._video_medias = [str(p.resolve()) for p in preferred if p.exists()]

        if self._video_medias:
            # 去重，保留顺序
            self._video_medias = list(dict.fromkeys(self._video_medias))

        for raw_name in images_data.get("店铺地址", []):
            filename = Path(raw_name).name
            path = self.images_dir / filename
            if not path.exists():
                continue

            full = str(path.resolve())
            target_store = str(store_targets.get(filename, "") or "").strip()
            if target_store in self._address_index:
                self._address_index[target_store].append(full)
                continue

            inferred_store = self._infer_store_from_name(filename)
            if inferred_store in self._address_index:
                self._address_index[inferred_store].append(full)
            else:
                self._address_index["sh_renmin"].append(full)

    def reload_rule_configs(self) -> None:
        """重载规则模板与媒体白名单。"""
        self.knowledge_service.reload_address_config()
        self._reply_templates = dict(DEFAULT_REPLY_TEMPLATES)
        if self.reply_templates_path.exists():
            try:
                loaded = json.loads(self.reply_templates_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._reply_templates.update(loaded)
            except Exception:
                pass

        repeat_pool = self._reply_templates.get("repeat_pool")
        if isinstance(repeat_pool, list):
            pool = [str(x).strip() for x in repeat_pool if str(x).strip()]
            self._dedupe_reply_pool = pool or list(DEFAULT_REPLY_TEMPLATES.get("repeat_pool", []))
        else:
            self._dedupe_reply_pool = list(DEFAULT_REPLY_TEMPLATES.get("repeat_pool", []))

        self._media_whitelist_sessions = set()
        if self.media_whitelist_path.exists():
            try:
                loaded = json.loads(self.media_whitelist_path.read_text(encoding="utf-8"))
                session_ids = loaded.get("session_ids", []) if isinstance(loaded, dict) else []
                if isinstance(session_ids, list):
                    self._media_whitelist_sessions = {str(x).strip() for x in session_ids if str(x).strip()}
            except Exception:
                self._media_whitelist_sessions = set()

    def decide(
        self,
        session_id: str,
        user_name: str,
        latest_user_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        first_turn_global_override: Optional[bool] = None,
    ) -> AgentDecision:
        """主决策入口"""
        self.memory_store.prune_expired(ttl_days=self.memory_ttl_days)

        user_hash = self._hash_user(user_name or session_id)
        session_state = self.memory_store.get_session_state(session_id, user_hash=user_hash)
        user_state = self.memory_store.get_user_state(user_hash)
        if first_turn_global_override is None:
            is_first_turn_global = self.is_user_first_turn_global(user_id_hash=user_hash)
        else:
            is_first_turn_global = bool(first_turn_global_override)
        self._sync_media_state_from_conversation_log(
            session_id=session_id,
            user_hash=user_hash,
            session_state=session_state,
        )

        raw_text = (latest_user_text or "").strip()
        text = self.knowledge_service.normalize_user_text(raw_text).strip()
        if self._looks_like_phone_submission(text):
            return AgentDecision(
                reply_text=USER_PHONE_SUBMITTED_REPLY,
                intent="contact",
                route_reason="user_phone_submitted",
                reply_goal="承接联系方式",
                media_plan="none",
                reply_source="rule",
                rule_id="CONTACT_PHONE_SUBMITTED",
                rule_applied=True,
                reply_mode=self.reply_mode,
            )
        route = self.knowledge_service.resolve_store_recommendation(text)
        if self._should_recover_to_shanghai_arrival_help(text, session_state):
            route = {
                "city": "shanghai",
                "target_store": "unknown",
                "reason": "shanghai_need_arrival_point",
                "route_type": "need_district",
                "store_address": None,
                "detected_region": "上海",
            }
        if self._should_force_out_of_coverage_from_geo_followup(text=text, session_state=session_state):
            route = {
                "city": "unknown",
                "target_store": "unknown",
                "reason": "out_of_coverage",
                "route_type": "non_coverage",
                "store_address": None,
                "detected_region": "外地",
            }
        intent = self._detect_intent(text)
        decision: Optional[AgentDecision] = None
        if self.reply_mode == REPLY_MODE_LLM_DIRECT:
            decision = self._decide_llm_reply(
                latest_user_text=raw_text,
                intent=intent,
                route_reason=str(route.get("reason", "unknown") or "unknown"),
                conversation_history=conversation_history or [],
                session_state=session_state,
                allow_address_guardrails=False,
            )
        price_priority_decision = None if self.reply_mode == REPLY_MODE_LLM_DIRECT else self._decide_price_priority_reply(
            latest_user_text=text,
            route=route,
            conversation_history=conversation_history or [],
            session_state=session_state,
            user_state=user_state,
            user_id_hash=user_hash,
        )
        address_text_after_image_decision = None if self.reply_mode == REPLY_MODE_LLM_DIRECT else self._build_address_text_after_image_decision(
            latest_user_text=text,
            route=route,
            intent=intent,
            session_state=session_state,
        )
        address_contact_after_text_decision = None if self.reply_mode == REPLY_MODE_LLM_DIRECT else self._build_address_contact_after_text_decision(
            latest_user_text=text,
            route=route,
            intent=intent,
            session_state=session_state,
        )
        appointment_kb_decision: Optional[AgentDecision] = None
        process_priority_decision: Optional[AgentDecision] = None
        business_block_priority_decision: Optional[AgentDecision] = None
        if price_priority_decision is None and self._looks_like_appointment_query(text):
            appointment_kb_decision = self._decide_appointment_priority_reply(
                latest_user_text=text,
                route=route,
                user_state=user_state,
                user_id_hash=user_hash,
            )
        if price_priority_decision is None and appointment_kb_decision is None:
            process_priority_decision = self._decide_process_priority_reply(
                latest_user_text=text,
                route=route,
                user_state=user_state,
                user_id_hash=user_hash,
            )
        if (
            price_priority_decision is None
            and appointment_kb_decision is None
            and process_priority_decision is None
        ):
            business_block_priority_decision = self._decide_business_block_priority_reply(
                latest_user_text=text,
                route=route,
                user_state=user_state,
                user_id_hash=user_hash,
            )

        if decision is not None:
            pass
        elif price_priority_decision is not None:
            decision = price_priority_decision
        elif business_block_priority_decision is not None:
            decision = business_block_priority_decision
        elif process_priority_decision is not None:
            decision = process_priority_decision
        elif address_text_after_image_decision is not None:
            decision = address_text_after_image_decision
        elif address_contact_after_text_decision is not None:
            decision = address_contact_after_text_decision
        elif appointment_kb_decision and appointment_kb_decision.reply_source == "knowledge":
            decision = appointment_kb_decision
        elif self._should_apply_rule_decision(text=text, intent=intent, route=route, session_state=session_state):
            print(f"[DEBUG] 走规则决策: intent={intent}, route_reason={route.get('reason', 'unknown')}, target_store={route.get('target_store', 'unknown')}")
            decision = self._decide_rule_reply(
                text=text,
                intent=intent,
                route=route,
                session_state=session_state,
                conversation_history=conversation_history or [],
                user_state=user_state,
                is_first_turn_global=is_first_turn_global,
            )
        else:
            print(f"[DEBUG] 不走规则决策，走知识库或LLM: intent={intent}, route_reason={route.get('reason', 'unknown')}")
            decision = appointment_kb_decision or self._decide_general_reply(
                latest_user_text=text,
                intent=intent,
                route=route,
                conversation_history=conversation_history or [],
                session_state=session_state,
                user_state=user_state,
                user_id_hash=user_hash,
            )

        copy_lock_rule_ids = {
            "PURCHASE_CONTACT_FROM_KNOWN_GEO",
            "PURCHASE_REMOTE_CONTACT_IMAGE",
            "PURCHASE_REMOTE_CONTACT_REMIND_ONLY",
            "ADDR_OUT_OF_COVERAGE",
            "ADDR_STORE_RECOMMEND",
            "CONTACT_SEND_IMAGE",
        }
        should_rewrite = (
            decision.reply_source in ("llm", "fallback")
            and self.reply_mode != REPLY_MODE_LLM_DIRECT
            and decision.rule_id not in copy_lock_rule_ids
        )
        if should_rewrite:
            knowledge_reply_count = int(session_state.get("knowledge_reply_count", 0) or 0)
            rewritten_text, _ = self._rewrite_if_repeated(
                reply_text=decision.reply_text,
                latest_user_text=raw_text,
                conversation_history=conversation_history or [],
                user_state=user_state,
                user_id_hash=user_hash,
            )
            decision.reply_text = rewritten_text
            decision.kb_repeat_rewritten = False
        else:
            knowledge_reply_count = int(session_state.get("knowledge_reply_count", 0) or 0)

        decision.reply_mode = self.reply_mode
        decision.purchase_both_first_hint_sent = bool(
            session_state.get("purchase_both_first_hint_sent", False)
        )
        decision.is_first_turn_global = False if self.reply_mode == REPLY_MODE_LLM_DIRECT else bool(is_first_turn_global)
        both_images_sent = self._has_both_images_sent(session_state)
        decision.both_images_sent_state = both_images_sent
        decision.video_trigger_user_count = int(session_state.get("session_user_message_count_after_contact", 0) or 0)

        original_media_plan = decision.media_plan
        if self.reply_mode == REPLY_MODE_LLM_DIRECT:
            media_items, media_skip_reason = [], "reply_mode_llm_direct"
        else:
            media_items, media_skip_reason = self._plan_media_items(
                session_id=session_id,
                text=text,
                intent=decision.intent,
                route=route,
                route_reason=decision.route_reason,
                media_plan=original_media_plan,
                session_state=session_state,
                user_state=user_state,
                force_contact_image=bool(decision.force_contact_image),
            )
        decision.media_items = media_items
        decision.media_skip_reason = media_skip_reason
        decision.first_turn_media_guard_applied = False
        if self.reply_mode != REPLY_MODE_LLM_DIRECT:
            self._populate_first_turn_media_plan(
                session_id=session_id,
                user_name=user_name,
                decision=decision,
            )
        else:
            decision.first_turn_image_items = []
            decision.first_turn_video_items = []
            decision.first_turn_text_required = False
            decision.first_turn_retry_policy = {}
        if not decision.media_items:
            decision.media_plan = "none"

        now = datetime.now().isoformat()
        target_store = route.get("target_store", "unknown")
        detected_region = route.get("detected_region", "") or ""
        next_knowledge_reply_count = knowledge_reply_count + (1 if decision.reply_source == "knowledge" else 0)
        next_price_priority_reply_count = int(session_state.get("price_priority_reply_count", 0) or 0)
        if decision.rule_id in {"PRICE_PRIORITY", "PRICE_PRIORITY_FALLBACK", "PRICE_PRIORITY_PRIVATE_GUIDE"}:
            next_price_priority_reply_count += 1
        next_address_text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
        next_address_contact_reply_count_by_store = dict(session_state.get("address_contact_reply_count_by_store", {}) or {})
        if decision.rule_id == "ADDR_TEXT_AFTER_IMAGE":
            decision_store = str(route.get("target_store", "") or "")
            if not decision_store or decision_store == "unknown":
                decision_store = str(session_state.get("last_target_store", "") or "")
            if decision_store and decision_store != "unknown":
                next_address_text_reply_count_by_store[decision_store] = int(next_address_text_reply_count_by_store.get(decision_store, 0) or 0) + 1
        if decision.rule_id == "ADDR_CONTACT_AFTER_TEXT":
            decision_store = str(route.get("target_store", "") or "")
            if not decision_store or decision_store == "unknown":
                decision_store = str(session_state.get("last_target_store", "") or "")
            if decision_store and decision_store != "unknown":
                next_address_contact_reply_count_by_store[decision_store] = int(next_address_contact_reply_count_by_store.get(decision_store, 0) or 0) + 1
        self.memory_store.update_session_state(
            session_id,
            {
                "last_route_reason": decision.route_reason,
                "last_intent": decision.intent,
                "last_reply_goal": decision.reply_goal,
                "last_detected_region": detected_region or session_state.get("last_detected_region", ""),
                "last_target_store": target_store if target_store != "unknown" else session_state.get("last_target_store", ""),
                "last_geo_route_reason": route.get("reason", "unknown") if (target_store != "unknown" or detected_region) else session_state.get("last_geo_route_reason", "unknown"),
                "last_geo_updated_at": now if (target_store != "unknown" or detected_region) else session_state.get("last_geo_updated_at", ""),
                "knowledge_reply_count": next_knowledge_reply_count,
                "price_priority_reply_count": next_price_priority_reply_count,
                "address_text_reply_count_by_store": next_address_text_reply_count_by_store,
                "address_contact_reply_count_by_store": next_address_contact_reply_count_by_store,
                "address_info_shared": bool(
                    session_state.get("address_info_shared", False)
                    or self._reply_shares_address_info(decision.reply_text)
                ),
            },
            user_hash=user_hash,
        )
        self.memory_store.save()
        return decision

    def mark_reply_sent(
        self,
        session_id: str,
        user_name: str,
        reply_text: str,
        *,
        is_first_turn_global: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """文本发送成功后的状态推进；返回需要立即发送的视频媒体（若命中）"""
        if self.reply_mode == REPLY_MODE_LLM_DIRECT:
            user_hash = self._hash_user(user_name or session_id)
            user_state = self.memory_store.get_user_state(user_hash)
            normalized = self._normalize_for_dedupe(reply_text)
            recent_hashes = list(user_state.get("recent_reply_hashes", []) or [])
            if normalized:
                recent_hashes.append(normalized)
            if len(recent_hashes) > 40:
                recent_hashes = recent_hashes[-40:]
            user_state["recent_reply_hashes"] = recent_hashes
            self.memory_store.update_user_state(user_hash, user_state)
            self.memory_store.save()
            return None
        user_hash = self._hash_user(user_name or session_id)
        user_state = self.memory_store.get_user_state(user_hash)
        normalized = self._normalize_for_dedupe(reply_text)

        recent_hashes = list(user_state.get("recent_reply_hashes", []) or [])
        if normalized:
            recent_hashes.append(normalized)
        if len(recent_hashes) > 40:
            recent_hashes = recent_hashes[-40:]
        user_state["recent_reply_hashes"] = recent_hashes

        session_video = self.summarize_session_video_from_log(session_id=session_id)
        if session_video.get("contact_sent") and not session_video.get("contact_followup_video_sent"):
            user_messages_after_contact = int(session_video.get("user_message_count_after_contact", 0) or 0)
            if user_messages_after_contact >= 2:
                video_item = self._build_video_media_item(trigger_source="contact_followup")
                if video_item:
                    self.memory_store.update_user_state(user_hash, user_state)
                    self.memory_store.save()
                    return video_item

        self.memory_store.update_user_state(user_hash, user_state)
        self.memory_store.save()
        return None

    def build_post_text_media_queue(
        self,
        session_id: str,
        user_name: str,
        planned_media_items: List[Dict[str, Any]],
        extra_media_items: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        user_hash = self._hash_user(user_name or session_id)
        session_state = self.memory_store.get_session_state(session_id, user_hash=user_hash)
        pending_items = self._sanitize_pending_required_media(
            session_state.get("pending_required_media", []),
            latest_planned=planned_media_items,
        )
        queue: List[Dict[str, Any]] = []
        queue.extend(pending_items)

        for item in planned_media_items or []:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "") or "")
            if item_type == "address_image":
                queue = [x for x in queue if not (str(x.get("type", "")) == "address_image" and x.get("target_store") == item.get("target_store"))]
            elif item_type == "contact_image":
                queue = [x for x in queue if str(x.get("type", "")) != "contact_image"]
            queue.append(dict(item))

        for item in extra_media_items or []:
            if isinstance(item, dict):
                queue.append(dict(item))

        return queue

    def judge_post_reply_media(
        self,
        session_id: str,
        user_name: str,
        latest_user_text: str,
        reply_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        decision: Optional[AgentDecision] = None,
    ) -> MediaJudgeDecision:
        user_hash = self._hash_user(user_name or session_id)
        session_state = self.memory_store.get_session_state(session_id, user_hash=user_hash)
        normalized_text = self.knowledge_service.normalize_user_text(latest_user_text).strip()
        history = conversation_history or []
        route = self.knowledge_service.resolve_store_recommendation(normalized_text)
        intent = decision.intent if decision is not None else self._detect_intent(normalized_text)

        if self._looks_like_direct_contact_request(normalized_text):
            if self._is_contact_image_sent_for_current_geo(session_state):
                return MediaJudgeDecision(
                    send_contact_image=False,
                    reason="direct_contact_request",
                    reminder_only=True,
                    skip_reason="contact_image_already_sent",
                )
            media_items, skip_reason = self._plan_media_items(
                session_id=session_id,
                text=normalized_text,
                intent="contact",
                route=route,
                route_reason="direct_contact_request",
                media_plan="contact_image",
                session_state=session_state,
                user_state=self.memory_store.get_user_state(user_hash),
                force_contact_image=True,
            )
            return MediaJudgeDecision(
                send_contact_image=bool(media_items),
                reason="direct_contact_request",
                reminder_only=False,
                skip_reason=str(skip_reason or ""),
                media_items=media_items,
            )

        if self._should_trigger_precise_address_contact_image(
            latest_user_text=latest_user_text,
            normalized_text=normalized_text,
            reply_text=reply_text,
            intent=intent,
            route=route,
            session_state=session_state,
            conversation_history=history,
        ):
            if self._is_contact_image_sent_for_current_geo(session_state):
                return MediaJudgeDecision(
                    send_contact_image=False,
                    reason="precise_address_followup",
                    reminder_only=True,
                    skip_reason="contact_image_already_sent",
                )
            media_items, skip_reason = self._plan_media_items(
                session_id=session_id,
                text=normalized_text,
                intent="contact",
                route=route,
                route_reason="precise_address_followup",
                media_plan="contact_image",
                session_state=session_state,
                user_state=self.memory_store.get_user_state(user_hash),
                force_contact_image=True,
            )
            return MediaJudgeDecision(
                send_contact_image=bool(media_items),
                reason="precise_address_followup",
                reminder_only=False,
                skip_reason=str(skip_reason or ""),
                media_items=media_items,
            )

        return MediaJudgeDecision(skip_reason="no_media_rule_matched")

    def mark_media_sent(self, session_id: str, user_name: str, media_item: Dict[str, Any], success: bool) -> None:
        """媒体发送回执"""
        if not success or not media_item:
            return

        user_hash = self._hash_user(user_name or session_id)
        session_state = self.memory_store.get_session_state(session_id, user_hash=user_hash)
        user_state = self.memory_store.get_user_state(user_hash)
        now = datetime.now().isoformat()

        media_type = media_item.get("type", "")

        if media_type == "address_image":
            sent_count = int(session_state.get("address_image_sent_count", 0) or 0)
            session_state["address_image_sent_count"] = sent_count + 1
            stores = set(session_state.get("sent_address_stores", []) or [])
            target_store = media_item.get("target_store", "")
            if target_store:
                stores.add(target_store)
                sent_map = session_state.get("address_image_last_sent_at_by_store", {}) or {}
                if not isinstance(sent_map, dict):
                    sent_map = {}
                sent_map[target_store] = now
                session_state["address_image_last_sent_at_by_store"] = sent_map
                session_state["last_target_store"] = target_store
            session_state["sent_address_stores"] = list(stores)

        elif media_type == "contact_image":
            sent_count = int(session_state.get("contact_image_sent_count", 0) or 0)
            session_state["contact_image_sent_count"] = sent_count + 1
            session_state["contact_image_last_sent_at"] = now
            session_state["contact_warmup"] = False
            session_state["last_geo_pending"] = False

        if media_type in REQUIRED_MEDIA_TYPES:
            self._remove_pending_required_media(session_state, media_item)
            budget = session_state.get("required_media_retry_budget", {}) or {}
            budget.pop(self._pending_media_key(media_item), None)
            session_state["required_media_retry_budget"] = budget

        self.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
        self.memory_store.update_user_state(user_hash, user_state)
        self.memory_store.save()

    def enqueue_media_compensation(
        self,
        session_id: str,
        user_name: str,
        media_item: Dict[str, Any],
        failure_code: str = "",
        failure_detail: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not media_item:
            return None
        media_type = str(media_item.get("type", "") or "")
        if media_type not in REQUIRED_MEDIA_TYPES:
            return None

        user_hash = self._hash_user(user_name or session_id)
        session_state = self.memory_store.get_session_state(session_id, user_hash=user_hash)
        pending_items = self._sanitize_pending_required_media(session_state.get("pending_required_media", []))
        clean_item = dict(media_item)
        pending_id = self._pending_media_key(clean_item)
        clean_item["pending_media_id"] = pending_id
        clean_item["pending_required"] = True
        clean_item["queued_at"] = datetime.now().isoformat()

        if media_type == "contact_image":
            pending_items = [x for x in pending_items if str(x.get("type", "")) != "contact_image"]
        elif media_type == "address_image":
            target_store = str(clean_item.get("target_store", "") or "")
            pending_items = [
                x for x in pending_items
                if not (str(x.get("type", "")) == "address_image" and str(x.get("target_store", "") or "") == target_store)
            ]
        pending_items.append(clean_item)

        budget = session_state.get("required_media_retry_budget", {}) or {}
        budget[pending_id] = int(budget.get(pending_id, 0) or 0) + 1

        self.memory_store.update_session_state(
            session_id,
            {
                "pending_required_media": pending_items,
                "pending_required_media_updated_at": datetime.now().isoformat(),
                "last_required_media_failure_code": str(failure_code or ""),
                "last_required_media_failure_detail": str(failure_detail or ""),
                "required_media_retry_budget": budget,
            },
            user_hash=user_hash,
        )
        self.memory_store.save()
        return clean_item

    def clear_media_compensation(self, session_id: str, user_name: str, media_item: Dict[str, Any]) -> None:
        user_hash = self._hash_user(user_name or session_id)
        session_state = self.memory_store.get_session_state(session_id, user_hash=user_hash)
        self._remove_pending_required_media(session_state, media_item)
        budget = session_state.get("required_media_retry_budget", {}) or {}
        budget.pop(self._pending_media_key(media_item), None)
        session_state["required_media_retry_budget"] = budget
        self.memory_store.update_session_state(session_id, session_state, user_hash=user_hash)
        self.memory_store.save()

    def set_options(
        self,
        use_knowledge_first: bool,
        knowledge_threshold: float,
        first_reply_video_enabled: Optional[bool] = None,
        reply_mode: Optional[str] = None,
    ) -> None:
        self.use_knowledge_first = bool(use_knowledge_first)
        self.knowledge_threshold = max(0.0, min(1.0, float(knowledge_threshold)))
        if first_reply_video_enabled is not None:
            self.first_reply_video_enabled = bool(first_reply_video_enabled)
        if reply_mode in {REPLY_MODE_LEGACY, REPLY_MODE_LLM_DIRECT}:
            self.reply_mode = str(reply_mode)

    def get_status(self) -> Dict[str, Any]:
        """给 UI 的状态快照"""
        return {
            "use_knowledge_first": self.use_knowledge_first,
            "knowledge_threshold": self.knowledge_threshold,
            "first_reply_video_enabled": self.first_reply_video_enabled,
            "reply_mode": self.reply_mode,
            "memory_ttl_days": self.memory_ttl_days,
            "system_prompt_loaded": bool(self._system_prompt_doc_text),
            "playbook_loaded": bool(self._playbook_doc_text),
            "brand_knowledge_loaded": bool(self._brand_knowledge_doc_text),
            "address_image_count": sum(len(v) for v in self._address_index.values()),
            "contact_image_count": len(self._contact_images),
            "video_media_count": len(self._video_medias),
            "template_loaded": bool(self._reply_templates),
            "media_whitelist_count": len(self._media_whitelist_sessions),
        }

    def _detect_intent(self, text: str) -> str:
        # 特殊处理1：如果包含售后关键词（清洗、保养等），优先识别为售后问题
        aftercare_keywords = ("清洗", "售后", "保养", "打理", "维护", "怎么洗", "如何洗", "自己洗", "不会洗", "洗发", "护理")
        if any(k in (text or "") for k in aftercare_keywords):
            return "general"  # 让它走通用流程，匹配清洗相关的知识库

        # 特殊处理2：如果包含"不在XX地"+"到店"等模糊问题，走LLM
        # 考虑各种表达：不在上海、不在北京、在异地、外地、不在本地等
        remote_location_keywords = ("不在上海", "不是上海", "不去上海", "不在北京", "不是北京", "不去北京",
                                   "在异地", "在外地", "不在本地", "外地的", "异地的", "没办法到店", "无法到店", "不能到店")
        ambiguous_keywords = ("怎么办", "如何", "怎么做", "怎么弄")
        if any(k in (text or "") for k in remote_location_keywords) and any(k in (text or "") for k in ambiguous_keywords):
            # 如果同时包含售后关键词，优先走售后
            if any(k in (text or "") for k in aftercare_keywords):
                return "general"
            # 否则也走general，让系统根据上下文判断
            return "general"

        if self._looks_like_direct_contact_request(text):
            return "contact"

        if self.knowledge_service.is_shanghai_route_alias_address_candidate(text):
            return "address"
        if self.knowledge_service.is_address_query(text):
            return "address"
        if self.knowledge_service.is_purchase_intent(text):
            return "purchase"
        if any(k in (text or "") for k in CONTACT_INTENT_KEYWORDS):
            return "contact"
        return "general"

    def _looks_like_direct_contact_request(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False

        direct_patterns = (
            "联系方式",
            "联系方法",
            "联系信息",
            "二维码",
            "微信号",
            "电话",
            "手机号",
            "你的联系",
            "你们联系",
            "你的微信",
            "你们微信",
            "怎么加",
            "如何加",
            "加你",
            "加你们",
            "怎么添加",
            "如何添加",
            "怎么加微信",
            "如何加微信",
            "怎么联系",
            "如何联系",
        )
        return any(pattern in normalized for pattern in direct_patterns)

    def _should_trigger_precise_address_contact_image(
        self,
        latest_user_text: str,
        normalized_text: str,
        reply_text: str,
        intent: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
    ) -> bool:
        if self._looks_like_direct_contact_request(normalized_text):
            return False
        if not self._has_address_info_shared_context(conversation_history, session_state):
            return False
        if not self._is_precise_address_followup(latest_user_text):
            return False
        if self._has_blocking_address_followup_topic(normalized_text):
            return False
        return True

    def _has_address_info_shared_context(
        self,
        conversation_history: List[Dict[str, str]],
        session_state: Dict[str, Any],
    ) -> bool:
        if bool(session_state.get("address_info_shared", False)):
            return True
        return self._history_has_address_info_shared(conversation_history)

    def _history_has_address_info_shared(self, conversation_history: List[Dict[str, str]]) -> bool:
        for item in reversed(conversation_history or []):
            if str(item.get("role", "") or "") != "assistant":
                continue
            if self._reply_shares_address_info(str(item.get("content", "") or "")):
                return True
        return False

    def _reply_shares_address_info(self, reply_text: str) -> bool:
        normalized = self.knowledge_service.normalize_user_text(reply_text)
        if not normalized:
            return False
        if self._infer_answer_type(reply_text) in {"store_address", "address_general"}:
            return True
        if any(token in normalized for token in ("北京1家", "北京只有1家", "上海有5家", "上海共有5家")):
            return True
        if any(token in normalized for token in ("静安", "人民广场", "人广", "虹口", "五角场", "徐汇", "朝阳区")) and any(
            token in normalized for token in ("门店", "地址", "位置", "区域", "城市")
        ):
            return True
        return False

    def _is_precise_address_followup(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        precise_keywords = (
            "具体地址",
            "具体位置",
            "具体在哪",
            "多少号",
            "几号",
            "几楼",
            "楼层",
            "哪一栋",
            "哪栋",
            "哪个门",
            "从哪进",
            "哪个出口",
            "几号出口",
            "导航",
            "怎么导航",
            "怎么走",
            "怎么去",
            "怎么过去",
            "如何去",
            "如何过去",
            "坐车",
            "坐什么车",
            "地铁",
            "几号线",
            "哪一站",
            "哪个站",
            "开车怎么去",
            "打车到哪里",
            "定位",
            "停车",
        )
        generic_only_patterns = (
            "地址在哪",
            "地址给我",
            "上海地址给我",
            "北京地址给我",
            "店铺在那里",
            "在什么地方",
            "在哪里",
            "位置在哪",
        )
        if any(keyword in normalized for keyword in precise_keywords):
            return True
        if normalized in generic_only_patterns:
            return False
        if any(keyword in normalized for keyword in ADDRESS_FOLLOWUP_PRIORITY_KEYWORDS):
            return True
        return False

    def _has_blocking_address_followup_topic(self, normalized_text: str) -> bool:
        return any(keyword in normalized_text for keyword in ADDRESS_FOLLOWUP_BLOCK_KEYWORDS)

    def _is_ambiguous_short_fragment(self, text: str, intent: str, route: Dict[str, Any]) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized or len(normalized) > 2:
            return False
        if intent != "general":
            return False
        if str(route.get("reason", "unknown") or "unknown") != "unknown":
            return False
        ambiguous_tokens = {"址", "店", "路", "位", "地址", "位置"}
        return normalized in ambiguous_tokens

    def _looks_like_phone_submission(self, text: str) -> bool:
        normalized = re.sub(r"[^\d]", "", str(text or ""))
        if not normalized:
            return False
        return bool(re.fullmatch(r"1[3-9]\d{9}", normalized))

    def _should_apply_rule_decision(
        self,
        text: str,
        intent: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> bool:
        # 如果包含售后关键词，不走规则决策，让它走知识库或LLM
        aftercare_keywords = ("清洗", "售后", "保养", "打理", "维护", "怎么洗", "如何洗", "自己洗", "不会洗", "洗发", "护理")
        if any(k in (text or "") for k in aftercare_keywords):
            return False

        route_type = route.get("route_type", "unknown")
        target_store = route.get("target_store", "unknown")

        will_send_address_image = (
            route_type in ("coverage", "non_coverage", "need_district", "need_clarify") or
            intent == "address"
        )

        if intent == "address":
            session_target_store = str(session_state.get("last_target_store", "") or "")
            sent_stores = set(session_state.get("sent_address_stores", []) or [])
            text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
            contact_reply_count_by_store = dict(session_state.get("address_contact_reply_count_by_store", {}) or {})
            if (
                target_store == "unknown"
                and session_target_store
                and session_target_store != "unknown"
                and session_target_store in sent_stores
                and int(text_reply_count_by_store.get(session_target_store, 0) or 0) >= 1
                and int(contact_reply_count_by_store.get(session_target_store, 0) or 0) >= 1
            ):
                # 已经给过一次真实文字地址和一次联系方式兜底后，后续泛地址追问直接走 LLM，避免继续追问地区。
                return False

        # 原有的规则决策逻辑
        if route_type in ("coverage", "non_coverage", "need_district", "need_clarify"):
            return True
        if intent in ("address", "purchase"):
            return True
        if bool(session_state.get("last_geo_pending", False)) and self._looks_like_geo_reply(text=text, route=route):
            return True
        return False

    def _looks_like_geo_reply(self, text: str, route: Dict[str, Any]) -> bool:
        reason = route.get("reason", "unknown")
        if reason != "unknown":
            return True

        normalized = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", (text or ""))
        if not normalized:
            return False

        geo_tokens = (
            "北京", "上海", "徐汇", "徐家汇", "静安", "虹口", "杨浦", "五角场", "人广", "人民广场",
            "河北", "石家庄", "天津", "内蒙古", "江苏", "浙江", "苏州", "杭州", "东北", "省", "市", "区", "县", "州", "盟", "旗"
        )
        return any(token in normalized for token in geo_tokens)

    def _is_remote_geo_followup_reply(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return False
        return "外地" in normalized

    def _should_force_out_of_coverage_from_geo_followup(self, text: str, session_state: Dict[str, Any]) -> bool:
        if not bool(session_state.get("last_geo_pending", False)):
            return False
        if not self._is_remote_geo_followup_reply(text):
            return False
        normalized = re.sub(r"\s+", "", str(text or ""))
        last_geo_route_reason = str(session_state.get("last_geo_route_reason", "") or "")
        if last_geo_route_reason in ("need_district", "shanghai_need_district"):
            if any(keyword in normalized for keyword in SHANGHAI_ROUTE_HELP_KEYWORDS):
                return False
        return True

    def _build_address_text_after_image_decision(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        intent: str,
        session_state: Dict[str, Any],
    ) -> Optional[AgentDecision]:
        if intent != "address" and not self.knowledge_service.is_shanghai_route_alias_address_candidate(latest_user_text):
            return None
        if not self._should_continue_address_followup(latest_user_text=latest_user_text, session_state=session_state):
            return None

        target_store = str(route.get("target_store", "") or "")
        if not target_store or target_store == "unknown":
            target_store = str(session_state.get("last_target_store", "") or "")
        if not target_store or target_store == "unknown":
            return None

        sent_stores = set(session_state.get("sent_address_stores", []) or [])
        last_target_store = str(session_state.get("last_target_store", "") or "")
        has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
        if target_store not in sent_stores and not (has_sent_address and last_target_store == target_store):
            return None

        text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
        if int(text_reply_count_by_store.get(target_store, 0) or 0) >= 1:
            return None

        store = self.knowledge_service.get_store_display(target_store)
        store_name = str(store.get("store_name", "") or "门店")

        return AgentDecision(
            reply_text=self._normalize_reply_text(f"姐姐，{store_name}位置可以看图中圈圈的位置哦"),
            intent="address",
            route_reason=str(route.get("reason", "unknown") or "unknown"),
            reply_goal="解答",
            media_plan="address_image",
            reply_source="rule",
            rule_id="ADDR_TEXT_AFTER_IMAGE",
            rule_applied=True,
        )

    def _build_address_contact_after_text_decision(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        intent: str,
        session_state: Dict[str, Any],
    ) -> Optional[AgentDecision]:
        if intent != "address" and not self.knowledge_service.is_shanghai_route_alias_address_candidate(latest_user_text):
            return None
        if not self._should_continue_address_followup(latest_user_text=latest_user_text, session_state=session_state):
            return None

        target_store = str(route.get("target_store", "") or "")
        if not target_store or target_store == "unknown":
            target_store = str(session_state.get("last_target_store", "") or "")
        if not target_store or target_store == "unknown":
            return None

        sent_stores = set(session_state.get("sent_address_stores", []) or [])
        last_target_store = str(session_state.get("last_target_store", "") or "")
        has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
        if target_store not in sent_stores and not (has_sent_address and last_target_store == target_store):
            return None

        text_reply_count_by_store = dict(session_state.get("address_text_reply_count_by_store", {}) or {})
        if int(text_reply_count_by_store.get(target_store, 0) or 0) < 1:
            return None

        contact_reply_count_by_store = dict(session_state.get("address_contact_reply_count_by_store", {}) or {})
        if int(contact_reply_count_by_store.get(target_store, 0) or 0) >= 1:
            return None

        return AgentDecision(
            reply_text=ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK,
            intent="address",
            route_reason=str(route.get("reason", "unknown") or "unknown"),
            reply_goal="解答",
            media_plan="none",
            reply_source="rule",
            rule_id="ADDR_CONTACT_AFTER_TEXT",
            rule_applied=True,
        )

    def _should_continue_address_followup(self, latest_user_text: str, session_state: Dict[str, Any]) -> bool:
        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        if not normalized:
            return False

        if self.knowledge_service.is_shanghai_route_alias_address_candidate(normalized):
            has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
            has_target_store = str(session_state.get("last_target_store", "") or "").strip() not in ("", "unknown")
            if has_sent_address and has_target_store:
                return True

        if any(keyword in normalized for keyword in ADDRESS_FOLLOWUP_PRIORITY_KEYWORDS):
            return True

        if any(keyword in normalized for keyword in ADDRESS_FOLLOWUP_BLOCK_KEYWORDS):
            return False

        if any(keyword in normalized for keyword in ADDRESS_FOLLOWUP_EXPLICIT_KEYWORDS):
            return True

        if any(keyword in normalized for keyword in ADDRESS_FOLLOWUP_RESIDUAL_KEYWORDS):
            has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
            has_target_store = str(session_state.get("last_target_store", "") or "").strip() not in ("", "unknown")
            return has_sent_address and has_target_store

        return False

    def _resolve_geo_context(self, route: Dict[str, Any], session_state: Dict[str, Any]) -> Dict[str, Any]:
        target_store = route.get("target_store", "unknown")
        detected_region = route.get("detected_region", "") or ""
        if target_store and target_store != "unknown":
            return {
                "known": True,
                "source": "route_target_store",
                "target_store": target_store,
                "region": detected_region,
            }
        if detected_region:
            return {
                "known": True,
                "source": "route_detected_region",
                "target_store": session_state.get("last_target_store", ""),
                "region": detected_region,
            }

        last_target_store = session_state.get("last_target_store", "")
        if last_target_store and last_target_store != "unknown":
            return {
                "known": True,
                "source": "session_last_target_store",
                "target_store": last_target_store,
                "region": session_state.get("last_detected_region", ""),
            }

        last_region = session_state.get("last_detected_region", "")
        if last_region:
            return {
                "known": True,
                "source": "session_last_detected_region",
                "target_store": "",
                "region": last_region,
            }

        if int(session_state.get("address_image_sent_count", 0) or 0) > 0:
            return {
                "known": True,
                "source": "session_address_image_history",
                "target_store": "",
                "region": "",
            }

        return {
            "known": False,
            "source": "",
            "target_store": "",
            "region": "",
        }

    def _decide_rule_reply(
        self,
        text: str,
        intent: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        user_state: Dict[str, Any],
        is_first_turn_global: bool = False,
    ) -> AgentDecision:
        reason = route.get("reason", "unknown")
        target_store = route.get("target_store", "unknown")
        geo_context = self._resolve_geo_context(route, session_state)
        both_images_sent = self._has_both_images_sent(session_state)
        neg_shanghai_hint = self._has_neg_shanghai_hint(text)

        if is_first_turn_global and intent == "purchase" and reason in ("unknown", "need_region"):
            return self._build_geo_followup_decision(session_state=session_state, route_reason="need_region", intent="purchase")

        if reason == "shanghai_need_arrival_point":
            session_state["last_geo_pending"] = True
            session_state["last_geo_route_reason"] = "need_arrival_point"
            return AgentDecision(
                reply_text=self._render_template("ask_sh_arrival_point"),
                intent="address",
                route_reason="need_arrival_point",
                reply_goal="追问地区",
                media_plan="none",
                reply_source="rule",
                rule_id="ADDR_ASK_ARRIVAL_POINT",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        if reason == "shanghai_need_district":
            return self._build_geo_followup_decision(session_state=session_state, route_reason="need_district", intent="address")

        if reason == "sh_route_need_clarify":
            session_state["last_geo_pending"] = True
            session_state["last_geo_route_reason"] = "need_clarify"
            return AgentDecision(
                reply_text=self._render_template("ask_sh_route_clarify"),
                intent="address",
                route_reason="need_clarify",
                reply_goal="追问地区",
                media_plan="none",
                reply_source="rule",
                rule_id="ADDR_SH_ROUTE_NEED_CLARIFY",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        # “不在上海怎么买”优先走远程联系方式逻辑，避免被历史上海门店上下文误导。
        if (
            intent == "purchase"
            and neg_shanghai_hint
            and geo_context.get("known")
            and not (reason == "out_of_coverage" and route.get("detected_region"))
        ):
            session_state["last_geo_pending"] = False
            session_state["geo_followup_round"] = 0
            session_state["geo_choice_offered"] = False
            if self._is_contact_image_sent_for_current_geo(session_state):
                return AgentDecision(
                    reply_text=self._render_template("purchase_contact_remote_remind_only"),
                    intent="purchase",
                    route_reason="not_in_shanghai_remote",
                    reply_goal="推进购买意图",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="PURCHASE_REMOTE_CONTACT_REMIND_ONLY",
                    rule_applied=True,
                    geo_context_source=geo_context.get("source", ""),
                )
            return AgentDecision(
                reply_text=self._render_template("purchase_contact_intro"),
                intent="purchase",
                route_reason="not_in_shanghai_remote",
                reply_goal="推进购买意图",
                media_plan="contact_image",
                reply_source="rule",
                rule_id="PURCHASE_REMOTE_CONTACT_IMAGE",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        if reason == "out_of_coverage":
            if self._should_recover_to_shanghai_arrival_help(text, session_state):
                session_state["last_geo_pending"] = True
                session_state["last_geo_route_reason"] = "need_arrival_point"
                return AgentDecision(
                    reply_text=self._render_template("ask_sh_arrival_point"),
                    intent="address",
                    route_reason="need_arrival_point",
                    reply_goal="追问地区",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="ADDR_ASK_ARRIVAL_POINT",
                    rule_applied=True,
                    geo_context_source=geo_context.get("source", ""),
                )
            region = route.get("detected_region") or route_region(reason, text) or session_state.get("last_detected_region", "") or "您所在地区"
            session_state["last_geo_pending"] = False
            session_state["geo_followup_round"] = 0
            session_state["geo_choice_offered"] = False
            session_state["last_geo_route_reason"] = ""

            # 如果已经发送过联系方式图片，只用固定话术提醒
            if self._is_contact_image_sent_for_current_geo(session_state):
                return AgentDecision(
                    reply_text="姐姐，请往上滑看图中画框框的地方找我～♥️",
                    intent="purchase" if intent == "purchase" else "address",
                    route_reason="out_of_coverage",
                    reply_goal="推进购买意图",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="ADDR_OUT_OF_COVERAGE_REMIND_ONLY",
                    rule_applied=True,
                    geo_context_source=geo_context.get("source", ""),
                )

            return AgentDecision(
                reply_text=self._render_template("non_coverage_contact", region=region),
                intent="purchase" if intent == "purchase" else "address",
                route_reason="out_of_coverage",
                reply_goal="推进购买意图",
                media_plan="contact_image",
                reply_source="rule",
                rule_id="ADDR_OUT_OF_COVERAGE",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        # 北方（天津/河北/内蒙古）默认走北京门店地址导向；
        # 若已发过联系方式图，则优先固定“画圈”提醒，避免偏航到包邮话术。
        if reason == "north_fallback_beijing" and intent in ("purchase", "address"):
            session_state["last_geo_pending"] = False
            session_state["geo_followup_round"] = 0
            session_state["geo_choice_offered"] = False
            if self._is_contact_image_sent_for_current_geo(session_state):
                return AgentDecision(
                    reply_text=self._render_template("purchase_contact_remote_remind_only"),
                    intent="purchase",
                    route_reason=reason,
                    reply_goal="推进购买意图",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="PURCHASE_REMOTE_CONTACT_REMIND_ONLY",
                    rule_applied=True,
                    geo_context_source=geo_context.get("source", ""),
                )

            store = self.knowledge_service.get_store_display("beijing_chaoyang")
            store_name = self._store_recommend_display_name(
                "beijing_chaoyang",
                store.get("store_name", "北京朝阳门店"),
            )
            return AgentDecision(
                reply_text=self._render_template("store_recommend", store_name=store_name),
                intent="address",
                route_reason=reason,
                reply_goal="解答",
                media_plan="address_image",
                reply_source="rule",
                rule_id="ADDR_STORE_RECOMMEND",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        if intent == "purchase" and reason != "shanghai_need_district" and geo_context.get("known") and both_images_sent:
            strong_count = int(session_state.get("strong_intent_after_both_count", 0) or 0)
            session_state["strong_intent_after_both_count"] = strong_count + 1
            hint_sent = bool(session_state.get("purchase_both_first_hint_sent", False))
            if not hint_sent:
                session_state["purchase_both_first_hint_sent"] = True
                return AgentDecision(
                    reply_text=self._render_template("strong_intent_after_both_first"),
                    intent="purchase",
                    route_reason=reason if reason != "unknown" else "both_images_lock",
                    reply_goal="推进购买意图",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="PURCHASE_AFTER_BOTH_FIRST_HINT",
                    rule_applied=True,
                    geo_context_source=geo_context.get("source", ""),
                    both_images_sent_state=True,
                    purchase_both_first_hint_sent=True,
                )

            follow_decision = self._decide_general_reply(
                latest_user_text=text,
                intent=intent,
                route=route,
                conversation_history=conversation_history,
                session_state=session_state,
                user_state=user_state,
            )
            follow_decision.media_plan = "none"
            follow_decision.geo_context_source = geo_context.get("source", "")
            follow_decision.both_images_sent_state = True
            follow_decision.purchase_both_first_hint_sent = bool(
                session_state.get("purchase_both_first_hint_sent", False)
            )
            return follow_decision

        if intent == "purchase" and reason != "shanghai_need_district" and geo_context.get("known"):
            contact_sent = self._is_contact_image_sent_for_current_geo(session_state)
            session_state["last_geo_pending"] = False
            session_state["geo_followup_round"] = 0
            session_state["geo_choice_offered"] = False
            if contact_sent:
                return AgentDecision(
                    reply_text=self._render_template("purchase_contact_remind_only"),
                    intent="purchase",
                    route_reason=reason if reason != "unknown" else "known_geo_context",
                    reply_goal="推进购买意图",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="PURCHASE_CONTACT_REMIND_ONLY",
                    rule_applied=True,
                    geo_context_source=geo_context.get("source", ""),
                )

            return AgentDecision(
                reply_text=self._render_template("purchase_contact_intro"),
                intent="purchase",
                route_reason=reason if reason != "unknown" else "known_geo_context",
                reply_goal="推进购买意图",
                media_plan="contact_image",
                reply_source="rule",
                rule_id="PURCHASE_CONTACT_FROM_KNOWN_GEO",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        if target_store != "unknown":
            store = self.knowledge_service.get_store_display(target_store)
            store_name = self._store_recommend_display_name(target_store, store.get("store_name", "门店"))
            session_state["last_geo_pending"] = False
            session_state["geo_followup_round"] = 0
            session_state["geo_choice_offered"] = False
            session_state["last_geo_route_reason"] = ""
            return AgentDecision(
                reply_text=self._render_template("store_recommend", store_name=store_name),
                intent="address",
                route_reason=reason,
                reply_goal="解答",
                media_plan="address_image",
                reply_source="rule",
                rule_id="ADDR_STORE_RECOMMEND",
                rule_applied=True,
                geo_context_source=geo_context.get("source", ""),
            )

        # address / purchase 未识别到地区：进入 2次追问 + 1次选择题
        return self._build_geo_followup_decision(session_state=session_state, route_reason="need_region", intent=intent)

    def _build_geo_followup_decision(self, session_state: Dict[str, Any], route_reason: str, intent: str) -> AgentDecision:
        round_count = int(session_state.get("geo_followup_round", 0) or 0)
        choice_offered = bool(session_state.get("geo_choice_offered", False))

        if round_count < 2:
            next_round = round_count + 1
            session_state["geo_followup_round"] = next_round
            session_state["geo_choice_offered"] = False
            session_state["last_geo_pending"] = True
            session_state["last_geo_route_reason"] = route_reason
            if route_reason == "need_district":
                template_key = "ask_sh_district_r1" if next_round == 1 else "ask_sh_district_r2"
                rule_id = f"ADDR_ASK_DISTRICT_R{next_round}"
            else:
                template_key = "ask_region_r1" if next_round == 1 else "ask_region_r2"
                rule_id = f"ADDR_ASK_REGION_R{next_round}"
        elif not choice_offered:
            session_state["geo_choice_offered"] = True
            session_state["last_geo_pending"] = True
            session_state["last_geo_route_reason"] = route_reason
            template_key = "ask_sh_district_choice" if route_reason == "need_district" else "ask_region_choice"
            rule_id = "ADDR_ASK_DISTRICT_CHOICE" if route_reason == "need_district" else "ADDR_ASK_REGION_CHOICE"
        else:
            # 用户持续地址/购买类但仍不给地区，重置到下一轮 2+1 循环
            session_state["geo_followup_round"] = 1
            session_state["geo_choice_offered"] = False
            session_state["last_geo_pending"] = True
            session_state["last_geo_route_reason"] = route_reason
            template_key = "ask_sh_district_r1_reset" if route_reason == "need_district" else "ask_region_r1_reset"
            rule_id = "ADDR_ASK_DISTRICT_R1_RESET" if route_reason == "need_district" else "ADDR_ASK_REGION_R1_RESET"

        out_intent = intent if intent in ("address", "purchase") else "address"
        return AgentDecision(
            reply_text=self._render_template(template_key),
            intent=out_intent,
            route_reason=route_reason,
            reply_goal="追问地区",
            media_plan="none",
            reply_source="rule",
            rule_id=rule_id,
            rule_applied=True,
        )

    def _should_recover_to_shanghai_arrival_help(self, text: str, session_state: Dict[str, Any]) -> bool:
        if not bool(session_state.get("last_geo_pending", False)):
            return False
        if str(session_state.get("last_geo_route_reason", "") or "") not in ("need_district", "shanghai_need_district"):
            return False
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return False
        return any(keyword in normalized for keyword in SHANGHAI_ROUTE_HELP_KEYWORDS)

    def _is_follow_up_question(self, text: str, conversation_history: List[Dict[str, str]]) -> bool:
        """检测是否为追问，根据用户选择的策略"""
        text_stripped = text.strip()

        if any(keyword in text_stripped for keyword in SERVICE_HOURS_PRIORITY_KEYWORDS):
            return False

        # 场景1：简短回复（<10字符）
        if len(text_stripped) < 10:
            return True

        # 场景2：包含追问关键词
        follow_up_keywords = ["怎么", "如何", "为什么", "那", "呢", "吗", "太", "很", "什么"]
        if any(k in text for k in follow_up_keywords) and len(text_stripped) < 20:
            return True

        # 场景3：与上一轮对话高度相关（关键词重叠>30%）
        if conversation_history and len(conversation_history) >= 2:
            last_user_msg = conversation_history[-2].get("content", "")
            last_assistant_msg = conversation_history[-1].get("content", "")

            # 提取关键词（去除标点和常见词）
            def extract_keywords(s):
                import re
                s = re.sub(r'[，。！？、,.!?~\s]+', '', s)
                # 去除常见词
                common_words = set("的了吗呢啊哦嗯姐姐我们您")
                return set(c for c in s if c not in common_words)

            user_words = extract_keywords(text_stripped)
            last_words = extract_keywords(last_user_msg + last_assistant_msg)

            if user_words and last_words:
                overlap = len(user_words & last_words) / len(user_words)
                if overlap > 0.3:
                    return True

        return False

    def _has_price_priority(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        if any(keyword in normalized for keyword in ADDRESS_PRIORITY_OVER_PRICE_KEYWORDS):
            return False
        explicit_price_keywords = (
            "多少钱",
            "价格",
            "价位",
            "报价",
            "费用",
            "收费",
            "预算",
            "贵",
            "便宜",
            "什么价",
            "什么价格",
            "大概多少钱",
        )
        has_explicit_price_signal = any(keyword in normalized for keyword in explicit_price_keywords)
        if (
            not has_explicit_price_signal
            and (
                self.knowledge_service.is_shanghai_route_alias_address_candidate(text)
                or self.knowledge_service.is_address_query(text)
            )
        ):
            return False
        return any(keyword in normalized for keyword in PRICE_PRIORITY_KEYWORDS)

    def _decide_price_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        session_state: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        del conversation_history
        text = (latest_user_text or "").strip()
        if not self._has_price_priority(text):
            return None
        should_send_address_image = self._should_attach_address_image_for_price_query(text, route)

        price_priority_count = int(session_state.get("price_priority_reply_count", 0) or 0)
        if price_priority_count == 2:
            return AgentDecision(
                reply_text="姐姐，具体明细的价位，您可以留个☎️，我加您具体跟您介绍，这样会方便一点～",
                intent="price",
                route_reason="price_priority_private_followup",
                reply_goal="承接联系方式",
                media_plan="address_image" if should_send_address_image else "none",
                reply_source="knowledge",
                rule_id="PRICE_PRIORITY_PRIVATE_GUIDE",
                rule_applied=True,
                kb_match_score=0.0,
                kb_match_question="",
                kb_match_mode="price_priority_private_guide",
                kb_item_id="",
                kb_variant_total=0,
                kb_variant_selected_index=-1,
                kb_variant_fallback_llm=False,
                kb_confident=True,
            )

        kb_detail = self.knowledge_service.find_answer_detail(text, threshold=self.knowledge_threshold)
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        if kb_detail.get("matched") and kb_intent == "price":
            kb_answer = str(kb_detail.get("answer", "") or "").strip()
            kb_answers = [
                str(x).strip()
                for x in (kb_detail.get("answers", []) or [])
                if str(x).strip()
            ]
            if kb_answer and kb_answer not in kb_answers:
                kb_answers.append(kb_answer)

            selected_answer, selected_index, exhausted = self._select_kb_variant_answer(
                answers=kb_answers,
                user_state=user_state,
                user_id_hash=user_id_hash,
            )
            base_answer = selected_answer or kb_answer or (kb_answers[0] if kb_answers else "")
            if base_answer:
                self._remember_selected_kb_answer(
                    user_state=user_state,
                    user_id_hash=user_id_hash,
                    answer_text=base_answer,
                )
                return AgentDecision(
                    reply_text=self._append_price_fact_followup(base_answer, text, route),
                    intent="price",
                    route_reason="price_priority",
                    reply_goal="解答",
                    media_plan="address_image" if should_send_address_image else "none",
                    reply_source="knowledge",
                    rule_id="PRICE_PRIORITY",
                    rule_applied=True,
                    kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
                    kb_match_question=str(kb_detail.get("question", "") or ""),
                    kb_match_mode=f"price_priority_{str(kb_detail.get('mode', '') or 'match')}",
                    kb_item_id=str(kb_detail.get("item_id", "") or ""),
                    kb_variant_total=len(kb_answers),
                    kb_variant_selected_index=selected_index if selected_answer else (-1 if exhausted else 0),
                    kb_variant_fallback_llm=False,
                    kb_confident=True,
                )

        fallback_answer = "姐姐价格一般在3000到6000之间，具体要看材质、款式、头围和想要的效果。"
        return AgentDecision(
            reply_text=self._append_price_fact_followup(fallback_answer, text, route),
            intent="price",
            route_reason="price_priority_fallback",
            reply_goal="解答",
            media_plan="address_image" if should_send_address_image else "none",
            reply_source="knowledge",
            rule_id="PRICE_PRIORITY_FALLBACK",
            rule_applied=True,
            kb_match_score=0.0,
            kb_match_question="",
            kb_match_mode="price_priority_fallback",
            kb_item_id="",
            kb_variant_total=0,
            kb_variant_selected_index=-1,
            kb_variant_fallback_llm=False,
            kb_confident=True,
        )

    def _append_price_fact_followup(self, base_reply: str, latest_user_text: str, route: Dict[str, Any]) -> str:
        base = str(base_reply or "").strip()
        if not base:
            return base

        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        followups: List[str] = []

        if self._looks_like_same_day_duration_query(normalized):
            followups.append(PRICE_FACT_FOLLOWUP_SAME_DAY_DURATION)
        elif self._looks_like_duration_query(normalized):
            followups.append(PRICE_FACT_FOLLOWUP_GENERAL_DURATION)
        price_geo_followup = self._build_price_geo_followup(latest_user_text, route)
        if price_geo_followup:
            followups.append(price_geo_followup)
        if self._looks_like_appointment_query(latest_user_text):
            followups.append(PRICE_FACT_FOLLOWUP_APPOINTMENT)
        if any(token in normalized for token in ("材质", "区别", "为什么", "怎么定", "怎么算", "档次", "等级", "效果", "款式")):
            followups.append(PRICE_FACT_FOLLOWUP_PRICING_BASIS)
        if any(token in normalized for token in ("定制", "流程", "怎么做", "怎么弄")):
            followups.append(PRICE_FACT_FOLLOWUP_PROCESS)

        unique_followups: List[str] = []
        seen = set()
        for item in followups:
            key = re.sub(r"\s+", "", item)
            if key in seen:
                continue
            seen.add(key)
            unique_followups.append(item)

        if not unique_followups:
            return self._normalize_reply_text(base)

        trailing_emoji = self._extract_trailing_known_reply_emoji(base)
        base_clean = base[:-len(trailing_emoji)].strip() if trailing_emoji and base.endswith(trailing_emoji) else base
        base_clean = base_clean.rstrip("，,；; ")
        if not re.search(r"[。！？!?]$", base_clean):
            base_clean = f"{base_clean}。"
        combined = f"{base_clean}{''.join(unique_followups)}"
        return self._normalize_reply_text(combined)

    def _build_price_geo_followup(self, latest_user_text: str, route: Dict[str, Any]) -> str:
        text = str(latest_user_text or "").strip()
        normalized = re.sub(r"\s+", "", text).lower()
        if not normalized:
            return ""
        route_reason = str(route.get("reason", "") or "").strip()
        if route_reason == "shanghai_need_district":
            return PRICE_FACT_FOLLOWUP_SHANGHAI_DISTRICT

        has_explicit_geo_context = self._has_precise_geo_context_for_current_query(route)
        asks_store_location = (
            self.knowledge_service.is_address_query(text)
            or any(token in normalized for token in STORE_CONVENIENCE_QUERY_KEYWORDS)
        )
        if not asks_store_location and not has_explicit_geo_context:
            return ""

        target_store = str(route.get("target_store", "") or "").strip()
        route_type = str(route.get("route_type", "") or "").strip()
        if route_type == "coverage" and target_store and target_store != "unknown":
            fallback_name = str(route.get("store_name", "") or "")
            store_name = self._store_recommend_display_name(target_store, fallback_name)
            return f"您这个位置去{store_name}会更方便一些。"

        return PRICE_FACT_FOLLOWUP_STORE_DISTRIBUTION

    def _should_attach_address_image_for_price_query(self, latest_user_text: str, route: Dict[str, Any]) -> bool:
        text = str(latest_user_text or "").strip()
        normalized = re.sub(r"\s+", "", text).lower()
        if not normalized:
            return False
        target_store = str(route.get("target_store", "") or "").strip()
        route_type = str(route.get("route_type", "") or "").strip()
        has_explicit_geo_context = self._has_precise_geo_context_for_current_query(route)
        asks_store_location = (
            self.knowledge_service.is_address_query(text)
            or any(token in normalized for token in STORE_CONVENIENCE_QUERY_KEYWORDS)
        )
        return bool(
            (asks_store_location or has_explicit_geo_context)
            and route_type == "coverage"
            and target_store
            and target_store != "unknown"
        )

    def _has_precise_geo_context_for_current_query(self, route: Dict[str, Any]) -> bool:
        route_reason = str(route.get("reason", "") or "").strip()
        if not route_reason:
            return False
        if route_reason.startswith("sh_district_map:"):
            return True
        if route_reason.startswith("sh_route_scored:"):
            return True
        return route_reason in {
            "beijing_all_district",
            "north_fallback_beijing",
            "jiangzhe_to_sh_renmin",
        }

    def _looks_like_same_day_duration_query(self, normalized_text: str) -> bool:
        normalized = str(normalized_text or "")
        if not normalized:
            return False
        return any(
            token in normalized
            for token in (
                "一天",
                "当天",
                "当天能",
                "一天能",
                "当天拿",
                "当天做",
                "做完吗",
                "做得完",
                "完成吗",
                "能完成吗",
                "能做完吗",
                "能做好吗",
            )
        )

    def _looks_like_duration_query(self, normalized_text: str) -> bool:
        normalized = str(normalized_text or "")
        if not normalized:
            return False
        if self._looks_like_same_day_duration_query(normalized):
            return True
        return any(
            token in normalized
            for token in (
                "多久",
                "几天",
                "多长时间",
                "周期",
                "时间",
                "多久能好",
                "多久能做",
                "多久能完成",
                "多久能拿",
                "什么时候能拿",
                "什么时候做好",
            )
        )

    def _looks_like_lifespan_query(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return False
        return any(token in normalized for token in LIFESPAN_PRIORITY_KEYWORDS)

    def _decide_lifespan_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        text = (latest_user_text or "").strip()
        if not self._looks_like_lifespan_query(text):
            return None

        kb_detail = self.knowledge_service.find_answer_detail(text, threshold=self.knowledge_threshold)
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
        if not (kb_detail.get("matched") and ("使用寿命" in tags or kb_intent in {"general", "aftercare"})):
            return None

        kb_answer = str(kb_detail.get("answer", "") or "").strip()
        kb_answers = [
            str(x).strip()
            for x in (kb_detail.get("answers", []) or [])
            if str(x).strip()
        ]
        if kb_answer and kb_answer not in kb_answers:
            kb_answers.append(kb_answer)
        answer = kb_answers[0] if kb_answers else kb_answer
        if not answer:
            return None

        selected_answer, selected_index, exhausted = self._select_kb_variant_answer(
            answers=kb_answers,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        answer = selected_answer or answer
        self._remember_selected_kb_answer(
            user_state=user_state,
            user_id_hash=user_id_hash,
            answer_text=answer,
        )
        return AgentDecision(
            reply_text=answer,
            intent="general",
            route_reason="lifespan_priority",
            reply_goal="解答",
            media_plan="none",
            reply_source="knowledge",
            rule_id="LIFESPAN_PRIORITY",
            rule_applied=True,
            kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
            kb_match_question=str(kb_detail.get("question", "") or ""),
            kb_match_mode=f"lifespan_priority_{str(kb_detail.get('mode', '') or 'match')}",
            kb_item_id=str(kb_detail.get("item_id", "") or ""),
            kb_variant_total=len(kb_answers),
            kb_variant_selected_index=selected_index if selected_answer else (-1 if exhausted else 0),
            kb_variant_fallback_llm=False,
            kb_confident=True,
        )

    def _decide_appointment_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        store_specific_reply = self._build_store_appointment_contact_reply(latest_user_text, route)
        kb_detail = self.knowledge_service.find_answer_detail(
            latest_user_text,
            threshold=self.knowledge_threshold,
        )
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
        if not (kb_detail.get("matched") and (kb_intent == "appointment" or "预约" in tags)):
            if store_specific_reply:
                return AgentDecision(
                    reply_text=store_specific_reply,
                    intent="appointment",
                    route_reason=str(route.get("reason", "unknown") or "unknown"),
                    reply_goal="解答",
                    media_plan="contact_image",
                    reply_source="knowledge",
                    rule_id="KB_MATCH_CONTACT_IMAGE",
                    rule_applied=False,
                    kb_match_score=0.0,
                    kb_match_question="",
                    kb_match_mode="appointment_route_contact_fallback",
                    kb_item_id="",
                    kb_variant_total=0,
                    kb_variant_selected_index=-1,
                    kb_variant_fallback_llm=False,
                    kb_confident=True,
                    force_contact_image=True,
                    kb_contact_trigger_type="appointment",
                )
            return None

        kb_answer = str(kb_detail.get("answer", "") or "").strip()
        kb_answers = [
            str(x).strip()
            for x in (kb_detail.get("answers", []) or [])
            if str(x).strip()
        ]
        if kb_answer and kb_answer not in kb_answers:
            kb_answers.insert(0, kb_answer)

        selected_answer, selected_index, exhausted = self._select_kb_variant_answer(
            answers=kb_answers,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        answer = selected_answer or kb_answer or (kb_answers[0] if kb_answers else "")
        if not answer:
            return None
        if store_specific_reply:
            answer = store_specific_reply

        return AgentDecision(
            reply_text=answer,
            intent="appointment",
            route_reason=str(route.get("reason", "unknown") or "unknown"),
            reply_goal="解答",
            media_plan="contact_image",
            reply_source="knowledge",
            rule_id="KB_MATCH_CONTACT_IMAGE",
            rule_applied=False,
            kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
            kb_match_question=str(kb_detail.get("question", "") or ""),
            kb_match_mode=f"appointment_priority_{str(kb_detail.get('mode', '') or 'match')}",
            kb_item_id=str(kb_detail.get("item_id", "") or ""),
            kb_variant_total=len(kb_answers),
            kb_variant_selected_index=selected_index if selected_answer else (-1 if exhausted else 0),
            kb_variant_fallback_llm=False,
            kb_confident=True,
            force_contact_image=True,
            kb_contact_trigger_type="appointment",
        )

    def _build_store_appointment_contact_reply(self, latest_user_text: str, route: Dict[str, Any]) -> str:
        text = str(latest_user_text or "").strip()
        if not text:
            return ""
        route_type = str(route.get("route_type", "") or "").strip()
        target_store = str(route.get("target_store", "") or "").strip()
        if route_type != "coverage" or not target_store or target_store == "unknown":
            return ""
        if not (
            self.knowledge_service.is_address_query(text)
            or self._has_precise_geo_context_for_current_query(route)
        ):
            return ""
        store = self.knowledge_service.get_store_display(target_store)
        store_name = self._store_recommend_display_name(target_store, store.get("store_name", "门店"))
        return f"姐姐，我们是需要预约的，推荐您到{store_name}，具体位置您可以看下面的圈圈+我好友，我发给您路线地址❤️"

    def _looks_like_process_query(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        return any(keyword in normalized for keyword in PROCESS_PRIORITY_KEYWORDS)

    def _decide_process_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        if not self._looks_like_process_query(latest_user_text):
            return None

        kb_detail = self.knowledge_service.find_answer_detail(
            latest_user_text,
            threshold=min(self.knowledge_threshold, 0.1),
        )
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
        if not (kb_detail.get("matched") and (kb_intent == "process" or {"流程", "次数"} & tags)):
            return None

        kb_answer = str(kb_detail.get("answer", "") or "").strip()
        kb_answers = [
            str(x).strip()
            for x in (kb_detail.get("answers", []) or [])
            if str(x).strip()
        ]
        if kb_answer and kb_answer not in kb_answers:
            kb_answers.append(kb_answer)

        selected_answer, selected_index, exhausted = self._select_kb_variant_answer(
            answers=kb_answers,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        answer = selected_answer or kb_answer or (kb_answers[0] if kb_answers else "")
        if not answer:
            return None

        self._remember_selected_kb_answer(
            user_state=user_state,
            user_id_hash=user_id_hash,
            answer_text=answer,
        )
        return AgentDecision(
            reply_text=answer,
            intent="process",
            route_reason=str(route.get("reason", "unknown") or "unknown"),
            reply_goal="解答",
            media_plan="none",
            reply_source="knowledge",
            rule_id="PROCESS_PRIORITY",
            rule_applied=True,
            kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
            kb_match_question=str(kb_detail.get("question", "") or ""),
            kb_match_mode=f"process_priority_{str(kb_detail.get('mode', '') or 'match')}",
            kb_item_id=str(kb_detail.get("item_id", "") or ""),
            kb_variant_total=len(kb_answers),
            kb_variant_selected_index=selected_index if selected_answer else (-1 if exhausted else 0),
            kb_variant_fallback_llm=False,
            kb_confident=True,
        )

    def _looks_like_business_block_query(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        return any(keyword in normalized for keyword in BUSINESS_BLOCK_PRIORITY_KEYWORDS)

    def _decide_business_block_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        if not self._looks_like_business_block_query(latest_user_text):
            return None

        kb_detail = self.knowledge_service.find_answer_detail(
            latest_user_text,
            threshold=min(self.knowledge_threshold, 0.1),
        )
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        if kb_intent not in {"franchise", "reseller_block", "factory_cooperation_block", "learn_block"}:
            return None

        kb_answer = str(kb_detail.get("answer", "") or "").strip()
        kb_answers = [
            str(x).strip()
            for x in (kb_detail.get("answers", []) or [])
            if str(x).strip()
        ]
        if kb_answer and kb_answer not in kb_answers:
            kb_answers.append(kb_answer)

        selected_answer, selected_index, exhausted = self._select_kb_variant_answer(
            answers=kb_answers,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        answer = selected_answer or kb_answer or (kb_answers[0] if kb_answers else "")
        if not answer:
            return None

        self._remember_selected_kb_answer(
            user_state=user_state,
            user_id_hash=user_id_hash,
            answer_text=answer,
        )
        return AgentDecision(
            reply_text=answer,
            intent=kb_intent,
            route_reason=str(route.get("reason", "unknown") or "unknown"),
            reply_goal="解答",
            media_plan="none",
            reply_source="knowledge",
            rule_id="BUSINESS_BLOCK_PRIORITY",
            rule_applied=True,
            kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
            kb_match_question=str(kb_detail.get("question", "") or ""),
            kb_match_mode=f"business_block_priority_{str(kb_detail.get('mode', '') or 'match')}",
            kb_item_id=str(kb_detail.get("item_id", "") or ""),
            kb_variant_total=len(kb_answers),
            kb_variant_selected_index=selected_index if selected_answer else (-1 if exhausted else 0),
            kb_variant_fallback_llm=False,
            kb_confident=True,
        )

    def _decide_general_reply(
        self,
        latest_user_text: str,
        intent: str,
        route: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        session_state: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> AgentDecision:
        route_reason = route.get("reason", "unknown")
        contact_sent = int(session_state.get("contact_image_sent_count", 0) or 0) >= 1
        kb_blocked_by_polite_guard = False
        kb_polite_guard_reason = ""

        media_placeholder_decision = self._decide_media_placeholder_reply(
            latest_user_text=latest_user_text,
            route_reason=route_reason,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if media_placeholder_decision is not None:
            return media_placeholder_decision

        lifespan_priority_decision = self._decide_lifespan_priority_reply(
            latest_user_text=latest_user_text,
            route=route,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if lifespan_priority_decision is not None:
            return lifespan_priority_decision

        if intent == "contact":
            if contact_sent:
                prompt_count = int(session_state.get("contact_followup_prompt_count", 0) or 0)
                session_state["contact_followup_prompt_count"] = prompt_count + 1
                template_key = "contact_followup_1" if (prompt_count % 2) == 0 else "contact_followup_2"
                return AgentDecision(
                    reply_text=self._render_template(template_key),
                    intent="contact",
                    route_reason=route_reason,
                    reply_goal="推进购买意图",
                    media_plan="none",
                    reply_source="rule",
                    rule_id="CONTACT_FOLLOWUP",
                    rule_applied=True,
                )
            return AgentDecision(
                reply_text=self._render_template("contact_intro"),
                intent="contact",
                route_reason=route_reason,
                reply_goal="推进购买意图",
                media_plan="contact_image",
                reply_source="rule",
                rule_id="CONTACT_SEND_IMAGE",
                rule_applied=True,
            )

        if self._is_ambiguous_short_fragment(latest_user_text, intent=intent, route=route):
            return AgentDecision(
                reply_text=self._render_template("ask_ambiguous_short_fragment"),
                intent="address",
                route_reason="ambiguous_short_fragment",
                reply_goal="追问地区",
                media_plan="none",
                reply_source="rule",
                rule_id="ADDR_AMBIGUOUS_SHORT_FRAGMENT",
                rule_applied=True,
            )

        # 追问检测：优先走 LLM
        if self._is_follow_up_question(latest_user_text, conversation_history):
            return self._decide_llm_reply(
                latest_user_text=latest_user_text,
                intent=intent,
                route_reason=route_reason,
                conversation_history=conversation_history,
                session_state=session_state,
                rule_id="LLM_FOLLOW_UP",
            )

        # 规则外：先知识库，未命中再 LLM
        if self.use_knowledge_first:
            kb_detail = self.knowledge_service.find_answer_detail(
                latest_user_text,
                threshold=self.knowledge_threshold,
            )
            kb_blocked_by_polite_guard = bool(kb_detail.get("blocked_by_polite_guard", False))
            kb_polite_guard_reason = str(kb_detail.get("polite_guard_reason", "") or "")
            if kb_detail.get("matched"):
                kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
                kb_tags = {
                    str(tag).strip()
                    for tag in (kb_detail.get("tags", []) or [])
                    if str(tag).strip()
                }
                force_direct_kb = kb_intent == "service_hours" or "营业时间" in kb_tags
                # 场景4：低置信度（0.5-0.7）走 LLM
                confidence = kb_detail.get("confidence", "high")
                if confidence in ["low", "medium"] and not force_direct_kb:
                    # 使用知识库答案作为参考，但让 LLM 结合上下文重新生成
                    return self._decide_llm_reply(
                        latest_user_text=latest_user_text,
                        intent=intent,
                        route_reason=route_reason,
                        conversation_history=conversation_history,
                        session_state=session_state,
                        kb_match_score=kb_detail.get("score", 0.0),
                        kb_match_question=kb_detail.get("question", ""),
                        kb_match_mode=kb_detail.get("mode", ""),
                        kb_item_id=kb_detail.get("item_id", ""),
                        rule_id="LLM_LOW_CONFIDENCE_KB",
                    )

                # 高置信度（>=0.7），返回知识库答案
                kb_contact_trigger_type = self._resolve_kb_contact_trigger_type(
                    latest_user_text=latest_user_text,
                    kb_detail=kb_detail,
                )
                force_contact_image = bool(kb_contact_trigger_type)
                kb_answer = str(kb_detail.get("answer", "") or "").strip()
                kb_answers = [
                    str(x).strip()
                    for x in (kb_detail.get("answers", []) or [])
                    if str(x).strip()
                ]
                if kb_answer and kb_answer not in kb_answers:
                    kb_answers.insert(0, kb_answer)

                selected_answer, selected_index, exhausted = self._select_kb_variant_answer(
                    answers=kb_answers,
                    user_state=user_state,
                    user_id_hash=user_id_hash,
                )
                if selected_answer:
                    return AgentDecision(
                        reply_text=selected_answer,
                        intent=intent,
                        route_reason=route_reason,
                        reply_goal="解答",
                        media_plan="contact_image" if force_contact_image else "none",
                        reply_source="knowledge",
                        rule_id="KB_MATCH_CONTACT_IMAGE" if force_contact_image else "KB_MATCH",
                        rule_applied=False,
                        kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
                        kb_match_question=str(kb_detail.get("question", "") or ""),
                        kb_match_mode=str(kb_detail.get("mode", "") or ""),
                        kb_item_id=str(kb_detail.get("item_id", "") or ""),
                        kb_variant_total=len(kb_answers),
                        kb_variant_selected_index=selected_index,
                        kb_variant_fallback_llm=False,
                        kb_confident=True,
                        kb_blocked_by_polite_guard=False,
                        kb_polite_guard_reason="",
                        force_contact_image=force_contact_image,
                        kb_contact_trigger_type=kb_contact_trigger_type,
                    )

                if exhausted:
                    rewrite_prompt = self._build_kb_variant_fallback_prompt(
                        latest_user_text=latest_user_text,
                        kb_question=str(kb_detail.get("question", "") or ""),
                        kb_answer=kb_answer or (kb_answers[0] if kb_answers else ""),
                    )
                    return self._decide_llm_reply(
                        latest_user_text=latest_user_text,
                        intent=intent,
                        route_reason=route_reason,
                        conversation_history=conversation_history,
                        session_state=session_state,
                        kb_blocked_by_polite_guard=False,
                        kb_polite_guard_reason="",
                        user_message_override=rewrite_prompt,
                        rule_id="LLM_KB_VARIANT_FALLBACK",
                        kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
                        kb_match_question=str(kb_detail.get("question", "") or ""),
                        kb_match_mode=str(kb_detail.get("mode", "") or ""),
                        kb_item_id=str(kb_detail.get("item_id", "") or ""),
                        kb_variant_total=len(kb_answers),
                        kb_variant_selected_index=-1,
                        kb_variant_fallback_llm=True,
                        kb_confident=True,
                    )

        return self._decide_llm_reply(
            latest_user_text=latest_user_text,
            intent=intent,
            route_reason=route_reason,
            conversation_history=conversation_history,
            session_state=session_state,
            kb_blocked_by_polite_guard=kb_blocked_by_polite_guard,
            kb_polite_guard_reason=kb_polite_guard_reason,
        )

    def _decide_media_placeholder_reply(
        self,
        latest_user_text: str,
        route_reason: str,
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        text = re.sub(r"\s+", "", str(latest_user_text or ""))
        if text == "[图片]":
            reply_text = self._select_media_placeholder_reply(
                pool=list(IMAGE_MEDIA_REPLY_POOL),
                user_state=user_state,
                user_id_hash=user_id_hash,
            )
            return AgentDecision(
                reply_text=reply_text,
                intent="price",
                route_reason="media_image_price_reply",
                reply_goal="解答",
                media_plan="none",
                reply_source="knowledge",
                rule_id="MEDIA_IMAGE_REPLY",
                rule_applied=True,
                kb_variant_total=len(IMAGE_MEDIA_REPLY_POOL),
                kb_variant_selected_index=-1,
                kb_variant_fallback_llm=False,
                kb_confident=True,
            )
        if text == "[视频]":
            reply_text = self._select_media_placeholder_reply(
                pool=list(VIDEO_MEDIA_REPLY_POOL),
                user_state=user_state,
                user_id_hash=user_id_hash,
            )
            return AgentDecision(
                reply_text=reply_text,
                intent="price",
                route_reason="media_video_price_reply",
                reply_goal="解答",
                media_plan="none",
                reply_source="knowledge",
                rule_id="MEDIA_VIDEO_REPLY",
                rule_applied=True,
                kb_variant_total=len(VIDEO_MEDIA_REPLY_POOL),
                kb_variant_selected_index=-1,
                kb_variant_fallback_llm=False,
                kb_confident=True,
            )
        if text == "[表情]":
            reply_text = self._select_media_placeholder_reply(
                pool=list(EMOJI_MEDIA_REPLY_POOL),
                user_state=user_state,
                user_id_hash=user_id_hash,
            )
            return AgentDecision(
                reply_text=reply_text,
                intent="general",
                route_reason="media_emoji_reply",
                reply_goal="解答",
                media_plan="none",
                reply_source="knowledge",
                rule_id="MEDIA_EMOJI_REPLY",
                rule_applied=True,
                kb_variant_total=len(EMOJI_MEDIA_REPLY_POOL),
                kb_variant_selected_index=-1,
                kb_variant_fallback_llm=False,
                kb_confident=True,
            )
        return None

    def _select_media_placeholder_reply(
        self,
        pool: List[str],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> str:
        selected_answer, _selected_index, exhausted = self._select_kb_variant_answer(
            answers=pool,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        reply_text = selected_answer or (pool[0] if pool else "")
        if not reply_text and pool:
            reply_text = pool[0]
        if exhausted and pool:
            reply_text = random.choice(pool)
        if reply_text:
            self._remember_selected_kb_answer(
                user_state=user_state,
                user_id_hash=user_id_hash,
                answer_text=reply_text,
            )
        return reply_text

    def _decide_llm_reply(
        self,
        latest_user_text: str,
        intent: str,
        route_reason: str,
        conversation_history: List[Dict[str, str]],
        session_state: Optional[Dict[str, Any]] = None,
        kb_blocked_by_polite_guard: bool = False,
        kb_polite_guard_reason: str = "",
        user_message_override: str = "",
        rule_id: str = "LLM_GENERAL",
        kb_match_score: float = 0.0,
        kb_match_question: str = "",
        kb_match_mode: str = "",
        kb_item_id: str = "",
        kb_variant_total: int = 0,
        kb_variant_selected_index: int = -1,
        kb_variant_fallback_llm: bool = False,
        kb_confident: bool = False,
        allow_address_guardrails: bool = True,
    ) -> AgentDecision:
        self._current_prompt_conversation_history = conversation_history or []
        composed_prompt, prompt_meta = self._build_general_llm_prompt(latest_user_text)
        self.llm_service.set_system_prompt(composed_prompt)
        effective_user_message = user_message_override or latest_user_text
        conversation_state = prompt_meta.get("conversation_state", {}) if isinstance(prompt_meta, dict) else {}
        if (
            not user_message_override
            and bool(prompt_meta.get("standard_reply_hit", False))
            and str(prompt_meta.get("standard_reply_answer", "") or "").strip()
        ):
            effective_user_message = (
                f"用户刚问：{latest_user_text}\n"
                f"高置信标准话术核心结论：{str(prompt_meta.get('standard_reply_answer', '') or '').strip()}\n"
                "请严格保留关键事实、数字、时间或区间，再改写成自然的客服回复。"
            )
        if (
            not user_message_override
            and str(prompt_meta.get("standard_reply_intent", "") or "") == "appointment"
            and str(conversation_state.get("last_answer_type", "") or "") == "appointment"
        ):
            effective_user_message = (
                f"用户刚问：{latest_user_text}\n"
                "用户上一轮已经知道需要预约了，这一轮是在追问具体怎么预约。\n"
                "请直接说明下一步怎么操作，避免重复“我们是预约制的呢”。"
            )
        direct_standard_reply = (
            bool(prompt_meta.get("standard_reply_hit", False))
            and str(prompt_meta.get("standard_reply_intent", "") or "") in {"service_hours", "lifespan"}
            and str(prompt_meta.get("standard_reply_answer", "") or "").strip()
        )
        success, result = self.llm_service.generate_reply_sync(
            user_message=effective_user_message,
            conversation_history=conversation_history,
        )
        model_name = self.llm_service.get_current_model_name()
        if not success:
            return AgentDecision(
                reply_text=self._render_template("llm_fallback"),
                intent=intent,
                route_reason=route_reason,
                reply_goal="解答",
                media_plan="none",
                reply_source="fallback",
                rule_id="LLM_FALLBACK",
                rule_applied=False,
                llm_model=model_name,
                llm_fallback_reason=str(result or ""),
                kb_match_score=kb_match_score,
                kb_match_question=kb_match_question,
                kb_match_mode=kb_match_mode,
                kb_item_id=kb_item_id,
                kb_variant_total=kb_variant_total,
                kb_variant_selected_index=kb_variant_selected_index,
                kb_variant_fallback_llm=kb_variant_fallback_llm,
                kb_confident=kb_confident,
                kb_blocked_by_polite_guard=kb_blocked_by_polite_guard,
                kb_polite_guard_reason=kb_polite_guard_reason,
                reply_mode=self.reply_mode,
                standard_reply_hit=bool(prompt_meta.get("standard_reply_hit", False)),
                standard_reply_question=str(prompt_meta.get("standard_reply_question", "") or ""),
                standard_reply_confidence=str(prompt_meta.get("standard_reply_confidence", "") or ""),
                standard_reply_intent=str(prompt_meta.get("standard_reply_intent", "") or ""),
                brand_knowledge_used=bool(prompt_meta.get("brand_knowledge_used", False)),
            )

        if direct_standard_reply:
            llm_reply = self._normalize_reply_text(str(prompt_meta.get("standard_reply_answer", "") or ""))
        else:
            llm_reply = self._normalize_reply_text(result)
        llm_reply = self._apply_llm_reply_guardrails(
            latest_user_text=latest_user_text,
            reply_text=llm_reply,
            session_state=session_state or {},
            conversation_history=conversation_history,
            allow_address_guardrails=allow_address_guardrails,
        )

        return AgentDecision(
            reply_text=llm_reply,
            intent=intent,
            route_reason=route_reason,
            reply_goal="解答",
            media_plan="none",
            reply_source="llm",
            rule_id=rule_id,
            rule_applied=False,
            llm_model=model_name,
            kb_match_score=kb_match_score,
            kb_match_question=kb_match_question,
            kb_match_mode=kb_match_mode,
            kb_item_id=kb_item_id,
            kb_variant_total=kb_variant_total,
            kb_variant_selected_index=kb_variant_selected_index,
            kb_variant_fallback_llm=kb_variant_fallback_llm,
            kb_confident=kb_confident,
            kb_blocked_by_polite_guard=kb_blocked_by_polite_guard,
            kb_polite_guard_reason=kb_polite_guard_reason,
            reply_mode=self.reply_mode,
            standard_reply_hit=bool(prompt_meta.get("standard_reply_hit", False)),
            standard_reply_question=str(prompt_meta.get("standard_reply_question", "") or ""),
            standard_reply_confidence=str(prompt_meta.get("standard_reply_confidence", "") or ""),
            standard_reply_intent=str(prompt_meta.get("standard_reply_intent", "") or ""),
            brand_knowledge_used=bool(prompt_meta.get("brand_knowledge_used", False)),
        )

    def _select_kb_variant_answer(
        self,
        answers: List[str],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Tuple[str, int, bool]:
        candidates: List[str] = []
        seen: set[str] = set()
        for raw in answers or []:
            text = str(raw or "").strip()
            if not text:
                continue
            norm = self._normalize_for_dedupe(text)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            candidates.append(text)
            if len(candidates) >= 5:
                break
        if not candidates:
            return "", -1, False

        previous = self.summarize_recent_assistant_hashes_from_logs(user_id_hash=user_id_hash, limit=80)
        previous |= set(user_state.get("recent_reply_hashes", []) or [])
        for idx, candidate in enumerate(candidates):
            if self._normalize_for_dedupe(candidate) not in previous:
                return candidate, idx, False
        return "", -1, True

    def _remember_selected_kb_answer(
        self,
        user_state: Dict[str, Any],
        user_id_hash: str,
        answer_text: str,
    ) -> None:
        normalized = self._normalize_for_dedupe(answer_text)
        if not normalized:
            return

        recent_hashes = list(user_state.get("recent_reply_hashes", []) or [])
        recent_hashes.append(normalized)
        if len(recent_hashes) > 40:
            recent_hashes = recent_hashes[-40:]
        user_state["recent_reply_hashes"] = recent_hashes

        if user_id_hash:
            self.memory_store.update_user_state(user_id_hash, user_state)
            self.memory_store.save()

    def _build_kb_variant_fallback_prompt(self, latest_user_text: str, kb_question: str, kb_answer: str) -> str:
        return (
            f"用户刚问：{latest_user_text}\n"
            f"命中的知识库问题：{kb_question}\n"
            f"核心结论：{kb_answer}\n"
            "请保持核心结论不变，改写成结论先行、完整自然的客服回复。"
        )

    def _rewrite_if_repeated(
        self,
        reply_text: str,
        latest_user_text: str,
        conversation_history: List[Dict[str, str]],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Tuple[str, bool]:
        normalized = self._normalize_for_dedupe(reply_text)
        if not normalized:
            return reply_text, False

        previous = self.summarize_recent_assistant_hashes_from_logs(user_id_hash=user_id_hash, limit=40)
        memory_hashes = set(user_state.get("recent_reply_hashes", []) or [])
        if memory_hashes:
            previous |= memory_hashes
        if normalized not in previous:
            return reply_text, False

        # 优先让 LLM 改写，最多 2 次；仍重复则走去重池兜底。
        rewrite_prompt = (
            f"用户刚问：{latest_user_text}\n"
            f"下面这句客服话术和历史重复，请保留核心意思但换一种自然表达：{reply_text}"
        )
        composed_prompt, _ = self._build_general_llm_prompt(latest_user_text)
        self.llm_service.set_system_prompt(composed_prompt)

        for _ in range(2):
            ok, result = self.llm_service.generate_reply_sync(
                user_message=rewrite_prompt,
                conversation_history=conversation_history,
            )
            if not ok:
                continue
            candidate = self._normalize_reply_text(result)
            if self._normalize_for_dedupe(candidate) not in previous:
                return candidate, True
            rewrite_prompt = f"仍重复，请再次改写这句客服回复：{candidate}"

        fallback = self._avoid_repeat(user_state, reply_text)
        return fallback, self._normalize_for_dedupe(fallback) != normalized

    def _plan_media_items(
        self,
        session_id: str,
        text: str,
        intent: str,
        route: Dict[str, Any],
        route_reason: str,
        media_plan: str,
        session_state: Dict[str, Any],
        user_state: Dict[str, Any],
        force_contact_image: bool = False,
    ) -> Tuple[List[Dict[str, Any]], str]:
        items: List[Dict[str, Any]] = []
        skip_reason = ""
        target_store = route.get("target_store", "unknown")
        if media_plan == "address_image" and target_store in ("", "unknown"):
            target_store = str(session_state.get("last_target_store", "") or "unknown")
        reason = route_reason or route.get("reason", "unknown")
        detected_region = route.get("detected_region", "") or ""

        if media_plan == "address_image":
            if target_store == "unknown":
                skip_reason = "address_target_unknown"
            item, reason_hint = self._queue_address_image(
                session_id=session_id,
                session_state=session_state,
                target_store=target_store,
                route_reason=reason,
                detected_region=detected_region,
            )
            if item:
                items.append(item)
            elif reason_hint:
                skip_reason = reason_hint

        if media_plan == "contact_image" and not items:
            item, reason_hint = self._queue_contact_image(
                session_id=session_id,
                text=text,
                intent=intent,
                reason=reason,
                route=route,
                session_state=session_state,
                force_contact_image=force_contact_image,
            )
            if item:
                items.append(item)
            elif reason_hint and not skip_reason:
                skip_reason = reason_hint

        # delayed_video 不即时发送，仍由发送回执推进。
        return items, skip_reason

    def _queue_address_image(
        self,
        session_id: str,
        session_state: Dict[str, Any],
        target_store: str,
        route_reason: str,
        detected_region: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        if target_store == "unknown":
            return None, "address_target_unknown"

        image_path = self._pick_address_image(target_store)
        if not image_path:
            return None, "address_image_missing"

        store = self.knowledge_service.get_store_display(target_store)

        return (
            {
                "type": "address_image",
                "path": image_path,
                "target_store": target_store,
                "store_name": store.get("store_name", ""),
                "store_address": store.get("store_address", ""),
                "detected_region": detected_region,
                "route_reason": route_reason,
            },
            "",
        )

    def _queue_contact_image(
        self,
        session_id: str,
        text: str,
        intent: str,
        reason: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
        force_contact_image: bool = False,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        if not self._contact_images:
            return None, "contact_image_missing"

        whitelist = self._is_media_whitelist_session(session_id)
        if not whitelist:
            sent_count = int(session_state.get("contact_image_sent_count", 0) or 0)
            if sent_count >= CONTACT_IMAGE_MAX_SEND:
                return None, "contact_image_already_sent"

        if force_contact_image or reason == "out_of_coverage" or intent in ("contact", "purchase"):
            return (
                {
                    "type": "contact_image",
                    "path": random.choice(self._contact_images),
                    "detected_region": route.get("detected_region", "") or route_region(reason, text),
                    "route_reason": reason,
                    "target_store": route.get("target_store", ""),
                },
                "",
            )

        return None, "contact_image_not_applicable"

    def _resolve_kb_contact_trigger_type(self, latest_user_text: str, kb_detail: Dict[str, Any]) -> str:
        normalized_text = re.sub(r"\s+", "", (latest_user_text or ""))
        if any(keyword in normalized_text for keyword in CONTACT_TRIGGER_KEYWORDS):
            if any(keyword in normalized_text for keyword in APPOINTMENT_PRIORITY_KEYWORDS):
                return "appointment"
            return "shipping"

        tags = kb_detail.get("tags", [])
        if isinstance(tags, list):
            normalized_tags = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
            if "预约" in normalized_tags:
                return "appointment"
            if any(tag.lower() in normalized_tags for tag in CONTACT_TRIGGER_TAGS):
                return "shipping"

        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        if kb_intent in CONTACT_TRIGGER_INTENTS:
            return "appointment"
        return ""

    def _looks_like_appointment_query(self, text: str) -> bool:
        normalized_text = re.sub(r"\s+", "", (text or ""))
        if not normalized_text:
            return False
        return any(keyword in normalized_text for keyword in APPOINTMENT_PRIORITY_KEYWORDS)

    def _is_contact_image_sent_for_current_geo(self, session_state: Dict[str, Any]) -> bool:
        return int(session_state.get("contact_image_sent_count", 0) or 0) > 0

    def _has_both_images_sent(self, session_state: Dict[str, Any]) -> bool:
        return (
            int(session_state.get("address_image_sent_count", 0) or 0) > 0
            and int(session_state.get("contact_image_sent_count", 0) or 0) > 0
        )

    def _sync_media_state_from_conversation_log(
        self,
        session_id: str,
        user_hash: str,
        session_state: Dict[str, Any],
    ) -> None:
        user_summary = self.summarize_user_media_from_logs(user_id_hash=user_hash)
        session_state["address_image_sent_count"] = int(user_summary.get("address_image_sent_count", 0) or 0)
        session_state["contact_image_sent_count"] = int(user_summary.get("contact_image_sent_count", 0) or 0)
        session_state["address_image_last_sent_at_by_store"] = dict(user_summary.get("address_image_last_sent_at_by_store", {}) or {})
        session_state["sent_address_stores"] = list(user_summary.get("sent_address_stores", []) or [])
        session_state["contact_image_last_sent_at"] = str(user_summary.get("contact_image_last_sent_at", "") or "")

        latest_store = str(user_summary.get("last_target_store", "") or "").strip()
        if latest_store:
            session_state["last_target_store"] = latest_store

        session_video = self.summarize_session_video_from_log(session_id=session_id)
        session_state["session_video_armed"] = bool(session_video.get("contact_sent"))
        session_state["session_video_sent"] = bool(
            session_video.get("first_reply_video_sent") or session_video.get("contact_followup_video_sent")
        )
        session_state["session_post_contact_reply_count"] = int(session_video.get("assistant_reply_count_after_contact", 0) or 0)
        session_state["session_user_message_count_after_contact"] = int(session_video.get("user_message_count_after_contact", 0) or 0)

    def _sanitize_pending_required_media(
        self,
        items: Any,
        latest_planned: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        latest_address_targets = {
            str(item.get("target_store", "") or "")
            for item in (latest_planned or [])
            if isinstance(item, dict) and str(item.get("type", "")) == "address_image"
        }
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            media_type = str(raw.get("type", "") or "")
            if media_type not in REQUIRED_MEDIA_TYPES:
                continue
            item = copy.deepcopy(raw)
            if media_type == "address_image":
                target_store = str(item.get("target_store", "") or "")
                if latest_address_targets and target_store and target_store not in latest_address_targets:
                    continue
            item["pending_media_id"] = self._pending_media_key(item)
            item["pending_required"] = True
            sanitized.append(item)
        return sanitized

    def _remove_pending_required_media(self, session_state: Dict[str, Any], media_item: Dict[str, Any]) -> None:
        media_type = str((media_item or {}).get("type", "") or "")
        media_key = self._pending_media_key(media_item)
        pending_items = []
        for item in session_state.get("pending_required_media", []) or []:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "") or "")
            if item_type != media_type:
                pending_items.append(item)
                continue
            if self._pending_media_key(item) == media_key:
                continue
            pending_items.append(item)
        session_state["pending_required_media"] = pending_items
        session_state["pending_required_media_updated_at"] = datetime.now().isoformat()

    def _pending_media_key(self, media_item: Dict[str, Any]) -> str:
        media_type = str((media_item or {}).get("type", "") or "")
        if media_type == "address_image":
            return f"address_image:{str((media_item or {}).get('target_store', '') or '')}"
        if media_type == "contact_image":
            return "contact_image"
        return f"{media_type}:{str((media_item or {}).get('path', '') or '')}"

    def summarize_user_media_from_logs(self, user_id_hash: str) -> Dict[str, Any]:
        summary = {
            "address_image_sent_count": 0,
            "contact_image_sent_count": 0,
            "address_image_last_sent_at_by_store": {},
            "sent_address_stores": [],
            "contact_image_last_sent_at": "",
            "last_target_store": "",
        }
        if not user_id_hash:
            return summary

        address_ts_map: Dict[str, datetime] = {}
        sent_address_stores: set[str] = set()
        last_target_store = ""
        last_target_store_ts: Optional[datetime] = None
        contact_last_ts: Optional[datetime] = None

        for log_path in self.conversation_log_dir.glob("*.jsonl"):
            records = self._scan_session_media_records(log_path=log_path, user_id_hash=user_id_hash)
            for rec in records:
                media_type = rec.get("type", "")
                ts = self._parse_iso(str(rec.get("timestamp", "") or ""))
                if media_type == "address_image":
                    summary["address_image_sent_count"] += 1
                    target_store = str(rec.get("target_store", "") or "")
                    if target_store:
                        sent_address_stores.add(target_store)
                        if ts and (target_store not in address_ts_map or ts > address_ts_map[target_store]):
                            address_ts_map[target_store] = ts
                        if ts and (not last_target_store_ts or ts > last_target_store_ts):
                            last_target_store = target_store
                            last_target_store_ts = ts
                        elif not ts and not last_target_store:
                            last_target_store = target_store
                elif media_type == "contact_image":
                    summary["contact_image_sent_count"] += 1
                    if ts and (not contact_last_ts or ts > contact_last_ts):
                        contact_last_ts = ts

        summary["sent_address_stores"] = sorted(sent_address_stores)
        summary["last_target_store"] = last_target_store
        summary["address_image_last_sent_at_by_store"] = {
            store: dt.isoformat() for store, dt in address_ts_map.items()
        }
        if contact_last_ts:
            summary["contact_image_last_sent_at"] = contact_last_ts.isoformat()
        return summary

    def _store_recommend_display_name(self, target_store: str, fallback_name: str = "") -> str:
        if target_store == "beijing_chaoyang":
            return "北京朝阳店"
        return str(fallback_name or "门店")

    def summarize_user_turns_from_logs(self, user_id_hash: str) -> Dict[str, int]:
        summary = {
            "event_count": 0,
            "user_message_count": 0,
            "assistant_reply_count": 0,
        }
        if not user_id_hash:
            return summary

        for log_path in self.conversation_log_dir.glob("*.jsonl"):
            try:
                for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if str(record.get("user_id_hash", "") or "") != user_id_hash:
                        continue
                    summary["event_count"] += 1
                    event_type = str(record.get("event_type", "") or "")
                    if event_type == "user_message":
                        summary["user_message_count"] += 1
                    elif event_type == "assistant_reply":
                        summary["assistant_reply_count"] += 1
            except Exception:
                continue
        return summary

    def is_user_first_turn_global(self, user_id_hash: str) -> bool:
        turns = self.summarize_user_turns_from_logs(user_id_hash=user_id_hash)
        return int(turns.get("event_count", 0) or 0) == 0

    def build_first_turn_video_items(self, session_id: str) -> List[Dict[str, Any]]:
        """为首轮固定承接生成视频计划，不触发规则/知识库/LLM决策。"""
        if self.reply_mode == REPLY_MODE_LLM_DIRECT:
            return []
        session_video = self.summarize_session_video_from_log(session_id=session_id)
        if session_video.get("first_reply_video_sent"):
            return []
        video_item = self._build_video_media_item(trigger_source="first_reply")
        if not video_item:
            return []
        video_item["first_turn_media"] = True
        return [video_item]

    def _populate_first_turn_media_plan(
        self,
        session_id: str,
        user_name: str,
        decision: AgentDecision,
    ) -> None:
        del user_name
        if self.reply_mode == REPLY_MODE_LLM_DIRECT:
            decision.first_turn_image_items = []
            decision.first_turn_video_items = []
            decision.first_turn_text_required = False
            decision.first_turn_retry_policy = {}
            return
        decision.first_turn_image_items = []
        decision.first_turn_video_items = []
        decision.first_turn_text_required = bool(decision.is_first_turn_global)
        decision.first_turn_retry_policy = {}

        if not decision.is_first_turn_global:
            return

        image_items = [
            dict(item)
            for item in (decision.media_items or [])
            if isinstance(item, dict) and str(item.get("type", "") or "") in ("address_image", "contact_image")
        ]
        for item in image_items:
            item["disable_compensation"] = True
            item["first_turn_media"] = True

        video_items: List[Dict[str, Any]] = []
        # 只要是全局首轮，就优先挂上首轮视频，避免普通问候场景因未命中图片或开关关闭而跳过。
        should_attach_first_reply_video = bool(decision.is_first_turn_global)
        if should_attach_first_reply_video:
            session_video = self.summarize_session_video_from_log(session_id=session_id)
            if not session_video.get("first_reply_video_sent"):
                video_item = self._build_video_media_item(trigger_source="first_reply")
                if video_item:
                    video_item["first_turn_media"] = True
                    video_items.append(video_item)

        decision.first_turn_image_items = image_items
        decision.first_turn_video_items = video_items
        decision.first_turn_retry_policy = {
            "image_retry_once_deferred": True,
            "video_retry_once_inline": True,
        }

    def summarize_session_video_from_log(self, session_id: str) -> Dict[str, Any]:
        summary = {
            "contact_sent": False,
            "first_reply_video_sent": False,
            "contact_followup_video_sent": False,
            "assistant_reply_count_after_contact": 0,
            "user_message_count_after_contact": 0,
        }
        lines = self._read_session_log_records(session_id)
        if not lines:
            return summary

        latest_contact_idx = -1
        for idx, record in enumerate(lines):
            if not isinstance(record, dict):
                continue
            if str(record.get("event_type", "") or "") != "media_result":
                continue
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if str(payload.get("type", "") or "") == "contact_image" and bool(payload.get("success")):
                latest_contact_idx = idx

        if latest_contact_idx < 0:
            return summary
        summary["contact_sent"] = True

        reply_count = 0
        user_count = 0
        for idx in range(latest_contact_idx + 1, len(lines)):
            record = lines[idx]
            if not isinstance(record, dict):
                continue
            event_type = str(record.get("event_type", "") or "")
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            if event_type == "media_result":
                if str(payload.get("type", "") or "") == "delayed_video" and bool(payload.get("success")):
                    trigger_source = str(payload.get("trigger_source", "") or "contact_followup")
                    if trigger_source == "first_reply":
                        summary["first_reply_video_sent"] = True
                    elif trigger_source == "contact_followup":
                        summary["contact_followup_video_sent"] = True
            elif event_type == "user_message":
                user_count += 1
            elif event_type == "assistant_reply":
                sent_types = payload.get("round_media_sent_types", [])
                if isinstance(sent_types, list) and "contact_image" in sent_types:
                    continue
                reply_count += 1

        summary["assistant_reply_count_after_contact"] = reply_count
        summary["user_message_count_after_contact"] = user_count
        return summary

    def _build_video_media_item(self, trigger_source: str) -> Optional[Dict[str, Any]]:
        video_path = self._pick_video_media()
        if not video_path:
            return None
        return {
            "type": "delayed_video",
            "path": video_path,
            "trigger_source": str(trigger_source or ""),
        }

    def _read_session_log_records(self, session_id: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for log_path in self._session_log_candidates(session_id):
            try:
                for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        continue
                    if str(record.get("session_id", "") or "") != session_id:
                        continue
                    records.append(record)
            except Exception:
                continue
        return records

    def _scan_session_media_records(self, log_path: Path, user_id_hash: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        pending_attempts: Dict[str, List[Dict[str, Any]]] = {
            "address_image": [],
            "contact_image": [],
            "delayed_video": [],
        }
        try:
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                if str(record.get("user_id_hash", "") or "") != user_id_hash:
                    continue
                event_type = str(record.get("event_type", "") or "")
                payload = record.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}

                if event_type == "media_attempt":
                    media_type = str(payload.get("type", "") or "")
                    if media_type in pending_attempts:
                        pending_attempts[media_type].append(payload)
                    continue

                if event_type != "media_result":
                    continue

                media_type = str(payload.get("type", "") or "")
                if media_type not in pending_attempts:
                    continue
                if not bool(payload.get("success")):
                    queue = pending_attempts.get(media_type, [])
                    if queue:
                        queue.pop(0)
                    continue

                attempt_payload = {}
                queue = pending_attempts.get(media_type, [])
                if queue:
                    attempt_payload = queue.pop(0)

                path = str((attempt_payload or {}).get("path", "") or "")
                target_store = str((attempt_payload or {}).get("target_store", "") or "").strip()
                if media_type == "address_image" and not target_store:
                    target_store = self._infer_store_from_image_path(path)

                records.append(
                    {
                        "type": media_type,
                        "timestamp": str(record.get("timestamp", "") or ""),
                        "path": path,
                        "target_store": target_store,
                        "store_name": str((attempt_payload or {}).get("store_name", "") or ""),
                        "store_address": str((attempt_payload or {}).get("store_address", "") or ""),
                        "detected_region": str((attempt_payload or {}).get("detected_region", "") or ""),
                        "route_reason": str((attempt_payload or {}).get("route_reason", "") or ""),
                    }
                )
        except Exception:
            return records
        return records

    def _session_log_file(self, session_id: str) -> Path:
        candidates = self._session_log_candidates(session_id)
        if candidates:
            return candidates[0]
        safe = re.sub(r"[^0-9A-Za-z_\-]", "_", session_id or "unknown")
        return self.conversation_log_dir / f"{safe}.jsonl"

    def _session_log_candidates(self, session_id: str) -> List[Path]:
        safe = re.sub(r"[^0-9A-Za-z_\-]", "_", session_id or "unknown")
        legacy_path = self.conversation_log_dir / f"{safe}.jsonl"
        results: List[Path] = []
        if legacy_path.exists():
            results.append(legacy_path)

        for log_path in sorted(self.conversation_log_dir.glob("*.jsonl")):
            if log_path == legacy_path:
                continue
            try:
                for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        continue
                    if str(record.get("session_id", "") or "") == session_id:
                        results.append(log_path)
                        break
            except Exception:
                continue
        return results

    def _infer_store_from_image_path(self, media_path: str) -> str:
        name = Path(str(media_path or "")).name
        return self._infer_store_from_name(name)

    def _infer_store_from_name(self, name: str) -> str:
        raw = str(name or "")
        if not raw:
            return ""
        if "北京" in raw:
            return "beijing_chaoyang"
        if "徐汇" in raw or "徐家汇" in raw:
            return "sh_xuhui"
        if "静安" in raw:
            return "sh_jingan"
        if "虹口" in raw:
            return "sh_hongkou"
        if "五角场" in raw or "杨浦" in raw:
            return "sh_wujiaochang"
        if any(k in raw for k in ("人广", "人民广场", "黄浦", "黄埔")):
            return "sh_renmin"
        return ""

    def _pick_address_image(self, target_store: str) -> Optional[str]:
        pool = self._address_index.get(target_store, [])
        if not pool and target_store.startswith("sh_"):
            pool = self._address_index.get("sh_renmin", [])
        if not pool and target_store == "beijing_chaoyang":
            pool = self._address_index.get("beijing_chaoyang", [])
        if not pool:
            return None
        return random.choice(pool)

    def _pick_video_media(self) -> Optional[str]:
        if self._video_medias:
            return random.choice(self._video_medias)
        # 视频实际发送已统一走页面素材库；没有本地视频文件时，仍允许触发 delayed_video。
        return MATERIAL_LIBRARY_VIDEO_SENTINEL

    def summarize_recent_assistant_hashes_from_logs(self, user_id_hash: str, limit: int = 40) -> set[str]:
        if not user_id_hash:
            return set()
        entries: List[Tuple[Optional[datetime], str]] = []
        for log_path in sorted(self.conversation_log_dir.glob("*.jsonl")):
            try:
                for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if str(record.get("user_id_hash", "") or "") != user_id_hash:
                        continue
                    if str(record.get("event_type", "") or "") != "assistant_reply":
                        continue
                    payload = record.get("payload", {})
                    if not isinstance(payload, dict):
                        continue
                    text = str(payload.get("text", "") or "").strip()
                    if not text:
                        continue
                    norm = self._normalize_for_dedupe(text)
                    if not norm:
                        continue
                    ts = self._parse_iso(str(record.get("timestamp", "") or ""))
                    entries.append((ts, norm))
            except Exception:
                continue
        entries.sort(key=lambda item: (item[0] is None, item[0] or datetime.min))
        tail = entries[-max(1, int(limit or 1)) :]
        return {norm for _, norm in tail}

    def _is_media_whitelist_session(self, session_id: str) -> bool:
        return session_id in self._media_whitelist_sessions

    def _build_general_llm_prompt(self, latest_user_text: str) -> Tuple[str, Dict[str, Any]]:
        normalized_text = self.knowledge_service.normalize_user_text(latest_user_text)
        faq_detail = self.knowledge_service.find_answer_detail(normalized_text, threshold=self.knowledge_threshold)
        faq_examples = self._top_kb_examples(normalized_text, limit=3)
        faq_block = "\n".join([f"- 问：{q}\n  答：{a}" for q, a in faq_examples]) or "（当前无高相关标准话术）"
        enterprise_guard = self._enterprise_guard_doc_text or "（企业知识约束文档缺失，请按已有品牌口径稳妥回复）"
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
        brand_snippets = self._top_brand_knowledge_snippets(normalized_text, limit=3)
        brand_block = "\n\n".join(brand_snippets) if brand_snippets else "（当前无高相关品牌知识片段）"
        conversation_state = self._summarize_llm_conversation_state(
            latest_user_text=latest_user_text,
            conversation_history=getattr(self, "_current_prompt_conversation_history", []) or [],
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

    def _summarize_llm_conversation_state(
        self,
        latest_user_text: str,
        conversation_history: List[Dict[str, str]],
        standard_reply_intent: str = "",
    ) -> Dict[str, str]:
        history = conversation_history or []
        combined_text = " ".join(str(item.get("content", "") or "") for item in history[-6:])
        current_text = f"{combined_text} {latest_user_text}".strip()
        normalized = self.knowledge_service.normalize_user_text(current_text)

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
            last_answer_type = self._infer_answer_type(last_assistant)

        latest_norm = self.knowledge_service.normalize_user_text(latest_user_text)
        reply_goal = "自然承接并回答当前问题"
        avoid_repeat = "无"
        if empathy_need != "无":
            reply_goal = "先简短安慰共情，再给可行方案"
            avoid_repeat = "不要一上来就直接索要联系方式"
        elif self._looks_like_appointment_query(latest_norm):
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
        elif self._looks_like_appointment_query(latest_norm):
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
        if self._looks_like_appointment_query(latest_norm) and last_answer_type == "appointment":
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

    def _infer_answer_type(self, text: str) -> str:
        normalized = self.knowledge_service.normalize_user_text(text)
        if not normalized:
            return "未知"
        if any(token in normalized for token in ("愚园路", "汉口路", "花园路", "政通路", "漕溪北路", "建外soho", "亚洲大厦")):
            return "store_address"
        if any(token in normalized for token in ("上海有5家", "上海共有5家", "北京只有1家", "北京1家", "静安", "人民广场", "人广", "虹口", "五角场", "徐汇", "朝阳区")) and any(
            token in normalized for token in ("门店", "地址", "位置", "区域", "城市")
        ):
            return "address_general"
        if "预约" in normalized:
            return "appointment"
        if any(token in normalized for token in ("9:30", "18:00", "营业时间", "周一到周五")):
            return "service_hours"
        if any(token in normalized for token in ("3到5年", "3-5年", "三到五年")):
            return "lifespan"
        if any(token in normalized for token in ("远程定制", "不方便到店")):
            return "remote_support"
        if any(token in normalized for token in ("3000", "4000", "5000", "6000", "价格")):
            return "price"
        return "general"

    def _top_kb_examples(self, query: str, limit: int = 3) -> List[Tuple[str, str]]:
        q = self._normalize_for_dedupe(self.knowledge_service.normalize_user_text(query))
        if not q:
            return []

        scored: List[Tuple[float, Tuple[str, str]]] = []
        items = self.knowledge_service.get_all_items()
        for item in items:
            question = (item.question or "").strip()
            answer = (item.answer or "").strip()
            if not question or not answer:
                continue
            score = self._simple_overlap_score(q, self._normalize_for_dedupe(question))
            if score > 0:
                scored.append((score, (question, answer)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored[:limit]]

    def _top_brand_knowledge_snippets(self, query: str, limit: int = 3) -> List[str]:
        text = self._brand_knowledge_doc_text.strip()
        q = self._normalize_for_dedupe(self.knowledge_service.normalize_user_text(query))
        if not text or not q:
            return []

        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
        scored: List[Tuple[float, str]] = []
        for chunk in chunks:
            normalized_chunk = self._normalize_for_dedupe(self.knowledge_service.normalize_user_text(chunk))
            score = self._simple_overlap_score(q, normalized_chunk)
            if score > 0:
                scored.append((score, chunk[:360]))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def _simple_overlap_score(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            return 0.9
        sa = set(a)
        sb = set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def _normalize_reply_text(self, text: str) -> str:
        value = (text or "").strip()
        if not value:
            return self._render_template("general_empty")

        # 仅移除独立的聊天时间戳，避免把营业时间这类正常业务内容误删。
        value = re.sub(r"(?:\s+|^)(\d{1,2}:\d{2})(?:已读|未读|送达)?$", "", value).strip()
        value = " ".join(value.split())
        value = self._strip_inline_emoji_symbols(value)

        # 联系方式合规拦截
        if any(k in value for k in CONTACT_COMPLIANCE_BLOCK_KEYWORDS):
            value = "姐姐，您留个☎️方式，我来加您好友"
        elif any(k in value for k in SHIPPING_BLOCK_KEYWORDS):
            value = SHIPPING_BLOCK_REPLACEMENT

        if not value:
            value = "姐姐我在呢"
        value = value.rstrip("，,；; ")
        if not re.search(r"[。！？!?]$", value):
            value = f"{value}。"
        # 随机选择emoji
        emoji = random.choice(REPLY_EMOJI_POOL)
        return f"{value}{emoji}"

    def _apply_llm_reply_guardrails(
        self,
        latest_user_text: str,
        reply_text: str,
        session_state: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        allow_address_guardrails: bool = True,
    ) -> str:
        text = (latest_user_text or "").strip()
        reply = (reply_text or "").strip()
        state = session_state or {}
        history = conversation_history or []

        if self._contains_explicit_phone_number(reply):
            if self._has_price_priority(text):
                return self._render_guardrail_reply(PRICE_GUARDRAIL_SAFE_REPLY)
            if self._needs_empathy_remote_support(text):
                return self._render_guardrail_reply(EMPATHY_REMOTE_SUPPORT_FALLBACK)
            if any(token in text for token in ("外地", "不在上海", "不在北京", "不方便到店", "远程定制", "不能去上海", "不能来上海")):
                return self._render_guardrail_reply(REMOTE_SUPPORT_FACT_FALLBACK)
            return PHONE_LEAK_BLOCK_FALLBACK

        if self._contains_invalid_ma_teacher_claim(reply):
            if self._is_ma_teacher_direct_query(text):
                return MA_TEACHER_DIRECT_QUERY_FALLBACK
            cleaned_reply = self._strip_invalid_ma_teacher_service_clauses(reply)
            if cleaned_reply and cleaned_reply != reply:
                return cleaned_reply
            return MA_TEACHER_ROLE_FALLBACK

        if self._is_contact_fact_risk(text, reply):
            if self._has_price_priority(text):
                return self._render_guardrail_reply(PRICE_GUARDRAIL_SAFE_REPLY)
            if self._needs_empathy_remote_support(text):
                return self._render_guardrail_reply(EMPATHY_REMOTE_SUPPORT_FALLBACK)
            if any(token in text for token in ("外地", "不在上海", "不在北京", "不方便到店", "远程定制", "不能去上海", "不能来上海")):
                return self._render_guardrail_reply(REMOTE_SUPPORT_FACT_FALLBACK)
            return self._render_guardrail_reply(CONTACT_FACT_FALLBACK)

        if self._has_price_priority(text):
            if self._contains_low_price_quote(reply) or self._contains_invalid_price_channel(reply):
                return self._render_guardrail_reply(PRICE_GUARDRAIL_SAFE_REPLY)

        if allow_address_guardrails and self._is_address_fact_risk(text, reply, state, history):
            if self._is_address_unsupported_query(text):
                return self._render_guardrail_reply(ADDRESS_FACT_FALLBACK)
            store_key = self._resolve_guardrail_store_key(text, reply, state, history)
            if store_key:
                store = self.knowledge_service.get_store_display(store_key)
                store_name = str(store.get("store_name", "") or "门店")
                return self._normalize_reply_text(f"姐姐，{store_name}位置可以看图中圈圈的位置哦")
            if self._reply_contains_unsupported_address_detail(reply):
                return self._render_guardrail_reply(ADDRESS_FACT_FALLBACK)
            return self._render_guardrail_reply(ADDRESS_FACT_FALLBACK)

        if allow_address_guardrails and self._is_address_unsupported_query(text):
            return self._normalize_reply_text(ADDRESS_UNSUPPORTED_FALLBACK)
        if self._needs_empathy_remote_support(text) and not self._reply_has_empathy(reply):
            return self._normalize_reply_text(f"姐姐那您先注意休息，身体要紧，{reply.lstrip('姐姐，').lstrip('姐姐').strip()}")
        return reply_text

    def _needs_empathy_remote_support(self, text: str) -> bool:
        normalized = self.knowledge_service.normalize_user_text(text)
        if not normalized:
            return False
        return self._has_health_issue_context(normalized) and self._has_remote_visit_block_context(normalized)

    def _has_health_issue_context(self, normalized_text: str) -> bool:
        normalized = self.knowledge_service.normalize_user_text(normalized_text)
        if not normalized:
            return False
        health_tokens = (
            "摔了",
            "摔跤",
            "受伤",
            "腿伤",
            "腿现在",
            "腿脚不方便",
            "生病",
            "住院",
            "身体不方便",
        )
        return any(token in normalized for token in health_tokens)

    def _has_remote_visit_block_context(self, normalized_text: str) -> bool:
        normalized = self.knowledge_service.normalize_user_text(normalized_text)
        if not normalized:
            return False
        remote_tokens = (
            "不能去上海",
            "不能来上海",
            "不方便去上海",
            "不方便到店",
            "不方便去店",
            "去不了上海",
            "来不了上海",
            "外地",
        )
        return any(token in normalized for token in remote_tokens)

    def _reply_has_empathy(self, text: str) -> bool:
        normalized = self.knowledge_service.normalize_user_text(text)
        if not normalized:
            return False
        empathy_tokens = ("注意休息", "别着急", "先养好", "先好好休息", "要紧", "辛苦了", "先把身体顾好")
        return any(token in normalized for token in empathy_tokens)

    def _is_contact_fact_risk(self, text: str, reply_text: str) -> bool:
        normalized_text = re.sub(r"\s+", "", str(text or "")).lower()
        normalized_reply = re.sub(r"\s+", "", str(reply_text or "")).lower()
        if self._looks_like_direct_contact_request(text):
            return True
        if re.search(r"1[3-9]\d{9}", normalized_text):
            return True
        if any(k.lower() in normalized_text for k in CONTACT_INTENT_KEYWORDS):
            return True
        if any(k.lower() in normalized_reply for k in CONTACT_COMPLIANCE_BLOCK_KEYWORDS):
            return True
        return bool(re.search(r"1[3-9]\d{9}", normalized_reply))

    def _contains_low_price_quote(self, reply_text: str) -> bool:
        normalized_reply = re.sub(r"\s+", "", str(reply_text or "")).lower()
        if any(token in normalized_reply for token in PRICE_LOW_RISK_PHRASES):
            return True
        explicit_numbers = [int(num) for num in re.findall(r"(\d{3,6})", normalized_reply)]
        return any(number < 3000 for number in explicit_numbers)

    def _contains_invalid_price_channel(self, reply_text: str) -> bool:
        normalized_reply = re.sub(r"\s+", "", str(reply_text or "")).lower()
        return any(token in normalized_reply for token in INVALID_PRICE_CHANNEL_KEYWORDS)

    def _is_address_fact_risk(
        self,
        text: str,
        reply_text: str,
        session_state: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
    ) -> bool:
        normalized_text = re.sub(r"\s+", "", str(text or "")).lower()
        normalized_reply = re.sub(r"\s+", "", str(reply_text or "")).lower()
        if any(keyword in normalized_text for keyword in ADDRESS_FACT_QUERY_KEYWORDS):
            return True
        if any(keyword in normalized_reply for keyword in ADDRESS_REPLY_RISK_KEYWORDS):
            return True
        if self._resolve_guardrail_store_key(text, reply_text, session_state, conversation_history):
            return any(keyword in normalized_reply for keyword in ADDRESS_REPLY_RISK_KEYWORDS)
        return False

    def _reply_contains_unsupported_address_detail(self, reply_text: str) -> bool:
        normalized_reply = re.sub(r"\s+", "", str(reply_text or "")).lower()
        unsupported_keywords = ("几楼", "楼层", "导航", "路线", "坐什么车", "哪个出口", "哪一站", "电梯")
        return any(keyword in normalized_reply for keyword in unsupported_keywords)

    def _render_guardrail_reply(self, text: str) -> str:
        value = (text or "").strip().rstrip("，,；; ")
        if not re.search(r"[。！？!?]$", value):
            value = f"{value}。"
        emoji = random.choice(REPLY_EMOJI_POOL)
        return f"{value}{emoji}"

    def _contains_explicit_phone_number(self, text: str) -> bool:
        value = str(text or "")
        if not value:
            return False
        compact = re.sub(r"[^\d]", "", value)
        if re.search(r"1[3-9]\d{9}", compact):
            return True
        if re.search(r"(400|800)\d{7,}", compact):
            return True
        return False

    def _contains_invalid_ma_teacher_claim(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if "马老师" not in normalized:
            return False
        return any(keyword in normalized for keyword in MA_TEACHER_INVALID_SERVICE_KEYWORDS)

    def _is_ma_teacher_direct_query(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if "马老师" not in normalized:
            return False
        direct_query_markers = ("找", "做", "在哪", "可以", "能", "安排", "约", "吗", "？", "?")
        return normalized == "马老师" or any(marker in normalized for marker in direct_query_markers)

    def _strip_invalid_ma_teacher_service_clauses(self, text: str) -> str:
        original = str(text or "").strip()
        if not original:
            return original

        trailing_emoji = self._extract_trailing_known_reply_emoji(original)
        body = original[:-len(trailing_emoji)] if trailing_emoji and original.endswith(trailing_emoji) else original

        sentence_parts = re.split(r"([。！？!?])", body)
        kept_sentences: List[str] = []
        removed = False

        for idx in range(0, len(sentence_parts), 2):
            segment = sentence_parts[idx].strip()
            punctuation = sentence_parts[idx + 1] if idx + 1 < len(sentence_parts) else ""
            if not segment and not punctuation:
                continue
            sentence = f"{segment}{punctuation}".strip()
            if not sentence:
                continue
            if self._contains_invalid_ma_teacher_claim(sentence):
                removed = True
                continue
            kept_sentences.append(sentence)

        if not removed:
            return original

        cleaned = "".join(kept_sentences).strip()
        cleaned = re.sub(r"[，,、；;]\s*$", "", cleaned)
        cleaned = cleaned.rstrip("，,；; ")
        if cleaned and trailing_emoji and trailing_emoji not in cleaned[-len(trailing_emoji) - 2 :]:
            cleaned = f"{cleaned}{trailing_emoji}"
        return cleaned

    def _extract_trailing_known_reply_emoji(self, text: str) -> str:
        value = str(text or "")
        for emoji in sorted(REPLY_EMOJI_POOL, key=len, reverse=True):
            if value.endswith(emoji):
                return emoji
        return ""

    def _resolve_guardrail_store_key(
        self,
        text: str,
        reply_text: str,
        session_state: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
    ) -> str:
        store_key = str((session_state or {}).get("last_target_store", "") or "").strip()
        if store_key and store_key != "unknown":
            return store_key

        candidates = [
            str(text or ""),
            str(reply_text or ""),
            " ".join(str(item.get("content", "") or "") for item in conversation_history[-4:]),
        ]
        for candidate in candidates:
            resolved = self._infer_store_from_context_text(candidate)
            if resolved:
                return resolved
        return ""

    def _infer_store_from_context_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return ""
        if any(token in normalized for token in ("建外soho", "朝阳", "北京店", "北京门店")):
            return "beijing_chaoyang"
        if any(token in normalized for token in ("静安寺", "静安店", "静安门店", "静安")):
            return "sh_jingan"
        if any(token in normalized for token in ("人民广场", "人广", "黄浦", "黄埔")):
            return "sh_renmin"
        if any(token in normalized for token in ("虹口", "花园路")):
            return "sh_hongkou"
        if any(token in normalized for token in ("五角场", "杨浦", "政通路")):
            return "sh_wujiaochang"
        if any(token in normalized for token in ("徐汇", "徐家汇", "漕溪北路")):
            return "sh_xuhui"
        return ""

    def _is_address_unsupported_query(self, text: str) -> bool:
        value = (text or "").strip().lower()
        if not value:
            return False
        return any(keyword in value for keyword in ADDRESS_UNSUPPORTED_QUERY_KEYWORDS)

    def _strip_inline_emoji_symbols(self, text: str) -> str:
        cleaned = re.sub(
            r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\uFE0F\u200D]",
            "",
            text or "",
        )
        cleaned = re.sub(r"\s*[~～]+\s*", "到", cleaned)
        return cleaned

    def _avoid_repeat(self, user_state: Dict[str, Any], reply_text: str) -> str:
        normalized = self._normalize_for_dedupe(reply_text)
        if not normalized:
            return reply_text

        previous = set(user_state.get("recent_reply_hashes", []) or [])
        if normalized in previous and self._dedupe_reply_pool:
            return random.choice(self._dedupe_reply_pool)
        return reply_text

    def _normalize_for_dedupe(self, text: str) -> str:
        value = (text or "").strip().lower()
        value = re.sub(r"[^\w\u4e00-\u9fa5]", "", value)
        return value

    def _has_neg_shanghai_hint(self, text: str) -> bool:
        value = re.sub(r"\s+", "", (text or ""))
        if not value:
            return False
        return any(keyword in value for keyword in NEG_SHANGHAI_HINT_KEYWORDS)

    def _hash_user(self, text: str) -> str:
        return hashlib.md5((text or "unknown").encode("utf-8", errors="ignore")).hexdigest()[:10]

    def _parse_iso(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _render_template(self, key: str, **kwargs: Any) -> str:
        template = self._reply_templates.get(key)
        if not isinstance(template, str) or not template.strip():
            template = DEFAULT_REPLY_TEMPLATES.get(key, "")
        text = str(template or "").format_map(_SafeDict(kwargs))
        text = " ".join(text.split())
        if not text:
            # 随机选择emoji
            emoji = random.choice(REPLY_EMOJI_POOL)
            return self._render_template("general_empty") if key != "general_empty" else f"姐姐我在呢，关于假发有什么问题您都可以问我{emoji}"
        # 替换模板中的固定emoji为随机emoji
        text = self._randomize_template_emoji(text)
        return text

    def _randomize_template_emoji(self, text: str) -> str:
        """将模板中的固定emoji替换为随机emoji"""
        # 替换🌹为随机emoji
        if "🌹" in text:
            emoji = random.choice(REPLY_EMOJI_POOL)
            text = text.replace("🌹", emoji)
        return text


def route_region(route_reason: str, text: str) -> str:
    if route_reason != "out_of_coverage":
        return ""
    m = re.search(r"([\u4e00-\u9fa5]{2,8}(?:省|市|区|县|州|盟|旗))", text or "")
    if not m:
        return ""
    candidate = m.group(1)
    tail = (text or "")[m.end():m.end() + 1]
    if candidate.endswith("区") and tail in ("别", "分"):
        return ""
    if any(token in candidate for token in ("什么区", "哪个区", "哪些区")):
        return ""
    return candidate
