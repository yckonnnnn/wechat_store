"""
地址拦截器服务

功能：
1. 检测 LLM 输出中的具体地址（6 家店的地址）
2. 只要匹配到 1 个及以上地址，全部替换为占位符
3. 返回所有匹配门店，供调用方决定发几张图

设计原则：
- 只拦截 6 家店的已知地址
- LLM 历史记录原始输出（由调用方负责，不在本模块处理）
- 拦截后触发对应门店的地址图片发送（1-2 家各发1张，3家+只发第1张）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class AddressMatch:
    """单个地址匹配结果"""
    store_name: str        # 门店名称（如"静安店"）
    address_text: str      # 匹配到的地址原文
    start_pos: int         # 在原文中的起始位置
    end_pos: int           # 在原文中的结束位置


@dataclass
class AddressInterceptResult:
    """地址拦截结果"""
    original_text: str           # 原始 LLM 输出
    processed_text: str          # 替换后的文本（用于发送）
    is_intercepted: bool         # 是否被拦截（match_count >= 1 时为 True）
    match_count: int             # 匹配到的地址数量
    matches: List[AddressMatch]  # 所有匹配详情
    trigger_address_image: bool  # 是否触发地址图片发送
    target_store: Optional[str]  # 第一个目标门店（向后兼容）
    target_stores: List[str]     # 所有匹配门店列表（1-2家发图，3+家仅取第1家）


class AddressInterceptor:
    """
    地址拦截器（6 家店全量地址拦截）

    拦截规则：
    1. 只要匹配到 1 个及以上地址，全部替换
    2. 1-2 家：各触发 1 张地址图片
    3. 3 家及以上：替换所有地址，仅触发第 1 家的图片（避免洪水轰炸）
    4. 只匹配 6 家店的已知地址模式
    """

    # 替换话术
    ADDRESS_PLACEHOLDER = "地址看图片中的位置"

    # 6 家店的地址模式配置（支持空格匹配）
    # 格式：(门店名称，[(地址关键词，正则模式), ...])
    STORE_ADDRESS_PATTERNS = [
        ("静安店", [
            (r"愚园路", r"愚园路\s*\d+\s*号(?:\s*环球世界大厦(?:\s*[A-Z] 座)?)?"),
        ]),
        ("人民广场店", [
            (r"汉口路", r"汉口路\s*\d+\s*号(?:\s*亚洲大厦(?:\s*[A-Z] 座)?)?"),
        ]),
        ("虹口店", [
            (r"花园路", r"花园路\s*\d+\s*号(?:\s*嘉和国际大厦(?:\s*(?:东楼 | 西楼 | 南楼 | 北楼))?)?"),
        ]),
        ("五角场店", [
            (r"政通路", r"政通路\s*\d+\s*号(?:\s*万达广场(?:\s*[A-Z]\s*栋)?(?:\s*[A-Z]\s*座)?)?"),
            (r"五角场万达", r"五角场\s*万达(?:广场)?(?:\s*\d+\s*号)?(?:\s*[A-Z]\s*栋)?(?:\s*[A-Z]\s*座)?"),
        ]),
        ("徐汇店", [
            (r"漕溪北路", r"漕溪北路\s*\d+\s*号(?:\s*中航德必大厦)?"),
        ]),
        ("北京店", [
            (r"建外 SOHO", r"建外\s*SOHO\s*(?:东区 | 西区)?"),
            (r"朝阳", r"朝阳区(?:\s*建外\s*SOHO)?(?:\s*(?:东区 | 西区))?"),
        ]),
    ]

    # 编译后的正则模式列表：[(store_name, keyword_pattern, compiled_regex), ...]
    _compiled_patterns: List[tuple] = []

    def __init__(self):
        if not self._compiled_patterns:
            self._compile_patterns()

    def _compile_patterns(self):
        """编译所有门店的正则模式"""
        self._compiled_patterns = []
        for store_name, patterns in self.STORE_ADDRESS_PATTERNS:
            for keyword, pattern in patterns:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled_patterns.append((store_name, keyword, compiled))

    def intercept(self, text: str) -> AddressInterceptResult:
        """
        拦截并替换地址（仅单门店地址）

        Args:
            text: LLM 输出的原始文本

        Returns:
            AddressInterceptResult: 拦截结果
        """
        if not text or not str(text).strip():
            return AddressInterceptResult(
                original_text=text or "",
                processed_text=text or "",
                is_intercepted=False,
                match_count=0,
                matches=[],
                trigger_address_image=False,
                target_store=None,
            )

        original_text = str(text)
        matches = []

        # 查找所有匹配的地址
        for store_name, keyword, pattern in self._compiled_patterns:
            for match in pattern.finditer(original_text):
                matches.append(AddressMatch(
                    store_name=store_name,
                    address_text=match.group(),
                    start_pos=match.start(),
                    end_pos=match.end(),
                ))

        # 去重（同一门店的连续地址合并为一个）
        matches = self._deduplicate_matches(matches, original_text)

        match_count = len(matches)

        if match_count == 0:
            return AddressInterceptResult(
                original_text=original_text,
                processed_text=original_text,
                is_intercepted=False,
                match_count=0,
                matches=[],
                trigger_address_image=False,
                target_store=None,
                target_stores=[],
            )

        # 1 个及以上：全部替换（从右到左，保证位置不漂移）
        sorted_desc = sorted(matches, key=lambda m: m.start_pos, reverse=True)
        processed_text = original_text
        for m in sorted_desc:
            processed_text = (
                processed_text[:m.start_pos] +
                self.ADDRESS_PLACEHOLDER +
                processed_text[m.end_pos:]
            )

        target_stores = [m.store_name for m in matches]

        # 3 家及以上：调用方只对第 1 家发图（避免洪水轰炸）
        # 图片发送张数的决策在 message_processor 中按 target_stores 长度控制
        return AddressInterceptResult(
            original_text=original_text,
            processed_text=processed_text,
            is_intercepted=True,
            match_count=match_count,
            matches=matches,
            trigger_address_image=True,
            target_store=matches[0].store_name,   # 向后兼容
            target_stores=target_stores,
        )

    def _deduplicate_matches(
        self,
        matches: List[AddressMatch],
        original_text: str,
    ) -> List[AddressMatch]:
        """
        去重匹配结果

        规则：
        1. 同一门店的连续/重叠地址 → 合并为一个（如"愚园路 172 号" + "环球世界大厦 A 座" → 1 个）
        2. 不同门店的地址 → 保留多个（如"静安店在愚园路 172 号，虹口店在花园路 16 号" → 2 个）
        """
        if not matches:
            return []

        # 按起始位置排序
        sorted_matches = sorted(matches, key=lambda m: m.start_pos)

        # 按门店分组，合并同一门店的连续地址
        store_groups: Dict[str, List[AddressMatch]] = {}
        for match in sorted_matches:
            if match.store_name not in store_groups:
                store_groups[match.store_name] = []
            store_groups[match.store_name].append(match)

        # 合并同一门店的连续/重叠地址为一个范围
        merged_matches: List[AddressMatch] = []
        for store_name, group in store_groups.items():
            # 合并该门店的所有地址为一个整体
            min_start = min(m.start_pos for m in group)
            max_end = max(m.end_pos for m in group)
            merged_text = original_text[min_start:max_end]

            merged_matches.append(AddressMatch(
                store_name=store_name,
                address_text=merged_text,
                start_pos=min_start,
                end_pos=max_end,
            ))

        # 按起始位置排序
        merged_matches.sort(key=lambda m: m.start_pos)
        return merged_matches

    def has_address(self, text: str) -> bool:
        """快速检测是否包含至少 1 个门店地址"""
        if not text:
            return False
        result = self.intercept(text)
        return result.is_intercepted

    def has_single_store_address(self, text: str) -> bool:
        """向后兼容保留，等同于 has_address（只要含地址就返回 True）"""
        return self.has_address(text)

    def reload_patterns(self):
        """重新编译模式（配置更新时调用）"""
        self._compiled_patterns = []
        self._compile_patterns()
