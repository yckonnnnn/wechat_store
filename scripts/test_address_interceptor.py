#!/usr/bin/env python3
"""
地址拦截器测试脚本

模拟 LLM 输出，测试地址拦截器是否正常工作。

用法：
  python3 scripts/test_address_interceptor.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.address_interceptor import AddressInterceptor


def print_test_case(title: str, llm_output: str, expected: str, interceptor: AddressInterceptor):
    """打印单个测试用例结果"""
    print("\n" + "=" * 70)
    print(f"📝 测试：{title}")
    print("-" * 70)
    print(f"🤖 LLM 输出:\n   {llm_output}")

    result = interceptor.intercept(llm_output)

    print(f"\n🎯 拦截结果:")
    print(f"   是否拦截：{'✅ 是' if result.is_intercepted else '❌ 否'}")
    print(f"   匹配地址数：{result.match_count}")

    if result.is_intercepted:
        print(f"   目标门店：{result.target_store}")
        print(f"   匹配地址：{result.matches[0].address_text}")
        print(f"\n📤 发送文本:\n   {result.processed_text}")
        print(f"\n📍 触发地址图片：✅ 是 ({result.target_store})")
    else:
        print(f"\n📤 发送文本 (保留原文):\n   {result.processed_text}")
        if result.match_count > 1:
            print(f"\nℹ️  多门店地址 ({result.match_count}个)，不触发图片")
        else:
            print(f"\nℹ️  无地址，不触发图片")

    # 验证预期
    if expected == "intercept":
        assert result.is_intercepted is True, f"预期拦截，但实际未拦截"
        print("\n✅ 验证通过：预期拦截，实际拦截")
    elif expected == "no_intercept":
        assert result.is_intercepted is False, f"预期不拦截，但实际拦截"
        print("\n✅ 验证通过：预期不拦截，实际不拦截")

    return result


def main():
    print("=" * 70)
    print("🚀 地址拦截器测试")
    print("=" * 70)

    interceptor = AddressInterceptor()

    # ── 测试用例 1: 单门店地址（静安店） ──────────────────────────────────────
    print("\n\n📍 场景 1: 单门店地址 - 应该拦截")
    print("=" * 70)

    test_cases_intercept = [
        ("静安店单地址", "姐姐，静安店在愚园路 172 号环球世界大厦 A 座。您方便的话留个电话。", "intercept"),
        ("虹口店单地址", "虹口店在花园路 16 号嘉和国际大厦东楼，您看方便吗？", "intercept"),
        ("黄浦店单地址", "黄浦店在汉口路 650 号亚洲大厦，您方便的话可以留个电话。", "intercept"),
    ]

    for title, llm_output, expected in test_cases_intercept:
        print_test_case(title, llm_output, expected, interceptor)

    # ── 测试用例 2: 多门店地址 ──────────────────────────────────────────────
    print("\n\n📍 场景 2: 多门店地址 - 不应该拦截")
    print("=" * 70)

    test_cases_no_intercept = [
        ("两家店", "姐姐，静安店在愚园路 172 号环球世界大厦 A 座，虹口店在花园路 16 号嘉和国际大厦东楼。您看哪个交通更方便？", "no_intercept"),
        ("三家店", "上海有三家店：静安店在愚园路 172 号，虹口店在花园路 16 号，黄浦店在汉口路 650 号。您看哪家离您最近？", "no_intercept"),
        ("无地址", "姐姐，您方便的话留个电话，我让专属顾问联系您。", "no_intercept"),
    ]

    for title, llm_output, expected in test_cases_no_intercept:
        print_test_case(title, llm_output, expected, interceptor)

    # ── 总结 ────────────────────────────────────────────────────────────────
    print("\n\n" + "=" * 70)
    print("✅ 所有测试用例执行完成！")
    print("=" * 70)
    print("""
📋 拦截规则总结：
   ✅ 单门店地址 → 拦截替换 + 触发对应门店地址图片
   ❌ 多门店地址 (2 个+) → 保留原文，不触发图片
   ❌ 无地址 → 保留原文，不触发图片

📊 日志记录：
   - JSON 日志记录原始 LLM 输出（含具体地址）
   - 发送给用户的是替换后的文本（"地址看图片中的位置"）
""")


if __name__ == "__main__":
    main()
