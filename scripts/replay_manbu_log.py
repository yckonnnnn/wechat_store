#!/usr/bin/env python3
"""
复测漫步人生 2026-03-26 聊天记录

用法:
    cd /Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev
    python3 scripts/replay_manbu_log.py
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import BRAND_KNOWLEDGE_FILE, ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


class ReplayLogger:
    """复测日志记录器"""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, turn: int, user_text: str, decision: Any, media_queue: List[Dict], session_state: Dict):
        record = {
            "turn": turn,
            "timestamp": datetime.now().isoformat(),
            "user_text": user_text,
            "reply_text": decision.reply_text if decision else "None",
            "intent": decision.intent if decision else "None",
            "route_reason": decision.route_reason if decision else "None",
            "rule_id": decision.rule_id if decision else "None",
            "reply_source": decision.reply_source if decision else "None",
            "contact_captured": session_state.get("contact_captured", False),
            "remote_contact_captured": session_state.get("remote_contact_captured", False),
            "contact_image_sent_count": session_state.get("contact_image_sent_count", 0),
            "media_plan": decision.media_plan if decision else "None",
            "media_types": [str(item.get("type", "")) for item in media_queue],
        }
        with self.output_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="复测漫步人生前30轮对话")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "conversations" / "漫步人生_2026-03-26.jsonl",
    )
    parser.add_argument("--turn-limit", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_file = args.log_file

    if not log_file.exists():
        print(f"错误：日志文件不存在：{log_file}")
        return 1

    # 读取原始日志中的用户消息
    user_messages = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if record.get("event_type") == "user_message":
                user_messages.append(record["payload"]["text"])

    if args.turn_limit > 0:
        user_messages = user_messages[: args.turn_limit]

    print(f"加载了 {len(user_messages)} 条用户消息")

    # 测试输出目录
    test_run_dir = Path(PROJECT_ROOT) / "data" / f"manbu_replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    test_run_dir.mkdir(parents=True, exist_ok=True)

    replay_log_path = test_run_dir / "replay_log.jsonl"
    replay_log = ReplayLogger(replay_log_path)

    # 初始化 Agent（使用真实 LLM）
    print("\n正在初始化 Agent（使用真实 DeepSeek 环境）...")

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = LLMService(config_manager)

    # 使用独立的记忆文件，避免污染现有数据
    memory_store = MemoryStore(test_run_dir / "agent_memory.json")

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
        conversation_log_dir=test_run_dir / "conversations",
    )

    agent.set_options(
        use_knowledge_first=agent.use_knowledge_first,
        knowledge_threshold=agent.knowledge_threshold,
        first_reply_video_enabled=False,
        reply_mode="llm_direct",
    )

    print(f"Agent 初始化完成，回复模式：llm_direct")
    print(f"测试输出目录：{test_run_dir}")
    print("\n" + "="*80 + "\n")

    # 模拟会话
    session_id = "manbu_replay_session"
    user_name = "漫步人生"
    user_hash = agent._hash_user(user_name)

    history: List[Dict[str, str]] = []

    for turn, user_text in enumerate(user_messages, start=1):
        print(f"\n【第{turn}轮】用户：{user_text[:50]}{'...' if len(user_text) > 50 else ''}")

        decision = agent.decide(
            session_id=session_id,
            user_name=user_name,
            latest_user_text=user_text,
            conversation_history=history,
        )

        # 获取当前 session_state
        session_state = memory_store.get_session_state(session_id, user_hash)

        # 模拟发送回复
        media_queue = []
        if decision:
            extra_video = agent.mark_reply_sent(session_id, user_name, decision.reply_text)
            media_queue = list(decision.media_items or [])
            if extra_video:
                media_queue.append(extra_video)

            # 模拟媒体发送完成
            for item in media_queue:
                if isinstance(item, dict):
                    agent.mark_media_sent(session_id, user_name, item, success=True)

            # 更新历史
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": decision.reply_text})

        # 打印关键状态
        contact_captured = session_state.get("contact_captured", False)
        remote_contact_captured = session_state.get("remote_contact_captured", False)
        contact_image_sent_count = session_state.get("contact_image_sent_count", 0)

        print(f"  回复：{decision.reply_text if decision else 'None'}")
        print(f"  意图：{decision.intent if decision else 'None'}")
        print(f"  路由：{decision.route_reason if decision else 'None'}")
        print(f"  规则：{decision.rule_id if decision else 'None'}")
        print(f"  来源：{decision.reply_source if decision else 'None'}")
        print(f"  contact_captured={contact_captured}, remote_contact_captured={remote_contact_captured}")
        print(f"  contact_image_sent_count={contact_image_sent_count}")

        # 记录日志
        replay_log.log(turn, user_text, decision, media_queue, session_state)

        # 检测异常：用户已提交手机号但仍在要求留联系方式
        if turn > 10 and not contact_captured and not remote_contact_captured:
            print(f"  ⚠️  警告：第{turn}轮仍未识别到手机号提交状态！")

    print("\n" + "="*80)
    print(f"复测完成！日志已保存到：{replay_log_path}")
    print(f"记忆文件：{test_run_dir / 'agent_memory.json'}")
    print(f"会话日志：{test_run_dir / 'conversations' / f'{session_id}.jsonl'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
