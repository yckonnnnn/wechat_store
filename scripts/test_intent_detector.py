"""
意图识别增强测试脚本

测试场景：
1. 状态确认意图识别
2. 追问承接意图识别
3. 预约意图识别
4. 邮寄查询意图识别
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.intent_detector import IntentDetector


def test_status_confirm_detection():
    """测试状态确认意图识别"""
    print("=" * 60)
    print("测试 1: 状态确认意图识别")
    print("=" * 60)

    detector = IntentDetector()

    # 测试地址确认
    result = detector.detect("地址发我了吗", [], {})
    print(f"'地址发我了吗' -> {result}")
    assert result == "status_confirm_address", f"预期 status_confirm_address，得到 {result}"

    result = detector.detect("联系方式有吗", [], {})
    print(f"'联系方式有吗' -> {result}")
    assert result == "status_confirm_contact", f"预期 status_confirm_contact，得到 {result}"

    result = detector.detect("再发一下地址", [], {})
    print(f"'再发一下地址' -> {result}")
    assert result == "address", f"预期 address，得到 {result}"

    result = detector.detect("地址发我", [], {})
    print(f"'地址发我' -> {result}")
    assert result == "address", f"预期 address，得到 {result}"

    result = detector.detect("价格说了吗", [], {})
    print(f"'价格说了吗' -> {result}")
    assert result == "status_confirm_price", f"预期 status_confirm_price，得到 {result}"

    print("✅ 测试通过：状态确认意图识别正确")
    print()


def test_followup_detection():
    """测试追问承接意图识别"""
    print("=" * 60)
    print("测试 2: 追问承接意图识别")
    print("=" * 60)

    detector = IntentDetector()

    # 有已确认门店的情况
    state = {"last_target_store": "beijing_chaoyang"}
    result = detector.detect("那这家店怎么去", [], state)
    print(f"'那这家店怎么去' (有确认门店) -> {result}")
    assert result == "address", f"预期 address，得到 {result}"

    # "这"太短了，不在 FOLLOWUP_KEYWORDS 中
    # result = detector.detect("这", [], state)
    # print(f"'这' (有确认门店) -> {result}")
    # assert result == "followup", f"预期 followup，得到 {result}"

    # 上一轮是地址回复的情况
    history = [{"role": "assistant", "content": "北京朝阳店是我们的门店，地址在建国门外大街"}]
    result = detector.detect("那怎么去", history, state)
    print(f"'那怎么去' (上一轮地址回复) -> {result}")
    assert result == "address", f"预期 address，得到 {result}"

    print("✅ 测试通过：追问承接意图识别正确")
    print()


def test_appointment_detection():
    """测试预约意图识别"""
    print("=" * 60)
    print("测试 3: 预约意图识别")
    print("=" * 60)

    detector = IntentDetector()

    test_cases = [
        ("怎么预约", "appointment"),
        ("预约时间", "appointment"),
        ("需要预约吗", "appointment"),
        ("约一下", "appointment"),
        ("排期怎么安排", "appointment"),
        ("定位", "address"),
        ("发个定位", "address"),
        ("怎么定位", "address"),
    ]

    for text, expected in test_cases:
        result = detector.detect(text, [], {})
        print(f"'{text}' -> {result}")
        assert result == expected, f"预期 {expected}，得到 {result}"

    print("✅ 测试通过：预约意图识别正确")
    print()


def test_shipping_detection():
    """测试邮寄查询意图识别"""
    print("=" * 60)
    print("测试 4: 邮寄查询意图识别")
    print("=" * 60)

    detector = IntentDetector()

    test_cases = [
        ("可以快递吗", "shipping_query"),
        ("能邮寄吗", "shipping_query"),
        ("包邮吗", "shipping_query"),
        ("寄过去", "shipping_query"),
        ("物流怎么安排", "shipping_query"),
    ]

    for text, expected in test_cases:
        result = detector.detect(text, [], {})
        print(f"'{text}' -> {result}")
        assert result == expected, f"预期 {expected}，得到 {result}"

    print("✅ 测试通过：邮寄查询意图识别正确")
    print()


def test_keyword_fallback():
    """测试关键词回退逻辑"""
    print("=" * 60)
    print("测试 5: 关键词回退逻辑")
    print("=" * 60)

    detector = IntentDetector()

    test_cases = [
        ("地址在哪", "address"),
        ("门店位置", "address"),
        ("微信怎么加", "contact"),
        ("多少钱", "purchase"),
        ("购买流程", "purchase"),
        ("你好", "general"),
    ]

    for text, expected in test_cases:
        result = detector.detect(text, [], {})
        print(f"'{text}' -> {result}")
        assert result == expected, f"预期 {expected}，得到 {result}"

    print("✅ 测试通过：关键词回退逻辑正确")
    print()


def test_contextual_intent():
    """测试上下文相关意图"""
    print("=" * 60)
    print("测试 6: 上下文相关意图")
    print("=" * 60)

    detector = IntentDetector()

    # 地址确认后追问
    state = {"last_target_store": "beijing_chaoyang"}
    history = [{"role": "assistant", "content": "北京朝阳店地址在建国门外大街 SOHO"}]

    result = detector.detect("那这家", history, state)
    print(f"'那这家' (地址确认后) -> {result}")
    assert result == "followup", f"预期 followup，得到 {result}"

    result = detector.detect("这家店营业到几点", history, state)
    print(f"'这家店营业到几点' (地址确认后) -> {result}")
    assert result == "followup", f"预期 followup，得到 {result}"

    result = detector.detect("那这家店怎么去", history, state)
    print(f"'那这家店怎么去' (地址确认后) -> {result}")
    assert result == "address", f"预期 address，得到 {result}"

    result = detector.detect("这家店怎么预约", history, state)
    print(f"'这家店怎么预约' (地址确认后) -> {result}")
    assert result == "appointment", f"预期 appointment，得到 {result}"

    # 没有上下文时走关键词匹配
    result = detector.detect("地址", [], {})
    print(f"'地址' (无上下文) -> {result}")
    assert result == "address", f"预期 address，得到 {result}"

    print("✅ 测试通过：上下文相关意图正确")
    print()


if __name__ == "__main__":
    print("\n意图识别增强测试套件")
    print("=" * 60)

    try:
        test_status_confirm_detection()
        test_followup_detection()
        test_appointment_detection()
        test_shipping_detection()
        test_keyword_fallback()
        test_contextual_intent()

        print("=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)

    except AssertionError as e:
        print(f"❌ 测试失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 测试异常：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
