"""
知识库存储模块
负责知识库的加载、保存、搜索和管理
"""

import json
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PySide6.QtCore import QObject, Signal


class KnowledgeItem:
    """知识库条目"""

    def __init__(
        self,
        question: str = "",
        answer: str = "",
        answers: Optional[List[str]] = None,
        item_id: str = None,
        intent: str = "",
        tags: Optional[List[str]] = None,
    ):
        self.id = item_id or str(uuid.uuid4())
        self.question = question.strip() if question else ""
        merged_answers: List[str] = []
        if answer:
            merged_answers.append(str(answer).strip())
        if isinstance(answers, list):
            merged_answers.extend([str(x).strip() for x in answers])
        self.answers = self._prepare_answers(merged_answers)
        self.intent = intent.strip() if intent else ""
        self.tags = [t.strip() for t in (tags or []) if t.strip()]
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

    @staticmethod
    def _prepare_answers(raw_answers: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen: set[str] = set()
        for raw in raw_answers or []:
            text = str(raw or "").strip()
            if not text:
                continue
            key = re.sub(r"\s+", "", text)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
            if len(cleaned) >= 5:
                break
        return cleaned

    @property
    def answer(self) -> str:
        return self.answers[0] if self.answers else ""

    @answer.setter
    def answer(self, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            self.answers = []
            return
        if self.answers:
            self.answers[0] = text
            self.answers = self._prepare_answers(self.answers)
            return
        self.answers = [text]

    def set_answers(self, answers: Optional[List[str]]) -> None:
        self.answers = self._prepare_answers([str(x).strip() for x in (answers or [])])

    def to_dict(self) -> dict:
        # 持久化业务字段
        return {
            "intent": self.intent,
            "question": self.question,
            "answer": self.answer,
            "answers": self.answers,
            "tags": self.tags
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeItem":
        answers = data.get("answers", [])
        answer = str(data.get("answer", "") or "")
        item = cls(
            question=str(data.get("question", "") or ""),
            answer=answer,
            answers=answers if isinstance(answers, list) else None,
            intent=str(data.get("intent") or data.get("category", "") or ""),
            tags=data.get("tags", []) or [],
        )
        item.id = data.get("id", str(uuid.uuid4()))
        item.created_at = data.get("created_at", datetime.now().isoformat())
        item.updated_at = data.get("updated_at", datetime.now().isoformat())
        return item


class KnowledgeRepository(QObject):
    """知识库仓库，负责知识库数据的管理"""

    data_changed = Signal()  # 数据变更信号

    def __init__(self, data_file: Path = None):
        super().__init__()
        self.data_file = data_file
        self._items: List[KnowledgeItem] = []
        self._search_cache: Dict[str, List[KnowledgeItem]] = {}
        self.load()

    def load(self) -> bool:
        """从文件加载知识库"""
        try:
            if self.data_file and self.data_file.exists():
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._items = [KnowledgeItem.from_dict(item) for item in data]
                    else:
                        self._items = []
            else:
                self._items = []
            self._search_cache.clear()
            return True
        except Exception as e:
            print(f"[KnowledgeRepository] 加载知识库失败: {e}")
            self._items = []
            return False

    def save(self) -> bool:
        """保存知识库到文件"""
        try:
            if self.data_file:
                self.data_file.parent.mkdir(parents=True, exist_ok=True)
                data = [item.to_dict() for item in self._items]
                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[KnowledgeRepository] 保存知识库失败: {e}")
            return False

    def get_all(self) -> List[KnowledgeItem]:
        """获取所有知识库条目"""
        return self._items.copy()

    def get_by_id(self, item_id: str) -> Optional[KnowledgeItem]:
        """根据ID获取条目"""
        for item in self._items:
            if item.id == item_id:
                return item
        return None

    def add(
        self,
        question: str,
        answer: str = "",
        intent: str = "",
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        answers: Optional[List[str]] = None,
    ) -> KnowledgeItem:
        """添加新条目"""
        resolved_intent = (intent or category or "").strip()
        effective_answers = [str(x).strip() for x in (answers or []) if str(x).strip()]
        primary_answer = str(answer or (effective_answers[0] if effective_answers else "")).strip()
        if not tags:
            resolved_intent, auto_tags = self._infer_intent_and_tags(question, primary_answer)
            if not resolved_intent:
                resolved_intent = intent or category or "general"
            tags = auto_tags
        item = KnowledgeItem(
            question=question,
            answer=primary_answer,
            answers=effective_answers,
            intent=resolved_intent,
            tags=tags,
        )
        self._items.append(item)
        self._search_cache.clear()
        self.data_changed.emit()
        self.save()
        return item

    def update(
        self,
        item_id: str,
        question: str = None,
        answer: str = None,
        intent: str = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        answers: Optional[List[str]] = None,
    ) -> bool:
        """更新条目"""
        item = self.get_by_id(item_id)
        if not item:
            return False

        if question is not None:
            item.question = question.strip()
        if answers is not None:
            normalized_answers = [str(x).strip() for x in answers if str(x).strip()]
            item.set_answers(normalized_answers)
            if answer is not None and answer.strip():
                item.answer = answer.strip()
        elif answer is not None:
            item.answer = answer.strip()
        resolved_intent = intent if intent is not None else category
        if resolved_intent is not None:
            item.intent = resolved_intent.strip()
        if tags is not None:
            item.tags = [t.strip() for t in tags if t.strip()]
        item.updated_at = datetime.now().isoformat()

        self._search_cache.clear()
        self.data_changed.emit()
        self.save()
        return True

    def delete(self, item_id: str) -> bool:
        """删除条目"""
        for i, item in enumerate(self._items):
            if item.id == item_id:
                self._items.pop(i)
                self._search_cache.clear()
                self.data_changed.emit()
                self.save()
                return True
        return False

    def search(self, query: str) -> List[KnowledgeItem]:
        """搜索知识库"""
        if not query:
            return self._items.copy()

        # 检查缓存
        cache_key = query.lower()
        if cache_key in self._search_cache:
            return self._search_cache[cache_key].copy()

        results = []
        keywords = query.lower().split()

        for item in self._items:
            # 计算匹配分数
            score = 0
            question_lower = item.question.lower()
            answer_text = " ".join(item.answers if item.answers else ([item.answer] if item.answer else []))
            answer_lower = answer_text.lower()

            for keyword in keywords:
                if keyword in question_lower:
                    score += 10  # 问题匹配权重高
                if keyword in answer_lower:
                    score += 5   # 答案匹配权重低

            if score > 0:
                results.append((score, item))

        # 按分数排序
        results.sort(key=lambda x: x[0], reverse=True)
        result_items = [item for _, item in results]

        # 缓存结果
        self._search_cache[cache_key] = result_items
        return result_items

    def find_best_match_detail(self, user_message: str, threshold: float = 0.6) -> Dict[str, object]:
        """找到最佳匹配答案，并返回命中细节。"""
        detail: Dict[str, object] = {
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
        if not user_message or not self._items:
            return detail

        query_raw = (user_message or "").strip()
        query = query_raw.lower()
        best_item: Optional[KnowledgeItem] = None
        best_score = 0.0
        best_mode = "none"

        query_variants = [x.strip().lower() for x in re.split(r"[？?；;、，,。!\n]+", query_raw) if x.strip()]
        if not query_variants:
            query_variants = [query]

        for item in self._items:
            question = (item.question or "").strip()
            if not question:
                continue
            question_lower = question.lower()

            # 特殊处理：盘发只在用户明确提到"盘发"时才匹配
            if "盘发" in question_lower:
                if not any("盘发" in v for v in query_variants):
                    continue

            for variant in query_variants:
                if not variant:
                    continue
                score = 0.0
                mode = "none"

                if variant == question_lower:
                    score = 1.0
                    mode = "exact"
                elif variant in question_lower or question_lower in variant:
                    score = 0.8
                    mode = "contains"
                else:
                    user_words = set(re.findall(r"\w+", variant))
                    question_words = set(re.findall(r"\w+", question_lower))
                    if user_words and question_words:
                        union = user_words | question_words
                        if union:
                            overlap = len(user_words & question_words) / len(union)
                            if overlap > score:
                                score = overlap
                                mode = "token_overlap"

                    set_a = set(re.sub(r"\s+", "", variant))
                    set_b = set(re.sub(r"\s+", "", question_lower))
                    if set_a and set_b:
                        union = set_a | set_b
                        if union:
                            char_overlap = len(set_a & set_b) / len(union)
                            if char_overlap > score:
                                score = char_overlap
                                mode = "char_overlap"

                if score > best_score:
                    best_score = score
                    best_item = item
                    best_mode = mode

        if best_item and best_score >= threshold:
            matched_answers = list(best_item.answers or ([best_item.answer] if best_item.answer else []))
            detail.update(
                {
                    "matched": True,
                    "answer": best_item.answer,
                    "answers": matched_answers,
                    "question": best_item.question,
                    "score": float(best_score),
                    "mode": best_mode,
                    "intent": best_item.intent,
                    "tags": list(best_item.tags or []),
                    "item_id": str(best_item.id or ""),
                }
            )
        return detail

    def find_best_match(self, user_message: str, threshold: float = 0.6) -> Optional[Tuple[str, float]]:
        """找到最佳匹配的知识库答案（兼容旧接口）。"""
        detail = self.find_best_match_detail(user_message=user_message, threshold=threshold)
        if detail.get("matched"):
            return str(detail.get("answer", "") or ""), float(detail.get("score", 0.0) or 0.0)
        return None

    def import_from_file(self, file_path: Path) -> Tuple[int, int]:
        """从文件导入知识库

        Returns:
            (成功数量, 失败数量)
        """
        suffix = file_path.suffix.lower()
        if suffix == ".xlsx":
            return self._import_from_excel(file_path)

        success = 0
        failed = 0

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, list):
                for item_data in data:
                    try:
                        if isinstance(item_data, dict):
                            question = item_data.get('question') or item_data.get('q')
                            answer = item_data.get('answer') or item_data.get('a')
                            answers = item_data.get("answers") if isinstance(item_data.get("answers"), list) else []
                            intent = item_data.get('intent') or item_data.get('category', '')
                            tags = item_data.get('tags', []) or []
                            if question and (answer or answers):
                                self.add(question, str(answer or ""), intent=intent, tags=tags, answers=answers)
                                success += 1
                            else:
                                failed += 1
                        elif isinstance(item_data, (list, tuple)) and len(item_data) >= 2:
                            self.add(str(item_data[0]), str(item_data[1]))
                            success += 1
                    except Exception:
                        failed += 1

            self.save()
            return (success, failed)

        except Exception as e:
            print(f"[KnowledgeRepository] 导入失败: {e}")
            return (0, 1)

    def export_to_file(self, file_path: Path) -> bool:
        """导出知识库到文件"""
        try:
            data = [item.to_dict() for item in self._items]
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[KnowledgeRepository] 导出失败: {e}")
            return False

    def clear(self) -> None:
        """清空知识库"""
        self._items.clear()
        self._search_cache.clear()
        self.data_changed.emit()
        self.save()

    def count(self) -> int:
        """获取条目数量"""
        return len(self._items)

    def _infer_intent_and_tags(self, question: str, answer: str) -> Tuple[str, List[str]]:
        text = f"{question or ''} {answer or ''}"

        address_keywords = ("地址", "位置", "门店", "店铺", "在哪", "哪里", "怎么去", "上海", "北京")
        price_keywords = ("价格", "多少钱", "价位", "贵", "最低价", "预算", "报价")
        wearing_keywords = ("佩戴", "闷热", "夏天", "自然", "真实", "麻烦", "舒适", "头发", "掉发")

        tags: List[str] = []
        if any(k in text for k in address_keywords):
            intent = "address"
            tags.extend(["地址", "门店"])
        elif any(k in text for k in price_keywords):
            intent = "price"
            tags.extend(["价格", "预算"])
        elif any(k in text for k in wearing_keywords):
            intent = "wearing"
            tags.extend(["佩戴体验"])
        else:
            intent = "general"
            tags.extend(["通用"])

        if "上海" in text:
            tags.append("上海")
        if "北京" in text:
            tags.append("北京")
        if "预约" in text:
            tags.append("预约")
        if "售后" in text:
            tags.append("售后")

        # 去重保序
        dedup_tags = []
        for t in tags:
            if t not in dedup_tags:
                dedup_tags.append(t)
        return intent, dedup_tags

    def _import_from_excel(self, file_path: Path) -> Tuple[int, int]:
        success = 0
        failed = 0
        try:
            rows = self._read_xlsx_rows(file_path)
            if not rows:
                return (0, 0)

            # 兼容表头：常见问题/参考答案
            header = rows[0]
            q_idx = self._find_col_index(header, ("常见问题", "问题", "question", "q"))
            a_idx = self._find_col_index(header, ("参考答案", "答案", "answer", "a"))
            if q_idx < 0 or a_idx < 0:
                return (0, len(rows) - 1 if len(rows) > 1 else 0)

            for row in rows[1:]:
                try:
                    question = row[q_idx].strip() if q_idx < len(row) else ""
                    answer = row[a_idx].strip() if a_idx < len(row) else ""
                    if not question or not answer:
                        failed += 1
                        continue
                    intent, tags = self._infer_intent_and_tags(question, answer)
                    self.add(question, answer, intent=intent, tags=tags)
                    success += 1
                except Exception:
                    failed += 1
            self.save()
            return (success, failed)
        except Exception as e:
            print(f"[KnowledgeRepository] Excel导入失败: {e}")
            return (0, 1)

    def _find_col_index(self, header: List[str], candidates: Tuple[str, ...]) -> int:
        normalized = [str(x).strip().lower() for x in header]
        for c in candidates:
            key = c.strip().lower()
            if key in normalized:
                return normalized.index(key)
        return -1

    def _read_xlsx_rows(self, file_path: Path) -> List[List[str]]:
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(file_path) as zf:
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall("a:si", ns):
                    texts = [t.text or "" for t in si.findall(".//a:t", ns)]
                    shared_strings.append("".join(texts))

            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
            sheet_nodes = wb.findall("a:sheets/a:sheet", ns)
            if not sheet_nodes:
                return []
            rid = sheet_nodes[0].attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rid, "")
            if not target:
                return []
            if not target.startswith("xl/"):
                target = f"xl/{target}"

            sheet_root = ET.fromstring(zf.read(target))
            rows: List[List[str]] = []
            for row in sheet_root.findall(".//a:row", ns):
                row_values: List[str] = []
                for cell in row.findall("a:c", ns):
                    cell_type = cell.attrib.get("t")
                    val_node = cell.find("a:v", ns)
                    if val_node is None or val_node.text is None:
                        row_values.append("")
                        continue
                    raw_val = val_node.text
                    if cell_type == "s":
                        try:
                            row_values.append(shared_strings[int(raw_val)])
                        except Exception:
                            row_values.append("")
                    else:
                        row_values.append(raw_val)
                rows.append(row_values)
            return rows
