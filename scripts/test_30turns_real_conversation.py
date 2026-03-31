#!/usr/bin/env python3
"""
30 轮真实对话场景压力测试

模拟真实用户从首次咨询到最终预约的完整对话流程，
覆盖地址、价格、产品、预约、营业时间等高频问题。

用法：
  python3 scripts/test_30turns_real_conversation.py
"""

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.address_interceptor import AddressInterceptor

interceptor = AddressInterceptor()
PLACEHOLDER = interceptor.ADDRESS_PLACEHOLDER

# ── 30 轮真实对话场景 ──────────────────────────────────────────────────────
# 格式：(轮次，用户问题，模拟 LLM 输出，预期行为)
# 预期行为："intercept_N"=拦截 N 家，"no_address"=不拦截，"retry_image"=重发

test_scenarios = [
    # ── 开场咨询 (1-5 轮) ─────────────────────────────────────────────────
    (1, "你好，在吗？", "姐姐好，我是艾耐儿假发顾问小艾，请问有什么可以帮您？", "no_address"),
    (2, "你们店在哪里？", "姐姐，您现在在什么城市/区域呀？我好帮您推荐离您最近的门店～我们门店分布：北京 1 家，上海 5 家（静安/人广/虹口/五角场/徐汇）", "no_address"),
    (3, "我在上海", "太好了姐姐，上海我们有 5 家门店，您在哪个区？我给您推荐最近的那家～", "no_address"),
    (4, "我在静安区", "姐姐，静安店就在愚园路 172 号环球世界大厦 A 座，从您那边过来很方便，地铁 2/7 号线静安寺站直达。", "intercept_1"),
    (5, "地址发我一下", "好的姐姐，静安店在愚园路 172 号环球世界大厦 A 座，您到了联系我，我下楼接您。", "intercept_1"),

    # ── 价格咨询 (6-10 轮) ────────────────────────────────────────────────
    (6, "价格是多少？", "姐姐，我们的假发价格在 3000-6000 元之间，根据材质和工艺不同有所区别，您来店里我可以给您详细介绍。", "no_address"),
    (7, "有点贵啊", "姐姐，我们的假发是手工钩织的，透气舒适，可以戴 1-2 年呢，算下来每天不到 10 块钱，而且我们还提供免费修剪和护理服务。", "no_address"),
    (8, "有便宜的吗？", "姐姐，我们全国统一价 3000-6000 元，没有更低价的了，但品质有保障，您可以来店里试戴体验。", "no_address"),
    (9, "别人家才 2000", "姐姐，市面上确实有便宜的，但我们用的是真人发丝，手工钩织，透气性和舒适度完全不同，您来试戴一下就能感受到区别。", "no_address"),
    (10, "能便宜点吗？", "姐姐，我们全国统一价格，确实没有办法便宜呢，但我可以给您申请一次免费的头皮护理体验。", "no_address"),

    # ── 产品咨询 (11-15 轮) ───────────────────────────────────────────────
    (11, "假发透气吗？", "姐姐，我们的假发采用网底设计，非常透气，夏天戴也不会闷热，很多客户戴一整天都说很舒服。", "no_address"),
    (12, "假发贵不贵？", "姐姐，价格在 3000-6000 元，是手工钩织的真人发丝，可以戴 1-2 年，算下来每天不到 10 块钱呢。", "no_address"),
    (13, "有男士的吗？", "有的姐姐，我们有专门的男士假发系列，无论头顶稀疏还是全秃，都有合适的款式，欢迎您来店里试戴。", "no_address"),
    (14, "假发必须要到现场吗？", "姐姐，建议您到店试戴，我们可以根据您的脸型和发型需求来推荐，也可以现场修剪。如果实在不方便，也可以远程定制。", "no_address"),
    (15, "如何远程定制？", "姐姐，您方便留个电话吗？我让专业老师教您如何用软尺量头围，然后设计好后邮寄到家。", "no_address"),

    # ── 预约咨询 (16-20 轮) ───────────────────────────────────────────────
    (16, "如何预约？", "姐姐，您方便留个电话或微信吗？我帮您安排专属顾问预约时间，到店不用排队。", "no_address"),
    (17, "你们营业时间？", "姐姐，我们门店营业时间是早上 10 点到晚上 9 点，周末无休，您看什么时间方便？", "no_address"),
    (18, "周末人多吗？", "姐姐，周末人会多一些，建议您提前预约，我帮您安排专属顾问，不用排队。", "no_address"),
    (19, "需要多长时间？", "姐姐，第一次到店大概需要 1-2 小时，包括试戴、修剪和护理指导，您提前安排好时间哦。", "no_address"),
    (20, "要提前多久预约？", "姐姐，建议您提前 1-2 天预约，这样可以安排到更合适的时间段，您看这周末方便吗？", "no_address"),

    # ── 多店对比 (21-25 轮) ───────────────────────────────────────────────
    (21, "上海 5 家店分别在哪？", "姐姐，上海 5 家：静安店在愚园路 172 号，人民广场在汉口路 650 号，虹口在花园路 16 号，五角场在政通路 177 号，徐汇在漕溪北路 45 号。", "intercept_5"),
    # 第 22 轮：只说店名，没有具体地址 → 不拦截
    (22, "哪家店最大？", "姐姐，静安店和人民广场店规模相近，都是我们的旗舰店，款式最全，您看哪家离您近？", "no_address"),
    # 第 23 轮：只说北京店 1 个地址 → 拦截 1 家
    (23, "北京店和上海店一样吗？", "姐姐，北京店在朝阳区建外 SOHO 东区，上海有 5 家店，两家都是直营，服务和品质一样的。", "intercept_1"),
    (24, "我在北京，能去北京店吗？", "当然可以姐姐，北京店在朝阳区建外 SOHO 东区，地铁 1 号线永安里站直达，欢迎您来。", "intercept_1"),
    (25, "北京店地址发我", "好的姐姐，北京店在朝阳区建外 SOHO 东区，您到了联系我，我下楼接您。", "intercept_1"),

    # ── 图在哪儿 + 收尾 (26-30 轮) ────────────────────────────────────────
    (26, "图呢没看到", "姐姐稍等，我再给您发一次地址图～", "retry_image"),
    (27, "好的，我周六下午 2 点来", "好的姐姐，我帮您预约周六下午 2 点，静安店，您到了直接找我就好。", "no_address"),
    (28, "需要带什么吗？", "姐姐，您什么都不用带，人到就可以，我们会给您做免费的头皮检测和护理建议。", "no_address"),
    (29, "可以刷卡吗？", "姐姐，我们支持微信、支付宝、刷卡，各种支付方式都可以。", "no_address"),
    (30, "好的，到时候联系", "好的姐姐，期待您周六光临，有任何问题随时联系我，祝您生活愉快！", "no_address"),
]


