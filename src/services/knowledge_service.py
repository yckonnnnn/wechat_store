"""
知识库服务模块
提供知识库相关的业务逻辑封装
"""

import json
import re
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Set
from PySide6.QtCore import QObject, Signal

from ..data.knowledge_repository import KnowledgeRepository, KnowledgeItem


class KnowledgeService(QObject):
    """知识库服务，封装知识库的业务操作"""

    # 信号
    item_added = Signal(str)        # 条目添加 (item_id)
    item_updated = Signal(str)      # 条目更新 (item_id)
    item_deleted = Signal(str)      # 条目删除 (item_id)
    data_imported = Signal(int)     # 数据导入 (count)
    data_exported = Signal(str)     # 数据导出 (file_path)
    search_completed = Signal(list) # 搜索完成 (results)
    ADDRESS_KEYWORDS = ("地址", "位置", "门店", "店铺", "在哪", "哪里", "怎么去")
    STORE_DETAILS = {
        "beijing_chaoyang": {
            "city": "beijing",
            "store_name": "北京朝阳门店",
            "store_address": "朝阳区建外SOHO东区"
        },
        "sh_jingan": {
            "city": "shanghai",
            "store_name": "上海静安门店",
            "store_address": "静安区愚园路172号环球世界大厦A座"
        },
        "sh_renmin": {
            "city": "shanghai",
            "store_name": "上海人民广场门店",
            "store_address": "黄埔区汉口路650号亚洲大厦"
        },
        "sh_hongkou": {
            "city": "shanghai",
            "store_name": "上海虹口门店",
            "store_address": "虹口区花园路16号嘉和国际大厦东楼"
        },
        "sh_wujiaochang": {
            "city": "shanghai",
            "store_name": "上海五角场门店",
            "store_address": "政通路177号，万达广场E栋C座"
        },
        "sh_xuhui": {
            "city": "shanghai",
            "store_name": "上海徐汇门店",
            "store_address": "徐汇区漕溪北路45号中航德必大厦"
        }
    }
    SHANGHAI_DISTRICT_STORE_MAP = {
        "闵行": "sh_xuhui",
        "长宁": "sh_jingan",
        "静安寺": "sh_jingan",
        "虹口": "sh_hongkou",
        "杨浦": "sh_wujiaochang",
        "五角场": "sh_wujiaochang",
        "黄浦": "sh_renmin",
        "黄埔": "sh_renmin",
        "人民广场": "sh_renmin",
        "人广": "sh_renmin",
        "徐汇": "sh_xuhui",
        "徐家汇": "sh_xuhui",
        "静安": "sh_jingan",
        "浦东": "sh_renmin",
        "浦东新区": "sh_renmin",
        "青浦": "sh_renmin",
        "金山": "sh_renmin",
        "崇明": "sh_renmin",
        "宝山": "sh_hongkou",
        "普陀": "sh_jingan",
        "松江": "sh_xuhui",
        "嘉定": "sh_xuhui",
        "奉贤": "sh_xuhui",
    }
    NON_COVERAGE_REGION_HINTS = (
        "新疆", "西藏", "青海", "宁夏", "甘肃", "云南", "贵州", "广西", "海南",
        "黑龙江", "吉林", "辽宁", "山东", "山西", "陕西", "河南", "湖北", "湖南",
        "江西", "福建", "广东", "四川", "重庆", "安徽",
        "东北", "西北", "西南", "华南", "华北",
        "大连", "沈阳", "哈尔滨", "长春", "呼和浩特", "兰州", "乌鲁木齐", "拉萨",
        "西宁", "银川", "昆明", "南宁", "海口", "郑州", "武汉", "长沙", "南昌",
        "福州", "厦门", "广州", "深圳", "成都", "重庆市"
    )
    PURCHASE_INTENT_KEYWORDS = (
        "怎么买",
        "怎么购买",
        "我想买",
        "能买到吗",
        "在哪里买",
        "怎么下单",
        "怎么订",
        "怎么预约",
        "预约",
        "到店",
        "试戴",
    )
    PRICE_KEYWORDS = ("价格", "多少钱", "价位", "报价", "收费", "预算", "贵", "便宜")
    WEARING_KEYWORDS = (
        "佩戴", "麻烦", "闷", "热", "自然", "掉", "会掉吗", "材质", "真人发",
        "好打理", "清洗", "梳", "售后", "保养", "透气"
    )
    GENERIC_PREFIXES = (
        "好的", "好", "嗯", "额", "那个", "请问", "想问下", "想问一下",
        "我想问", "麻烦问下", "麻烦问一下"
    )
    POLITE_CLOSING_REQUIRED_TAGS = ("礼貌", "结束语")
    REGION_ROUTE_PROVINCE_KEY_MAP = {
        "河北": "河北",
        "河北省": "河北",
        "天津": "天津",
        "天津市": "天津",
        "内蒙古": "内蒙古",
        "内蒙古自治区": "内蒙古",
        "江苏": "江苏",
        "江苏省": "江苏",
        "浙江": "浙江",
        "浙江省": "浙江",
    }

    def __init__(self, repository: KnowledgeRepository, address_config_path: Optional[Path] = None):
        super().__init__()
        self.repository = repository
        self.address_config_path = address_config_path or (Path("config") / "address.json")
        self._address_region_tokens: Set[str] = set()
        self._address_token_to_canonical: Dict[str, str] = {}

        # 连接仓库信号
        self.repository.data_changed.connect(self._on_data_changed)
        self.reload_address_config()

    def _on_data_changed(self):
        """数据变更处理"""
        pass  # 可以在需要时添加通用处理

    def reload_address_config(self) -> None:
        """加载非覆盖地区词典（config/address.json）。"""
        self._address_region_tokens = set()
        self._address_token_to_canonical = {}
        if not self.address_config_path.exists():
            return
        try:
            data = json.loads(self.address_config_path.read_text(encoding="utf-8"))
            provinces = data.get("provinces", []) if isinstance(data, dict) else []
            for item in provinces:
                if not isinstance(item, dict):
                    continue
                province_name = str(item.get("name", "")).strip()
                if province_name:
                    self._register_region_name(province_name, canonical=province_name)
                for city in item.get("cities", []) or []:
                    city_name = str(city).strip()
                    if city_name:
                        canonical = province_name or city_name
                        self._register_region_name(city_name, canonical=canonical)
        except Exception:
            self._address_region_tokens = set()
            self._address_token_to_canonical = {}

    def _register_region_name(self, name: str, canonical: str) -> None:
        for token in self._expand_region_tokens(name):
            if len(token) < 2:
                continue
            self._address_region_tokens.add(token)
            self._address_token_to_canonical.setdefault(token, canonical)

    def _expand_region_tokens(self, name: str) -> Set[str]:
        raw = str(name or "").strip()
        if not raw:
            return set()
        tokens: Set[str] = {raw}
        suffixes = (
            "特别行政区",
            "维吾尔自治区",
            "壮族自治区",
            "回族自治区",
            "自治区",
            "自治州",
            "地区",
            "省",
            "市",
            "区",
            "县",
            "州",
            "盟",
            "旗",
        )
        for suffix in suffixes:
            if raw.endswith(suffix):
                trimmed = raw[: -len(suffix)].strip()
                if len(trimmed) >= 2:
                    tokens.add(trimmed)
        return {t for t in tokens if t}

    def search(self, query: str) -> List[KnowledgeItem]:
        """搜索知识库"""
        results = self.repository.search(query)
        self.search_completed.emit([item.to_dict() for item in results])
        return results

    def find_answer_detail(self, user_message: str, threshold: float = 0.6) -> Dict[str, object]:
        """根据用户消息查找最佳答案，并返回命中细节。"""
        query = (user_message or "").strip()
        if not query:
            return {
                "matched": False,
                "answer": "",
                "answers": [],
                "question": "",
                "score": 0.0,
                "mode": "none",
                "intent": "",
                "tags": [],
                "item_id": "",
                "blocked_by_polite_guard": False,
                "polite_guard_reason": "",
            }

        blocked_by_polite_guard = False
        polite_guard_reason = ""
        normalized_query = self._normalize_for_kb(query)

        # 特殊处理：如果用户表达"贵"的情绪，优先匹配价格贵相关的知识库
        expensive_keywords = ["贵", "太贵", "也贵", "那么贵", "这么贵", "有点贵"]
        if any(k in query for k in expensive_keywords):
            # 尝试匹配价格贵相关的知识库
            items = self.repository.get_all()
            expensive_items = [
                item for item in items
                if any(tag in ["价格", "议价"] for tag in (item.tags or []))
                and any(k in (item.question or "") for k in ["贵", "优惠", "便宜"])
            ]
            if expensive_items:
                best_item = None
                best_score = 0.0
                for item in expensive_items:
                    score = self._simple_overlap_score(query, item.question)
                    if score > best_score:
                        best_score = score
                        best_item = item
                if best_item and best_score >= 0.1:  # 降低阈值，因为是特殊匹配
                    return {
                        "matched": True,
                        "answer": best_item.answer,
                        "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                        "question": best_item.question,
                        "score": float(best_score),
                        "mode": "expensive_priority",
                        "intent": best_item.intent,
                        "tags": list(best_item.tags or []),
                        "item_id": str(best_item.id or ""),
                        "blocked_by_polite_guard": False,
                        "polite_guard_reason": "",
                    }

        # 特殊处理：如果用户询问"进口"，优先匹配进口相关的知识库
        import_keywords = ["进口", "日本", "国外"]
        if any(k in query for k in import_keywords):
            items = self.repository.get_all()
            import_items = [
                item for item in items
                if "进口" in (item.tags or []) or "进口" in (item.question or "")
            ]
            if import_items:
                best_item = None
                best_score = 0.0
                for item in import_items:
                    score = self._simple_overlap_score(query, item.question)
                    if score > best_score:
                        best_score = score
                        best_item = item
                if best_item and best_score >= 0.1:  # 降低阈值
                    return {
                        "matched": True,
                        "answer": best_item.answer,
                        "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                        "question": best_item.question,
                        "score": float(best_score),
                        "mode": "import_priority",
                        "intent": best_item.intent,
                        "tags": list(best_item.tags or []),
                        "item_id": str(best_item.id or ""),
                        "blocked_by_polite_guard": False,
                        "polite_guard_reason": "",
                    }

        # 特殊处理：脸型相关问题
        face_shape_keywords = ["脸型", "脸胖", "脸大", "圆脸", "方脸", "脸比较大", "脸有点胖"]
        if any(k in query for k in face_shape_keywords):
            items = self.repository.get_all()
            face_items = [
                item for item in items
                if "脸型" in (item.tags or []) or any(k in (item.question or "") for k in ["脸型", "脸胖", "脸大"])
            ]
            if face_items:
                best_item = None
                best_score = 0.0
                for item in face_items:
                    score = self._simple_overlap_score(query, item.question)
                    if score > best_score:
                        best_score = score
                        best_item = item
                if best_item and best_score >= 0.1:
                    return {
                        "matched": True,
                        "answer": best_item.answer,
                        "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                        "question": best_item.question,
                        "score": float(best_score),
                        "mode": "face_shape_priority",
                        "intent": best_item.intent,
                        "tags": list(best_item.tags or []),
                        "item_id": str(best_item.id or ""),
                        "blocked_by_polite_guard": False,
                        "polite_guard_reason": "",
                    }

        # 特殊处理：白发相关问题
        white_hair_keywords = ["白发", "头发白", "白头发"]
        if any(k in query for k in white_hair_keywords):
            items = self.repository.get_all()
            white_hair_items = [
                item for item in items
                if "白发" in (item.tags or []) or "白发" in (item.question or "")
            ]
            if white_hair_items:
                best_item = None
                best_score = 0.0
                for item in white_hair_items:
                    score = self._simple_overlap_score(query, item.question)
                    if score > best_score:
                        best_score = score
                        best_item = item
                if best_item and best_score >= 0.1:
                    return {
                        "matched": True,
                        "answer": best_item.answer,
                        "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                        "question": best_item.question,
                        "score": float(best_score),
                        "mode": "white_hair_priority",
                        "intent": best_item.intent,
                        "tags": list(best_item.tags or []),
                        "item_id": str(best_item.id or ""),
                        "blocked_by_polite_guard": False,
                        "polite_guard_reason": "",
                    }

        # 特殊处理：假发乱了/头发乱了
        messy_hair_keywords = ["假发乱", "头发乱", "乱了"]
        if any(k in query for k in messy_hair_keywords):
            items = self.repository.get_all()
            messy_items = [
                item for item in items
                if "售后" in (item.tags or []) or "整理" in (item.tags or []) or "假发乱" in (item.question or "")
            ]
            if messy_items:
                best_item = None
                best_score = 0.0
                for item in messy_items:
                    score = self._simple_overlap_score(query, item.question)
                    if score > best_score:
                        best_score = score
                        best_item = item
                if best_item and best_score >= 0.1:
                    return {
                        "matched": True,
                        "answer": best_item.answer,
                        "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                        "question": best_item.question,
                        "score": float(best_score),
                        "mode": "messy_hair_priority",
                        "intent": best_item.intent,
                        "tags": list(best_item.tags or []),
                        "item_id": str(best_item.id or ""),
                        "blocked_by_polite_guard": False,
                        "polite_guard_reason": "",
                    }

        # 特殊处理：自己洗/需要洗/不会洗
        wash_keywords = ["自己洗", "需要洗", "要洗吗", "能洗吗", "可以洗", "不会洗", "怎么洗", "如何清洗", "不会清洗", "怎么清洗"]
        if any(k in query for k in wash_keywords):
            items = self.repository.get_all()
            wash_items = [
                item for item in items
                if any(k in (item.question or "") for k in ["可以洗", "能洗", "清洗", "自己洗"])
            ]
            if wash_items:
                best_item = None
                best_score = 0.0
                for item in wash_items:
                    score = self._simple_overlap_score(query, item.question)
                    if score > best_score:
                        best_score = score
                        best_item = item
                if best_item and best_score >= 0.1:
                    return {
                        "matched": True,
                        "answer": best_item.answer,
                        "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                        "question": best_item.question,
                        "score": float(best_score),
                        "mode": "wash_priority",
                        "intent": best_item.intent,
                        "tags": list(best_item.tags or []),
                        "item_id": str(best_item.id or ""),
                        "blocked_by_polite_guard": False,
                        "polite_guard_reason": "",
                    }

        # 特殊处理：季节相关问题（夏天/冬天）
        season_keywords = {"夏天": ["夏天", "热", "闷"], "冬天": ["冬天", "冷", "保暖"]}
        for season, related_words in season_keywords.items():
            if season in query:
                items = self.repository.get_all()
                season_items = [
                    item for item in items
                    if season in (item.question or "")
                ]
                if season_items:
                    best_item = None
                    best_score = 0.0
                    for item in season_items:
                        score = self._simple_overlap_score(query, item.question)
                        if score > best_score:
                            best_score = score
                            best_item = item
                    if best_item and best_score >= 0.1:
                        return {
                            "matched": True,
                            "answer": best_item.answer,
                            "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                            "question": best_item.question,
                            "score": float(best_score),
                            "mode": "season_priority",
                            "intent": best_item.intent,
                            "tags": list(best_item.tags or []),
                            "item_id": str(best_item.id or ""),
                            "blocked_by_polite_guard": False,
                            "polite_guard_reason": "",
                        }

        # 特殊处理：通用价格查询优先级
        generic_price_keywords = ["假发多少钱", "假发价格", "多少钱", "价位", "价格"]
        specific_style_keywords = ["短款", "短发", "长款", "长发", "盘发", "中长", "齐肩"]

        if any(k in query for k in generic_price_keywords):
            # 如果没有提到具体款式，优先匹配通用价格问题
            if not any(k in query for k in specific_style_keywords):
                items = self.repository.get_all()
                generic_price_items = [
                    item for item in items
                    if item.intent == "price"
                    and "价格多少" in (item.question or "")
                    and not any(style in (item.question or "") for style in specific_style_keywords)
                ]
                if generic_price_items:
                    best_item = generic_price_items[0]  # 直接返回第一个通用价格问题
                    return {
                        "matched": True,
                        "answer": best_item.answer,
                        "answers": list(best_item.answers or []),
                        "question": best_item.question,
                        "score": 0.9,  # 高分数表示优先匹配
                        "mode": "generic_price_priority",
                        "intent": best_item.intent,
                        "tags": list(best_item.tags or []),
                        "item_id": str(best_item.id or ""),
                        "confidence": "high",  # 添加置信度
                        "blocked_by_polite_guard": False,
                        "polite_guard_reason": "",
                    }

        detail = self.repository.find_best_match_detail(query, threshold=0.7)  # 从0.6提高到0.7
        detail, blocked, reason = self._apply_polite_closing_guard(
            detail=detail,
            raw_query=query,
            normalized_query=normalized_query,
        )
        if blocked:
            blocked_by_polite_guard = True
            polite_guard_reason = reason or "polite_not_exact"
        if detail.get("matched"):
            # 添加置信度判断
            score = detail.get("score", 0.0)
            if score >= 0.7:
                detail["confidence"] = "high"
            elif score >= 0.5:
                detail["confidence"] = "medium"
            else:
                detail["confidence"] = "low"
            detail["blocked_by_polite_guard"] = False
            detail["polite_guard_reason"] = ""
            return detail

        if normalized_query and normalized_query != query:
            relaxed_threshold = max(0.5, float(threshold) - 0.2)  # 从0.35提高到0.5
            detail = self.repository.find_best_match_detail(normalized_query, relaxed_threshold)
            detail, blocked, reason = self._apply_polite_closing_guard(
                detail=detail,
                raw_query=query,
                normalized_query=normalized_query,
            )
            if blocked:
                blocked_by_polite_guard = True
                polite_guard_reason = reason or "polite_not_exact"
            if detail.get("matched"):
                # 添加置信度判断
                score = detail.get("score", 0.0)
                if score >= 0.7:
                    detail["confidence"] = "high"
                elif score >= 0.5:
                    detail["confidence"] = "medium"
                else:
                    detail["confidence"] = "low"
                detail["mode"] = f"normalized_{detail.get('mode', 'match')}"
                detail["blocked_by_polite_guard"] = False
                detail["polite_guard_reason"] = ""
                return detail

        intent_fallback = self._find_answer_by_intent_hint_detail(normalized_query or query, raw_query=query)
        if intent_fallback.get("matched"):
            intent_fallback["blocked_by_polite_guard"] = False
            intent_fallback["polite_guard_reason"] = ""
            return intent_fallback
        if intent_fallback.get("blocked_by_polite_guard"):
            blocked_by_polite_guard = True
            polite_guard_reason = str(intent_fallback.get("polite_guard_reason", "") or polite_guard_reason)
        return {
            "matched": False,
            "answer": "",
            "answers": [],
            "question": "",
            "score": 0.0,
            "mode": "none",
            "intent": "",
            "tags": [],
            "item_id": "",
            "blocked_by_polite_guard": blocked_by_polite_guard,
            "polite_guard_reason": polite_guard_reason,
        }

    def find_answer(self, user_message: str, threshold: float = 0.6) -> Optional[str]:
        """根据用户消息查找最佳答案（兼容旧接口）"""
        detail = self.find_answer_detail(user_message=user_message, threshold=threshold)
        if detail.get("matched"):
            return str(detail.get("answer", "") or "")
        return None

    def _normalize_for_kb(self, text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return ""

        for prefix in self.GENERIC_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()

        normalized = re.sub(r"[，。！？、,.!?~\s]+", "", normalized)
        normalized = normalized.replace("是多少", "多少").replace("什么价格", "价格多少")
        return normalized

    def _find_answer_by_intent_hint_detail(self, query: str, raw_query: str = "") -> Dict[str, object]:
        text = (query or "").strip()
        if not text:
            return {
                "matched": False,
                "answer": "",
                "answers": [],
                "question": "",
                "score": 0.0,
                "mode": "intent_hint",
                "intent": "",
                "tags": [],
                "item_id": "",
                "blocked_by_polite_guard": False,
                "polite_guard_reason": "",
            }

        intents: List[str] = []
        if any(k in text for k in self.PRICE_KEYWORDS):
            intents.append("price")
        if self.is_address_query(text):
            intents.append("address")
        if any(k in text for k in self.WEARING_KEYWORDS):
            intents.append("wearing")
        if not intents:
            intents.append("general")

        items = self.repository.get_all()
        blocked_by_polite_guard = False
        polite_guard_reason = ""
        raw = (raw_query or text).strip()
        for intent in intents:
            candidates = [item for item in items if (item.intent or "").lower() == intent]
            if not candidates:
                continue

            best_item = None
            best_score = -1.0
            for item in candidates:
                if self._is_polite_closing_item(getattr(item, "tags", []) or []):
                    if not self._is_exact_polite_trigger(raw, item.question):
                        blocked_by_polite_guard = True
                        if self._looks_like_mixed_non_polite_query(raw):
                            polite_guard_reason = "polite_mixed_query"
                        elif not polite_guard_reason:
                            polite_guard_reason = "polite_not_exact"
                        continue
                score = self._simple_overlap_score(text, item.question)
                if score > best_score:
                    best_score = score
                    best_item = item

            min_score = 0.25 if intent == "general" else 0.15  # 从0.15/0.05提高到0.25/0.15
            if best_item and best_item.answer and best_score >= min_score:
                # 添加置信度判断
                if best_score >= 0.7:
                    confidence = "high"
                elif best_score >= 0.5:
                    confidence = "medium"
                else:
                    confidence = "low"
                return {
                    "matched": True,
                    "answer": best_item.answer,
                    "answers": list(best_item.answers or ([best_item.answer] if best_item.answer else [])),
                    "question": best_item.question,
                    "score": float(best_score),
                    "mode": "intent_hint",
                    "intent": intent,
                    "tags": list(best_item.tags or []),
                    "item_id": str(best_item.id or ""),
                    "confidence": confidence,
                    "blocked_by_polite_guard": False,
                    "polite_guard_reason": "",
                }
        return {
            "matched": False,
            "answer": "",
            "answers": [],
            "question": "",
            "score": 0.0,
            "mode": "intent_hint",
            "intent": "",
            "tags": [],
            "item_id": "",
            "blocked_by_polite_guard": blocked_by_polite_guard,
            "polite_guard_reason": polite_guard_reason,
        }

    def _simple_overlap_score(self, a: str, b: str) -> float:
        na = self._normalize_for_kb(a)
        nb = self._normalize_for_kb(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        if na in nb or nb in na:
            return 0.9

        set_a = set(na)
        set_b = set(nb)
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def _is_polite_closing_item(self, tags: List[str]) -> bool:
        tag_set = {str(tag).strip() for tag in (tags or []) if str(tag).strip()}
        return all(required in tag_set for required in self.POLITE_CLOSING_REQUIRED_TAGS)

    def _is_exact_polite_trigger(self, query: str, matched_question: str) -> bool:
        q = self._normalize_for_kb(query)
        target = self._normalize_for_kb(matched_question)
        if not q or not target:
            return False
        return q == target

    def _looks_like_mixed_non_polite_query(self, query: str) -> bool:
        normalized = self._normalize_for_kb(query)
        if not normalized:
            return False
        non_polite_signals = (
            "怎么办",
            "怎么",
            "买",
            "预约",
            "价格",
            "多少",
            "材质",
            "地址",
            "哪里",
            "在哪",
            "上海",
            "北京",
            "不在",
            "不是",
        )
        return any(token in normalized for token in non_polite_signals)

    def _apply_polite_closing_guard(
        self,
        detail: Dict[str, object],
        raw_query: str,
        normalized_query: str,
    ) -> Tuple[Dict[str, object], bool, str]:
        if not detail.get("matched"):
            return detail, False, ""

        tags = detail.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        if not self._is_polite_closing_item(tags):
            return detail, False, ""

        question = str(detail.get("question", "") or "")
        if self._is_exact_polite_trigger(raw_query, question) or self._is_exact_polite_trigger(normalized_query, question):
            return detail, False, ""

        reason = "polite_mixed_query" if self._looks_like_mixed_non_polite_query(raw_query) else "polite_not_exact"
        blocked_detail = {
            "matched": False,
            "answer": "",
            "answers": [],
            "question": "",
            "score": 0.0,
            "mode": "none",
            "intent": "",
            "tags": [],
            "item_id": "",
        }
        return blocked_detail, True, reason

    def is_address_query(self, text: str) -> bool:
        """是否为地址相关咨询"""
        text = (text or "").strip()
        return bool(text) and any(keyword in text for keyword in self.ADDRESS_KEYWORDS)

    def is_purchase_intent(self, text: str) -> bool:
        """是否包含明确购买意图关键词"""
        normalized = re.sub(r"\s+", "", (text or ""))
        if not normalized:
            return False
        return any(keyword in normalized for keyword in self.PURCHASE_INTENT_KEYWORDS)

    def resolve_store_recommendation(self, user_text: str) -> dict:
        """根据用户地理位置解析推荐门店（仅路由，不生成文案）"""
        text = (user_text or "").strip()
        if not text:
            return {
                "city": "unknown",
                "target_store": "unknown",
                "reason": "unknown",
                "route_type": "unknown",
                "store_address": None,
                "detected_region": "",
            }

        compact = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", text)
        neg_beijing = bool(re.search(r"(不在|不是|不去).*北京", compact))
        neg_shanghai = bool(re.search(r"(不在|不是|不去).*上海", compact))

        # 明确表示“不在北京/不在上海（含两者）”时，按非覆盖处理，避免落到 unknown。
        if neg_beijing or neg_shanghai:
            if neg_beijing and neg_shanghai:
                detected_region = "非沪京地区"
            elif neg_shanghai:
                detected_region = "非上海地区"
            else:
                detected_region = "非北京地区"
            return {
                "city": "unknown",
                "target_store": "unknown",
                "reason": "out_of_coverage",
                "route_type": "non_coverage",
                "store_address": None,
                "detected_region": detected_region,
            }
        # 北京：任何北京区县都只推荐朝阳
        beijing_markers = (
            "北京", "朝阳", "海淀", "丰台", "通州", "顺义", "门头沟", "大兴", "昌平",
            "石景山", "西城", "东城", "房山", "怀柔", "平谷", "密云", "延庆"
        )
        if not neg_beijing and any(k in text for k in beijing_markers):
            return self._build_route("beijing_chaoyang", "beijing_all_district")

        # 京津冀 + 内蒙古 -> 北京
        if any(k in text for k in ("天津", "河北", "内蒙古")):
            return self._build_route("beijing_chaoyang", "north_fallback_beijing")

        # 上海明确区映射
        for district, store_key in self.SHANGHAI_DISTRICT_STORE_MAP.items():
            if district in text:
                return self._build_route(store_key, f"sh_district_map:{district}")

        # 只说上海未带区：追问区，不直接给门店
        if not neg_shanghai and "上海" in text:
            return {
                "city": "shanghai",
                "target_store": "unknown",
                "reason": "shanghai_need_district",
                "route_type": "need_district",
                "store_address": None,
                "detected_region": "上海",
            }

        # 江浙地区 -> 上海人民广场
        if any(k in text for k in (
            "江苏", "浙江", "苏州", "无锡", "常州", "南通", "南京", "宁波",
            "杭州", "绍兴", "嘉兴", "湖州", "金华", "温州"
        )):
            return self._build_route("sh_renmin", "jiangzhe_to_sh_renmin")

        # 其他明确地区（如新疆/大连）-> 非覆盖地区固定话术
        detected_region = self._extract_region_mention(text)
        if detected_region:
            routed = self._build_coverage_route_by_detected_region(detected_region)
            if routed:
                return routed
            return {
                "city": "unknown",
                "target_store": "unknown",
                "reason": "out_of_coverage",
                "route_type": "non_coverage",
                "store_address": None,
                "detected_region": detected_region
            }

        # 未识别地区 -> unknown（走追问）
        return {
            "city": "unknown",
            "target_store": "unknown",
            "reason": "unknown",
            "route_type": "unknown",
            "store_address": None,
            "detected_region": "",
        }

    def _build_route(self, target_store: str, reason: str) -> dict:
        detail = self.STORE_DETAILS.get(target_store, {})
        return {
            "city": detail.get("city", "unknown"),
            "target_store": target_store,
            "reason": reason,
            "route_type": "coverage",
            "store_address": detail.get("store_address"),
            "store_name": detail.get("store_name", ""),
            "detected_region": "",
        }

    def _build_coverage_route_by_detected_region(self, detected_region: str) -> Optional[Dict[str, object]]:
        region_key = self._normalize_region_key(detected_region)
        if region_key in ("河北", "天津", "内蒙古"):
            return self._build_route("beijing_chaoyang", "north_fallback_beijing")
        if region_key in ("江苏", "浙江"):
            return self._build_route("sh_renmin", "jiangzhe_to_sh_renmin")
        return None

    def _normalize_region_key(self, region: str) -> str:
        raw = str(region or "").strip()
        if not raw:
            return ""
        mapped = self.REGION_ROUTE_PROVINCE_KEY_MAP.get(raw)
        if mapped:
            return mapped
        suffixes = (
            "特别行政区",
            "维吾尔自治区",
            "壮族自治区",
            "回族自治区",
            "自治区",
            "自治州",
            "地区",
            "省",
            "市",
            "区",
            "县",
            "州",
            "盟",
            "旗",
        )
        for suffix in suffixes:
            if raw.endswith(suffix):
                trimmed = raw[: -len(suffix)].strip()
                if trimmed:
                    return self.REGION_ROUTE_PROVINCE_KEY_MAP.get(trimmed, trimmed)
        return raw

    def get_store_display(self, target_store: str) -> dict:
        detail = self.STORE_DETAILS.get(target_store, {})
        return {
            "target_store": target_store,
            "store_name": detail.get("store_name", ""),
            "store_address": detail.get("store_address")
        }

    def _extract_region_mention(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""

        # 优先 address.json 词典，覆盖范围外地区都按非覆盖处理
        if self._address_region_tokens:
            for token in sorted(self._address_region_tokens, key=len, reverse=True):
                if token and token in text:
                    return self._address_token_to_canonical.get(token, token)

        # 优先命中已知非覆盖地区词典
        for region in self.NON_COVERAGE_REGION_HINTS:
            if region in text:
                return region

        # 兜底：识别常见地名后缀，如“XX省/XX市/XX区/XX县/XX州”
        m = re.search(r"([\u4e00-\u9fa5]{2,8}(?:省|市|区|县|州|盟|旗))", text)
        if m:
            candidate = m.group(1)
            # 避免把“区别/区分”等词误判成地区（如“不同价格有什么区别”）。
            tail = text[m.end():m.end() + 1]
            if candidate.endswith("区") and tail in ("别", "分"):
                return ""
            if any(token in candidate for token in ("什么区", "哪个区", "哪些区")):
                return ""
            return candidate
        return ""

    def add_item(
        self,
        question: str,
        answer: str,
        intent: str = "",
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        answers: Optional[List[str]] = None,
    ) -> Optional[str]:
        """添加知识库条目

        Returns:
            新条目的ID，失败返回None
        """
        if not question or (not answer and not answers):
            return None

        item = self.repository.add(question, answer, intent=intent, tags=tags, category=category, answers=answers)
        self.item_added.emit(item.id)
        return item.id

    def update_item(
        self,
        item_id: str,
        question: str = None,
        answer: str = None,
        intent: str = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        answers: Optional[List[str]] = None,
    ) -> bool:
        """更新知识库条目"""
        success = self.repository.update(
            item_id,
            question,
            answer,
            intent=intent,
            tags=tags,
            category=category,
            answers=answers,
        )
        if success:
            self.item_updated.emit(item_id)
        return success

    def delete_item(self, item_id: str) -> bool:
        """删除知识库条目"""
        success = self.repository.delete(item_id)
        if success:
            self.item_deleted.emit(item_id)
        return success

    def get_all_items(self) -> List[KnowledgeItem]:
        """获取所有条目"""
        return self.repository.get_all()

    def get_item_by_id(self, item_id: str) -> Optional[KnowledgeItem]:
        """根据ID获取条目"""
        return self.repository.get_by_id(item_id)

    def import_from_file(self, file_path: Path) -> Tuple[int, int]:
        """从文件导入知识库

        Returns:
            (成功数量, 失败数量)
        """
        success, failed = self.repository.import_from_file(file_path)
        if success > 0:
            self.data_imported.emit(success)
        return success, failed

    def export_to_file(self, file_path: Path) -> bool:
        """导出知识库到文件"""
        success = self.repository.export_to_file(file_path)
        if success:
            self.data_exported.emit(str(file_path))
        return success

    def clear_all(self) -> bool:
        """清空所有知识库数据"""
        try:
            self.repository.clear()
            return True
        except Exception:
            return False

    def get_count(self) -> int:
        """获取条目总数"""
        return self.repository.count()

    def get_quick_answers(self, keywords: List[str]) -> List[Tuple[str, str]]:
        """获取快速回复选项

        Args:
            keywords: 关键词列表

        Returns:
            [(question, answer), ...]
        """
        results = []
        for keyword in keywords:
            items = self.repository.search(keyword)
            for item in items[:3]:  # 每个关键词取前3个结果
                results.append((item.question, item.answer))
        return results
