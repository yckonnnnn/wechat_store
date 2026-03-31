#!/usr/bin/env python3
"""
地址拦截器 20 轮压力测试

模拟用户连续问 20 轮地址问题，验证拦截器是否正常工作。
每轮打印：
- LLM 输出原文
- 是否拦截
- 是否触发地址图片发送
- 最终发送文本
"""

import sys
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.address_interceptor import AddressInterceptor


# 模拟 LLM 回复池（针对不同门店）
LLM_REPLIES = {
    "jingan": [
        "姐姐，静安店在愚园路 172 号环球世界大厦 A 座。您方便的话留个电话。",
        "静安店在愚园路 172 号环球世界大厦 A 座，您看方便吗？",
        "我推荐静安店，在愚园路 172 号环球世界大厦 A 座。您方便留个手机号吗？",
        "姐姐，静安店地址是愚园路 172 号环球世界大厦 A 座，好找到的。",
        "静安店在愚园路 172 号环球世界大厦 A 座，地铁过来也方便的。",
    ],
    "hongkou": [
        "虹口店在花园路 16 号嘉和国际大厦东楼，您看方便吗？",
        "姐姐，虹口店在花园路 16 号嘉和国际大厦东楼。您方便的话留个电话。",
        "我推荐虹口店，在花园路 16 号嘉和国际大厦东楼。您方便留个手机号吗？",
        "姐姐，虹口店地址是花园路 16 号嘉和国际大厦东楼，好找到的。",
        "虹口店在花园路 16 号嘉和国际大厦东楼，地铁过来也方便的。",
    ],
    "huangpu": [
        "黄浦店在汉口路 650 号亚洲大厦，您方便的话留个电话。",
        "姐姐，黄浦店在汉口路 650 号亚洲大厦。您看方便吗？",
        "我推荐黄浦店，在汉口路 650 号亚洲大厦。您方便留个手机号吗？",
        "姐姐，黄浦店地址是汉口路 650 号亚洲大厦，好找到的。",
        "黄浦店在汉口路 650 号亚洲大厦，地铁过来也方便的。",
    ],
    "multi": [
        "姐姐，静安店在愚园路 172 号环球世界大厦 A 座，虹口店在花园路 16 号嘉和国际大厦东楼。您看哪个交通更方便？",
        "上海有两家店：静安店在愚园路 172 号，虹口店在花园路 16 号。您看哪家离您近？",
        "静安店在愚园路 172 号环球世界大厦 A 座，黄浦店在汉口路 650 号亚洲大厦。您选一家方便的吧。",
        "我们有三家店：静安店在愚园路 172 号，虹口店在花园路 16 号，黄浦店在汉口路 650 号。您看哪家近？",
        "姐姐，静安店在愚园路 172 号，虹口店在花园路 16 号。两家都可以的，您看哪家方便？",
    ],
    "no_address": [
        "姐姐，您方便的话留个电话，我让专属顾问联系您。",
        "您直接按上面的方式加我就可以哦，定位、路线还有预约和价格这些我都能继续发给您。",
        "姐姐，记得请添加我好友哦，我会发详细定位还有乘车路线以及预约/价格方面事项给到您。",
        "因咨询较多，我是智能助手小艾，请添加真人客服一对一详细为您解答！",
        "您记得加一下我这边哦，后面定位、路线还有预约价格这些我都继续跟您对接。",
    ],
}


