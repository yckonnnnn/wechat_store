#!/usr/bin/env python3
"""
按模板运行专项验收测试。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

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
class TurnResult:
    turn: int
    input: str
    reply_text: str
    reply_source: str
    intent: str
    route_reason: str
    media_plan: str
    standard_reply_hit: bool
    brand_knowledge_used: bool


@dataclass
class CaseResult:
    idx: int
    category: str
    mode: str
    turns: List[TurnResult]


def build_agent(sim_dir: Path) -> CustomerServiceAgent:
    sim_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)
    agent = CustomerServiceAgent(
        knowledge_service=KnowledgeService(KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE), address_config_path=Path("config") / "address.json"),
        llm_service=LLMService(ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)),
        memory_store=MemoryStore(sim_dir / "agent_memory.json"),
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


def run_template(template_path: Path) -> Dict[str, Any]:
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    template_type = str(payload.get("type", "single_turn") or "single_turn")
    cases = list(payload.get("cases", []) or [])
    sim_dir = Path("data") / "template_runtime" / template_path.stem / datetime.now().strftime("%Y%m%d_%H%M%S")
    agent = build_agent(sim_dir)
    results: List[CaseResult] = []

    for case in cases:
        idx = int(case.get("idx", 0) or 0)
        category = str(case.get("category", "") or "")
        turns: List[TurnResult] = []
        history: List[Dict[str, str]] = []
        messages = [str(case.get("question", "") or "")] if template_type == "single_turn" else [str(x) for x in (case.get("messages", []) or []) if str(x).strip()]
        for turn_idx, text in enumerate(messages, 1):
            decision = agent.decide(
                session_id=f"{template_path.stem}_{idx:02d}",
                user_name=f"{template_path.stem}_{idx:02d}",
                latest_user_text=text,
                conversation_history=history,
            )
            agent.mark_reply_sent(f"{template_path.stem}_{idx:02d}", f"{template_path.stem}_{idx:02d}", decision.reply_text)
            turns.append(
                TurnResult(
                    turn=turn_idx,
                    input=text,
                    reply_text=decision.reply_text,
                    reply_source=decision.reply_source,
                    intent=decision.intent,
                    route_reason=decision.route_reason,
                    media_plan=decision.media_plan,
                    standard_reply_hit=bool(getattr(decision, "standard_reply_hit", False)),
                    brand_knowledge_used=bool(getattr(decision, "brand_knowledge_used", False)),
                )
            )
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": decision.reply_text})
        results.append(CaseResult(idx=idx, category=category, mode=template_type, turns=turns))

    report_dir = Path("data") / "template_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{template_path.stem}.json"
    report_path.write_text(
        json.dumps(
            {
                "name": payload.get("name", template_path.stem),
                "description": payload.get("description", ""),
                "type": template_type,
                "template_path": str(template_path),
                "report_path": str(report_path),
                "sim_dir": str(sim_dir),
                "results": [asdict(item) for item in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return json.loads(report_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="按模板运行专项验收测试")
    parser.add_argument("template", help="模板文件路径")
    args = parser.parse_args()
    report = run_template(Path(args.template))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
