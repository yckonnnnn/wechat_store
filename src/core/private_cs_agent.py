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
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..data.memory_store import MemoryStore
from . import agent_media
from . import agent_llm_reply
from . import agent_rule_engine
from . import agent_contact_flow
from .intent_detector import IntentDetector
from .agent_guardrails import (
    apply_llm_reply_guardrails,
    build_reply_closure_info,
    mask_precise_address_for_output,
    normalize_reply_text,
)
from .business_hours import STANDARD_BUSINESS_HOURS_FACT, STANDARD_BUSINESS_HOURS_REPLY
from .agent_prompt_builder import build_general_llm_prompt, summarize_llm_conversation_state
from .agent_types import AgentDecision, MediaJudgeDecision, _SafeDict
from ..services.knowledge_service import KnowledgeService
from ..services.llm_service import LLMService
from ..services.conversation_logger import ConversationLogger
from ..utils.constants import BRAND_KNOWLEDGE_FILE
from .session_state_unified import UnifiedSessionState
from .deduplication import DeduplicationChecker


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
REMOTE_REGION_HINT_KEYWORDS = (
    "不在上海",
    "不是上海",
    "不去上海",
    "不在北京",
    "不是北京",
    "不去北京",
    "外地",
    "异地",
    "哈尔滨",
)
REMOTE_VISIT_BLOCK_KEYWORDS = (
    "没空去店里",
    "不方便到店",
    "不能到店",
    "无法到店",
    "不方便去店里",
    "没办法到店",
)
REMOTE_SHIPPING_QUERY_KEYWORDS = (
    "邮寄",
    "快递",
    "寄过去",
    "寄吗",
    "能不能邮寄",
    "可以快递吗",
    "可以邮寄吗",
)
REMOTE_PURCHASE_PROGRESS_KEYWORDS = (
    "怎么买",
    "想买",
    "购买",
    "怎么购买",
    "怎么买呢",
)
REMOTE_DIRECT_QUERY_KEYWORDS = (
    "远程定制",
    "远程做",
    "远程弄",
    "远程可以吗",
    "能不能远程",
    "可以远程吗",
    "外地怎么弄",
    "外地怎么办",
    "不方便到店怎么办",
    "不到店可以吗",
)
REMOTE_URGENT_KEYWORDS = (
    "快点回我",
    "别绕了",
    "直接说",
    "快点",
)

SHIPPING_BLOCK_KEYWORDS = (
    "包邮",
    "快递",
    "邮寄",
    "到家",
)
SHIPPING_BLOCK_REPLACEMENT = "姐姐我们是到店定制哦"
ADDRESS_UNSUPPORTED_FALLBACK = "姐姐，您要是明确想看哪家门店的位置，我就给您对应发，不会给您绕开。"
MATERIAL_LIBRARY_VIDEO_SENTINEL = "__material_library_video__"
ADDRESS_FACT_FALLBACK = "姐姐，您这轮如果是想确认推荐逻辑，我就按您的要求继续说明；如果是想看具体位置，我给您对应发。"
ADDRESS_GENERIC_FOLLOWUP_CONTACT_FALLBACK = "姐姐，您这轮更想确认推荐逻辑还是具体位置，您说哪个我就接着说哪个。"
ADDRESS_IMAGE_LIMIT_REPLY_POOL = (
    "姐姐，您可以看上面我给您发的图，因平台限制我这边没法一直重复发送具体地址；如果您没看到或者找不到，您留个电话，我来联系您语音跟您说会更方便一些❤️",
    "姐姐，前面的位置图我已经给您发过啦，平台这边没法反复补发同一张；如果您没看到或者不方便找，您留个电话，我来联系您语音告诉您会更方便❤️",
    "姐姐，上面的地址图您可以先看一下哦，平台限制下我这边不能一直重复发同一张；要是您还是没看到或者找不到，您留个电话，我来联系您语音沟通会更方便❤️",
)
PRICE_FACT_FALLBACK = "姐姐，具体的价格，设计，您可以留个☎️，我来添加您，专门给您详细介绍"
PRICE_GUARDRAIL_SAFE_REPLY = "姐姐，我们的价格有3000、4000、5000、6000不同档位，具体要根据材质、款式、头围、脸型和需求方案来定。"
CONTACT_FACT_FALLBACK = "姐姐，我先把您这轮真正想确认的问题说清楚。"
PHONE_LEAK_BLOCK_FALLBACK = "姐姐，电话我这边不直接展开说，您这轮想确认什么我继续给您讲清楚。"
REMOTE_SUPPORT_FACT_FALLBACK = "姐姐，外地也支持远程定制，不过精准度会比到店稍低一些哦。❤️"
EMPATHY_REMOTE_SUPPORT_FALLBACK = "姐姐那您先注意休息，身体要紧，不方便来上海的话我们也可以先远程帮您看看。❤️"
USER_PHONE_SUBMITTED_REPLY = "收到啦姐姐，电话我这边已经记下了，您后面直接说想确认什么就行❤️"
CONTACT_ALREADY_ADDED_REPLY = "好的姐姐，我这边看到了，咱们就按刚才的方式接着聊，我来给您详细介绍❤️"
CONTACT_ALREADY_CAPTURED_REPLY = "收到啦姐姐，您之前留的方式我这边已经记下了，不用重复发，我会尽快联系您详细介绍❤️"
WEEKEND_CLOSED_REPLY = STANDARD_BUSINESS_HOURS_REPLY
MEDIA_DELIVERY_RETRY_FALLBACK = "姐姐，刚才可能网络有点延迟，您明确说下是要补发位置图还是联系方式图，我马上给您补。"
VISIT_TIME_CONFIRM_REPLY = "姐姐，时间应该可以的，但要跟技术老师协调一下，所以您加我为好友，我帮你预约好时间，这样你会更方便❤️。"
REMOTE_FLOW_ENTRY_REPLY = "姐姐，外地也可以远程定制，您直接看上面的图片加专属客服，我让老师一对一帮您看，合适的话再给您安排。❤️"
REMOTE_FLOW_FOLLOWUP_REPLY = "姐姐，您加上专属客服后，把大概情况发过去，老师会先帮您看适不适合远程定制，再跟您说后面的安排。❤️"
REMOTE_FLOW_URGENT_REPLY = "姐姐您别着急，外地这边是可以远程定制的，您直接加上专属客服，我们这边马上接着给您安排。❤️"
REMOTE_FLOW_SHIPPING_REPLY = "姐姐，可以远程定制的，合适的话后面也可以给您寄，您先加上专属客服，我们这边先帮您看看情况。❤️"
REMOTE_FLOW_DIRECT_ADD_REPLY = "好的姐姐，我这就加您❤️"
REMOTE_FLOW_ENTRY_REPLY_POOL = (
    "姐姐，外地也可以远程定制，您直接看上面的图片加专属客服，我让老师一对一帮您看，合适的话再给您安排。❤️",
    "姐姐，不方便到店也没关系，我们可以先按远程定制给您安排，您加上专属客服后，老师会先帮您看具体适不适合。❤️",
    "姐姐，外地这边也是可以做远程定制的，您先加上专属客服，把大概情况发过去，老师会一对一帮您看。❤️",
)
REMOTE_FLOW_CAPABILITY_REPLY_POOL = (
    "姐姐，外地也是可以远程定制的，您把大概情况发给专属客服，老师会先帮您判断适不适合，再跟您说后面的安排。❤️",
    "姐姐，可以远程定制的呢，您先加上专属客服，把您的情况发过去，老师会先帮您看方案。❤️",
    "姐姐，远程定制是可以做的，您加上专属客服后，老师会先了解您的需求，再给您安排下一步。❤️",
)
REMOTE_FLOW_MEASUREMENT_REPLY_POOL = (
    "姐姐，不会量头围也可以的，您加上专属客服后，老师会一步一步教您怎么量，不用担心。🌹",
    "姐姐，可以的呢，不会量头围没关系，专属客服会教您怎么量，跟着操作就行。🌹",
    "姐姐，没问题的，不会量头围的话老师会教您，您加上专属客服后按步骤来就可以。🌹",
)
REMOTE_FLOW_PROCESS_REPLY_POOL = (
    "姐姐，如果是远程定制的话，一般是先加专属客服，老师先了解您的需求，再指导您量头围，确认好之后再安排后面的定制。🌹",
    "姐姐，远程这边通常是先加专属客服，老师先看您的情况，再教您量头围，确认方案后再继续安排。🌹",
    "姐姐，如果您是外地做远程，一般先联系专属客服，老师会先了解需求和头围这些，再帮您往下安排。🌹",
)
REMOTE_FLOW_CONTACT_REPLY_POOL = (
    "姐姐，您直接看上面的图片加专属客服就可以，老师会继续帮您往下安排。🌹",
    "姐姐，您按上面的图片加专属客服就行，后面老师会一对一跟您对接。🌹",
    "姐姐，您直接按上面的图片联系专属客服就可以，老师会继续帮您安排后面的流程。🌹",
)
REMOTE_MEASUREMENT_KEYWORDS = (
    "量头围",
    "头围",
    "怎么量",
    "不会量",
    "自己量",
    "测量",
)
REMOTE_PROCESS_KEYWORDS = (
    "流程",
    "怎么走",
    "怎么买",
    "想买",
    "先到店还是先预约",
    "先预约还是先到店",
    "先预约",
    "先到店",
)
VISIT_APPOINTMENT_REPLY_POOL = (
    "姐姐，我们这边是预约制的呢，您方便告诉我哪天有时间？我帮您安排专属老师给您预留时间🌷",
    "姐姐，到店这边需要提前预约哦，您把方便的时间告诉我，我帮您先安排好老师。🌷",
    "姐姐，您来之前提前预约一下就可以，这样老师能提前给您留好时间。🌷",
)
VISIT_PROCESS_REPLY_POOL = (
    "姐姐，如果是到店的话，一般是先预约时间，再到门店让老师一对一看您的情况，这样会更方便。🌹",
    "姐姐，到店这边通常是先预约，到了门店后老师会先看您的需求，再帮您安排后面的流程。🌹",
    "姐姐，想来门店的话一般先约时间，到店后老师会先看您的情况，再给您往下安排。🌹",
)
VISIT_MEASUREMENT_REPLY_POOL = (
    "姐姐，到店的话老师会现场帮您量头围的，您不用担心自己不会量。🌹",
    "姐姐，可以的呢，来门店后老师会直接帮您量头围，您不用自己量。🌹",
    "姐姐，没问题的，到店以后老师会现场帮您量头围和看脸型，您不用自己准备。🌹",
)
VISIT_CONTACT_REPLY_POOL = (
    "姐姐，您直接看上面的图片加专属客服就可以，我帮您继续安排预约。🌹",
    "姐姐，您按上面的图片联系专属客服就行，后面我帮您对接预约时间。🌹",
    "姐姐，您直接按图片加专属客服，我这边接着帮您安排到店时间。🌹",
)
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
    "门牌号",
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
    "门牌号",
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
    "门牌号",
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
    "门牌号",
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
    "怎么约",
    "怎么约呀",
    "约呀",
    "预月",
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
    "ask_region_r1": "姐姐，您在什么城市/区域呀？您在哪个城市呀，哪个区域也可以告诉我，我可以帮您针对性推荐门店，我们目前北京朝阳1家、上海5家（静安、人广、虹口、五角场、徐汇）🌹",
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
    "store_recommend": "姐姐，推荐您去{store_name}，我给您发一张位置图，您直接看图片会更直观，如果找不到可以留个☎️，我来具体给你发路线～",
    "non_coverage_contact": "姐姐，{region}暂时没有我们的门店，目前假发是需要根据头围和脸型进行私人定制的，您可以直接看下面的图片，会有专门的老师跟您远程鉴定～💗",
    "contact_intro": "姐姐您直接看图片添加后跟我说一声，我这边一对一继续跟进您呀😊",
    "purchase_contact_intro": "姐姐您可以直接看图片添加，会有专门的老师给您介绍～❤️",
    "purchase_contact_remind_only": "姐姐，您直接看上面的图片添加就可以，可以详细给您介绍怎么买～💗",
    "purchase_contact_remote_remind_only": "姐姐，您可以往上看图片里标注的位置添加，我让老师一对一跟您远程定制❤️",
    "strong_intent_after_both_first": "姐姐，您可以直接看上面的图片里标注的位置添加，我让老师跟您预约～💗",
    "contact_followup_1": "姐姐，您方便的话直接留个☎️给我，我来加您，后面我跟您详细对接😊",
    "contact_followup_2": "姐姐，您直接发个☎️给我就行，我这边加您后继续跟您详细说😊",
    "llm_fallback": "姐姐，刚刚这句我没组织好，您这轮最想确认哪一点，我直接接着说清楚🌹",
    "general_empty": "姐姐我在呢，您这轮最想确认哪一点，我直接接着说清楚🌹",
    "precise_address_closure_pool": [
        "姐姐您看下我发的位置图，按图找会更直观些，方便的话我也可以继续帮您安排预约呀🌹",
        "姐姐具体位置我给您放在图片里啦，您照着图看更清楚，方便的话我继续帮您安排😊",
        "姐姐您直接看位置图会更好找一些，按图过去更直观，您要预约的话我也能接着帮您安排🌷",
        "姐姐位置我已经放到图里啦，您看图找会方便很多，需要的话我继续帮您安排呀❤️",
        "姐姐您看下位置图哦，照着图过去会更省事，方便的话我也可以帮您继续预约💗",
        "姐姐门店位置您看图片会更清楚些，按图找就好，需要我继续帮您安排的话您告诉我呀🌸",
        "姐姐我给您发位置图啦，您跟着图看会更明白，方便的话我继续帮您安排💐",
        "姐姐您看图片里的位置提示就行，找起来更直观些，要是想约我也可以继续帮您跟进🥰",
        "姐姐位置图您点开看一下哦，比文字更好找，方便的话我这边继续帮您安排😄",
        "姐姐您按我发的位置图看就好，会更容易找到，您要预约的话我也可以继续帮您处理🌺",
    ],
    "repeat_pool": [
        "姐姐我在，您可以继续说下最关心的问题呀🌹",
        "姐姐收到，我帮您一步步梳理最合适的方案呀🌹",
        "姐姐明白，我先把关键点给您讲清楚呀🌹",
    ],
}

