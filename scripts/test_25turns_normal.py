#!/usr/bin/env python3
"""
25 轮正常场景仿真测试 - 覆盖地址、价格、质量、售后、营业时间等高频问题
"""
import sys
import hashlib
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(Path("/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev")))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE, ENV_FILE
from src.utils.emoji_helper import add_random_emoji


# ── 25 轮正常场景对话脚本 ─────────────────────────────────────────────────────────
# 设计原则：模拟真实用户正常咨询的全流程，覆盖所有高频问题
TURNS = [
    # 价格咨询 (1-5)
    "你们家假发多少钱",
    "价格为什么这么贵",
    "有没有便宜点的",
    "3000 的和 6000 的有什么区别",
    "6000 元的是真人头发吗",

    # 门店地址 (6-10)
    "你们店在哪里",
    "上海有几家店",
    "静安店具体地址是什么",
    "人民广场店怎么去",
    "北京有店吗",

    # 产品质量 (11-15)
    "假发戴起来自然吗",
    "会不会很热",
    "假发是什么材质做的",
    "能不能洗头",
    "假发质量怎么样",

    # 售后服务 (16-20)
    "你们有售后吗",
    "保修多久",
    "坏了可以修吗",
    "多久保养一次",
    "保养怎么弄",

    # 营业时间/收尾 (21-25)
    "你们营业时间是多少",
    "周末营业吗",
    "需要提前预约吗",
    "好的我想去店里看看，怎么联系",
    "那我先考虑一下，有需要再联系你",
]


def build_user_hash(user_name: str) -> str:
    return hashlib.sha256(user_name.encode()).hexdigest()[:16]


def build_agent() -> CustomerServiceAgent:
    base = Path("/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev")
    sim_dir = base / "data" / "test_25turns_normal"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "conversations").mkdir(exist_ok=True)

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=base / "config" / "address.json")
    llm_service = LLMService(config_manager)
    memory_store = MemoryStore(sim_dir / "agent_memory.json")

    return CustomerServiceAgent(
        knowledge_service=knowledge_service,
        llm_service=llm_service,
        memory_store=memory_store,
        images_dir=base / "images",
        image_categories_path=base / "config" / "image_categories.json",
        system_prompt_doc_path=base / "docs" / "system_prompt_private_ai_customer_service.md",
        playbook_doc_path=base / "docs" / "private_ai_customer_service_playbook.md",
        conversation_log_dir=sim_dir / "conversations",
    )


def run():
    agent = build_agent()
    status = agent.get_status()
    print("=" * 70)
    print(f"模型：{agent.llm_service.get_current_model_name()}")
    print(f"system_prompt_loaded: {status['system_prompt_loaded']}")
    print(f"contact_images: {status['contact_image_count']}")
    print(f"video_medias: {status['video_media_count']}")
    print("=" * 70)

    session_id = "test_25turns_normal_session"
    user_name = "测试用户张女士"
    history: List[Dict[str, str]] = []

    errors = 0
    error_details = []
    emoji_stats = {"with_emoji": 0, "without_emoji": 0}

    for i, user_text in enumerate(TURNS, 1):
        print(f"\n{'─'*70}")
        print(f"[轮 {i:02d}/25] 用户：{user_text}")

        try:
            decision = agent.decide(
                session_id=session_id,
                user_name=user_name,
                latest_user_text=user_text,
                conversation_history=history,
            )
        except Exception as e:
            print(f"  ❌ decide() 抛出异常：{e}")
            errors += 1
            error_details.append(f"轮{i}: {str(e)}")
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": "[ERROR]"})
            continue

        reply = decision.reply_text or ""

        # 模拟后端添加 emoji
        reply_with_emoji = add_random_emoji(
            reply,
            context=str(getattr(decision, "intent", "general") or "general"),
            gender="male" if "帅哥" in reply else "female",
        )

        print(f"  客服：{reply_with_emoji}")
        print(f"  [intent={decision.intent}  source={decision.reply_source}  llm={decision.llm_request_ms}ms]")

        if not reply:
            print(f"  ⚠️ 回复为空")
            errors += 1
            error_details.append(f"轮{i}: 回复为空")

        # 统计 emoji 添加情况
        if reply_with_emoji != reply:
            emoji_stats["with_emoji"] += 1
        else:
            emoji_stats["without_emoji"] += 1

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})

    print(f"\n{'='*70}")
    print(f"完成 25 轮对话，错误数：{errors}")
    print(f"最终历史长度：{len(history)} 条")
    print(f"Emoji 添加统计：{emoji_stats['with_emoji']} 条已添加，{emoji_stats['without_emoji']} 条未添加")

    if errors == 0:
        print("✅ 全部通过")
    else:
        print(f"❌ 有 {errors} 轮异常")
        for detail in error_details:
            print(f"  - {detail}")

    # 输出完整对话记录
    print(f"\n{'='*70}")
    print("完整对话记录（Markdown 格式）")
    print(f"{'='*70}\n")

    print("| 轮次 | 用户消息 | 客服回复（带 emoji） | 意图 | 来源 | LLM 耗时 |")
    print("|------|----------|---------------------|------|------|----------|")
    for i in range(0, len(history), 2):
        if i + 1 < len(history):
            user_msg = history[i]["content"]
            assistant_msg = history[i + 1]["content"]
            turn_num = i // 2 + 1
            print(f"| {turn_num:02d} | {user_msg} | {assistant_msg} | - | - | - |")

    return errors


if __name__ == "__main__":
    sys.exit(run())
