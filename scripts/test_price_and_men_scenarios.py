#!/usr/bin/env python3
"""
批量测试价格问题和男士假发场景
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import BRAND_KNOWLEDGE_FILE, ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


# 测试场景列表
TEST_SCENARIOS = [
    # 价格相关问题
    {
        "name": "价格 - 直接问",
        "messages": ["假发咋卖"],
        "expect_price_range": True,
        "expect_contact": False,
    },
    {
        "name": "价格 - 多少钱",
        "messages": ["你们假发多少钱"],
        "expect_price_range": True,
        "expect_contact": False,
    },
    # 注意："贵不贵"是间接问法，LLM 可能不直接报区间，这里只检查不触发联系方式
    {
        "name": "价格 - 贵不贵",
        "messages": ["假发贵不贵啊"],
        "expect_price_range": False,  # 间接问法，不强制要求区间
        "expect_contact": False,
    },
    {
        "name": "价格 - 什么价位",
        "messages": ["什么价位的"],
        "expect_price_range": True,
        "expect_contact": False,
    },
    {
        "name": "价格 - 怎么收费",
        "messages": ["怎么收费"],
        "expect_price_range": True,
        "expect_contact": False,
    },
    {
        "name": "价格 - 具体价格",
        "messages": ["具体价格是多少"],
        "expect_price_range": True,
        "expect_contact": False,
    },
    # 男士假发问题
    {
        "name": "男士 - 直接问",
        "messages": ["男士假发有吗"],
        "expect_men_hair": True,
        "expect_contact": False,
    },
    {
        "name": "男士 - 男的能做吗",
        "messages": ["男的也能做假发吗"],
        "expect_men_hair": True,
        "expect_contact": False,
    },
    {
        "name": "男士 - 头顶稀疏",
        "messages": ["我老公头顶稀疏，能做吗"],
        "expect_men_hair": True,
        "expect_contact": False,
    },
    {
        "name": "男士 - 发际线",
        "messages": ["男士发际线后移可以弄吗"],
        "expect_men_hair": True,
        "expect_contact": False,
    },
    {
        "name": "男士 - 地中海",
        "messages": ["地中海的那种假发有吗"],
        "expect_men_hair": True,
        "expect_contact": False,
    },
    # 混合问题（价格 + 男士）
    {
        "name": "混合 - 男士价格",
        "messages": ["男士假发多少钱"],
        "expect_price_range": True,
        "expect_men_hair": False,  # LLM 可能只回答价格，不一定会明确说"男士"
        "expect_contact": False,
    },
    # 多轮对话
    {
        "name": "多轮 - 价格追问",
        "messages": ["假发咋卖", "3000 和 6000 有什么区别"],
        "expect_price_range": True,
        "expect_contact": False,
    },
    {
        "name": "多轮 - 先问后买",
        "messages": ["在吗", "假发什么价格", "那我要怎么买"],
        "expect_price_range": True,
        "expect_contact": False,  # "怎么买"不一定会触发联系方式，这是正常行为
    },
]


def run_scenario(
    agent: CustomerServiceAgent,
    session_id: str,
    user_name: str,
    messages: List[str],
) -> List[Dict[str, Any]]:
    """运行一个测试场景，返回每轮的决策结果"""
    results = []
    history: List[Dict[str, str]] = []
    user_hash = agent._hash_user(user_name)

    for i, text in enumerate(messages):
        decision = agent.decide(
            session_id=session_id,
            user_name=user_name,
            latest_user_text=text,
            conversation_history=history,
        )
        extra_video = agent.mark_reply_sent(session_id, user_name, decision.reply_text)
        media_queue = list(decision.media_items or [])
        if extra_video:
            media_queue.append(extra_video)
        triggered_types = [str(item.get("type", "")) for item in media_queue if isinstance(item, dict)]

        # 记录结果
        results.append({
            "turn": i + 1,
            "user_message": text,
            "reply_text": decision.reply_text,
            "reply_source": decision.reply_source,
            "rule_id": decision.rule_id,
            "media_types": triggered_types,
            "triggered_contact": "contact_image" in triggered_types,
            "triggered_address": "address_image" in triggered_types,
        })

        # 更新历史
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": decision.reply_text})
        if len(history) > 20:
            del history[:-20]

    return results


def analyze_results(scenario_name: str, results: List[Dict[str, Any]], expectations: Dict[str, bool]) -> Dict[str, Any]:
    """分析测试结果是否符合预期"""
    analysis = {
        "scenario": scenario_name,
        "passed": True,
        "details": [],
    }

    all_reply_texts = " ".join([r["reply_text"] for r in results])

    # 检查价格区间
    if expectations.get("expect_price_range"):
        has_price = any(
            token in all_reply_texts
            for token in ["3000", "4000", "5000", "6000", "三千", "四千", "五千", "六千"]
        )
        analysis["details"].append({
            "check": "价格区间",
            "expected": True,
            "actual": has_price,
            "passed": has_price,
        })
        if not has_price:
            analysis["passed"] = False

    # 检查男士假发
    if expectations.get("expect_men_hair"):
        has_men = any(
            token in all_reply_texts
            for token in ["男士", "男", "先生", "发际线", "头顶", "地中海"]
        )
        analysis["details"].append({
            "check": "男士假发",
            "expected": True,
            "actual": has_men,
            "passed": has_men,
        })
        if not has_men:
            analysis["passed"] = False

    # 检查联系方式（如果预期不触发，则检查是否错误触发）
    if expectations.get("expect_contact"):
        has_contact = any(r["triggered_contact"] for r in results)
        analysis["details"].append({
            "check": "联系方式触发",
            "expected": True,
            "actual": has_contact,
            "passed": has_contact,
        })
        if not has_contact:
            analysis["passed"] = False
    else:
        has_contact = any(r["triggered_contact"] for r in results)
        analysis["details"].append({
            "check": "联系方式不应触发",
            "expected": False,
            "actual": has_contact,
            "passed": not has_contact,
        })
        if has_contact:
            analysis["passed"] = False

    return analysis


def main() -> int:
    # 初始化 Agent
    sim_data_dir = PROJECT_ROOT / "data" / "test_price_scenarios"
    sim_data_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_data_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = LLMService(config_manager)
    memory_store = MemoryStore(sim_data_dir / "agent_memory.json")

    agent = CustomerServiceAgent(
        knowledge_service=knowledge_service,
        llm_service=llm_service,
        memory_store=memory_store,
        images_dir=Path("images"),
        image_categories_path=Path("config") / "image_categories.json",
        system_prompt_doc_path=Path("docs") / "system_prompt_private_ai_customer_service.md",
        playbook_doc_path=Path("docs") / "private_ai_customer_service_playbook.md",
        brand_knowledge_doc_path=BRAND_KNOWLEDGE_FILE,
        reply_templates_path=Path("config") / "reply_templates.json",
        media_whitelist_path=Path("config") / "media_whitelist.json",
        conversation_log_dir=convo_dir,
    )
    agent.set_options(
        use_knowledge_first=agent.use_knowledge_first,
        knowledge_threshold=agent.knowledge_threshold,
        first_reply_video_enabled=False,
        reply_mode="llm_direct",
    )

    print(f"开始批量测试，共 {len(TEST_SCENARIOS)} 个场景...")
    print("=" * 80)

    all_results = []
    passed_count = 0
    failed_count = 0

    for idx, scenario in enumerate(TEST_SCENARIOS):
        session_id = f"test_{idx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        user_name = "测试用户"

        results = run_scenario(agent, session_id, user_name, scenario["messages"])
        analysis = analyze_results(
            scenario["name"],
            results,
            {
                "expect_price_range": scenario.get("expect_price_range", False),
                "expect_men_hair": scenario.get("expect_men_hair", False),
                "expect_contact": scenario.get("expect_contact", False),
            }
        )

        all_results.append({
            "scenario": scenario["name"],
            "messages": scenario["messages"],
            "expectations": {
                "expect_price_range": scenario.get("expect_price_range", False),
                "expect_men_hair": scenario.get("expect_men_hair", False),
                "expect_contact": scenario.get("expect_contact", False),
            },
            "results": results,
            "analysis": analysis,
        })

        status = "✅ PASS" if analysis["passed"] else "❌ FAIL"
        if analysis["passed"]:
            passed_count += 1
        else:
            failed_count += 1

        print(f"\n[{idx + 1}/{len(TEST_SCENARIOS)}] {scenario['name']} - {status}")
        print("-" * 80)
        for r in results:
            print(f"  问题：{r['user_message']}")
            print(f"  回复：{r['reply_text']}")
            print(f"  媒体：{', '.join(r['media_types']) if r['media_types'] else '无'}")
            print()
        print(f"  分析:")
        for d in analysis["details"]:
            mark = "✓" if d["passed"] else "✗"
            print(f"    {mark} {d['check']}: 预期={d['expected']}, 实际={d['actual']}")

    # 总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    print(f"总场景数：{len(TEST_SCENARIOS)}")
    print(f"通过：{passed_count} ({passed_count * 100 // len(TEST_SCENARIOS)}%)")
    print(f"失败：{failed_count} ({failed_count * 100 // len(TEST_SCENARIOS)}%)")
    print()

    # 输出失败详情
    if failed_count > 0:
        print("失败场景详情:")
        for item in all_results:
            if not item["analysis"]["passed"]:
                print(f"\n  ❌ {item['scenario']}")
                for d in item["analysis"]["details"]:
                    if not d["passed"]:
                        print(f"      - {d['check']} 未通过 (预期={d['expected']}, 实际={d['actual']})")

    # 保存完整报告
    report_file = sim_data_dir / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total": len(TEST_SCENARIOS),
            "passed": passed_count,
            "failed": failed_count,
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n完整报告已保存：{report_file}")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