ADDRESS_IMAGE_COOLDOWN_HOURS = 24

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
        conversation_logger: Optional[ConversationLogger] = None,
    ):
        self.knowledge_service = knowledge_service
        self.llm_service = llm_service
        self.memory_store = memory_store
        self.conversation_logger = conversation_logger

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
        self.first_reply_video_enabled = True
        self.reply_mode = REPLY_MODE_LEGACY

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
        self._precise_address_closure_pool = list(DEFAULT_REPLY_TEMPLATES.get("precise_address_closure_pool", []))
        self._fixed_contact_closure_norms: set[str] = set()
        self._reply_emoji_pool = REPLY_EMOJI_POOL
        self._contact_compliance_block_keywords = CONTACT_COMPLIANCE_BLOCK_KEYWORDS
        self._shipping_block_keywords = SHIPPING_BLOCK_KEYWORDS
        self._shipping_block_replacement = SHIPPING_BLOCK_REPLACEMENT
        self._price_guardrail_safe_reply = PRICE_GUARDRAIL_SAFE_REPLY
        self._empathy_remote_support_fallback = EMPATHY_REMOTE_SUPPORT_FALLBACK
        self._remote_support_fact_fallback = REMOTE_SUPPORT_FACT_FALLBACK
        self._phone_leak_block_fallback = PHONE_LEAK_BLOCK_FALLBACK
        self._contact_fact_fallback = CONTACT_FACT_FALLBACK
        self._address_fact_fallback = ADDRESS_FACT_FALLBACK
        self._address_unsupported_fallback = ADDRESS_UNSUPPORTED_FALLBACK
        self._ma_teacher_direct_query_fallback = MA_TEACHER_DIRECT_QUERY_FALLBACK
        self._ma_teacher_role_fallback = MA_TEACHER_ROLE_FALLBACK

        self.reload_prompt_docs()
        self.reload_media_library()
        self.reload_rule_configs()

        # 初始化统一状态管理
        if self.conversation_logger:
            self.unified_state = UnifiedSessionState(
                self.memory_store,
                # SessionManager 由外部传入，在 decide() 时动态创建
                None,  # type: ignore
                self.conversation_logger,
            )
        else:
            self.unified_state = None  # type: ignore

        # 初始化意图识别器
        self.intent_detector = IntentDetector()

        # 初始化去重检查器
        self.dedup_checker = DeduplicationChecker(self.memory_store)

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

        precise_address_pool = self._reply_templates.get("precise_address_closure_pool")
        if isinstance(precise_address_pool, list):
            pool = [str(x).strip() for x in precise_address_pool if str(x).strip()]
            self._precise_address_closure_pool = pool or list(DEFAULT_REPLY_TEMPLATES.get("precise_address_closure_pool", []))
        else:
            self._precise_address_closure_pool = list(DEFAULT_REPLY_TEMPLATES.get("precise_address_closure_pool", []))

        self._fixed_contact_closure_norms = self._collect_fixed_contact_closure_norms()

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
        session_manager: Optional[Any] = None,
    ) -> AgentDecision:
        """主决策入口"""
        self.memory_store.prune_expired(ttl_days=self.memory_ttl_days)
        visible_history = list(conversation_history or [])

        user_hash = self._hash_user(user_name or session_id)

        # 获取统一状态（优先）或回退到旧逻辑
        if self.conversation_logger:
            unified_state_manager = UnifiedSessionState(
                self.memory_store,
                session_manager,
                self.conversation_logger,
            )
            state = unified_state_manager.get_state(session_id, user_hash)
            self._current_unified_state = state
        else:
            session_state = self.memory_store.get_session_state(session_id, user_hash=user_hash)
            self._current_unified_state = session_state

        session_state = self._current_unified_state
        user_state = self.memory_store.get_user_state(user_hash)
        if first_turn_global_override is None:
            if visible_history:
                is_first_turn_global = False
            elif self._has_meaningful_session_progress(session_state):
                is_first_turn_global = False
            else:
                try:
                    is_first_turn_global = bool(self.is_user_first_turn_global(user_hash))
                except Exception:
                    is_first_turn_global = True
        else:
            is_first_turn_global = bool(first_turn_global_override)
        self._sync_media_state_from_conversation_log(
            session_id=session_id,
            user_hash=user_hash,
            session_state=session_state,
        )
        self._reconcile_conversation_context_with_visible_history(
            session_id=session_id,
            latest_user_text=latest_user_text,
            conversation_history=visible_history,
            session_state=session_state,
            user_state=user_state,
        )

        raw_text = (latest_user_text or "").strip()
        text = self.knowledge_service.normalize_user_text(raw_text).strip()
        if self._looks_like_phone_submission(text):
            decision = AgentDecision(
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
            agent_contact_flow.persist_contact_capture_state(self, session_id, user_hash, session_state, decision)
            return decision
        contact_progress_ack_decision = agent_contact_flow.build_contact_progress_ack_decision(
            self,
            text=text,
            session_state=session_state,
            conversation_history=conversation_history,
        )
        if contact_progress_ack_decision is not None:
            agent_contact_flow.persist_contact_capture_state(
                self, session_id, user_hash, session_state, contact_progress_ack_decision
            )
            return contact_progress_ack_decision
        weekend_closed_decision = self._build_weekend_closed_decision(
            text=text,
            session_state=session_state,
        )
        if weekend_closed_decision is not None:
            return weekend_closed_decision
        raw_route = self.knowledge_service.resolve_store_recommendation(text)
        route = self._enrich_route_from_conversation_state(
            latest_user_text=raw_text,
            route=raw_route,
            session_state=session_state,
        )
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
        intent = self.intent_detector.detect(
            text=text,
            conversation_history=visible_history or [],
            state=self._current_unified_state,
        )
        session_state["current_mainline"] = agent_rule_engine.determine_current_mainline(
            self,
            text=text,
            intent=intent,
            route=route,
            state=session_state,
        )
        decision: Optional[AgentDecision] = None
        forced_first_turn_address_decision: Optional[AgentDecision] = None
        if (
            is_first_turn_global
            and self._looks_like_generic_address_opening(raw_text, intent=intent)
            and str(raw_route.get("target_store", "") or "").strip() in {"", "unknown"}
            and str(raw_route.get("reason", "") or "unknown") in {"unknown", "need_region", "need_clarify"}
        ):
            forced_first_turn_address_decision = self._decide_rule_reply(
                text=text,
                intent="address",
                route=raw_route,
                session_state=session_state,
                conversation_history=conversation_history or [],
                user_state=user_state,
                is_first_turn_global=is_first_turn_global,
            )
        if decision is None:
            decision = forced_first_turn_address_decision
        remote_flow_decision = self._build_remote_flow_decision(
            text=raw_text,
            route=route,
            session_state=session_state,
            conversation_history=visible_history or [],
        )
        if remote_flow_decision is not None:
            normalized_raw_text = self.knowledge_service.normalize_user_text(raw_text)
            normalized_raw_compact = re.sub(r"\s+", "", str(normalized_raw_text or ""))
            if (
                self.knowledge_service.is_address_query(raw_text)
                or self.knowledge_service.is_shanghai_route_alias_address_candidate(raw_text)
                or self._looks_like_generic_address_opening(raw_text, intent="address")
                or any(token in normalized_raw_compact for token in ("地址", "位置", "门店", "哪个城市", "什么城市"))
            ):
                remote_flow_decision = None
        if decision is None and self.reply_mode == REPLY_MODE_LLM_DIRECT:
            decision = self._decide_llm_direct_seed_reply(
                latest_user_text=raw_text,
                intent=intent,
                route=route,
                conversation_history=conversation_history or [],
                session_state=session_state,
                user_state=user_state,
                user_id_hash=user_hash,
                is_first_turn_global=is_first_turn_global,
            )
        price_priority_decision = None if decision is not None else self._decide_price_priority_reply(
            latest_user_text=text,
            route=route,
            conversation_history=conversation_history or [],
            session_state=session_state,
            user_state=user_state,
            user_id_hash=user_hash,
        )
        mainline_for_followups = str(session_state.get("current_mainline", "business_answer") or "business_answer")
        address_text_after_image_decision = None if decision is not None or mainline_for_followups != "business_answer" else self._build_address_text_after_image_decision(
            latest_user_text=text,
            route=route,
            intent=intent,
            session_state=session_state,
        )
        contact_followup_decision = None if decision is not None or mainline_for_followups != "business_answer" else self._build_contact_followup_decision(
            latest_user_text=text,
            intent=intent,
            session_state=session_state,
        )
        address_contact_after_text_decision = None if decision is not None or mainline_for_followups != "business_answer" else self._build_address_contact_after_text_decision(
            latest_user_text=text,
            route=route,
            intent=intent,
            session_state=session_state,
        )
        travel_schedule_store_followup_decision = None if decision is not None or mainline_for_followups != "business_answer" else self._build_travel_schedule_store_followup_decision(
            latest_user_text=text,
            route=route,
            session_state=session_state,
        )
        appointment_kb_decision: Optional[AgentDecision] = None
        process_priority_decision: Optional[AgentDecision] = None
        business_block_priority_decision: Optional[AgentDecision] = None
        if (
            price_priority_decision is None
            and self._looks_like_appointment_query(text)
            and int(session_state.get("contact_image_sent_count", 0) or 0) <= 0
        ):
            appointment_kb_decision = self._decide_appointment_priority_reply(
                latest_user_text=text,
                route=route,
                session_state=session_state,
                conversation_history=conversation_history or [],
                user_state=user_state,
                user_id_hash=user_hash,
            )
        if price_priority_decision is None:
            process_priority_decision = self._decide_process_priority_reply(
                latest_user_text=text,
                route=route,
                user_state=user_state,
                user_id_hash=user_hash,
            )
        suitable_audience_priority_decision: Optional[AgentDecision] = None
        if price_priority_decision is None and process_priority_decision is None:
            suitable_audience_priority_decision = self._decide_suitable_audience_priority_reply(
                latest_user_text=text,
                route=route,
                user_state=user_state,
                user_id_hash=user_hash,
            )
        if (
            price_priority_decision is None
            and process_priority_decision is None
            and suitable_audience_priority_decision is None
        ):
            business_block_priority_decision = self._decide_business_block_priority_reply(
                latest_user_text=text,
                route=route,
                user_state=user_state,
                user_id_hash=user_hash,
            )

        effective_rule_intent = intent
        if (
            effective_rule_intent == "appointment"
            and appointment_kb_decision is None
            and self._looks_like_appointment_query(text)
            and self._has_both_images_sent(session_state)
        ):
            effective_rule_intent = "purchase"

        if (
            effective_rule_intent in {"followup", "general"}
            and self._looks_like_appointment_query(text)
            and str(session_state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
        ):
            effective_rule_intent = "appointment"

        if remote_flow_decision is not None:
            decision = remote_flow_decision
        elif decision is not None:
            pass
        elif price_priority_decision is not None:
            decision = price_priority_decision
        elif business_block_priority_decision is not None:
            decision = business_block_priority_decision
        elif process_priority_decision is not None:
            decision = process_priority_decision
        elif suitable_audience_priority_decision is not None:
            decision = suitable_audience_priority_decision
        elif appointment_kb_decision is not None:
            decision = appointment_kb_decision
        elif address_text_after_image_decision is not None:
            decision = address_text_after_image_decision
        elif contact_followup_decision is not None:
            decision = contact_followup_decision
        elif address_contact_after_text_decision is not None:
            decision = address_contact_after_text_decision
        elif travel_schedule_store_followup_decision is not None:
            decision = travel_schedule_store_followup_decision
        elif (
            str(session_state.get("current_mainline", "business_answer") or "business_answer") != "business_answer"
            or str(route.get("reason", "unknown") or "unknown") in {"need_region", "need_district", "shanghai_need_district", "sh_route_need_clarify", "shanghai_need_arrival_point"}
            or (
                effective_rule_intent == "appointment"
                and str(session_state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
            )
            or (
                self._should_apply_rule_decision(text=text, intent=effective_rule_intent, route=route, session_state=session_state)
                and not (
                    self.reply_mode == REPLY_MODE_LLM_DIRECT
                    and self._should_keep_llm_direct_address_guardrails(text, session_state=session_state)
                )
            )
        ):
            print(f"[DEBUG] 走规则决策: intent={effective_rule_intent}, route_reason={route.get('reason', 'unknown')}, target_store={route.get('target_store', 'unknown')}")
            decision = self._decide_rule_reply(
                text=text,
                intent=effective_rule_intent,
                route=route,
                session_state=session_state,
                conversation_history=conversation_history or [],
                user_state=user_state,
                is_first_turn_global=is_first_turn_global,
            )
        else:
            print(f"[DEBUG] 不走规则决策，走知识库或LLM: intent={intent}, route_reason={route.get('reason', 'unknown')}")
            if (
                appointment_kb_decision is None
                and self.reply_mode != REPLY_MODE_LLM_DIRECT
                and self._looks_like_appointment_query(text)
                and self._should_apply_rule_decision(
                    text=text,
                    intent="purchase",
                    route=route,
                    session_state=session_state,
                )
            ):
                decision = self._decide_rule_reply(
                    text=text,
                    intent="purchase",
                    route=route,
                    session_state=session_state,
                    conversation_history=conversation_history or [],
                    user_state=user_state,
                    is_first_turn_global=is_first_turn_global,
                )
            elif self.reply_mode == REPLY_MODE_LLM_DIRECT:
                llm_direct_address_guardrails = self._should_apply_llm_direct_address_guardrails(
                    text=text,
                    session_state=session_state,
                )
                allow_precise_address_closure = True
                if (
                    not llm_direct_address_guardrails
                    and self.knowledge_service.is_address_query(text)
                    and str(route.get("reason", "") or "unknown") == "unknown"
                    and str(session_state.get("last_target_store", "") or "").strip() in {"", "unknown"}
                    and int(session_state.get("address_image_sent_count", 0) or 0) <= 0
                ):
                    allow_precise_address_closure = False
                decision = self._decide_llm_reply(
                    latest_user_text=raw_text,
                    intent=intent,
                    route_reason=str(route.get("reason", "unknown") or "unknown"),
                    conversation_history=conversation_history or [],
                    session_state=session_state,
                    allow_address_guardrails=llm_direct_address_guardrails,
                    allow_precise_address_closure=allow_precise_address_closure,
                )
            else:
                decision = appointment_kb_decision or self._decide_general_reply(
                    latest_user_text=text,
                    intent=intent,
                    route=route,
                    conversation_history=conversation_history or [],
                    session_state=session_state,
                    user_state=user_state,
                    user_id_hash=user_hash,
                )

        if (
            decision is not None
            and str(decision.rule_id or "") == "ADDR_STORE_RECOMMEND"
            and visible_history
            and self._should_skip_store_recommend_override(route=route, session_state=session_state)
        ):
            if self.reply_mode == REPLY_MODE_LLM_DIRECT:
                decision = self._decide_llm_reply(
                    latest_user_text=raw_text,
                    intent=intent,
                    route_reason=str(route.get("reason", "unknown") or "unknown"),
                    conversation_history=conversation_history or [],
                    session_state=session_state,
                    allow_address_guardrails=True,
                    allow_precise_address_closure=False,
                    rule_id="LLM_FOLLOW_UP",
                )
            else:
                decision = self._decide_general_reply(
                    latest_user_text=text,
                    intent=intent,
                    route=route,
                    conversation_history=conversation_history or [],
                    session_state=session_state,
                    user_state=user_state,
                    user_id_hash=user_hash,
                )

        if (
            decision is not None
            and bool(session_state.get("contact_captured", False))
            and (
                str(intent or "") == "contact"
                or self._looks_like_direct_contact_request(raw_text)
            )
            and str(decision.rule_id or "") not in {
                "CONTACT_PHONE_SUBMITTED",
                "CONTACT_ALREADY_ADDED",
                "CONTACT_ALREADY_CAPTURED",
                "LLM_CONTACT_CAPTURED",
            }
            and self._is_contact_fact_risk(raw_text, decision.reply_text)
        ):
            decision = self._decide_llm_reply(
                latest_user_text=raw_text,
                intent=intent,
                route_reason=str(route.get("reason", "unknown") or "unknown"),
                conversation_history=conversation_history or [],
                session_state=session_state,
                rule_id="LLM_CONTACT_CAPTURED",
            )

        copy_lock_rule_ids = {
            "STORE_RECOMMENDATION",
            "ADDRESS_DELIVERY_FIRST",
            "ADDRESS_DELIVERY_RESEND",
            "CONTACT_DELIVERY_FIRST",
            "CONTACT_DELIVERY_RESEND",
        }
        if not bool(getattr(decision, "kb_blocked_by_polite_guard", False)):
            kb_detail = self.knowledge_service.find_answer_detail(text, threshold=self.knowledge_threshold)
            if bool(kb_detail.get("blocked_by_polite_guard", False)):
                decision.kb_blocked_by_polite_guard = True
                decision.kb_polite_guard_reason = str(kb_detail.get("polite_guard_reason", "") or "")
        should_rewrite = (
            decision.reply_source in ("llm", "fallback")
            and self.reply_mode != REPLY_MODE_LLM_DIRECT
            and decision.rule_id not in copy_lock_rule_ids
        )
        if should_rewrite:
            knowledge_reply_count = int(session_state.get("knowledge_reply_count", 0) or 0)
            rewritten_text, rewritten = self._rewrite_if_repeated(
                reply_text=decision.reply_text,
                latest_user_text=raw_text,
                conversation_history=conversation_history or [],
                user_state=user_state,
                user_id_hash=user_hash,
            )
            decision.reply_text = rewritten_text
            decision.kb_repeat_rewritten = bool(rewritten)
        else:
            knowledge_reply_count = int(session_state.get("knowledge_reply_count", 0) or 0)

        decision.reply_mode = self.reply_mode
        decision.purchase_both_first_hint_sent = bool(
            session_state.get("purchase_both_first_hint_sent", False)
        )
        decision.is_first_turn_global = bool(is_first_turn_global)
        both_images_sent = self._has_both_images_sent(session_state)
        decision.both_images_sent_state = both_images_sent
        decision.video_trigger_user_count = int(session_state.get("session_user_message_count_after_contact", 0) or 0)

        original_media_plan = decision.media_plan
        planning_route = dict(route or {})
        if (
            str(decision.rule_id or "") == "ADDR_STORE_RECOMMEND"
            and str(planning_route.get("target_store", "") or "").strip() in {"", "unknown"}
        ):
            inferred_store = str(
                self._infer_store_from_context_text(decision.reply_text)
                or session_state.get("last_target_store", "")
                or ""
            ).strip()
            if inferred_store and inferred_store != "unknown":
                planning_route["target_store"] = inferred_store
        delivery_rule_ids = {
            "ADDRESS_DELIVERY_FIRST",
            "ADDRESS_DELIVERY_RESEND",
            "CONTACT_DELIVERY_FIRST",
            "CONTACT_DELIVERY_RESEND",
        }
        if self.reply_mode == REPLY_MODE_LLM_DIRECT and str(decision.rule_id or "") not in delivery_rule_ids:
            media_items, media_skip_reason = [], "reply_mode_llm_direct"
        else:
            media_items, media_skip_reason = self._plan_media_items(
                session_id=session_id,
                text=text,
                intent=decision.intent,
                route=planning_route,
                route_reason=decision.route_reason,
                media_plan=original_media_plan,
                session_state=session_state,
                user_state=user_state,
                force_contact_image=bool(decision.force_contact_image),
            )
        decision.media_items = media_items
        decision.media_skip_reason = media_skip_reason
        decision.first_turn_media_guard_applied = False
        self._populate_first_turn_media_plan(
            session_id=session_id,
            user_name=user_name,
            decision=decision,
        )
        if not bool(getattr(self, "first_reply_video_enabled", False)):
            decision.first_turn_video_items = []
        if not decision.media_items:
            decision.media_plan = "none"

        current_answer_topic, current_answer_facts, current_answer_mode = self._build_answer_context_summary(
            latest_user_text=raw_text,
            decision=decision,
            route=route,
            session_state=session_state,
        )
        if current_answer_topic == "service_hours" and not self._extract_business_hours_fact(decision.reply_text):
            decision.reply_text = STANDARD_BUSINESS_HOURS_REPLY
            current_answer_facts["business_hours"] = STANDARD_BUSINESS_HOURS_FACT
        conversation_state_updates = self._build_conversation_state_updates(
            latest_user_text=raw_text,
            decision=decision,
            route=route,
            session_state=session_state,
            current_answer_topic=current_answer_topic,
            current_answer_facts=current_answer_facts,
        )
        contextualized = False
        if self._should_contextualize_followup_reply(
            latest_user_text=raw_text,
            current_topic=current_answer_topic,
            current_facts=current_answer_facts,
            decision=decision,
            session_state=session_state,
        ):
            rewritten_text, contextualized = self._contextualize_topic_followup_reply(
                latest_user_text=raw_text,
                base_reply_text=decision.reply_text,
                current_topic=current_answer_topic,
                current_facts=current_answer_facts,
                conversation_history=conversation_history or [],
                session_state=session_state,
            )
            if contextualized:
                guarded_text, reply_closure_info = self._apply_llm_reply_guardrails(
                    latest_user_text=raw_text,
                    reply_text=rewritten_text,
                    session_state=session_state,
                    conversation_history=conversation_history or [],
                    allow_address_guardrails=(current_answer_topic == "store_recommendation"),
                    allow_precise_address_closure=(current_answer_topic == "store_recommendation"),
                )
                decision.reply_text = guarded_text
                decision.reply_closure_info = dict(reply_closure_info or getattr(decision, "reply_closure_info", {}) or {})
                decision.kb_repeat_rewritten = True
                current_answer_mode = "contextual_llm"

        decision.reply_text = mask_precise_address_for_output(decision.reply_text)

        now = datetime.now().isoformat()
        target_store = route.get("target_store", "unknown")
        detected_region = route.get("detected_region", "") or ""
        persisted_store = str(
            conversation_state_updates.get("current_store_context", "")
            or conversation_state_updates.get("store_delivery_authority", "")
            or (target_store if target_store != "unknown" else "")
        ).strip()
        next_knowledge_reply_count = knowledge_reply_count + (1 if decision.reply_source == "knowledge" else 0)
        next_price_priority_reply_count = int(session_state.get("price_priority_reply_count", 0) or 0)
        if decision.rule_id in {"PRICE_PRIORITY", "PRICE_PRIORITY_FALLBACK", "PRICE_PRIORITY_PRIVATE_GUIDE"}:
            next_price_priority_reply_count += 1
        self.memory_store.update_session_state(
            session_id,
            {
                "last_route_reason": decision.route_reason,
                "last_intent": decision.intent,
                "last_reply_goal": decision.reply_goal,
                "last_detected_region": detected_region or session_state.get("last_detected_region", ""),
                "last_target_store": persisted_store or session_state.get("last_target_store", ""),
                "last_geo_route_reason": route.get("reason", "unknown") if (target_store != "unknown" or detected_region) else session_state.get("last_geo_route_reason", "unknown"),
                "last_geo_updated_at": now if (target_store != "unknown" or detected_region) else session_state.get("last_geo_updated_at", ""),
                "knowledge_reply_count": next_knowledge_reply_count,
                "price_priority_reply_count": next_price_priority_reply_count,
                "address_info_shared": bool(session_state.get("address_info_shared", False) or self._reply_shares_address_info(decision.reply_text)),
                "last_answer_topic": current_answer_topic,
                "last_answer_facts": current_answer_facts,
                "last_answer_mode": current_answer_mode,
                "last_answer_text_normalized": self._normalize_for_dedupe(decision.reply_text),
                "session_runtime_turn_count": int(session_state.get("session_runtime_turn_count", 0) or 0) + 1,
                "current_mainline": str(session_state.get("current_mainline", "business_answer") or "business_answer"),
                **conversation_state_updates,
            },
            user_hash=user_hash,
        )
        self.memory_store.save()
        return decision

    def _has_meaningful_session_progress(self, session_state: Optional[Dict[str, Any]] = None) -> bool:
        state = dict(session_state or {})
        if str(state.get("last_route_reason", "") or "").strip() not in {"", "unknown"}:
            return True
        if str(state.get("last_answer_topic", "") or "").strip():
            return True
        if str(state.get("last_target_store", "") or "").strip() not in {"", "unknown"}:
            return True
        if int(state.get("address_image_sent_count", 0) or 0) > 0:
            return True
        if int(state.get("contact_image_sent_count", 0) or 0) > 0:
            return True
        if int(state.get("geo_followup_round", 0) or 0) > 0:
            return True
        if bool(state.get("remote_flow_active", False)):
            return True
        return False

    def mark_reply_sent(
        self,
        session_id: str,
        user_name: str,
        reply_text: str,
        *,
        is_first_turn_global: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return agent_media.mark_reply_sent(
            self,
            session_id=session_id,
            user_name=user_name,
            reply_text=reply_text,
            is_first_turn_global=is_first_turn_global,
        )

    def build_post_text_media_queue(
        self,
        session_id: str,
        user_name: str,
        planned_media_items: List[Dict[str, Any]],
        extra_media_items: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        return agent_media.build_post_text_media_queue(
            self,
            session_id=session_id,
            user_name=user_name,
            planned_media_items=planned_media_items,
            extra_media_items=extra_media_items,
        )

    def judge_post_reply_media(
        self,
        session_id: str,
        user_name: str,
        latest_user_text: str,
        reply_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        decision: Optional[AgentDecision] = None,
    ) -> MediaJudgeDecision:
        return agent_media.judge_post_reply_media(
            self,
            session_id=session_id,
            user_name=user_name,
            latest_user_text=latest_user_text,
            reply_text=reply_text,
            conversation_history=conversation_history,
            decision=decision,
        )

    def mark_media_sent(self, session_id: str, user_name: str, media_item: Dict[str, Any], success: bool) -> None:
        agent_media.mark_media_sent(self, session_id=session_id, user_name=user_name, media_item=media_item, success=success)

    def enqueue_media_compensation(
        self,
        session_id: str,
        user_name: str,
        media_item: Dict[str, Any],
        failure_code: str = "",
        failure_detail: str = "",
    ) -> Optional[Dict[str, Any]]:
        return agent_media.enqueue_media_compensation(
            self,
            session_id=session_id,
            user_name=user_name,
            media_item=media_item,
            failure_code=failure_code,
            failure_detail=failure_detail,
        )

    def clear_media_compensation(self, session_id: str, user_name: str, media_item: Dict[str, Any]) -> None:
        agent_media.clear_media_compensation(self, session_id=session_id, user_name=user_name, media_item=media_item)

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
        return agent_rule_engine.detect_intent(self, text)

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
            "加我微信",
            "直接加我",
            "怎么添加",
            "如何添加",
            "怎么加微信",
            "如何加微信",
            "怎么联系",
            "如何联系",
        )
        return any(pattern in normalized for pattern in direct_patterns)

    def _looks_like_missing_media_request(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        patterns = (
            "没收到",
            "没有收到",
            "刚没收到",
            "还没收到",
            "没看见",
            "没看到",
            "看不到",
            "图呢",
            "图片呢",
            "位置图呢",
            "地址图呢",
            "联系方式图呢",
            "翻不到",
            "找不到图",
            "没发成功",
        )
        return any(pattern in normalized for pattern in patterns)

    def _looks_like_closing_confirmation(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        patterns = (
            "我先加你们",
            "我先加",
            "先加你们",
            "先加上",
            "晚点定时间",
            "晚点联系",
            "回头定时间",
            "回头联系",
            "谢谢那天我到上海来",
            "谢谢到上海来",
            "到上海来",
        )
        return any(pattern in normalized for pattern in patterns)

    def _build_closing_confirmation_reply(self) -> str:
        return self._normalize_reply_text(
            "好的姐姐，您加上专属客服后，确定好方便的时间随时告诉我，我这边再帮您接着安排。"
        )

    def _normalize_flow_text(self, text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).lower()

    def _looks_like_remote_region_query(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_REGION_HINT_KEYWORDS)

    def _looks_like_remote_visit_block(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_VISIT_BLOCK_KEYWORDS)

    def _looks_like_remote_shipping_query(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_SHIPPING_QUERY_KEYWORDS)

    def _looks_like_remote_purchase_progress(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_PURCHASE_PROGRESS_KEYWORDS)

    def _looks_like_remote_direct_query(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_DIRECT_QUERY_KEYWORDS)

    def _looks_like_remote_urgent_query(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_URGENT_KEYWORDS)

    def _looks_like_remote_contact_followup(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        if not normalized:
            return False
        if self._looks_like_direct_contact_request(text):
            return True
        return any(token in normalized for token in ("微信", "电话", "留个", "加我"))

    def _looks_like_remote_measurement_query(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_MEASUREMENT_KEYWORDS)

    def _looks_like_remote_process_query(self, text: str) -> bool:
        normalized = self._normalize_flow_text(text)
        return bool(normalized) and any(token in normalized for token in REMOTE_PROCESS_KEYWORDS)

    def _pick_remote_flow_reply(
        self,
        *,
        session_state: Dict[str, Any],
        category: str,
        replies: Tuple[str, ...],
    ) -> str:
        pool = [str(item).strip() for item in (replies or ()) if str(item).strip()]
        if not pool:
            return REMOTE_FLOW_FOLLOWUP_REPLY
        counters = dict(session_state.get("remote_reply_counters", {}) or {})
        index = int(counters.get(category, 0) or 0) % len(pool)
        counters[category] = int(counters.get(category, 0) or 0) + 1
        session_state["remote_reply_counters"] = counters
        return pool[index]

    def _pick_visit_flow_reply(
        self,
        *,
        session_state: Dict[str, Any],
        category: str,
        replies: Tuple[str, ...],
    ) -> str:
        pool = [str(item).strip() for item in (replies or ()) if str(item).strip()]
        if not pool:
            return self._render_template("purchase_contact_intro")
        counters = dict(session_state.get("visit_reply_counters", {}) or {})
        index = int(counters.get(category, 0) or 0) % len(pool)
        counters[category] = int(counters.get(category, 0) or 0) + 1
        session_state["visit_reply_counters"] = counters
        return pool[index]

    def _is_remote_flow_active(self, session_state: Optional[Dict[str, Any]] = None) -> bool:
        return bool((session_state or {}).get("remote_flow_active", False))

    def _is_remote_flow_first_contact(self, session_state: Optional[Dict[str, Any]] = None) -> bool:
        state = dict(session_state or {})
        return not bool(state.get("remote_contact_image_sent", False) or int(state.get("contact_image_sent_count", 0) or 0) > 0)

    def _build_remote_flow_decision(
        self,
        text: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[AgentDecision]:
        normalized = self._normalize_flow_text(text)
        if not normalized:
            return None
        if bool(session_state.get("contact_captured", False)):
            return None
        address_like_remote_break = (
            self.knowledge_service.is_address_query(text)
            or self.knowledge_service.is_shanghai_route_alias_address_candidate(text)
            or any(token in normalized for token in ("地址", "位置", "门店", "在哪", "哪里"))
        )
        if self._is_remote_flow_active(session_state) and address_like_remote_break:
            return None

        route_reason = str(route.get("reason", "") or "unknown")
        remote_active = self._is_remote_flow_active(session_state)
        purchase_like_remote = (
            self._looks_like_remote_purchase_progress(text)
            or self._looks_like_remote_direct_query(text)
            or self._looks_like_appointment_query(text)
            or self.knowledge_service.is_address_query(text)
            or self.knowledge_service.is_purchase_intent(text)
        )
        strong_remote_statement = (
            self._looks_like_remote_visit_block(text)
            or self._looks_like_remote_shipping_query(text)
            or (
                self._looks_like_remote_region_query(text)
                and not purchase_like_remote
                and "我在" in normalized
                and not any(token in normalized for token in ("怎么", "如何", "地址", "位置", "预约", "买"))
            )
        )
        explicit_remote_entry = (
            (
                self._looks_like_remote_direct_query(text)
                or (
                    route_reason in {"out_of_coverage", "not_in_shanghai_remote"}
                    and not bool(session_state.get("last_geo_pending", False))
                    and (
                        strong_remote_statement
                        or purchase_like_remote
                        or self._looks_like_remote_region_query(text)
                        or "我在" in normalized
                    )
                )
            )
        )
        if not remote_active and not explicit_remote_entry:
            return None
        explicit_remote = explicit_remote_entry or (remote_active and strong_remote_statement)
        history = list(conversation_history or [])
        visible_remote_history = any(
            str(item.get("role", "") or "") == "assistant"
            and any(token in str(item.get("content", "") or "") for token in ("远程定制", "外地也可以"))
            for item in history
        )
        remote_followup = remote_active and (
            self._looks_like_remote_shipping_query(text)
            or (
                self._looks_like_remote_purchase_progress(text)
                and visible_remote_history
            )
            or self._looks_like_remote_urgent_query(text)
            or self._looks_like_remote_contact_followup(text)
        )
        if not explicit_remote and not remote_followup:
            return None

        first_contact = self._is_remote_flow_first_contact(session_state)
        reply_intent = "purchase"
        if self._looks_like_remote_urgent_query(text):
            reply_text = REMOTE_FLOW_URGENT_REPLY
        elif self._looks_like_direct_contact_request(text):
            reply_text = REMOTE_FLOW_DIRECT_ADD_REPLY
        elif self._looks_like_remote_shipping_query(text):
            reply_text = REMOTE_FLOW_SHIPPING_REPLY
        elif self._looks_like_remote_measurement_query(text):
            reply_text = self._pick_remote_flow_reply(
                session_state=session_state,
                category="measurement",
                replies=REMOTE_FLOW_MEASUREMENT_REPLY_POOL,
            )
            reply_intent = "general"
        elif self._looks_like_remote_process_query(text) or self._looks_like_appointment_query(text):
            reply_text = self._pick_remote_flow_reply(
                session_state=session_state,
                category="process",
                replies=REMOTE_FLOW_PROCESS_REPLY_POOL,
            )
        elif self._looks_like_remote_contact_followup(text):
            reply_text = self._pick_remote_flow_reply(
                session_state=session_state,
                category="contact",
                replies=REMOTE_FLOW_CONTACT_REPLY_POOL,
            )
        elif self._looks_like_remote_direct_query(text):
            reply_text = self._pick_remote_flow_reply(
                session_state=session_state,
                category="capability",
                replies=REMOTE_FLOW_CAPABILITY_REPLY_POOL if not first_contact else REMOTE_FLOW_ENTRY_REPLY_POOL,
            )
        elif first_contact:
            reply_text = self._pick_remote_flow_reply(
                session_state=session_state,
                category="entry",
                replies=REMOTE_FLOW_ENTRY_REPLY_POOL,
            )
        else:
            reply_text = self._pick_remote_flow_reply(
                session_state=session_state,
                category="capability",
                replies=REMOTE_FLOW_CAPABILITY_REPLY_POOL,
            )

        return AgentDecision(
            reply_text=reply_text,
            intent=reply_intent,
            route_reason="remote_flow_entry" if first_contact else "remote_flow_followup",
            reply_goal="承接联系方式" if first_contact else "推进购买意图",
            media_plan="contact_image" if first_contact else "none",
            reply_source="rule",
            rule_id="REMOTE_FLOW_ENTRY" if first_contact else "REMOTE_FLOW_FOLLOWUP",
            rule_applied=True,
            force_contact_image=first_contact,
            reply_mode=self.reply_mode,
        )


    def _looks_like_weekend_closed_query(self, text: str, session_state: Optional[Dict[str, Any]] = None) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        has_date_or_weekday = any(
            token in normalized
            for token in (
                "周一", "周二", "周三", "周四", "周五", "周六", "周日", "周末", "周几",
                "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日", "星期几",
                "礼拜一", "礼拜二", "礼拜三", "礼拜四", "礼拜五", "礼拜六", "礼拜天", "礼拜几",
            )
        ) or bool(re.search(r"\d{1,2}[号日]", normalized))
        if not has_date_or_weekday:
            return False
        active_topic = str((session_state or {}).get("active_topic", "") or "")
        has_visit_signal = any(token in normalized for token in ("去", "过去", "到店", "营业", "上班", "开门", "时间", "几点", "预约", "可以吗", "行吗", "能吗"))
        return has_visit_signal or active_topic in {"service_hours", "appointment", "store_recommendation"}

    def _build_weekend_closed_decision(
        self,
        text: str,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentDecision]:
        if not self._looks_like_weekend_closed_query(text, session_state=session_state):
            return None
        return AgentDecision(
            reply_text=WEEKEND_CLOSED_REPLY,
            intent="general",
            route_reason="weekend_closed",
            reply_goal="解答",
            media_plan="none",
            reply_source="rule",
            rule_id="SERVICE_HOURS_WEEKEND_CLOSED",
            rule_applied=True,
            reply_mode=self.reply_mode,
        )

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
        if any(
            token in normalized
            for token in (
                "什么城市",
                "哪个城市",
                "什么区域",
                "哪个区域",
                "方便告诉我",
                "针对性推荐门店",
                "先确认一下",
                "确认一下",
            )
        ):
            return False
        if self._infer_answer_type(reply_text) in {"store_address", "address_general"}:
            return True
        if any(token in normalized for token in ("北京1家", "北京只有1家", "上海有5家", "上海共有5家")):
            return True
        if any(token in normalized for token in ("静安", "人民广场", "人广", "虹口", "五角场", "徐汇", "朝阳区", "朝阳店", "北京朝阳店")) and any(
            token in normalized for token in ("门店", "地址", "位置", "区域", "城市", "位置图", "图片")
        ):
            return True
        return False

    def _history_has_geo_followup_prompt(self, conversation_history: List[Dict[str, str]]) -> bool:
        prompt_tokens = (
            "什么城市",
            "哪个城市",
            "什么区域",
            "哪个区域",
            "方便告诉我",
            "北京朝阳1家",
            "上海5家",
            "静安",
            "虹口",
            "五角场",
            "徐汇",
        )
        for item in reversed(conversation_history or []):
            if str(item.get("role", "") or "") != "assistant":
                continue
            normalized = self.knowledge_service.normalize_user_text(str(item.get("content", "") or ""))
            if normalized and any(token in normalized for token in prompt_tokens):
                return True
        return False

    def _clear_address_session_context(
        self,
        session_state: Dict[str, Any],
        *,
        clear_geo_prompt: bool,
    ) -> None:
        session_state["address_prompt_count"] = 0
        session_state["last_target_store"] = ""
        session_state["current_store_context"] = ""
        session_state["store_delivery_authority"] = ""
        session_state["store_candidates"] = []
        session_state["sent_address_stores"] = []
        session_state["address_image_sent_count"] = 0
        session_state["address_image_last_sent_at_by_store"] = {}
        session_state["address_image_sent_paths_by_store"] = {}
        session_state["address_image_sent_count_by_store"] = {}
        session_state["address_image_resend_count_by_store"] = {}
        session_state["address_delivery_stage_by_store"] = {}
        session_state["address_info_shared"] = False
        facts = dict(session_state.get("conversation_facts", {}) or {})
        facts.pop("recommended_store", None)
        facts.pop("city", None)
        session_state["conversation_facts"] = facts
        if str(session_state.get("conversation_stage", "") or "") in {"address_image_sent", "store_recommended"}:
            session_state["conversation_stage"] = ""
        if clear_geo_prompt:
            session_state["geo_followup_round"] = 0
            session_state["geo_followup_exhausted"] = False
            session_state["geo_choice_offered"] = False
            session_state["last_geo_pending"] = False
            session_state["last_detected_region"] = ""
            session_state["last_geo_route_reason"] = "unknown"
            session_state["last_geo_updated_at"] = ""

    def _history_has_contact_context(
        self,
        latest_user_text: str,
        conversation_history: List[Dict[str, str]],
    ) -> bool:
        contact_tokens = (
            "留个",
            "留个方式",
            "留个电话",
            "留个☎️",
            "加您",
            "加你",
            "加好友",
            "联系方式",
            "联系您",
            "专属客服",
            "预约",
            "看图片添加",
            "图片添加",
            "按图添加",
            "添加后跟我说",
        )
        if self._looks_like_phone_submission(latest_user_text):
            return True
        for item in conversation_history or []:
            content = str(item.get("content", "") or "")
            if not content:
                continue
            if str(item.get("role", "") or "") == "user" and self._looks_like_phone_submission(content):
                return True
            normalized = self.knowledge_service.normalize_user_text(content)
            if normalized and any(token in normalized for token in contact_tokens):
                return True
        return False

    def _clear_contact_session_context(self, session_state: Dict[str, Any], preserve_contact_captured: bool = False) -> None:
        preserved_contact_captured = bool(session_state.get("contact_captured", False))
        session_state["contact_captured"] = preserved_contact_captured
        session_state["contact_image_sent_count"] = 0
        session_state["contact_image_resend_count"] = 0
        session_state["contact_image_last_sent_at"] = ""
        session_state["contact_image_sent_paths"] = []
        session_state["contact_delivery_stage"] = "not_delivered"
        session_state["remote_contact_image_sent"] = False
        session_state["remote_contact_captured"] = preserved_contact_captured if preserve_contact_captured else bool(session_state.get("remote_contact_captured", False))
        if str(session_state.get("active_topic", "") or "") == "appointment":
            session_state["active_topic"] = ""
        if str(session_state.get("conversation_stage", "") or "") == "appointment_ready":
            session_state["conversation_stage"] = ""
        facts = dict(session_state.get("conversation_facts", {}) or {})
        facts.pop("appointment_ready", None)
        session_state["conversation_facts"] = facts

    def _clear_transient_user_context(self, user_state: Dict[str, Any]) -> None:
        user_state["video_armed"] = False
        user_state["video_sent"] = False
        user_state["post_contact_reply_count"] = 0
        user_state["recent_reply_hashes"] = []

    def _clear_conversation_state_for_fresh_start(
        self,
        session_state: Dict[str, Any],
        user_state: Dict[str, Any],
    ) -> None:
        self._clear_address_session_context(session_state, clear_geo_prompt=True)
        self._clear_contact_session_context(session_state)
        session_state["last_route_reason"] = "unknown"
        session_state["last_intent"] = "general"
        session_state["last_reply_goal"] = "解答"
        session_state["active_topic"] = ""
        session_state["previous_topics"] = []
        session_state["topic_reply_memory"] = {}
        session_state["last_answer_topic"] = ""
        session_state["last_answer_facts"] = {}
        session_state["last_answer_mode"] = ""
        session_state["last_answer_text_normalized"] = ""
        session_state["pending_required_media"] = []
        session_state["planned_required_media"] = []
        session_state["session_video_armed"] = False
        session_state["session_video_sent"] = False
        session_state["session_post_contact_reply_count"] = 0
        session_state["session_user_message_count_after_contact"] = 0
        session_state["purchase_both_first_hint_sent"] = False
        session_state["session_runtime_turn_count"] = 0
        self._clear_transient_user_context(user_state)

    def _reconcile_conversation_context_with_visible_history(
        self,
        session_id: str,
        latest_user_text: str,
        conversation_history: List[Dict[str, str]],
        session_state: Dict[str, Any],
        user_state: Dict[str, Any],
    ) -> None:
        visible_history = list(conversation_history or [])
        block_inheritance = self._should_block_store_context_inheritance(latest_user_text)
        if not visible_history:
            normalized_latest = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
            explicit_address_revisit = (
                str(session_state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
                and int(session_state.get("address_image_sent_count", 0) or 0) > 0
                and any(token in normalized_latest for token in ("位置图", "再发", "看图", "在哪", "哪儿"))
            )
            preserve_hidden_context = bool(session_state.get("remote_flow_active", False))
            if explicit_address_revisit or preserve_hidden_context:
                return
            preserve_recent_hashes = not self._has_meaningful_session_progress(session_state)
            recent_hashes = list(user_state.get("recent_reply_hashes", []) or [])
            self._clear_conversation_state_for_fresh_start(session_state, user_state)
            if preserve_recent_hashes:
                user_state["recent_reply_hashes"] = recent_hashes
            return

        latest_candidates = list(dict.fromkeys(self._extract_store_candidates_from_text(latest_user_text)))
        visible_store = ""
        if not block_inheritance and len(latest_candidates) == 1 and self._should_lock_store_context_from_text(latest_user_text):
            visible_store = latest_candidates[0]
        current_store_context = str(session_state.get("current_store_context", "") or "").strip()
        if not visible_store and current_store_context:
            visible_store = current_store_context

        address_info_shared = self._history_has_address_info_shared(visible_history)
        geo_prompt_visible = self._history_has_geo_followup_prompt(visible_history)
        contact_context_visible = self._history_has_contact_context(latest_user_text, visible_history)
        if not visible_store and not address_info_shared and not geo_prompt_visible:
            self._clear_address_session_context(session_state, clear_geo_prompt=True)
        if not contact_context_visible:
            self._clear_contact_session_context(session_state)

        if visible_store:
            session_state["last_target_store"] = visible_store
            session_state["current_store_context"] = visible_store
            facts = dict(session_state.get("conversation_facts", {}) or {})
            facts["recommended_store"] = visible_store
            inferred_city = self._infer_city_from_store_key(visible_store)
            if inferred_city:
                facts["city"] = inferred_city
                session_state["last_detected_region"] = inferred_city
            session_state["conversation_facts"] = facts
        else:
            session_state["last_target_store"] = ""
            facts = dict(session_state.get("conversation_facts", {}) or {})
            facts.pop("recommended_store", None)
            session_state["conversation_facts"] = facts
            session_state["current_store_context"] = ""

        if latest_candidates:
            session_state["store_candidates"] = latest_candidates[:3]
        elif not visible_store:
            session_state["store_candidates"] = []

        session_state["address_info_shared"] = bool(address_info_shared)

        if not geo_prompt_visible:
            session_state["last_geo_pending"] = False
            session_state["last_geo_route_reason"] = "unknown"
            session_state["geo_followup_round"] = 0
            session_state["geo_followup_exhausted"] = False
            session_state["geo_choice_offered"] = False
            if not visible_store:
                session_state["last_detected_region"] = ""

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
        return agent_rule_engine.is_ambiguous_short_fragment(self, text, intent, route)

    def _looks_like_phone_submission(self, text: str) -> bool:
        return agent_rule_engine.looks_like_phone_submission(self, text)

    def _should_apply_rule_decision(
        self,
        text: str,
        intent: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> bool:
        return agent_rule_engine.should_apply_rule_decision(self, text, intent, route, session_state)

    def _looks_like_geo_reply(self, text: str, route: Dict[str, Any]) -> bool:
        return agent_rule_engine.looks_like_geo_reply(self, text, route)

    def _is_remote_geo_followup_reply(self, text: str) -> bool:
        return agent_rule_engine.is_remote_geo_followup_reply(self, text)

    def _should_force_out_of_coverage_from_geo_followup(self, text: str, session_state: Dict[str, Any]) -> bool:
        return agent_rule_engine.should_force_out_of_coverage_from_geo_followup(self, text, session_state)

    def _build_address_text_after_image_decision(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        intent: str,
        session_state: Dict[str, Any],
    ) -> Optional[AgentDecision]:
        return agent_rule_engine.build_address_text_after_image_decision(self, latest_user_text, route, intent, session_state)

    def _build_address_contact_after_text_decision(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        intent: str,
        session_state: Dict[str, Any],
    ) -> Optional[AgentDecision]:
        return agent_rule_engine.build_address_contact_after_text_decision(self, latest_user_text, route, intent, session_state)

    def _build_contact_followup_decision(
        self,
        latest_user_text: str,
        intent: str,
        session_state: Dict[str, Any],
    ) -> Optional[AgentDecision]:
        return agent_rule_engine.build_contact_followup_decision(self, latest_user_text, intent, session_state)

    def _build_travel_schedule_store_followup_decision(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> Optional[AgentDecision]:
        return agent_rule_engine.build_travel_schedule_store_followup_decision(self, latest_user_text, route, session_state)

    def _should_continue_address_followup(self, latest_user_text: str, session_state: Dict[str, Any]) -> bool:
        return agent_rule_engine.should_continue_address_followup(self, latest_user_text, session_state)

    def _resolve_geo_context(self, route: Dict[str, Any], session_state: Dict[str, Any]) -> Dict[str, Any]:
        return agent_rule_engine.resolve_geo_context(self, route, session_state)

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
        return agent_rule_engine.decide_rule_reply(
            self,
            text=text,
            intent=intent,
            route=route,
            session_state=session_state,
            conversation_history=conversation_history,
            user_state=user_state,
            is_first_turn_global=is_first_turn_global,
        )

    def _build_geo_followup_decision(self, session_state: Dict[str, Any], route_reason: str, intent: str) -> AgentDecision:
        return agent_rule_engine.build_geo_followup_decision(self, session_state, route_reason, intent)

    def _should_recover_to_shanghai_arrival_help(self, text: str, session_state: Dict[str, Any]) -> bool:
        return agent_rule_engine.should_recover_to_shanghai_arrival_help(self, text, session_state)

    def _is_follow_up_question(
        self,
        text: str,
        conversation_history: List[Dict[str, str]],
        session_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return agent_rule_engine.is_follow_up_question(self, text, conversation_history, session_state=session_state)

    def _has_price_priority(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        if self._is_precise_address_followup(text):
            return False
        if any(keyword in normalized for keyword in ADDRESS_PRIORITY_OVER_PRICE_KEYWORDS):
            return False
        if any(keyword in normalized for keyword in ("邮寄", "快递", "寄吗", "寄快递", "能买吗", "怎么买", "购买")):
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
        if not has_explicit_price_signal and re.search(r"价.{0,2}(多|几|贵|位)", normalized):
            has_explicit_price_signal = True
        if not has_explicit_price_signal and any(
            keyword in normalized for keyword in ("价各", "价差", "差哪里", "区别在哪", "区别", "有啥不同")
        ):
            has_explicit_price_signal = True
        if (
            not has_explicit_price_signal
            and (
                self.knowledge_service.is_shanghai_route_alias_address_candidate(text)
                or self.knowledge_service.is_address_query(text)
            )
        ):
            return False
        if has_explicit_price_signal:
            return True
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

        kb_detail = self.knowledge_service.find_answer_detail(text, threshold=self.knowledge_threshold)
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        kb_answer = str(kb_detail.get("answer", "") or "").strip()
        kb_answers = [
            str(x).strip()
            for x in (kb_detail.get("answers", []) or [])
            if str(x).strip()
        ]
        if kb_answer and kb_answer not in kb_answers:
            kb_answers.append(kb_answer)
        normalized = re.sub(r"\s+", "", text).lower()
        is_price_objection = any(token in normalized for token in ("贵", "便宜", "优惠", "折扣", "划算"))
        if kb_detail.get("matched") and kb_intent.startswith("price"):
            kb_mode = str(kb_detail.get("mode", "") or "").strip().lower()
            kb_tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
            is_price_objection = bool(
                is_price_objection
                or kb_mode == "expensive_priority"
                or "议价" in kb_tags
            )
            selected_answer, selected_index, exhausted = self._select_kb_variant_answer(
                answers=kb_answers,
                user_state=user_state,
                user_id_hash=user_id_hash,
            )
            base_answer = selected_answer or kb_answer or (kb_answers[0] if kb_answers else "")
            if base_answer:
                if price_priority_count == 2 and not is_price_objection:
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

        if price_priority_count == 2 and not is_price_objection:
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

    def _looks_like_production_timeline_query(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        duration_signal = any(
            token in normalized
            for token in (
                "多久",
                "几天",
                "多长时间",
                "周期",
                "一天",
                "当天",
                "时间",
                "什么时候",
            )
        )
        if not duration_signal:
            return False
        production_signal = any(
            token in normalized
            for token in (
                "假发",
                "做一个",
                "做假发",
                "做好",
                "做完",
                "做得完",
                "完成",
                "制作",
                "能拿",
                "拿到",
            )
        )
        return production_signal

    def _looks_like_time_arrangement_statement(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        if "时间" not in normalized and "几点去" not in normalized:
            return False
        patterns = (
            "定时间",
            "约时间",
            "安排时间",
            "协调时间",
            "联系她们定时间",
            "联系他们定时间",
            "联系她定时间",
            "联系他定时间",
            "告诉你",
            "朋友也要去",
            "朋友也去",
            "回头定时间",
            "晚点定时间",
            "什么时候去",
            "几点去",
            "哪天去",
        )
        return any(pattern in normalized for pattern in patterns)

    def _looks_like_lifespan_query(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return False
        return any(token in normalized for token in LIFESPAN_PRIORITY_KEYWORDS)

    def _decide_service_hours_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        del route
        text = str(latest_user_text or "").strip()
        if not text:
            return None
        if self._looks_like_closing_confirmation(text):
            return None
        probe_decision = AgentDecision(reply_text="", intent="general", route_reason="", reply_goal="", media_plan="none")
        if not self._is_service_hours_query_like(text, probe_decision):
            return None

        normalized = re.sub(r"\s+", "", text).lower()
        direct_service_hours_signal = any(token in normalized for token in ("营业时间", "几点", "到几点", "下班"))
        kb_detail = self.knowledge_service.find_answer_detail(text, threshold=self.knowledge_threshold)
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
        if not (kb_detail.get("matched") and (kb_intent == "service_hours" or "营业时间" in tags)):
            if not direct_service_hours_signal:
                return None
            fallback_answer = WEEKEND_CLOSED_REPLY
            return AgentDecision(
                reply_text=fallback_answer,
                intent="general",
                route_reason="service_hours_priority_fallback",
                reply_goal="解答",
                media_plan="none",
                reply_source="knowledge",
                rule_id="SERVICE_HOURS_PRIORITY",
                rule_applied=True,
                kb_match_score=0.0,
                kb_match_question="",
                kb_match_mode="service_hours_priority_fallback",
                kb_item_id="",
                kb_variant_total=0,
                kb_variant_selected_index=-1,
                kb_variant_fallback_llm=False,
                kb_confident=True,
            )

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
            route_reason="service_hours_priority",
            reply_goal="解答",
            media_plan="none",
            reply_source="knowledge",
            rule_id="SERVICE_HOURS_PRIORITY",
            rule_applied=True,
            kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
            kb_match_question=str(kb_detail.get("question", "") or ""),
            kb_match_mode=f"service_hours_priority_{str(kb_detail.get('mode', '') or 'match')}",
            kb_item_id=str(kb_detail.get("item_id", "") or ""),
            kb_variant_total=len(kb_answers),
            kb_variant_selected_index=selected_index if selected_answer else (-1 if exhausted else 0),
            kb_variant_fallback_llm=False,
            kb_confident=True,
        )

    def _decide_delivery_time_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        del route
        text = str(latest_user_text or "").strip()
        if not text or not self._looks_like_production_timeline_query(text):
            return None

        kb_detail = self.knowledge_service.find_answer_detail(text, threshold=min(self.knowledge_threshold, 0.1))
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
        if not (kb_detail.get("matched") and (kb_intent == "delivery_time" or {"当天", "时间"} & tags)):
            if not self._looks_like_same_day_duration_query(text):
                return None
            answer = self._normalize_reply_text("姐姐，当天是做不好的，我们是私人定制，需要时间制作。")
            self._remember_selected_kb_answer(
                user_state=user_state,
                user_id_hash=user_id_hash,
                answer_text=answer,
            )
            return AgentDecision(
                reply_text=answer,
                intent="general",
                route_reason="delivery_time_priority_fallback",
                reply_goal="解答",
                media_plan="none",
                reply_source="knowledge",
                rule_id="DELIVERY_TIME_PRIORITY",
                rule_applied=True,
                kb_match_score=0.0,
                kb_match_question="",
                kb_match_mode="delivery_time_priority_fallback",
                kb_item_id="",
                kb_variant_total=0,
                kb_variant_selected_index=-1,
                kb_variant_fallback_llm=False,
                kb_confident=True,
            )

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
            route_reason="delivery_time_priority",
            reply_goal="解答",
            media_plan="none",
            reply_source="knowledge",
            rule_id="DELIVERY_TIME_PRIORITY",
            rule_applied=True,
            kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
            kb_match_question=str(kb_detail.get("question", "") or ""),
            kb_match_mode=f"delivery_time_priority_{str(kb_detail.get('mode', '') or 'match')}",
            kb_item_id=str(kb_detail.get("item_id", "") or ""),
            kb_variant_total=len(kb_answers),
            kb_variant_selected_index=selected_index if selected_answer else (-1 if exhausted else 0),
            kb_variant_fallback_llm=False,
            kb_confident=True,
        )

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
        session_state: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        state = dict(session_state or {})
        has_both_images_sent = (
            int(state.get("address_image_sent_count", 0) or 0) > 0
            and int(state.get("contact_image_sent_count", 0) or 0) > 0
        )
        normalized = re.sub(r"\s+", "", str(latest_user_text or ""))
        if str(route.get("target_store", "") or "").strip() in {"", "unknown"} and any(
            token in normalized for token in ("先到店还是先预约", "先预约还是先到店", "先预约", "先到店")
        ):
            return AgentDecision(
                reply_text=self._pick_visit_flow_reply(
                    session_state=state,
                    category="appointment_process",
                    replies=VISIT_PROCESS_REPLY_POOL,
                ),
                intent="appointment",
                route_reason=str(route.get("reason", "unknown") or "unknown"),
                reply_goal="解答",
                media_plan="none",
                reply_source="rule",
                rule_id="VISIT_APPOINTMENT_PROCESS",
                rule_applied=True,
            )
        kb_detail = self.knowledge_service.find_answer_detail(
            latest_user_text,
            threshold=self.knowledge_threshold,
        )
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
        if has_both_images_sent and not (kb_detail.get("matched") and (kb_intent == "appointment" or "预约" in tags)):
            return None
        store_specific_reply = self._build_store_appointment_contact_reply(
            latest_user_text,
            route,
            session_state=state,
            conversation_history=conversation_history or [],
        )
        if store_specific_reply:
            route_target_store = str(route.get("target_store", "") or "").strip()
            if not route_target_store or route_target_store == "unknown":
                route_target_store = str(state.get("last_target_store", "") or "").strip()
            if route_target_store and route_target_store != "unknown":
                should_send_contact_image = (
                    int(state.get("contact_image_sent_count", 0) or 0) <= 0
                    and not bool(state.get("contact_captured", False))
                )
                return AgentDecision(
                    reply_text=store_specific_reply,
                    intent="appointment",
                    route_reason=str(route.get("reason", "unknown") or "unknown"),
                    reply_goal="承接联系方式" if should_send_contact_image else "解答",
                    media_plan="contact_image" if should_send_contact_image else "none",
                    reply_source="knowledge",
                    rule_id="KB_MATCH_CONTACT_IMAGE",
                    rule_applied=False,
                    kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
                    kb_match_question=str(kb_detail.get("question", "") or ""),
                    kb_match_mode="appointment_route_contact_fallback",
                    kb_item_id=str(kb_detail.get("item_id", "") or ""),
                    kb_variant_total=0,
                    kb_variant_selected_index=-1,
                    kb_variant_fallback_llm=False,
                    kb_confident=True,
                    force_contact_image=should_send_contact_image,
                    kb_contact_trigger_type="appointment",
                )
        if not (kb_detail.get("matched") and (kb_intent == "appointment" or "预约" in tags)):
            if has_both_images_sent:
                return None
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

        should_send_contact_image = (
            int(state.get("contact_image_sent_count", 0) or 0) <= 0
            and not bool(state.get("contact_captured", False))
        )
        if any(token in normalized for token in ("需要预约", "怎么预约", "如何预约", "要预约")):
            answer = self._pick_visit_flow_reply(
                session_state=state,
                category="appointment_intro",
                replies=VISIT_APPOINTMENT_REPLY_POOL,
            )
        return AgentDecision(
            reply_text=answer,
            intent="appointment",
            route_reason=str(route.get("reason", "unknown") or "unknown"),
            reply_goal="承接联系方式" if should_send_contact_image else "解答",
            media_plan="contact_image" if should_send_contact_image else "none",
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
            force_contact_image=should_send_contact_image,
            kb_contact_trigger_type="appointment",
        )

    def _build_store_appointment_contact_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        session_state: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        text = str(latest_user_text or "").strip()
        if not text:
            return ""
        state = dict(session_state or {})
        route_type = str(route.get("route_type", "") or "").strip()
        target_store = str(route.get("target_store", "") or "").strip()
        refer_current_store = any(
            token in re.sub(r"\s+", "", text)
            for token in ("这家", "这个店", "那家", "那个店", "刚才那家", "刚刚那家")
        )
        if (not target_store or target_store == "unknown") and refer_current_store:
            target_store = str(state.get("last_target_store", "") or "").strip()
        has_store_context = bool(target_store and target_store != "unknown")
        if route_type != "coverage" and not has_store_context:
            return ""
        visible_history = list(conversation_history or [])
        if not (
            self._looks_like_appointment_query(text)
            or self.knowledge_service.is_address_query(text)
            or self._has_precise_geo_context_for_current_query(route)
        ):
            return ""
        allow_store_specific_context = (
            bool(visible_history)
            or int(state.get("address_image_sent_count", 0) or 0) > 0
            or str(route.get("reason", "") or "").strip() not in {"", "unknown"}
        )
        if not allow_store_specific_context:
            return ""
        store = self.knowledge_service.get_store_display(target_store)
        store_name = str(store.get("store_name", "") or self._store_recommend_display_name(target_store, "门店"))
        if target_store == "beijing_chaoyang" and store_name.endswith("门店"):
            store_name = f"{store_name[:-2]}店"
        if bool(state.get("contact_captured", False)):
            return f"姐姐，电话我这边已经收到了，您把方便的时间告诉我，我就按{store_name}帮您继续安排。❤️"
        if int(state.get("contact_image_sent_count", 0) or 0) <= 0:
            return f"姐姐，{store_name}这边您看下面标注的位置添加我好友（专属客服），我帮您预约到店，好让老师提前安排接待您！❤️"
        return f"姐姐，您加上专属客服后，把方便的时间发我，我这边就帮您安排{store_name}的预约到店，好有老师接待您！❤️"

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
        state = dict(getattr(self, "_current_unified_state", {}) or {})
        normalized = re.sub(r"\s+", "", str(latest_user_text or ""))
        if any(token in normalized for token in ("量头围", "头围", "不会量", "怎么量")):
            return AgentDecision(
                reply_text=self._pick_visit_flow_reply(
                    session_state=state,
                    category="measurement",
                    replies=VISIT_MEASUREMENT_REPLY_POOL,
                ),
                intent="process",
                route_reason=str(route.get("reason", "unknown") or "unknown"),
                reply_goal="解答",
                media_plan="none",
                reply_source="rule",
                rule_id="VISIT_MEASUREMENT_PROCESS",
                rule_applied=True,
            )
        if any(token in normalized for token in ("流程", "怎么走", "想买", "先到店还是先预约", "先预约还是先到店", "先预约", "先到店")):
            return AgentDecision(
                reply_text=self._pick_visit_flow_reply(
                    session_state=state,
                    category="process",
                    replies=VISIT_PROCESS_REPLY_POOL,
                ),
                intent="process",
                route_reason=str(route.get("reason", "unknown") or "unknown"),
                reply_goal="解答",
                media_plan="none",
                reply_source="rule",
                rule_id="VISIT_PROCESS_PRIORITY",
                rule_applied=True,
            )

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

    def _decide_suitable_audience_priority_reply(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Optional[AgentDecision]:
        del route
        text = str(latest_user_text or "").strip()
        if not text:
            return None

        kb_detail = self.knowledge_service.find_answer_detail(
            latest_user_text,
            threshold=min(self.knowledge_threshold, 0.1),
        )
        kb_intent = str(kb_detail.get("intent", "") or "").strip().lower()
        tags = {str(tag).strip() for tag in (kb_detail.get("tags", []) or []) if str(tag).strip()}
        if not (kb_detail.get("matched") and (kb_intent == "suitable_audience_chat" or "适用人群" in tags)):
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
            route_reason="suitable_audience_priority",
            reply_goal="解答",
            media_plan="none",
            reply_source="knowledge",
            rule_id="SUITABLE_AUDIENCE_PRIORITY",
            rule_applied=True,
            kb_match_score=float(kb_detail.get("score", 0.0) or 0.0),
            kb_match_question=str(kb_detail.get("question", "") or ""),
            kb_match_mode=f"suitable_audience_priority_{str(kb_detail.get('mode', '') or 'match')}",
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
        return agent_rule_engine.decide_general_reply(
            self,
            latest_user_text=latest_user_text,
            intent=intent,
            route=route,
            conversation_history=conversation_history,
            session_state=session_state,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )

    def _decide_llm_direct_seed_reply(
        self,
        latest_user_text: str,
        intent: str,
        route: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        session_state: Dict[str, Any],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
        is_first_turn_global: bool = False,
    ) -> Optional[AgentDecision]:
        text = str(latest_user_text or "").strip()
        if not text:
            return None
        if self._looks_like_closing_confirmation(text):
            return AgentDecision(
                reply_text=self._build_closing_confirmation_reply(),
                intent="general",
                route_reason=str(route.get("reason", "unknown") or "unknown"),
                reply_goal="承接联系方式",
                media_plan="none",
                reply_source="rule",
                rule_id="CLOSING_CONFIRM_REPLY",
                rule_applied=True,
            )

        price_priority_decision = self._decide_price_priority_reply(
            latest_user_text=text,
            route=route,
            conversation_history=conversation_history,
            session_state=session_state,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if price_priority_decision is not None:
            return price_priority_decision

        delivery_time_priority_decision = self._decide_delivery_time_priority_reply(
            latest_user_text=text,
            route=route,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if delivery_time_priority_decision is not None:
            return delivery_time_priority_decision

        lifespan_priority_decision = self._decide_lifespan_priority_reply(
            latest_user_text=text,
            route=route,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if lifespan_priority_decision is not None:
            return lifespan_priority_decision

        suitable_audience_priority_decision = self._decide_suitable_audience_priority_reply(
            latest_user_text=text,
            route=route,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if suitable_audience_priority_decision is not None:
            return suitable_audience_priority_decision

        service_hours_priority_decision = self._decide_service_hours_priority_reply(
            latest_user_text=text,
            route=route,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if service_hours_priority_decision is not None:
            return service_hours_priority_decision

        process_priority_decision = self._decide_process_priority_reply(
            latest_user_text=text,
            route=route,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )
        if process_priority_decision is not None:
            return process_priority_decision

        route_target_store = str(route.get("target_store", "") or "").strip()
        route_reason = str(route.get("reason", "unknown") or "unknown")
        if (
            intent == "address"
            and (
                route_target_store not in {"", "unknown"}
                or route_reason in {
                    "unknown",
                    "need_region",
                    "need_district",
                    "need_clarify",
                    "sh_route_need_clarify",
                    "shanghai_need_arrival_point",
                    "shanghai_need_district",
                    "beijing_all_district",
                    "jiangzhe_to_sh_renmin",
                }
            )
            and not self._should_block_store_context_inheritance(text)
        ):
            rule_decision = self._decide_rule_reply(
                text=text,
                intent=intent,
                route=route,
                session_state=session_state,
                conversation_history=conversation_history,
                user_state=user_state,
                is_first_turn_global=is_first_turn_global,
            )
            rule_id = str(rule_decision.rule_id or "")
            if (
                rule_id in {"ADDR_STORE_RECOMMEND", "STORE_RECOMMENDATION", "ADDR_OUT_OF_COVERAGE"}
                or rule_id.startswith("ADDR_ASK_")
            ):
                return rule_decision

        if self._looks_like_appointment_query(text):
            appointment_priority_decision = self._decide_appointment_priority_reply(
                latest_user_text=text,
                route=route,
                session_state=session_state,
                user_state=user_state,
                user_id_hash=user_id_hash,
            )
            if appointment_priority_decision is not None:
                return appointment_priority_decision

        address_text_after_image_decision = self._build_address_text_after_image_decision(
            latest_user_text=text,
            route=route,
            intent=intent,
            session_state=session_state,
        )
        if address_text_after_image_decision is not None:
            return address_text_after_image_decision

        address_contact_after_text_decision = self._build_address_contact_after_text_decision(
            latest_user_text=text,
            route=route,
            intent=intent,
            session_state=session_state,
        )
        if address_contact_after_text_decision is not None:
            return address_contact_after_text_decision

        if self._should_apply_rule_decision(text=text, intent=intent, route=route, session_state=session_state):
            if self._should_keep_llm_direct_address_guardrails(text, session_state=session_state):
                return None
            rule_decision = self._decide_rule_reply(
                text=text,
                intent=intent,
                route=route,
                session_state=session_state,
                conversation_history=conversation_history,
                user_state=user_state,
                is_first_turn_global=is_first_turn_global,
            )
            rule_id = str(rule_decision.rule_id or "")
            if (
                rule_id in {"ADDR_STORE_RECOMMEND", "ADDR_OUT_OF_COVERAGE", "ADDR_TEXT_AFTER_IMAGE"}
                or rule_id.startswith("ADDR_ASK_")
            ):
                return rule_decision

        return None

    def _should_keep_llm_direct_address_guardrails(self, text: str, session_state: Optional[Dict[str, Any]] = None) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        if self._should_block_store_context_inheritance(text):
            return False
        session_state = dict(session_state or {})
        has_known_store = str(session_state.get("last_target_store", "") or "").strip() not in {"", "unknown"}
        has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
        if (
            not has_known_store
            and not has_sent_address
            and any(token in normalized for token in ("地址在哪", "地址在哪里", "地址在哪儿", "门店在哪", "位置在哪"))
        ):
            return False
        if has_known_store and has_sent_address:
            if self.knowledge_service.is_address_query(text):
                return False
            if self.knowledge_service.is_shanghai_route_alias_address_candidate(text):
                return False
            if any(token in normalized for token in ("位置图", "再发", "看图", "位置")):
                return False
        if self.knowledge_service.is_shanghai_route_alias_address_candidate(text):
            return True
        if any(token in normalized for token in ("具体地点", "具体位置", "具体地址")):
            return True
        if has_known_store and self.knowledge_service.is_address_query(text):
            return True
        return False

    def _looks_like_generic_address_opening(self, text: str, intent: str = "") -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        if str(intent or "") == "address":
            if any(token in normalized for token in ("地址", "位置", "门店", "哪家店")):
                return True
        opening_tokens = (
            "地址在哪", "地址在哪里", "地址在哪儿", "地址给我", "把地址发我",
            "位置在哪", "位置在哪里", "门店在哪", "门店在哪里", "店在哪", "店在哪里",
            "发我地址", "给我地址", "位置发我", "发个地址", "店地址",
        )
        return any(token in normalized for token in opening_tokens)

    def _should_apply_llm_direct_address_guardrails(
        self,
        text: str,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if self._should_keep_llm_direct_address_guardrails(text, session_state=session_state):
            return True

        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False

        session_state = dict(session_state or {})
        facts = dict(session_state.get("conversation_facts", {}) or {})
        known_store = str(
            facts.get("recommended_store", "")
            or session_state.get("last_target_store", "")
            or ""
        ).strip()
        has_sent_address = int(session_state.get("address_image_sent_count", 0) or 0) > 0
        if not has_sent_address or known_store in {"", "unknown"}:
            return False

        if self.knowledge_service.is_address_query(text):
            return True
        if self.knowledge_service.is_shanghai_route_alias_address_candidate(text):
            return True
        return any(token in normalized for token in ("位置图", "再发", "看图", "位置"))

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
        allow_precise_address_closure: bool = True,
    ) -> AgentDecision:
        return agent_llm_reply.decide_llm_reply(
            self,
            latest_user_text=latest_user_text,
            intent=intent,
            route_reason=route_reason,
            conversation_history=conversation_history,
            session_state=session_state,
            kb_blocked_by_polite_guard=kb_blocked_by_polite_guard,
            kb_polite_guard_reason=kb_polite_guard_reason,
            user_message_override=user_message_override,
            rule_id=rule_id,
            kb_match_score=kb_match_score,
            kb_match_question=kb_match_question,
            kb_match_mode=kb_match_mode,
            kb_item_id=kb_item_id,
            kb_variant_total=kb_variant_total,
            kb_variant_selected_index=kb_variant_selected_index,
            kb_variant_fallback_llm=kb_variant_fallback_llm,
            kb_confident=kb_confident,
            allow_address_guardrails=allow_address_guardrails,
            allow_precise_address_closure=allow_precise_address_closure,
        )

    def _select_kb_variant_answer(
        self,
        answers: List[str],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Tuple[str, int, bool]:
        return agent_llm_reply.select_kb_variant_answer(self, answers, user_state, user_id_hash=user_id_hash)

    def _remember_selected_kb_answer(
        self,
        user_state: Dict[str, Any],
        user_id_hash: str,
        answer_text: str,
    ) -> None:
        agent_llm_reply.remember_selected_kb_answer(self, user_state, user_id_hash, answer_text)

    def _build_kb_variant_fallback_prompt(self, latest_user_text: str, kb_question: str, kb_answer: str) -> str:
        return agent_llm_reply.build_kb_variant_fallback_prompt(self, latest_user_text, kb_question, kb_answer)

    def _rewrite_if_repeated(
        self,
        reply_text: str,
        latest_user_text: str,
        conversation_history: List[Dict[str, str]],
        user_state: Dict[str, Any],
        user_id_hash: str = "",
    ) -> Tuple[str, bool]:
        return agent_llm_reply.rewrite_if_repeated(
            self,
            reply_text=reply_text,
            latest_user_text=latest_user_text,
            conversation_history=conversation_history,
            user_state=user_state,
            user_id_hash=user_id_hash,
        )

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
        return agent_media.plan_media_items(
            self,
            session_id=session_id,
            text=text,
            intent=intent,
            route=route,
            route_reason=route_reason,
            media_plan=media_plan,
            session_state=session_state,
            user_state=user_state,
            force_contact_image=force_contact_image,
        )

    def _queue_address_image(
        self,
        session_id: str,
        session_state: Dict[str, Any],
        target_store: str,
        route_reason: str,
        detected_region: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        return agent_media.queue_address_image(
            self,
            session_id=session_id,
            session_state=session_state,
            target_store=target_store,
            route_reason=route_reason,
            detected_region=detected_region,
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
        return agent_media.queue_contact_image(
            self,
            session_id=session_id,
            text=text,
            intent=intent,
            reason=reason,
            route=route,
            session_state=session_state,
            force_contact_image=force_contact_image,
        )

    def _pick_contact_image_for_session(self, session_state: Dict[str, Any]) -> Optional[str]:
        return agent_media.pick_contact_image_for_session(self, session_state)

    def _resolve_kb_contact_trigger_type(self, latest_user_text: str, kb_detail: Dict[str, Any]) -> str:
        return agent_media.resolve_kb_contact_trigger_type(self, latest_user_text, kb_detail)

    def _looks_like_appointment_query(self, text: str) -> bool:
        return agent_media.looks_like_appointment_query(self, text)

    def _is_contact_image_sent_for_current_geo(self, session_state: Dict[str, Any]) -> bool:
        return agent_media.is_contact_image_sent_for_current_geo(self, session_state)

    def _has_both_images_sent(self, session_state: Dict[str, Any]) -> bool:
        return agent_media.has_both_images_sent(self, session_state)

    def _sync_media_state_from_conversation_log(
        self,
        session_id: str,
        user_hash: str,
        session_state: Dict[str, Any],
    ) -> None:
        agent_media.sync_media_state_from_conversation_log(self, session_id, user_hash, session_state)

    def _sanitize_pending_required_media(
        self,
        items: Any,
        session_state: Optional[Dict[str, Any]] = None,
        latest_planned: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        return agent_media.sanitize_pending_required_media(
            self,
            items,
            session_state=session_state,
            latest_planned=latest_planned,
        )

    def _remove_pending_required_media(self, session_state: Dict[str, Any], media_item: Dict[str, Any]) -> None:
        agent_media.remove_pending_required_media(self, session_state, media_item)

    def _remove_planned_required_media(self, session_state: Dict[str, Any], media_item: Dict[str, Any]) -> None:
        agent_media.remove_planned_required_media(self, session_state, media_item)

    def _pending_media_key(self, media_item: Dict[str, Any]) -> str:
        return agent_media.pending_media_key(self, media_item)

    def register_planned_required_media(
        self,
        session_id: str,
        user_name: str,
        media_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return agent_media.register_planned_required_media(
            self,
            session_id=session_id,
            user_name=user_name,
            media_items=media_items,
        )

    def summarize_user_media_from_logs(self, user_id_hash: str) -> Dict[str, Any]:
        return agent_media.summarize_user_media_from_logs(self, user_id_hash)

    def _store_recommend_display_name(self, target_store: str, fallback_name: str = "") -> str:
        return agent_media.store_recommend_display_name(self, target_store, fallback_name)

    def summarize_user_turns_from_logs(self, user_id_hash: str) -> Dict[str, int]:
        return agent_media.summarize_user_turns_from_logs(self, user_id_hash)

    def is_user_first_turn_global(self, user_id_hash: str) -> bool:
        return agent_media.is_user_first_turn_global(self, user_id_hash)

    def build_first_turn_video_items(self, session_id: str) -> List[Dict[str, Any]]:
        return agent_media.build_first_turn_video_items(self, session_id)

    def _populate_first_turn_media_plan(
        self,
        session_id: str,
        user_name: str,
        decision: AgentDecision,
    ) -> None:
        agent_media.populate_first_turn_media_plan(self, session_id, user_name, decision)

    def summarize_session_video_from_log(self, session_id: str) -> Dict[str, Any]:
        return agent_media.summarize_session_video_from_log(self, session_id)

    def _build_video_media_item(self, trigger_source: str) -> Optional[Dict[str, Any]]:
        return agent_media.build_video_media_item(self, trigger_source)

    def _read_session_log_records(self, session_id: str) -> List[Dict[str, Any]]:
        return agent_media.read_session_log_records(self, session_id)

    def _scan_session_media_records(self, log_path: Path, user_id_hash: str) -> List[Dict[str, Any]]:
        return agent_media.scan_session_media_records(self, log_path, user_id_hash)

    def _session_log_file(self, session_id: str) -> Path:
        return agent_media.session_log_file(self, session_id)

    def _session_log_candidates(self, session_id: str) -> List[Path]:
        return agent_media.session_log_candidates(self, session_id)

    def _infer_store_from_image_path(self, media_path: str) -> str:
        return agent_media.infer_store_from_image_path(self, media_path)

    def _infer_store_from_name(self, name: str) -> str:
        return agent_media.infer_store_from_name(self, name)

    def _pick_address_image(self, target_store: str, session_state: Optional[Dict[str, Any]] = None) -> Optional[str]:
        return agent_media.pick_address_image(self, target_store, session_state=session_state)

    def _pick_video_media(self) -> Optional[str]:
        return agent_media.pick_video_media(self)

    def summarize_recent_assistant_hashes_from_logs(self, user_id_hash: str, limit: int = 40) -> set[str]:
        return agent_media.summarize_recent_assistant_hashes_from_logs(self, user_id_hash, limit=limit)

    def _is_media_whitelist_session(self, session_id: str) -> bool:
        return agent_media.is_media_whitelist_session(self, session_id)

    def _build_general_llm_prompt(self, latest_user_text: str) -> Tuple[str, Dict[str, Any]]:
        return build_general_llm_prompt(self, latest_user_text)

    def _summarize_llm_conversation_state(
        self,
        latest_user_text: str,
        conversation_history: List[Dict[str, str]],
        standard_reply_intent: str = "",
    ) -> Dict[str, str]:
        return summarize_llm_conversation_state(self, latest_user_text, conversation_history, standard_reply_intent)

    def _infer_answer_type(self, text: str) -> str:
        return agent_llm_reply.infer_answer_type(self, text)

    def _top_kb_examples(self, query: str, limit: int = 3) -> List[Tuple[str, str]]:
        return agent_llm_reply.top_kb_examples(self, query, limit=limit)

    def _top_brand_knowledge_snippets(self, query: str, limit: int = 3) -> List[str]:
        return agent_llm_reply.top_brand_knowledge_snippets(self, query, limit=limit)

    def _simple_overlap_score(self, a: str, b: str) -> float:
        return agent_llm_reply.simple_overlap_score(self, a, b)

    def _normalize_reply_text(self, text: str) -> str:
        return normalize_reply_text(self, text)

    def _apply_llm_reply_guardrails(
        self,
        latest_user_text: str,
        reply_text: str,
        session_state: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        allow_address_guardrails: bool = True,
        allow_precise_address_closure: bool = True,
    ) -> Tuple[str, Dict[str, Any]]:
        return apply_llm_reply_guardrails(
            self,
            latest_user_text=latest_user_text,
            reply_text=reply_text,
            session_state=session_state,
            conversation_history=conversation_history,
            allow_address_guardrails=allow_address_guardrails,
            allow_precise_address_closure=allow_precise_address_closure,
        )

    def _build_reply_closure_info(
        self,
        reply_text: str,
        base_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return build_reply_closure_info(self, reply_text=reply_text, base_info=base_info)

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
        risky_reply_tokens = (
            "加您",
            "加你",
            "加好友",
            "留个方式",
            "具体沟通",
            "主动跟您介绍",
            "我来加您",
        )
        if self._looks_like_direct_contact_request(text):
            return True
        if re.search(r"1[3-9]\d{9}", normalized_text):
            return True
        if any(k.lower() in normalized_text for k in CONTACT_INTENT_KEYWORDS):
            return True
        if any(k.lower() in normalized_reply for k in CONTACT_COMPLIANCE_BLOCK_KEYWORDS):
            return True
        if any(token in normalized_reply for token in risky_reply_tokens):
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
        candidates = [
            str(text or ""),
            str(reply_text or ""),
            " ".join(str(item.get("content", "") or "") for item in conversation_history[-4:]),
        ]
        for candidate in candidates:
            resolved = self._infer_store_from_context_text(candidate)
            if resolved:
                return resolved
        store_key = str((session_state or {}).get("last_target_store", "") or "").strip()
        if store_key and store_key != "unknown":
            return store_key
        return ""

    def _infer_store_from_context_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return ""
        direct_store_keys = {
            "beijing_chaoyang",
            "sh_jingan",
            "sh_renmin",
            "sh_hongkou",
            "sh_wujiaochang",
            "sh_xuhui",
        }
        if normalized in direct_store_keys:
            return normalized

        store_aliases = {
            "beijing_chaoyang": ("建外soho", "朝阳", "北京店", "北京门店", "东三环中路"),
            "sh_jingan": ("静安寺", "静安店", "静安门店", "静安", "愚园路", "环球世界大厦"),
            "sh_renmin": ("人民广场", "人广", "黄浦", "黄埔", "汉口路", "亚洲大厦"),
            "sh_hongkou": ("虹口", "花园路", "嘉和国际大厦"),
            "sh_wujiaochang": ("五角场", "杨浦", "政通路", "万达广场e栋c座"),
            "sh_xuhui": ("徐汇", "徐家汇", "漕溪北路", "中航德必大厦"),
        }
        matched_stores = [
            store_key
            for store_key, aliases in store_aliases.items()
            if any(token in normalized for token in aliases)
        ]
        unique_stores = list(dict.fromkeys(matched_stores))
        if len(unique_stores) != 1:
            return ""
        return unique_stores[0]

    def _extract_store_candidates_from_text(self, text: str) -> List[str]:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return []
        store_aliases = {
            "beijing_chaoyang": ("建外soho", "朝阳", "北京店", "北京门店", "东三环中路"),
            "sh_jingan": ("静安寺", "静安店", "静安门店", "静安", "愚园路", "环球世界大厦"),
            "sh_renmin": ("人民广场", "人广", "黄浦", "黄埔", "汉口路", "亚洲大厦"),
            "sh_hongkou": ("虹口", "花园路", "嘉和国际大厦"),
            "sh_wujiaochang": ("五角场", "杨浦", "政通路", "万达广场e栋c座"),
            "sh_xuhui": ("徐汇", "徐家汇", "漕溪北路", "中航德必大厦"),
        }
        return [
            store_key
            for store_key, aliases in store_aliases.items()
            if any(token in normalized for token in aliases)
        ]

    def _should_block_store_context_inheritance(self, text: str) -> bool:
        return (
            agent_contact_flow.looks_like_store_recommendation_challenge(text)
            or agent_contact_flow.looks_like_store_preference_statement(text)
            or agent_contact_flow.looks_like_human_check(text)
            or agent_contact_flow.looks_like_repetition_frustration(text)
        )

    def _should_lock_store_context_from_text(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized or self._should_block_store_context_inheritance(text):
            return False
        lock_tokens = (
            "这家怎么预约",
            "这家营业到几点",
            "这家几点",
            "这家怎么走",
            "这家地址",
            "这家位置",
            "这个店怎么预约",
            "这个店营业到几点",
            "去这家",
            "就这家",
            "还是这家",
            "就是这家",
        )
        if any(token in normalized for token in lock_tokens):
            return True
        return bool(self._infer_store_from_context_text(text))

    def _infer_city_from_store_key(self, store_key: str) -> str:
        normalized = str(store_key or "").strip()
        if not normalized:
            return ""
        if normalized == "beijing_chaoyang":
            return "beijing"
        if normalized.startswith("sh_"):
            return "shanghai"
        return ""

    def _has_store_address_image_sent(
        self,
        session_state: Dict[str, Any],
        target_store: str,
    ) -> bool:
        normalized_store = str(target_store or "").strip()
        if not normalized_store or normalized_store == "unknown":
            return False
        sent_stores = {
            str(item).strip()
            for item in (session_state.get("sent_address_stores", []) or [])
            if str(item).strip()
        }
        return normalized_store in sent_stores

    def _should_skip_store_recommend_override(
        self,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> bool:
        target_store = str(route.get("target_store", "") or session_state.get("last_target_store", "") or "").strip()
        return self._has_store_address_image_sent(session_state, target_store)

    def _should_block_unresolved_address_media(
        self,
        latest_user_text: str,
        decision: AgentDecision,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> bool:
        if str(decision.intent or "") != "address":
            return False
        closure_info = dict(getattr(decision, "reply_closure_info", {}) or {})
        if str(closure_info.get("target_store", "") or "").strip():
            return False
        if str(closure_info.get("closure_type", "") or "") in {"precise_address", "address_image_promise", "store_recommendation"}:
            return False

        route_reason = str(
            decision.route_reason or route.get("reason", "") or session_state.get("last_geo_route_reason", "")
        ).strip()
        if route_reason in {"need_region", "need_district", "shanghai_need_district", "need_clarify", "sh_route_need_clarify"}:
            return True

        explicit_store = self._infer_store_from_context_text(latest_user_text)
        if explicit_store:
            return False

        if str(decision.reply_goal or "") == "追问地区":
            return True

        if int(session_state.get("address_image_sent_count", 0) or 0) > 0:
            return False

        target_store = str(route.get("target_store", "") or "").strip()
        if target_store and target_store != "unknown":
            return False

        return self.knowledge_service.is_address_query(latest_user_text)

    def _enrich_route_from_conversation_state(
        self,
        latest_user_text: str,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        enriched = dict(route or {})
        target_store = str(enriched.get("target_store", "") or "").strip()
        if target_store and target_store != "unknown":
            return enriched

        explicit_store = self._infer_store_from_context_text(latest_user_text)
        if explicit_store:
            enriched["target_store"] = explicit_store
            enriched["route_type"] = str(enriched.get("route_type", "") or "coverage")
            if str(enriched.get("reason", "") or "").strip() in {"", "unknown"}:
                enriched["reason"] = "explicit_store_mention"
            explicit_city = self._infer_city_from_store_key(explicit_store)
            if explicit_city:
                if not str(enriched.get("detected_region", "") or "").strip():
                    enriched["detected_region"] = explicit_city
                if not str(enriched.get("city", "") or "").strip():
                    enriched["city"] = explicit_city
            return enriched

        known_store = str(
            session_state.get("current_store_context", "")
            or session_state.get("store_delivery_authority", "")
            or
            (session_state.get("conversation_facts", {}) or {}).get("recommended_store", "")
            or session_state.get("last_target_store", "")
            or ""
        ).strip()
        if not known_store or known_store == "unknown":
            return enriched
        if self._should_block_store_context_inheritance(latest_user_text):
            return enriched

        route_reason = str(enriched.get("reason", "") or "").strip()
        route_city = str(enriched.get("city", "") or "").strip()
        route_detected_region = str(enriched.get("detected_region", "") or "").strip()
        if route_reason and route_reason not in {"unknown", "conversation_store_resume"}:
            return enriched
        if route_city and route_city not in {"", "unknown"}:
            return enriched
        if route_detected_region:
            return enriched

        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        if not normalized:
            return enriched
        if self._looks_like_generic_address_opening(latest_user_text, intent="address"):
            return enriched
        if any(token in normalized for token in ("我在上海", "我在北京", "上海地址", "北京地址", "哪个城市", "什么城市")):
            return enriched

        asks_address = (
            self.knowledge_service.is_address_query(latest_user_text)
            or self.knowledge_service.is_shanghai_route_alias_address_candidate(latest_user_text)
            or any(token in normalized for token in ("位置图", "位置图片", "看图", "再发我看下", "再发一下", "位置"))
        )
        same_store_confirmation = any(token in normalized for token in ("对吧", "是吧", "就是这家", "还是这家", "最近的"))
        asks_appointment = self._looks_like_appointment_query(latest_user_text) and any(
            token in normalized for token in ("这家", "这个店", "那家", "那个店")
        )

        if not (asks_address or asks_appointment or same_store_confirmation):
            return enriched

        enriched["target_store"] = known_store
        enriched["route_type"] = "coverage"
        enriched["reason"] = str(enriched.get("reason", "") or "conversation_store_resume")
        facts = dict(session_state.get("conversation_facts", {}) or {})
        if not enriched.get("detected_region"):
            enriched["detected_region"] = str(facts.get("city", "") or session_state.get("last_detected_region", "") or "")
        return enriched

    def _build_conversation_state_updates(
        self,
        latest_user_text: str,
        decision: AgentDecision,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
        current_answer_topic: str,
        current_answer_facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        facts = dict(session_state.get("conversation_facts", {}) or {})
        active_topic = str(session_state.get("active_topic", "") or "")
        previous_topics = [
            str(item).strip()
            for item in (session_state.get("previous_topics", []) or [])
            if str(item).strip()
        ]
        topic_reply_memory = dict(session_state.get("topic_reply_memory", {}) or {})
        current_turn_action = self._infer_current_turn_action(
            latest_user_text=latest_user_text,
            decision=decision,
            route=route,
            session_state=session_state,
            current_answer_topic=current_answer_topic,
        )

        route_city = str(route.get("city", "") or route.get("detected_region", "") or "").strip()
        if route_city and route_city not in {"unknown", "coverage"}:
            facts["city"] = route_city
        block_store_write = self._should_block_store_context_inheritance(latest_user_text)
        recommended_store = str(
            current_answer_facts.get("target_store", "")
            or route.get("target_store", "")
            or facts.get("recommended_store", "")
            or session_state.get("current_store_context", "")
            or session_state.get("store_delivery_authority", "")
            or session_state.get("last_target_store", "")
            or ""
        ).strip()
        if recommended_store and recommended_store != "unknown" and not block_store_write:
            facts["recommended_store"] = recommended_store
        elif block_store_write:
            facts.pop("recommended_store", None)
        if current_answer_topic == "price" and current_answer_facts.get("price_range"):
            facts["price_range"] = str(current_answer_facts.get("price_range", "") or "")
        if current_answer_topic == "service_hours" and current_answer_facts.get("business_hours"):
            facts["business_hours"] = str(current_answer_facts.get("business_hours", "") or "")
        if current_answer_topic == "lifespan" and current_answer_facts.get("lifespan"):
            facts["lifespan"] = str(current_answer_facts.get("lifespan", "") or "")
        if self._looks_like_appointment_query(latest_user_text) or "预约" in str(decision.reply_text or ""):
            facts["appointment_ready"] = True

        if current_answer_topic:
            if active_topic and active_topic != current_answer_topic:
                previous_topics = [topic for topic in [active_topic, *previous_topics] if topic and topic != current_answer_topic]
            active_topic = current_answer_topic
        previous_topics = previous_topics[:3]

        reply_expression_type = self._infer_reply_expression_type(
            latest_user_text=latest_user_text,
            current_answer_topic=current_answer_topic,
            decision=decision,
            current_turn_action=current_turn_action,
        )
        if current_answer_topic and reply_expression_type:
            topic_reply_memory[current_answer_topic] = reply_expression_type

        conversation_stage = self._infer_conversation_stage(
            latest_user_text=latest_user_text,
            decision=decision,
            route=route,
            session_state=session_state,
            facts=facts,
            current_answer_topic=current_answer_topic,
            current_turn_action=current_turn_action,
        )

        current_store_context = str(session_state.get("current_store_context", "") or "").strip()
        store_delivery_authority = str(session_state.get("store_delivery_authority", "") or "").strip()
        if not block_store_write and recommended_store and recommended_store != "unknown":
            if current_answer_topic in {"appointment", "service_hours", "store_recommendation"} or self._looks_like_appointment_query(latest_user_text):
                current_store_context = recommended_store
            if str(decision.reply_goal or "") == "地址交付":
                store_delivery_authority = recommended_store
        if str(decision.reply_goal or "") not in {"地址交付", "地址补发"}:
            store_delivery_authority = ""

        return {
            "conversation_facts": facts,
            "conversation_stage": conversation_stage,
            "topic_reply_memory": topic_reply_memory,
            "active_topic": active_topic,
            "previous_topics": previous_topics,
            "current_turn_action": current_turn_action,
            "current_store_context": current_store_context,
            "store_delivery_authority": store_delivery_authority,
            "store_candidates": list(dict.fromkeys(self._extract_store_candidates_from_text(latest_user_text)))[:3],
            **self._build_remote_flow_state_updates(
                latest_user_text=latest_user_text,
                decision=decision,
                route=route,
                session_state=session_state,
            ),
        }

    def _build_remote_flow_state_updates(
        self,
        latest_user_text: str,
        decision: AgentDecision,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        updates = {
            "remote_flow_active": bool(session_state.get("remote_flow_active", False)),
            "remote_contact_image_sent": bool(session_state.get("remote_contact_image_sent", False)),
            "remote_flow_reason": str(session_state.get("remote_flow_reason", "") or ""),
            "remote_contact_captured": bool(session_state.get("remote_contact_captured", False)),
            "contact_captured": bool(session_state.get("contact_captured", False)),
            "remote_reply_counters": dict(session_state.get("remote_reply_counters", {}) or {}),
        }
        route_reason = str(getattr(decision, "route_reason", "") or "")
        if route_reason in {"remote_flow_entry", "remote_flow_followup", "out_of_coverage", "not_in_shanghai_remote"}:
            updates["remote_flow_active"] = True
            updates["remote_flow_reason"] = route_reason
        if str(getattr(decision, "rule_id", "") or "") in {
            "CONTACT_PHONE_SUBMITTED",
            "CONTACT_ALREADY_ADDED",
            "CONTACT_ALREADY_CAPTURED",
        }:
            updates["remote_contact_captured"] = True
            updates["contact_captured"] = True

        normalized = self._normalize_flow_text(latest_user_text)
        if route.get("target_store") and str(route.get("target_store") or "") != "unknown" and not (
            self._looks_like_remote_region_query(latest_user_text)
            or self._looks_like_remote_visit_block(latest_user_text)
            or self._looks_like_remote_shipping_query(latest_user_text)
        ):
            updates["remote_flow_active"] = False
            updates["remote_flow_reason"] = ""
        if not updates["remote_flow_active"]:
            updates["remote_contact_image_sent"] = False
            updates["remote_contact_captured"] = False
            updates["remote_reply_counters"] = {}
        return updates

    def _infer_current_turn_action(
        self,
        latest_user_text: str,
        decision: AgentDecision,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
        current_answer_topic: str,
    ) -> str:
        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        previous_active_topic = str(session_state.get("active_topic", "") or "")
        conversation_stage = str(session_state.get("conversation_stage", "") or "")
        known_store = str(
            session_state.get("current_store_context", "")
            or (session_state.get("conversation_facts", {}) or {}).get("recommended_store", "")
            or session_state.get("last_target_store", "")
            or ""
        )
        if self._should_block_store_context_inheritance(latest_user_text):
            known_store = ""

        if known_store and self._looks_like_appointment_query(latest_user_text):
            return "advance_to_next_step"
        if known_store and (
            self.knowledge_service.is_address_query(latest_user_text)
            or any(token in normalized for token in ("位置图", "再发", "看图", "位置"))
        ):
            return "revisit_previous_info" if conversation_stage == "address_image_sent" else "confirm_previous_fact"
        if current_answer_topic and current_answer_topic == previous_active_topic:
            if any(token in normalized for token in ("对吧", "是吧", "是不是", "也是", "一样", "差不多")):
                return "confirm_previous_fact"
            return "followup_same_topic"
        if previous_active_topic == "store_recommendation" and current_answer_topic == "appointment":
            return "advance_to_next_step"
        if current_answer_topic:
            return "new_topic"
        if decision.rule_id in {"ADDR_TEXT_AFTER_IMAGE", "ADDR_CONTACT_AFTER_TEXT"}:
            return "revisit_previous_info"
        return "new_topic"

    def _infer_reply_expression_type(
        self,
        latest_user_text: str,
        current_answer_topic: str,
        decision: AgentDecision,
        current_turn_action: str,
    ) -> str:
        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        if current_answer_topic == "price":
            if any(token in normalized for token in ("贵", "便宜", "优惠", "折扣", "划算")):
                return "objection_response"
            if any(token in normalized for token in ("一样", "也是", "差不多", "第一款", "第二款")):
                return "difference_explainer"
            return "range_answer"
        if current_answer_topic == "service_hours":
            return "confirm_answer" if current_turn_action != "new_topic" else "standard_answer"
        if current_answer_topic == "lifespan":
            return "confirm_answer" if current_turn_action != "new_topic" else "standard_answer"
        if current_answer_topic == "store_recommendation":
            if decision.rule_id in {"ADDR_STORE_RECOMMEND", "STORE_RECOMMENDATION"}:
                return "store_recommendation"
            if current_turn_action == "revisit_previous_info":
                return "address_revisit"
            return "location_followup"
        if current_answer_topic == "appointment":
            return "appointment_progress" if current_turn_action == "advance_to_next_step" else "appointment_definition"
        return ""

    def _infer_conversation_stage(
        self,
        latest_user_text: str,
        decision: AgentDecision,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
        facts: Dict[str, Any],
        current_answer_topic: str,
        current_turn_action: str,
    ) -> str:
        if bool(facts.get("appointment_ready")) and self._looks_like_appointment_query(latest_user_text):
            return "appointment_ready"
        if current_answer_topic == "appointment":
            return "appointment_ready"
        if (
            str(session_state.get("store_delivery_authority", "") or "").strip()
            and int(session_state.get("address_image_sent_count", 0) or 0) > 0
            and str(facts.get("recommended_store", "") or "") != ""
            and not self._should_block_store_context_inheritance(latest_user_text)
        ):
            return "address_image_sent"
        if current_answer_topic == "store_recommendation" or decision.rule_id in {"ADDR_STORE_RECOMMEND", "STORE_RECOMMENDATION"}:
            return "store_recommended"
        if current_answer_topic == "price":
            return "price_answered"
        if current_answer_topic == "service_hours":
            return "service_hours_answered"
        if current_answer_topic == "lifespan":
            return "lifespan_answered"
        if current_turn_action == "advance_to_next_step" and str(facts.get("recommended_store", "") or ""):
            return "appointment_ready"
        return str(session_state.get("conversation_stage", "") or "")

    def _build_answer_context_summary(
        self,
        latest_user_text: str,
        decision: AgentDecision,
        route: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], str]:
        topic = ""
        facts: Dict[str, Any] = {}
        mode = ""
        text = str(latest_user_text or "").strip()
        normalized = re.sub(r"\s+", "", text).lower()

        if decision.rule_id in {"PRICE_PRIORITY", "PRICE_PRIORITY_FALLBACK"}:
            topic = "price"
            facts = {
                "price_range": self._extract_price_range_fact(decision.reply_text) or "3000-6000",
                "kb_item_id": str(decision.kb_item_id or ""),
            }
            mode = "direct_kb"
        elif self._is_lifespan_query_like(text, decision) and (
            decision.rule_id == "LIFESPAN_PRIORITY"
            or bool(self._extract_lifespan_fact(decision.reply_text))
        ):
            topic = "lifespan"
            facts = {
                "lifespan": self._extract_lifespan_fact(decision.reply_text) or "3到5年",
                "kb_item_id": str(decision.kb_item_id or ""),
            }
            mode = "direct_kb" if decision.reply_source == "knowledge" else "contextual_llm"
        elif self._is_service_hours_query_like(text, decision) and (
            decision.reply_source in {"knowledge", "llm"}
            or decision.rule_id == "LLM_KB_VARIANT_FALLBACK"
            or bool(self._extract_business_hours_fact(decision.reply_text))
        ):
            topic = "service_hours"
            facts = {
                "business_hours": self._extract_business_hours_fact(decision.reply_text) or STANDARD_BUSINESS_HOURS_FACT,
                "kb_item_id": str(decision.kb_item_id or ""),
            }
            mode = "direct_kb" if decision.reply_source == "knowledge" else "contextual_llm"
        elif decision.rule_id in {"ADDR_STORE_RECOMMEND", "STORE_RECOMMENDATION"}:
            target_store = str(route.get("target_store", "") or session_state.get("last_target_store", "") or "")
            if target_store and target_store != "unknown":
                store = self.knowledge_service.get_store_display(target_store)
                topic = "store_recommendation"
                facts = {
                    "target_store": target_store,
                    "store_name": self._store_recommend_display_name(target_store, store.get("store_name", "门店")),
                }
                mode = "rule_recommendation"
        elif self._looks_like_appointment_query(text) or "预约" in str(decision.reply_text or ""):
            topic = "appointment"
            facts = {
                "target_store": str(route.get("target_store", "") or session_state.get("last_target_store", "") or ""),
                "appointment_ready": True,
            }
            mode = "direct_kb" if decision.reply_source == "knowledge" else "contextual_llm"

        return topic, facts, mode

    def _should_contextualize_followup_reply(
        self,
        latest_user_text: str,
        current_topic: str,
        current_facts: Dict[str, Any],
        decision: AgentDecision,
        session_state: Dict[str, Any],
    ) -> bool:
        if current_topic not in {"price", "service_hours", "lifespan", "store_recommendation", "appointment"}:
            return False
        previous_topic = str(session_state.get("last_answer_topic", "") or "")
        current_turn_action = self._infer_current_turn_action(
            latest_user_text=latest_user_text,
            decision=decision,
            route={},
            session_state=session_state,
            current_answer_topic=current_topic,
        )
        if previous_topic != current_topic:
            if not (
                current_topic == "appointment"
                and previous_topic == "store_recommendation"
                and current_turn_action == "advance_to_next_step"
            ):
                return False
        previous_text = str(session_state.get("last_answer_text_normalized", "") or "")
        if not previous_text and current_topic != "appointment":
            return False
        current_text_normalized = self._normalize_for_dedupe(decision.reply_text)

        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        if current_topic == "price":
            if current_text_normalized and current_text_normalized != previous_text and not self._has_topic_followup_cue(latest_user_text, current_topic):
                return False
            if any(token in normalized for token in ("贵", "便宜", "优惠", "折扣", "划算")):
                return False
            previous_facts = session_state.get("last_answer_facts", {}) or {}
            previous_kb_item_id = str(previous_facts.get("kb_item_id", "") or "")
            current_kb_item_id = str(current_facts.get("kb_item_id", "") or "")
            if previous_kb_item_id and current_kb_item_id and previous_kb_item_id != current_kb_item_id:
                return False
        elif current_topic in {"service_hours", "lifespan"} and current_text_normalized and current_text_normalized != previous_text and not self._has_topic_followup_cue(latest_user_text, current_topic):
            return False
        if current_topic == "store_recommendation":
            previous_facts = session_state.get("last_answer_facts", {}) or {}
            if str(previous_facts.get("target_store", "") or "") != str(current_facts.get("target_store", "") or ""):
                return False
        if current_topic == "appointment" and current_turn_action not in {"advance_to_next_step", "followup_same_topic", "confirm_previous_fact"}:
            return False
        if current_topic == "appointment" and bool(getattr(decision, "force_contact_image", False)):
            return False
        if current_topic == "appointment" and str(getattr(decision, "rule_id", "") or "") == "KB_MATCH_CONTACT_IMAGE":
            return False
        if current_topic == "appointment" and str(getattr(decision, "rule_id", "") or "") in {
            "PURCHASE_CONTACT_REMIND_ONLY",
            "PURCHASE_CONTACT_FROM_KNOWN_GEO",
        }:
            return False

        if decision.reply_source not in {"knowledge", "rule", "llm"} and decision.rule_id != "LLM_KB_VARIANT_FALLBACK":
            return False
        return True

    def _has_topic_followup_cue(self, latest_user_text: str, current_topic: str) -> bool:
        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        if not normalized:
            return False
        topic_cues = {
            "price": ("一样", "也是", "差不多", "第一款", "第二款", "这个价格", "这个价", "那么贵", "太贵"),
            "service_hours": ("周一", "周二", "周三", "周四", "周五", "这个时间", "也是这个时间", "到几点"),
            "lifespan": ("也是", "这个寿命", "都这样", "这款也是", "也是这个"),
            "store_recommendation": ("对吧", "是吧", "最近的", "就是这家", "还是这家"),
            "appointment": ("预约", "要预约", "怎么预约", "几点去", "什么时候去", "周一去", "安排时间"),
        }
        return any(token in normalized for token in topic_cues.get(current_topic, ()))

    def _contextualize_topic_followup_reply(
        self,
        latest_user_text: str,
        base_reply_text: str,
        current_topic: str,
        current_facts: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        session_state: Dict[str, Any],
    ) -> Tuple[str, bool]:
        previous_topic = str(session_state.get("last_answer_topic", "") or "")
        previous_facts = dict(session_state.get("last_answer_facts", {}) or {})
        return agent_llm_reply.contextualize_topic_followup_reply(
            self,
            latest_user_text=latest_user_text,
            base_reply_text=base_reply_text,
            current_topic=current_topic,
            previous_topic=previous_topic,
            previous_facts=previous_facts,
            current_facts=current_facts,
            conversation_history=conversation_history,
            session_state=session_state,
        )

    def _extract_price_range_fact(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if "3000" in normalized and "6000" in normalized:
            return "3000-6000"
        return ""

    def _extract_business_hours_fact(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if any(token in normalized for token in ("9:30", "9：30", "930")) and any(
            token in normalized for token in ("18:00", "18：00", "1800", "下午6:00", "下午6：00", "下午6点")
        ):
            return STANDARD_BUSINESS_HOURS_FACT
        return ""

    def _extract_lifespan_fact(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if any(token in normalized for token in ("3到5年", "3-5年", "3～5年", "三到五年")):
            return "3到5年"
        return ""

    def _looks_like_travel_schedule_statement(self, latest_user_text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        if not normalized:
            return False
        return any(
            token in normalized
            for token in (
                "过段时间",
                "这段时间",
                "前段时间",
                "四月份",
                "五月份",
                "六月份",
                "七月份",
                "八月份",
                "九月份",
                "十月份",
                "十一月份",
                "十二月份",
                "1月份",
                "2月份",
                "3月份",
                "4月份",
                "5月份",
                "6月份",
                "7月份",
                "8月份",
                "9月份",
                "什么时候去",
                "多久去",
                "过多久去",
                "去北京",
                "去上海",
                "来北京",
                "来上海",
            )
        )

    def _is_service_hours_query_like(self, latest_user_text: str, decision: AgentDecision) -> bool:
        if decision.standard_reply_intent == "service_hours":
            return True
        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        direct_service_hours_signal = any(token in normalized for token in ("营业时间", "几点", "到几点", "下班"))
        if self._looks_like_production_timeline_query(latest_user_text) and not direct_service_hours_signal:
            return False
        if self._looks_like_time_arrangement_statement(latest_user_text) and not direct_service_hours_signal:
            return False
        generic_time_signal = "时间" in normalized
        has_weekday_signal = any(token in normalized for token in ("周一", "周二", "周三", "周四", "周五", "周几"))
        travel_time_signal = self._looks_like_travel_schedule_statement(latest_user_text)
        if travel_time_signal and not direct_service_hours_signal:
            return False
        if direct_service_hours_signal or (generic_time_signal and not travel_time_signal) or (
            has_weekday_signal and any(token in normalized for token in ("这个时间", "也是这个时间"))
        ):
            return True
        detail = self.knowledge_service.find_answer_detail(str(latest_user_text or ""), threshold=self.knowledge_threshold)
        detail_intent = str(detail.get("intent", "") or "").strip().lower()
        detail_tags = {str(tag).strip() for tag in (detail.get("tags", []) or []) if str(tag).strip()}
        return detail_intent == "service_hours" or "营业时间" in detail_tags

    def _is_lifespan_query_like(self, latest_user_text: str, decision: AgentDecision) -> bool:
        if decision.standard_reply_intent == "lifespan":
            return True
        normalized = re.sub(r"\s+", "", str(latest_user_text or "")).lower()
        if self._looks_like_travel_schedule_statement(latest_user_text):
            return False
        if any(token in normalized for token in ("多久", "几年", "寿命", "能用", "能戴", "都这样")):
            return True
        detail = self.knowledge_service.find_answer_detail(str(latest_user_text or ""), threshold=self.knowledge_threshold)
        return str(detail.get("intent", "") or "").strip().lower() == "lifespan"

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
        cleaned = re.sub(r"(?<=\d)\s*[-~～—]+\s*(?=\d)", "到", cleaned)
        cleaned = re.sub(r"\s*[~～]+\s*", "", cleaned)
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
            return self._render_template("general_empty") if key != "general_empty" else f"姐姐我在呢，您这轮最想确认哪一点，我直接接着说清楚{emoji}"
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

    def _collect_fixed_contact_closure_norms(self) -> set[str]:
        template_keys = (
            "contact_intro",
            "purchase_contact_intro",
            "purchase_contact_remind_only",
            "purchase_contact_remote_remind_only",
            "strong_intent_after_both_first",
            "contact_followup_1",
            "contact_followup_2",
            "llm_fallback",
        )
        fixed_texts = [
            str(self._reply_templates.get(key, DEFAULT_REPLY_TEMPLATES.get(key, "")) or "").strip()
            for key in template_keys
        ]
        fixed_texts.extend(
            [
                CONTACT_FACT_FALLBACK,
                PHONE_LEAK_BLOCK_FALLBACK,
                "姐姐，您留个☎️方式，我来加您好友",
            ]
        )
        return {
            self._normalize_for_dedupe(text)
            for text in fixed_texts
            if str(text).strip()
        }


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