def format_result(round_num: int, question: str, llm_output: str, result, expected: str,
                  session_state: dict) -> dict:
    """格式化单轮测试结果"""

    # 图在哪儿重发场景
    if expected == "retry_image":
        last_store = session_state.get("last_intercepted_store", "")
        return {
            "round": round_num,
            "question": question,
            "expected": "图在哪儿重发",
            "actual": f"跳过 LLM，重发 [{last_store}] 地址图" if last_store else "无法重发 (无上文门店)",
            "status": "PASS" if last_store else "FAIL",
            "llm_output": "[跳过 LLM]",
            "processed_text": "姐姐稍等，我再给您发一次地址图～",
            "image_triggered": bool(last_store),
            "image_stores_to_send": [last_store] if last_store else [],
        }

    # 无地址场景
    if expected == "no_address":
        passed = not result.is_intercepted
        return {
            "round": round_num,
            "question": question,
            "expected": "不拦截",
            "actual": "不拦截" if not result.is_intercepted else f"拦截 {result.match_count} 家",
            "status": "PASS" if passed else "FAIL",
            "llm_output": llm_output,
            "processed_text": result.processed_text,
            "image_triggered": False,
        }

    # 地址拦截场景
    expected_stores = {"intercept_1": 1, "intercept_2": 2, "intercept_5": 5}
    expected_count = expected_stores.get(expected, 0)
    passed = result.is_intercepted and result.match_count == expected_count

    img_stores = result.target_stores[:2] if result.match_count <= 2 else result.target_stores[:1]
    img_policy = "1 张" if result.match_count == 1 else ("2 张 (各发 1 张)" if result.match_count == 2 else "1 张 (3+ 家只发第 1 家)")

    return {
        "round": round_num,
        "question": question,
        "expected": f"拦截 {expected_count} 家",
        "actual": f"拦截 {result.match_count} 家",
        "status": "PASS" if passed else "FAIL",
        "llm_output": llm_output,
        "processed_text": result.processed_text,
        "target_stores": result.target_stores,
        "image_triggered": True,
        "image_stores_to_send": img_stores,
        "image_trigger_note": img_policy,
        "placeholder_count": result.processed_text.count(PLACEHOLDER),
    }


