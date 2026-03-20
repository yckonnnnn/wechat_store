#!/usr/bin/env python3
"""
本地客服策略快速仿真器（不依赖微信 UI）。

用法示例：
  python3 scripts/chat_simulator.py --no-llm
  python3 scripts/chat_simulator.py -m "不同价格有什么区别啊？" --no-llm
  python3 scripts/chat_simulator.py --media image --no-llm
  python3 scripts/chat_simulator.py --media video --session-id media_debug
  python3 scripts/chat_simulator.py --session-id user_debug_1 --user-name 调试用户
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import BRAND_KNOWLEDGE_FILE, ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


MEDIA_PLACEHOLDER_MAP = {
    "image": "[图片]",
    "video": "[视频]",
    "emoji": "[表情]",
}


class StubLLMService:
    """规则联调时的本地占位 LLM，避免真实 API 调用。"""

    def __init__(self, fixed_reply: str = "姐姐，这个问题我给您简要说明。"):
        self._prompt = ""
        self._fixed_reply = fixed_reply

    def set_system_prompt(self, prompt: str):
        self._prompt = prompt or ""

    def generate_reply_sync(self, user_message: str, conversation_history: Optional[List[Dict]] = None) -> Tuple[bool, str]:
        return True, self._fixed_reply

    def get_current_model_name(self) -> str:
        return "StubLLM"


def build_agent(no_llm: bool, stub_reply: str, sim_data_dir: Path, reply_mode: str) -> CustomerServiceAgent:
    sim_data_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_data_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = StubLLMService(stub_reply) if no_llm else LLMService(config_manager)
    memory_store = MemoryStore(sim_data_dir / "agent_memory.json")

    return CustomerServiceAgent(
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


def _append_session_event(
    session_log_file: Path,
    session_id: str,
    user_id_hash: str,
    event_type: str,
    payload: Dict[str, Any],
    reply_source: str = "",
    rule_id: str = "",
    model_name: str = "",
) -> None:
    record = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "user_id_hash": user_id_hash,
        "event_type": event_type,
        "reply_source": reply_source,
        "rule_id": rule_id,
        "model_name": model_name,
        "payload": payload,
    }
    session_log_file.parent.mkdir(parents=True, exist_ok=True)
    with session_log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_decision(decision, triggered_types: List[str]) -> None:
    triggered_set = set(triggered_types or [])
    trigger_flags = {
        "address_image": "address_image" in triggered_set,
        "contact_image": "contact_image" in triggered_set,
        "delayed_video": "delayed_video" in triggered_set,
    }
    media_types = [str(item.get("type", "")) for item in (decision.media_items or []) if isinstance(item, dict)]
    payload = {
        "reply_source": decision.reply_source,
        "reply_mode": getattr(decision, "reply_mode", ""),
        "intent": decision.intent,
        "route_reason": decision.route_reason,
        "rule_id": decision.rule_id,
        "media_plan": decision.media_plan,
        "media_types": media_types,
        "standard_reply_hit": bool(getattr(decision, "standard_reply_hit", False)),
        "standard_reply_question": str(getattr(decision, "standard_reply_question", "") or ""),
        "standard_reply_confidence": str(getattr(decision, "standard_reply_confidence", "") or ""),
        "brand_knowledge_used": bool(getattr(decision, "brand_knowledge_used", False)),
        "triggered_types_this_round": triggered_types,
        "triggered_flags_this_round": trigger_flags,
        "reply_text": decision.reply_text,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(
        f"本轮触发: 视频={'是' if trigger_flags['delayed_video'] else '否'} | "
        f"地址图片={'是' if trigger_flags['address_image'] else '否'} | "
        f"联系方式图片={'是' if trigger_flags['contact_image'] else '否'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="客服 Agent 命令行仿真器")
    parser.add_argument("-m", "--message", help="单次测试消息；不传则进入交互模式")
    parser.add_argument(
        "--media",
        choices=sorted(MEDIA_PLACEHOLDER_MAP.keys()),
        help="单次测试媒体占位消息：image / video / emoji",
    )
    parser.add_argument("--session-id", default="sim_session", help="会话 ID（默认 sim_session）")
    parser.add_argument("--user-name", default="sim_user", help="用户名（默认 sim_user）")
    parser.add_argument("--no-llm", action="store_true", help="禁用真实 LLM，使用本地占位回复")
    parser.add_argument("--stub-reply", default="姐姐，这个问题我给您简要说明。", help="--no-llm 时的固定回复")
    parser.add_argument("--reply-mode", default="llm_direct", choices=["legacy", "llm_direct"], help="回复模式")
    parser.add_argument(
        "--sim-data-dir",
        default="data/simulator",
        help="仿真数据目录（记忆和会话日志），默认 data/simulator",
    )
    args = parser.parse_args()

    agent = build_agent(
        no_llm=bool(args.no_llm),
        stub_reply=str(args.stub_reply or ""),
        sim_data_dir=Path(args.sim_data_dir),
        reply_mode=str(args.reply_mode or "llm_direct"),
    )
    agent.set_options(
        use_knowledge_first=agent.use_knowledge_first,
        knowledge_threshold=agent.knowledge_threshold,
        first_reply_video_enabled=False,
        reply_mode=str(args.reply_mode or "llm_direct"),
    )
    status = agent.get_status()
    print(
        json.dumps(
            {
                "reply_mode": status.get("reply_mode", ""),
                "brand_knowledge_loaded": bool(status.get("brand_knowledge_loaded", False)),
                "system_prompt_loaded": bool(status.get("system_prompt_loaded", False)),
                "playbook_loaded": bool(status.get("playbook_loaded", False)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    history: List[Dict[str, str]] = []
    session_log_file = Path(args.sim_data_dir) / "conversations" / f"{args.session_id}.jsonl"
    user_hash = agent._hash_user(args.user_name or args.session_id)  # noqa: SLF001

    def run_once(user_text: str) -> None:
        text = (user_text or "").strip()
        if not text:
            return
        _append_session_event(
            session_log_file=session_log_file,
            session_id=args.session_id,
            user_id_hash=user_hash,
            event_type="user_message",
            payload={"text": text},
        )
        decision = agent.decide(
            session_id=args.session_id,
            user_name=args.user_name,
            latest_user_text=text,
            conversation_history=history,
        )
        extra_video = agent.mark_reply_sent(args.session_id, args.user_name, decision.reply_text)
        media_queue = list(decision.media_items or [])
        if extra_video:
            media_queue.append(extra_video)
        triggered_types = [str(item.get("type", "")) for item in media_queue if isinstance(item, dict)]

        for item in media_queue:
            if not isinstance(item, dict):
                continue
            _append_session_event(
                session_log_file=session_log_file,
                session_id=args.session_id,
                user_id_hash=user_hash,
                event_type="media_attempt",
                payload=item,
                reply_source=decision.reply_source,
                rule_id=decision.rule_id,
                model_name=decision.llm_model,
            )
            _append_session_event(
                session_log_file=session_log_file,
                session_id=args.session_id,
                user_id_hash=user_hash,
                event_type="media_result",
                payload={"type": str(item.get("type", "")), "success": True, "result": {"ok": True}},
                reply_source=decision.reply_source,
                rule_id=decision.rule_id,
                model_name=decision.llm_model,
            )
            agent.mark_media_sent(args.session_id, args.user_name, item, success=True)

        _append_session_event(
            session_log_file=session_log_file,
            session_id=args.session_id,
            user_id_hash=user_hash,
            event_type="assistant_reply",
            reply_source=decision.reply_source,
            rule_id=decision.rule_id,
            model_name=decision.llm_model,
            payload={
                "text": decision.reply_text,
                "round_media_sent_types": triggered_types,
            },
        )
        print_decision(decision, triggered_types=triggered_types)
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": decision.reply_text})
        if len(history) > 20:
            del history[:-20]

    initial_message = ""
    if args.media:
        initial_message = MEDIA_PLACEHOLDER_MAP[str(args.media)]
    elif args.message:
        initial_message = str(args.message)

    if initial_message:
        run_once(initial_message)
        return 0

    print("进入交互模式。输入 /exit 退出，输入 /reset 清空当前会话上下文。")
    print("媒体快捷命令：/image 发送[图片]，/video 发送[视频]，/emoji 发送[表情]。")
    while True:
        try:
            text = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        if not text:
            continue
        if text in ("/exit", "exit", "quit"):
            print("已退出。")
            return 0
        if text == "/reset":
            history.clear()
            print("当前会话上下文已清空。")
            continue
        if text in {"/image", "/img"}:
            run_once(MEDIA_PLACEHOLDER_MAP["image"])
            continue
        if text in {"/video", "/vid"}:
            run_once(MEDIA_PLACEHOLDER_MAP["video"])
            continue
        if text in {"/emoji", "/emj"}:
            run_once(MEDIA_PLACEHOLDER_MAP["emoji"])
            continue
        run_once(text)


if __name__ == "__main__":
    raise SystemExit(main())
