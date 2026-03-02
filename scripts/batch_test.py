#!/usr/bin/env python3
"""
批量测试脚本
读取测试文件，按顺序测试每个问题，输出结果到根目录
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


def build_agent(sim_data_dir: Path) -> CustomerServiceAgent:
    """构建测试用的 Agent"""
    sim_data_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_data_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = LLMService(config_manager)
    memory_store = MemoryStore(sim_data_dir / "agent_memory.json")

    return CustomerServiceAgent(
        knowledge_service=knowledge_service,
        llm_service=llm_service,
        memory_store=memory_store,
        images_dir=Path("images"),
        image_categories_path=Path("config") / "image_categories.json",
        system_prompt_doc_path=Path("docs") / "system_prompt_private_ai_customer_service.md",
        playbook_doc_path=Path("docs") / "private_ai_customer_service_playbook.md",
        reply_templates_path=Path("config") / "reply_templates.json",
        media_whitelist_path=Path("config") / "media_whitelist.json",
        conversation_log_dir=convo_dir,
    )


def read_test_questions(file_path: Path) -> List[str]:
    """读取测试文件中的问题"""
    if not file_path.exists():
        return []

    questions = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 跳过空行和注释
            if line and not line.startswith("#"):
                questions.append(line)
    return questions


def test_question(agent: CustomerServiceAgent, question: str, session_id: str, user_name: str, history: List[Dict[str, str]]) -> Dict[str, str]:
    """测试单个问题"""
    decision = agent.decide(
        session_id=session_id,
        user_name=user_name,
        latest_user_text=question,
        conversation_history=history,
    )

    # 检查是否触发媒体发送
    extra_video = agent.mark_reply_sent(session_id, user_name, decision.reply_text)
    media_queue = list(decision.media_items or [])
    if extra_video:
        media_queue.append(extra_video)

    # 标记媒体已发送
    for item in media_queue:
        if isinstance(item, dict):
            agent.mark_media_sent(session_id, user_name, item, success=True)

    # 判断触发了哪些媒体
    triggered_types = set()
    for item in media_queue:
        if isinstance(item, dict):
            media_type = item.get("type", "")
            if media_type == "address_image":
                triggered_types.add("地址图片")
            elif media_type == "contact_image":
                triggered_types.add("联系方式图片")
            elif media_type == "delayed_video":
                triggered_types.add("视频")

    # 更新历史
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": decision.reply_text})
    if len(history) > 20:
        del history[:-20]

    return {
        "question": question,
        "reply": decision.reply_text,
        "media_triggered": ", ".join(sorted(triggered_types)) if triggered_types else "无",
    }


def main():
    """主函数"""
    # 读取测试文件
    test_file1 = PROJECT_ROOT / "常见问题测试1.md"
    test_file2 = PROJECT_ROOT / "常见问题测试2.md"

    questions1 = read_test_questions(test_file1)
    questions2 = read_test_questions(test_file2)

    print(f"测试文件1: {len(questions1)} 个问题")
    print(f"测试文件2: {len(questions2)} 个问题")

    # 构建 Agent
    sim_data_dir = Path("data/batch_test")
    agent = build_agent(sim_data_dir)

    # 测试结果
    results = []

    # 测试文件1
    print("\n开始测试文件1...")
    session_id = "batch_test_1"
    user_name = "test_user_1"
    history: List[Dict[str, str]] = []

    for i, question in enumerate(questions1, 1):
        print(f"  [{i}/{len(questions1)}] {question}")
        result = test_question(agent, question, session_id, user_name, history)
        results.append(result)

    # 测试文件2（新会话）
    print("\n开始测试文件2...")
    session_id = "batch_test_2"
    user_name = "test_user_2"
    history = []

    for i, question in enumerate(questions2, 1):
        print(f"  [{i}/{len(questions2)}] {question}")
        result = test_question(agent, question, session_id, user_name, history)
        results.append(result)

    # 输出结果到文件
    output_file = PROJECT_ROOT / "测试结果.txt"
    with output_file.open("w", encoding="utf-8") as f:
        f.write("问题\t回复\t触发媒体\n")
        f.write("=" * 100 + "\n")
        for result in results:
            f.write(f"{result['question']}\t{result['reply']}\t{result['media_triggered']}\n")

    print(f"\n测试完成！结果已保存到: {output_file}")
    print(f"共测试 {len(results)} 个问题")


if __name__ == "__main__":
    main()