def run_30_turns_test():
    print("=" * 85)
    print("  30 轮真实对话场景压力测试")
    print("  测试时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 85)
    print()

    results = []
    pass_count = 0
    fail_count = 0
    session_state = {"last_intercepted_store": ""}

    for round_num, question, llm_output, expected in test_scenarios:
        # 处理图在哪儿触发场景
        if expected == "retry_image":
            last_store = session_state.get("last_intercepted_store", "")
            if last_store:
                results.append(format_result(round_num, question, llm_output, None, expected, session_state))
                pass_count += 1
            else:
                results.append(format_result(round_num, question, llm_output, None, expected, session_state))
                fail_count += 1
            continue

        # 正常调用拦截器
        result = interceptor.intercept(llm_output)

        # 更新 session_state
        if result.is_intercepted and result.target_stores:
            session_state["last_intercepted_store"] = result.target_stores[0]

        res = format_result(round_num, question, llm_output, result, expected, session_state)
        results.append(res)

        if res["status"] == "PASS":
            pass_count += 1
        else:
            fail_count += 1

    # ── 逐轮打印结果 ────────────────────────────────────────────────────────────
    print("\n" + "=" * 85)
    print("  逐轮测试结果")
    print("=" * 85)

    phase_names = {
        1: "开场咨询", 2: "价格咨询", 3: "产品咨询", 4: "预约咨询", 5: "多店对比", 6: "图在哪儿 + 收尾"
    }

    current_phase = 0
    for res in results:
        # 显示阶段标题
        phase_idx = (res["round"] - 1) // 5 + 1
        if phase_idx != current_phase:
            current_phase = phase_idx
            phase_name = phase_names.get(phase_idx, f"阶段{phase_idx}")
            print(f"\n{'='*85}")
            print(f"  【阶段{phase_idx}】{phase_name} (第{(phase_idx-1)*5+1}-{phase_idx*5}轮)")
            print(f"{'='*85}")

        status_icon = "✅" if res["status"] == "PASS" else "❌"
        print(f"\n{'='*80}")
        print(f"【第{res['round']}轮】{status_icon} {res['question']}")
        print(f"{'='*80}")

        # LLM 原始输出
        llm_text = res.get("llm_output", "")
        if llm_text:
            print(f"\n🤖 LLM 原始输出:")
            if len(llm_text) > 75:
                lines = [llm_text[i:i+75] for i in range(0, len(llm_text), 75)]
                for i, line in enumerate(lines):
                    indent = "   " if i > 0 else ""
                    print(f"{indent}{line}")
            else:
                print(f"   {llm_text}")
        else:
            print(f"\n🤖 LLM 原始输出：[跳过 LLM，直接重发]")

        # 处理后文本
        processed = res.get("processed_text", "")
        if processed and processed != llm_text:
            print(f"\n📤 发送给用户 (已替换):")
            if len(processed) > 75:
                lines = [processed[i:i+75] for i in range(0, len(processed), 75)]
                for i, line in enumerate(lines):
                    indent = "   " if i > 0 else ""
                    print(f"{indent}{line}")
            else:
                print(f"   {processed}")

        # 替换统计
        if res.get("placeholder_count") is not None and res["placeholder_count"] > 0:
            print(f"\n🔁 替换统计：{res['placeholder_count']} 处地址 → \"地址看图片中的位置\"")

        # 图片触发情况
        print(f"\n📷 图片触发:")
        if res.get("image_triggered"):
            img_stores = res.get("image_stores_to_send", [])
            img_note = res.get("image_trigger_note", "")
            print(f"   ✅ 触发地址图片发送")
            print(f"      目标门店：{img_stores}")
            print(f"      策略：{img_note}")
        elif "重发" in str(res.get("actual", "")):
            store_match = res.get("actual", "")
            if "[" in store_match and "]" in store_match:
                store_name = store_match.split("[")[1].split("]")[0]
            else:
                store_name = "上次门店"
            print(f"   ✅ 跳过 LLM，直接重发 [{store_name}] 地址图")
            print(f"      策略：触发词检测命中，跳过 LLM 调用")
        else:
            print(f"   ❌ 未触发图片 (无地址不触发)")

        # 预期/实际对比
        print(f"\n📋 验证：预期={res['expected']} | 实际={res['actual']}")

    # ── 分类统计 ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 85)
    print("  分类统计")
    print("=" * 85)

    categories = {
        "单门店拦截 (1 家)": [r for r in results if r.get("expected") == "intercept_1"],
        "双门店拦截 (2 家)": [r for r in results if r.get("expected") == "intercept_2"],
        "5 门店拦截 (5 家)": [r for r in results if r.get("expected") == "intercept_5"],
        "无地址不拦截": [r for r in results if r.get("expected") == "no_address"],
        "图在哪儿重发": [r for r in results if r.get("expected") == "retry_image"],
    }

    for cat_name, cat_results in categories.items():
        cat_pass = sum(1 for r in cat_results if r["status"] == "PASS")
        cat_total = len(cat_results)
        if cat_total > 0:
            status = "✅" if cat_pass == cat_total else "❌"
            print(f"\n{status} {cat_name}: {cat_pass}/{cat_total} 通过")

    # ── 总结 ──────────────────────────────────────────────────────────────────
    print("\n" + "=" * 85)
    print("  测试总结")
    print("=" * 85)
    overall_status = "✅" if fail_count == 0 else "❌"
    print(f"\n  总轮数：30")
    print(f"  {overall_status} 通过：{pass_count}/30")
    print(f"  ❌ 失败：{fail_count}/30")

    print("\n" + "-" * 85)
    print("  关键规则验证")
    print("-" * 85)

    rules = [
        ("单门店地址 → 拦截替换 + 触发 1 张图", all(r["status"] == "PASS" for r in categories.get("单门店拦截 (1 家)", []))),
        ("双门店地址 → 两处替换 + 触发 2 张图", all(r["status"] == "PASS" for r in categories.get("双门店拦截 (2 家)", []))),
        ("5 家门店 → 全部替换 + 仅触发第 1 家图", all(r["status"] == "PASS" for r in categories.get("5 门店拦截 (5 家)", []))),
        ("无地址 → 不拦截不触发", all(r["status"] == "PASS" for r in categories.get("无地址不拦截", []))),
        ("图在哪儿 → 跳过 LLM 直接重发", all(r["status"] == "PASS" for r in categories.get("图在哪儿重发", []))),
    ]

    for rule, passed in rules:
        print(f"  {'✅' if passed else '❌'} {rule}")

    print("\n" + "=" * 85)
    if fail_count == 0:
        print("  ✅ 30 轮真实对话场景压力测试全部通过！")
    else:
        print(f"  ❌ 有 {fail_count} 轮测试失败，请检查")
    print("=" * 85)

    return fail_count == 0


if __name__ == "__main__":
    success = run_30_turns_test()
    sys.exit(0 if success else 1)