def run_20_turns_test():
    """运行 20 轮地址问题测试"""

    print("=" * 80)
    print("🚀 地址拦截器 20 轮压力测试")
    print("=" * 80)
    print()

    interceptor = AddressInterceptor()

    # 20 轮测试场景设计
    # 混合单门店、多门店、无地址场景
    test_plan = [
        ("单店-静安", random.choice(LLM_REPLIES["jingan"])),
        ("单店-虹口", random.choice(LLM_REPLIES["hongkou"])),
        ("单店-黄浦", random.choice(LLM_REPLIES["huangpu"])),
        ("多店-2 家", random.choice(LLM_REPLIES["multi"])),
        ("单店-静安", random.choice(LLM_REPLIES["jingan"])),
        ("无地址", random.choice(LLM_REPLIES["no_address"])),
        ("单店-虹口", random.choice(LLM_REPLIES["hongkou"])),
        ("多店-3 家", random.choice(LLM_REPLIES["multi"])),
        ("单店-黄浦", random.choice(LLM_REPLIES["huangpu"])),
        ("无地址", random.choice(LLM_REPLIES["no_address"])),
        ("单店-静安", random.choice(LLM_REPLIES["jingan"])),
        ("单店-虹口", random.choice(LLM_REPLIES["hongkou"])),
        ("多店 -2 家", random.choice(LLM_REPLIES["multi"])),
        ("单店 - 黄浦", random.choice(LLM_REPLIES["huangpu"])),
        ("无地址", random.choice(LLM_REPLIES["no_address"])),
        ("单店 - 静安", random.choice(LLM_REPLIES["jingan"])),
        ("单店 - 虹口", random.choice(LLM_REPLIES["hongkou"])),
        ("单店 - 黄浦", random.choice(LLM_REPLIES["huangpu"])),
        ("多店 -2 家", random.choice(LLM_REPLIES["multi"])),
        ("无地址", random.choice(LLM_REPLIES["no_address"])),
    ]

    # 统计
    stats = {
        "intercepted": 0,      # 拦截次数
        "not_intercepted": 0,  # 未拦截次数
        "image_triggered": 0,  # 触发地址图片次数
        "multi_store": 0,      # 多门店地址次数
        "no_address": 0,       # 无地址次数
    }

    for i, (scenario, llm_output) in enumerate(test_plan, 1):
        print(f"\n{'='*80}")
        print(f"📍 第 {i:2d} 轮 | 场景：{scenario}")
        print(f"{'-'*80}")

        # 调用拦截器
        result = interceptor.intercept(llm_output)

        # 打印 LLM 输出
        print(f"🤖 LLM 输出:\n   {llm_output}")

        # 打印拦截结果
        if result.is_intercepted:
            stores_str = "、".join(result.target_stores)
            img_stores = result.target_stores[:2] if result.match_count <= 2 else result.target_stores[:1]
            print(f"\n✅ 拦截状态：已拦截 ({result.match_count} 家门店：{stores_str})")
            print(f"🎯 触发图片门店：{img_stores}")
            print(f"📤 发送文本：{result.processed_text}")
            print(f"📷 触发地址图片：✅ 是")
            stats["intercepted"] += 1
            stats["image_triggered"] += 1
        elif result.match_count == 0:
            print(f"\n❌ 拦截状态：未拦截 (无地址)")
            print(f"📤 发送文本：{result.processed_text}")
            print(f"📷 触发地址图片：❌ 否 (无地址)")
            stats["not_intercepted"] += 1
            stats["no_address"] += 1
        else:
            print(f"\n❌ 拦截状态：未拦截")
            print(f"📤 发送文本：{result.processed_text}")
            print(f"📷 触发地址图片：❌ 否")
            stats["not_intercepted"] += 1

    # 打印统计
    print(f"\n\n{'='*80}")
    print("📊 测试统计")
    print(f"{'='*80}")
    print(f"   总轮数：20")
    print(f"   ✅ 拦截次数：{stats['intercepted']}")
    print(f"   ❌ 未拦截次数：{stats['not_intercepted']}")
    print(f"      - 多门店地址：{stats['multi_store']}")
    print(f"      - 无地址：{stats['no_address']}")
    print(f"   📷 触发地址图片：{stats['image_triggered']}")
    print()

    # 验证
    print(f"{'='*80}")
    print("✅ 验证结果")
    print(f"{'='*80}")

    # 新规则：单店 + 多店都拦截，只有无地址才不拦截
    expected_intercepted = sum(1 for s, _ in test_plan if not s.startswith("无地址"))
    expected_not_intercepted = sum(1 for s, _ in test_plan if s.startswith("无地址"))

    if stats["intercepted"] == expected_intercepted:
        print(f"✅ 拦截次数正确：{stats['intercepted']} (预期：{expected_intercepted})")
    else:
        print(f"❌ 拦截次数错误：{stats['intercepted']} (预期：{expected_intercepted})")

    if stats["not_intercepted"] == expected_not_intercepted:
        print(f"✅ 未拦截次数正确：{stats['not_intercepted']} (预期：{expected_not_intercepted})")
    else:
        print(f"❌ 未拦截次数错误：{stats['not_intercepted']} (预期：{expected_not_intercepted})")

    if stats["image_triggered"] == expected_intercepted:
        print(f"✅ 触发地址图片次数正确：{stats['image_triggered']} (预期：{expected_intercepted})")
    else:
        print(f"❌ 触发地址图片次数错误：{stats['image_triggered']} (预期：{expected_intercepted})")

    print()
    print("=" * 80)
    print("🎉 20 轮压力测试完成！")
    print("=" * 80)


if __name__ == "__main__":
    run_20_turns_test()
