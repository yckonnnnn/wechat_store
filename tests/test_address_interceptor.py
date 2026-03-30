"""
地址拦截器单元测试

测试场景：
1. 单门店地址拦截（静安店、虹口店等）
2. 多门店地址不拦截（2 个 + 地址）
3. 无地址不拦截
4. 边界情况（地址关键词重叠、多模式匹配）
"""

import pytest
from src.services.address_interceptor import AddressInterceptor, AddressMatch


class TestAddressInterceptor:
    """地址拦截器测试"""

    @pytest.fixture
    def interceptor(self):
        """创建拦截器实例"""
        return AddressInterceptor()

    # ── 单门店地址拦截测试 ──────────────────────────────────────────────────────

    def test_intercept_single_store_jingan(self, interceptor):
        """测试：静安店单地址拦截"""
        text = "姐姐，静安店在愚园路 172 号环球世界大厦 A 座。您方便的话留个电话。"
        result = interceptor.intercept(text)

        assert result.is_intercepted is True
        assert result.match_count == 1
        assert result.trigger_address_image is True
        assert result.target_store == "静安店"
        assert "地址看图片中的位置" in result.processed_text
        assert "愚园路 172 号" not in result.processed_text

    def test_intercept_single_store_hongkou(self, interceptor):
        """测试：虹口店单地址拦截"""
        text = "虹口店在花园路 16 号嘉和国际大厦东楼，您看方便吗？"
        result = interceptor.intercept(text)

        assert result.is_intercepted is True
        assert result.match_count == 1
        assert result.target_store == "虹口店"
        assert "地址看图片中的位置" in result.processed_text

    def test_intercept_single_store_huangpu(self, interceptor):
        """测试：黄浦店（人民广场店）单地址拦截"""
        text = "黄浦店在汉口路 650 号亚洲大厦，您方便的话可以留个电话。"
        result = interceptor.intercept(text)

        assert result.is_intercepted is True
        assert result.match_count == 1
        # 注意：汉口路匹配到的是"人民广场店"（内部命名），不是"黄浦店"（用户叫法）
        assert result.target_store == "人民广场店"
        assert "地址看图片中的位置" in result.processed_text

    # ── 多门店地址不拦截测试 ────────────────────────────────────────────────────

    def test_no_intercept_multiple_stores(self, interceptor):
        """测试：多门店地址不拦截"""
        text = "姐姐，静安店在愚园路 172 号环球世界大厦 A 座，虹口店在花园路 16 号嘉和国际大厦东楼。您看哪个交通更方便？"
        result = interceptor.intercept(text)

        assert result.is_intercepted is False
        assert result.match_count >= 2  # 至少匹配到 2 个地址
        assert result.trigger_address_image is False
        assert result.processed_text == text  # 保持原文

    def test_no_intercept_three_stores(self, interceptor):
        """测试：三家门店地址不拦截"""
        text = """
        上海有三家店：
        静安店在愚园路 172 号，
        虹口店在花园路 16 号，
        黄浦店在汉口路 650 号。
        您看哪家离您最近？
        """
        result = interceptor.intercept(text)

        assert result.is_intercepted is False
        assert result.match_count >= 3
        assert result.processed_text == text

    # ── 无地址不拦截测试 ────────────────────────────────────────────────────────

    def test_no_address(self, interceptor):
        """测试：无地址不拦截"""
        text = "姐姐，您方便的话留个电话，我让专属顾问联系您。"
        result = interceptor.intercept(text)

        assert result.is_intercepted is False
        assert result.match_count == 0
        assert result.trigger_address_image is False
        assert result.processed_text == text

    def test_empty_text(self, interceptor):
        """测试：空文本"""
        result = interceptor.intercept("")

        assert result.is_intercepted is False
        assert result.match_count == 0

    def test_none_text(self, interceptor):
        """测试：None 文本"""
        result = interceptor.intercept(None)

        assert result.is_intercepted is False
        assert result.match_count == 0

    # ── 边界情况测试 ────────────────────────────────────────────────────────────

    def test_same_address_multiple_patterns(self, interceptor):
        """测试：同一地址被多个模式匹配（去重）"""
        # "愚园路 172 号环球世界大厦 A 座" 可能同时匹配：
        # - 路名 + 门牌号模式
        # - 大厦模式
        text = "静安店在愚园路 172 号环球世界大厦 A 座"
        result = interceptor.intercept(text)

        assert result.is_intercepted is True
        # 去重后应该只有 1 个匹配
        assert result.match_count == 1

    def test_overlapping_addresses(self, interceptor):
        """测试：两个不同门店地址（应该不拦截）"""
        # 两个不同门店的地址：静安店和虹口店
        text = "我们在愚园路 172 号和花园路 16 号都有店"
        result = interceptor.intercept(text)

        # 两个不同的门店地址，不应该拦截
        assert result.is_intercepted is False
        assert result.match_count >= 2

    def test_partial_address_not_matched(self, interceptor):
        """测试：不完整的地址不匹配"""
        text = "我们在愚园路有一家新店"
        result = interceptor.intercept(text)

        # 没有门牌号，不应该匹配
        assert result.is_intercepted is False

    # ── 辅助方法测试 ────────────────────────────────────────────────────────────

    def test_has_single_store_address_true(self, interceptor):
        """测试：has_single_store_address - 单地址返回 True"""
        assert interceptor.has_single_store_address("静安店在愚园路 172 号") is True

    def test_has_single_store_address_false(self, interceptor):
        """测试：has_single_store_address - 多地址返回 False"""
        assert interceptor.has_single_store_address("静安店在愚园路 172 号，虹口店在花园路 16 号") is False
        assert interceptor.has_single_store_address("没有地址的文本") is False


class TestAddressMatch:
    """AddressMatch 数据类测试"""

    def test_address_match_creation(self):
        """测试：创建 AddressMatch 对象"""
        match = AddressMatch(
            store_name="静安店",
            address_text="愚园路 172 号",
            start_pos=5,
            end_pos=13,
        )

        assert match.store_name == "静安店"
        assert match.address_text == "愚园路 172 号"
        assert match.start_pos == 5
        assert match.end_pos == 13


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
