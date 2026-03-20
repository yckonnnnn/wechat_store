#!/usr/bin/env python3
"""
标准验收测试脚本。

用途：
1. 固化常见客服验收问题
2. 以 llm_direct 模式逐条调用当前 Agent
3. 输出 Markdown / JSON 结果，便于人工复测
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import BRAND_KNOWLEDGE_FILE, ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


@dataclass
class AcceptanceCase:
    idx: int
    category: str
    question: str


@dataclass
class AcceptanceResult:
    idx: int
    category: str
    question: str
    reply_text: str
    reply_source: str
    reply_mode: str
    intent: str
    route_reason: str
    media_plan: str
    media_types: List[str]
    standard_reply_hit: bool
    standard_reply_question: str
    standard_reply_confidence: str
    brand_knowledge_used: bool


CASES: List[AcceptanceCase] = [
    AcceptanceCase(1, "地址", "地址在哪呀"),
    AcceptanceCase(2, "地址", "我在上海"),
    AcceptanceCase(3, "地址", "我在北京朝阳，这边有门店吗"),
    AcceptanceCase(4, "地址", "我在徐汇附近，去哪家方便"),
    AcceptanceCase(5, "地址", "我不在上海，怎么弄呀"),
    AcceptanceCase(6, "地址", "我在外地，不方便到店，还能做吗"),
    AcceptanceCase(7, "繁体地址", "你們店在哪裡呀"),
    AcceptanceCase(8, "繁体地址", "我在人民廣場附近，有店嗎"),
    AcceptanceCase(9, "繁体地址", "北京朝陽有店嗎"),
    AcceptanceCase(10, "错别字地址", "地址在那里呀，我想过去看看"),
    AcceptanceCase(11, "错别字地址", "地只在哪呀姐姐，我在上嗨这边"),
    AcceptanceCase(12, "价格", "我想问下价格多少呀"),
    AcceptanceCase(13, "价格", "这款大概什么价位呀，贵不贵呢"),
    AcceptanceCase(14, "使用年限", "假发一般能用多久呀"),
    AcceptanceCase(15, "使用场景", "平时上班戴、出去旅游戴，合适吗"),
    AcceptanceCase(16, "使用场景", "夏天戴着会不会闷呀"),
    AcceptanceCase(17, "使用场景", "跳舞或者运动的时候会掉吗"),
    AcceptanceCase(18, "购买流程", "需要预约吗"),
    AcceptanceCase(19, "购买流程", "购买流程怎么走呀"),
    AcceptanceCase(20, "购买流程", "当天能做好带走吗"),
    AcceptanceCase(21, "购买流程", "外地能远程定制吗"),
    AcceptanceCase(22, "购买流程", "我不会量头围，也能做吗"),
    AcceptanceCase(23, "购买流程", "想买的话是先到店还是先预约呀"),
    AcceptanceCase(24, "营业时间", "请问营业时间是几点呀"),
    AcceptanceCase(25, "综合错别字", "你家门店在上嗨吗，我在许汇这边，哪家店近一点呀"),
    AcceptanceCase(26, "价格", "直播间里的发套怎么卖?"),
    AcceptanceCase(27, "地址", "地址在那个城市位置"),
    AcceptanceCase(28, "地址", "上海地址在哪里?"),
    AcceptanceCase(29, "地址", "我在江苏常州"),
    AcceptanceCase(30, "上下文地址", "好的谢谢那天我到上海来"),
    AcceptanceCase(31, "地址确认", "这个店是在人民广场吗?"),
    AcceptanceCase(32, "地址确认", "人民广场我认识的"),
    AcceptanceCase(33, "到店阻碍", "不方便去"),
    AcceptanceCase(34, "路线", "乘几号车?我在平凉路东宫"),
    AcceptanceCase(35, "地址", "店铺在那里?"),
    AcceptanceCase(36, "购买流程", "有没有链接，我可以在手机上下订单。"),
    AcceptanceCase(37, "营业时间", "好的，谢谢!几点上班，几点下班哦？"),
    AcceptanceCase(38, "繁体地址", "你好!楊浦区有门店吗?"),
    AcceptanceCase(39, "到店计划", "看看下周有时间就过去"),
    AcceptanceCase(40, "地址", "在什么地方?"),
    AcceptanceCase(41, "颜色", "这款有棕色的吗"),
    AcceptanceCase(42, "外地地址", "我们在武水区，内蒙古鄂尔多斯市无水区一个县城。"),
    AcceptanceCase(43, "产品理解", "对刚才你们直播的那个短发那个短发烫发短发那个。"),
    AcceptanceCase(44, "使用年限", "那一个假发能戴，能戴几年?"),
    AcceptanceCase(45, "外地地址", "绍兴市越城区有你们的店铺吗?"),
    AcceptanceCase(46, "远程定制", "我跟你说，我因为不小心摔了一跤，腿现在受伤了，不能去上海。"),
    AcceptanceCase(47, "远程定制", "我现在不方便，不能去上海。就是想在你们上面可以订一款。"),
    AcceptanceCase(48, "远程定制", "我跟你说我现在不方便。不能去上海没听懂吗?"),
    AcceptanceCase(49, "购买流程", "怎么卖到"),
    AcceptanceCase(50, "到店阻碍", "太远了"),
    AcceptanceCase(51, "地址", "你们假发在那?"),
    AcceptanceCase(52, "购买流程", "咋拍呀"),
    AcceptanceCase(53, "马老师", "我找马老师做可以吗‘"),
]


class StubLLMService:
    def __init__(self, fixed_reply: str = "姐姐，这个问题我给您简要说明。"):
        self._prompt = ""
        self._fixed_reply = fixed_reply

    def set_system_prompt(self, prompt: str):
        self._prompt = prompt or ""

    def generate_reply_sync(self, user_message: str, conversation_history=None) -> tuple:
        return True, self._fixed_reply

    def get_current_model_name(self) -> str:
        return "StubLLM"


def build_agent(sim_dir: Path, no_llm: bool = False, stub_reply: str = "") -> CustomerServiceAgent:
    sim_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = StubLLMService(stub_reply or "姐姐，这个问题我给您简要说明。") if no_llm else LLMService(config_manager)
    memory_store = MemoryStore(sim_dir / "agent_memory.json")

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
        use_knowledge_first=True,
        knowledge_threshold=0.6,
        first_reply_video_enabled=False,
        reply_mode="llm_direct",
    )
    return agent


def run_suite(agent: CustomerServiceAgent) -> List[AcceptanceResult]:
    results: List[AcceptanceResult] = []
    for case in CASES:
        decision = agent.decide(
            session_id=f"acceptance_{case.idx:02d}",
            user_name=f"acceptance_{case.idx:02d}",
            latest_user_text=case.question,
            conversation_history=[],
        )
        agent.mark_reply_sent(f"acceptance_{case.idx:02d}", f"acceptance_{case.idx:02d}", decision.reply_text)
        results.append(
            AcceptanceResult(
                idx=case.idx,
                category=case.category,
                question=case.question,
                reply_text=decision.reply_text,
                reply_source=decision.reply_source,
                reply_mode=getattr(decision, "reply_mode", ""),
                intent=decision.intent,
                route_reason=decision.route_reason,
                media_plan=decision.media_plan,
                media_types=[str(item.get("type", "")) for item in (decision.media_items or []) if isinstance(item, dict)],
                standard_reply_hit=bool(getattr(decision, "standard_reply_hit", False)),
                standard_reply_question=str(getattr(decision, "standard_reply_question", "") or ""),
                standard_reply_confidence=str(getattr(decision, "standard_reply_confidence", "") or ""),
                brand_knowledge_used=bool(getattr(decision, "brand_knowledge_used", False)),
            )
        )
    return results


def write_outputs(results: List[AcceptanceResult], output_prefix: Path) -> Dict[str, Path]:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_prefix.with_suffix(".json")
    md_path = output_prefix.with_suffix(".md")

    json_path.write_text(
        json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = ["# 标准验收测试结果", ""]
    for item in results:
        lines.append(f"## {item.idx}. {item.question}")
        lines.append(f"- 分类：{item.category}")
        lines.append(f"- 回复：{item.reply_text}")
        lines.append(f"- 来源：{item.reply_source} | 模式：{item.reply_mode}")
        lines.append(f"- intent：{item.intent} | route：{item.route_reason}")
        lines.append(f"- 标准话术命中：{'是' if item.standard_reply_hit else '否'}")
        lines.append(f"- 品牌知识参与：{'是' if item.brand_knowledge_used else '否'}")
        lines.append(f"- 媒体计划：{item.media_plan or 'none'}")
        lines.append("")
    md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {"json": json_path, "md": md_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 25 题标准验收测试")
    parser.add_argument("--no-llm", action="store_true", help="使用本地 Stub LLM")
    parser.add_argument("--stub-reply", default="", help="Stub LLM 固定回复")
    parser.add_argument(
        "--sim-dir",
        default="",
        help="运行时目录；不传时自动使用带时间戳的新目录，避免历史记忆污染验收结果",
    )
    parser.add_argument(
        "--output-prefix",
        default="data/acceptance_suite_report",
        help="输出文件前缀，默认 data/acceptance_suite_report",
    )
    args = parser.parse_args()

    sim_dir = Path(args.sim_dir) if str(args.sim_dir or "").strip() else (
        Path("data") / "acceptance_suite_runtime" / datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    agent = build_agent(
        sim_dir=sim_dir,
        no_llm=bool(args.no_llm),
        stub_reply=str(args.stub_reply or ""),
    )
    results = run_suite(agent)
    outputs = write_outputs(results, Path(args.output_prefix))

    print(
        json.dumps(
            {
                "count": len(results),
                "reply_mode": agent.reply_mode,
                "brand_knowledge_loaded": bool(agent.get_status().get("brand_knowledge_loaded", False)),
                "sim_dir": str(sim_dir),
                "json_report": str(outputs["json"]),
                "markdown_report": str(outputs["md"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("")
    for item in results:
        print(f"{item.idx}. {item.question}")
        print(f"   回复: {item.reply_text}")
        print(
            f"   来源={item.reply_source} | 标准话术={'是' if item.standard_reply_hit else '否'} | "
            f"品牌知识={'是' if item.brand_knowledge_used else '否'} | 媒体={item.media_plan or 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
