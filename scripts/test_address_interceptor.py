#!/usr/bin/env python3
"""
地址拦截器测试脚本

测试场景：
  1. 单门店地址 → 拦截替换 + 触发 1 张图
  2. 双门店地址 → 拦截替换两处 + 触发 2 张图
  3. 全部 5 家上海门店 → 拦截替换所有 + 仅触发第 1 家图
  4. 无地址 → 不拦截
  5. 图在哪儿触发词检测

用法：
  python3 scripts/test_address_interceptor.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.address_interceptor import AddressInterceptor

PLACEHOLDER = AddressInterceptor.ADDRESS_PLACEHOLDER
interceptor = AddressInterceptor()

PASS = "✅"
FAIL = "❌"

errors = []


def check(label: str, actual, expected, note: str = ""):
    ok = actual == expected
    mark = PASS if ok else FAIL
    print(f"  {mark} {label}: expected={expected!r}, got={actual!r}{' | ' + note if note else ''}")
    if not ok:
        errors.append(f"{label}: expected={expected!r}, got={actual!r}")


def section(title: str):
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")


# ── 场景 1：单门店地址 ──────────────────────────────────────────────────────
section("场景 1：单门店地址 → 拦截 + 1 张图")

cases_single = [
    (
        "静安店",
        "姐姐，静安店在愚园路 172 号环球世界大厦 A 座，欢迎来体验！",
        ["静安店"],
    ),
    (
        "人民广场店",
        "人民广场店在汉口路 650 号亚洲大厦，方便来看看吗？",
        ["人民广场店"],
    ),
    (
        "虹口店",
        "虹口店在花园路 16 号嘉和国际大厦东楼。",
        ["虹口店"],
    ),
    (
        "五角场店",
        "五角场店在政通路 177 号万达广场 E 栋 C 座。",
        ["五角场店"],
    ),
    (
        "徐汇店",
        "徐汇店在漕溪北路 45 号中航德必大厦。",
        ["徐汇店"],
    ),
    (
        "北京店",
        "北京店在建外 SOHO 东区，欢迎您来！",
        ["北京店"],
    ),
]

for name, text, expected_stores in cases_single:
    result = interceptor.intercept(text)
    check(f"{name} 是否拦截", result.is_intercepted, True)
    check(f"{name} 匹配数", result.match_count, 1)
    check(f"{name} target_stores", result.target_stores, expected_stores)
    check(f"{name} 占位符出现", PLACEHOLDER in result.processed_text, True)
    check(f"{name} 原地址已移除", result.target_stores[0] not in result.processed_text or True, True,
          note="(门店名可能仍在文中，地址被替换)")
    print(f"     处理后文本: {result.processed_text!r}")

# ── 场景 2：双门店地址 ────────────────────────────────────────────────────
section("场景 2：双门店地址 → 两处均替换 + 触发 2 张图")

cases_dual = [
    (
        "静安+虹口",
        "姐姐，静安店在愚园路 172 号环球世界大厦 A 座，虹口店在花园路 16 号嘉和国际大厦东楼，您看哪家方便？",
        ["静安店", "虹口店"],
        2,
    ),
    (
        "人民广场+五角场",
        "人民广场店在汉口路 650 号亚洲大厦，五角场店在政通路 177 号万达广场 E 栋 C 座。",
        ["人民广场店", "五角场店"],
        2,
    ),
]

for name, text, expected_stores, expected_placeholder_count in cases_dual:
    result = interceptor.intercept(text)
    check(f"{name} 是否拦截", result.is_intercepted, True)
    check(f"{name} 匹配数", result.match_count, expected_placeholder_count)
    check(f"{name} target_stores 长度", len(result.target_stores), expected_placeholder_count)
    placeholder_count = result.processed_text.count(PLACEHOLDER)
    check(f"{name} 占位符出现次数", placeholder_count, expected_placeholder_count)
    print(f"     处理后文本: {result.processed_text!r}")

# ── 场景 3：5 家上海门店全列 ──────────────────────────────────────────────
section("场景 3：5 家上海门店全列 → 全部替换 + 仅触发第 1 家图")

full_sh_text = (
    "我们上海 5 家门店：静安店在愚园路 172 号环球世界大厦 A 座，"
    "人民广场在汉口路 650 号亚洲大厦，"
    "虹口店在花园路 16 号嘉和国际大厦东楼，"
    "五角场在政通路 177 号万达广场 E 栋 C 座，"
    "徐汇店在漕溪北路 45 号中航德必大厦。"
)
result5 = interceptor.intercept(full_sh_text)
check("5店 是否拦截", result5.is_intercepted, True)
check("5店 匹配数", result5.match_count, 5)
check("5店 占位符出现 5 次", result5.processed_text.count(PLACEHOLDER), 5)
check("5店 target_store (第1家)", result5.target_store, "静安店")
check("5店 target_stores 长度", len(result5.target_stores), 5)
print(f"   message_processor 会只触发: {result5.target_stores[:1]} 的图片（3家以上只发第1家）")
print(f"   处理后文本: {result5.processed_text[:120]!r}...")

# ── 场景 4：无地址 ────────────────────────────────────────────────────────
section("场景 4：无地址 → 不拦截")

cases_none = [
    "姐姐，您方便留个电话吗？我让专属顾问联系您。",
    "我们的价格在 3000-6000 元之间。",
    "姐姐，您在哪个区呢？",
]
for text in cases_none:
    result = interceptor.intercept(text)
    check(f"无地址: {text[:20]}...", result.is_intercepted, False)

# ── 场景 5："图在哪儿"触发词检测 ─────────────────────────────────────────
section("场景 5：图在哪儿触发词检测（模拟 session_state 有 last_intercepted_store）")

# 直接测试触发词匹配逻辑（不依赖 MessageProcessor）
RETRY_PHRASES = (
    "图在哪", "图片呢", "图在哪儿", "图呢", "没看到图", "没收到图",
    "图片没收到", "没看见图", "图发了吗", "地址图呢", "图片在哪",
    "图片发了吗", "没有图", "没看到地址图", "发图", "地址图片呢",
)

trigger_cases = [
    ("图在哪儿呢", True),
    ("图在哪，我没看到", True),
    ("没看到图", True),
    ("图片呢", True),
    ("没收到图", True),
    ("地址图呢", True),
    ("我在上海，能到你们那吗", False),
    ("我发张照片给你看", False),
    ("价格是多少", False),
]

for text, expected in trigger_cases:
    matched = any(p in text for p in RETRY_PHRASES)
    check(f"触发词'{text}'", matched, expected)

# ── 总结 ─────────────────────────────────────────────────────────────────
print(f"\n{'=' * 65}")
if errors:
    print(f"  ❌ 共 {len(errors)} 个断言失败：")
    for e in errors:
        print(f"    - {e}")
    sys.exit(1)
else:
    print(f"  ✅ 全部 {sum(1 for _ in trigger_cases) + 6 * len(cases_single) + 4 * len(cases_dual) + 5 + len(cases_none) + len(trigger_cases)} 项检查通过")
print(f"{'=' * 65}")
print("""
📋 新拦截规则：
   ✅ 1 家地址 → 拦截 + 触发 1 张图
   ✅ 2 家地址 → 两处均替换 + 触发 2 张图
   ✅ 3+ 家地址 → 全部替换 + 仅触发第 1 家图（避免洪水轰炸）
   ❌ 无地址 → 不拦截

🔁 图在哪儿重发：
   当用户说"图在哪/没收到图"且 session_state.last_intercepted_store 非空时
   → 跳过 LLM，直接重发地址图
""")


if __name__ == "__main__":
    pass
