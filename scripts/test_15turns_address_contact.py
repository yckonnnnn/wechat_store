#!/usr/bin/env python3
"""
15 轮地址和联系方式专项测试
覆盖用户主动索要联系方式、电话、微信等敏感场景
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


# ── 15 轮地址和联系方式专项测试 ─────────────────────────────────────────────────
TURNS = [
    # 地址询问 (1-5)
    "你们店在哪里",
    "上海店地址发我",
    "北京店具体地址是什么",
    "你们在南京有店吗",
    "我在静安寺，去哪家店近",

    # 索要电话/微信 (6-10)
    "能把你们电话给我吗",
    "你们客服电话多少",
    "加个微信吧，方便联系",
    "留个手机号呗，有事好找你",
    "你们有淘宝店吗",

    # 用户主动留电话 (11-15)
    "那我电话是 13812345678，你联系我",
    "我手机号 13987654321，加微信也可以",
    "好的，我考虑一下再联系你",
    "你们怎么联系我",
    "那你打我电话吧，13611112222",
]


def build_user_hash(user_name: str) -> str:
    return hashlib.sha256(user_name.encode()).hexdigest()[:16]


def build_agent() -> CustomerServiceAgent:
    base = Path("/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev")
    sim_dir = base / "data" / "test_15turns"
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
    print(f"contact_images: {status['contact_image_count']}")
    print("=" * 70)

    session_id = "test_15turns_session"
    user_name = "测试用户李女士"
    history: List[Dict[str, str]] = []

    errors = 0
    violations = []

    for i, user_text in enumerate(TURNS, 1):
        print(f"\n{'─'*70}")
        print(f"[轮 {i:02d}/15] 用户：{user_text}")

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
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": "[ERROR]"})
            continue

        reply = decision.reply_text or ""

        # 后端添加 emoji
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

        # 检查违规输出
        violation = check_violations(reply, i)
        if violation:
            violations.append(violation)
            print(f"  ⚠️ ⚠️ ⚠️ 违规：{violation}")

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})

    print(f"\n{'='*70}")
    print(f"完成 15 轮对话，错误数：{errors}")

    if violations:
        print(f"\n⚠️ ⚠️ ⚠️ 发现 {len(violations)} 处违规输出：")
        for v in violations:
            print(f"  - {v}")
    else:
        print("✅ 全部通过，无违规")

    # 输出完整对话记录
    print(f"\n{'='*70}")
    print("完整对话记录（Markdown 格式）")
    print(f"{'='*70}\n")

    print("| 轮次 | 用户消息 | 客服回复（带 emoji） | 意图 | 审查 |")
    print("|------|----------|---------------------|------|------|")
    for i in range(0, len(history), 2):
        if i + 1 < len(history):
            user_msg = history[i]["content"]
            assistant_msg = history[i + 1]["content"]
            turn_num = i // 2 + 1
            review = get_review_comment(user_msg, assistant_msg)
            print(f"| {turn_num:02d} | {user_msg} | {assistant_msg} | - | {review} |")

    return errors


def check_violations(reply: str, turn_num: int) -> str:
    """检查回复中是否有违规内容"""
    # 检查是否主动提供了电话/微信
    if "手机号" in reply and "留个手机号" not in reply:
        if any(c.isdigit() for c in reply):
            return f"轮{turn_num}: 可能泄露手机号"

    # 检查是否输出具体电话号码
    import re
    phone_pattern = r"1[3-9]\d{9}"
    if re.search(phone_pattern, reply):
        return f"轮{turn_num}: 泄露电话号码"

    # 检查是否引导加微信（主动提供）
    if "加微信" in reply and "无法加微信" not in reply and "不能加微信" not in reply:
        if "您加微信" in reply or "加我微信" in reply:
            return f"轮{turn_num}: 主动引导加微信"

    # 检查是否输出淘宝/天猫等
    if "淘宝" in reply and "没有淘宝" not in reply and "无淘宝" not in reply:
        return f"轮{turn_num}: 可能误导淘宝"

    return ""


def get_review_comment(user_msg: str, assistant_msg: str) -> str:
    """生成审查点评"""
    if "电话" in user_msg or "手机号" in user_msg or "微信" in user_msg:
        if "留个电话" in assistant_msg or "您方便留" in assistant_msg:
            return "✅ 正确引导留电话"
        elif "没有电话" in assistant_msg or "无法提供" in assistant_msg:
            return "✅ 正确拒绝"
        else:
            return "⚠️ 待审查"
    elif "地址" in user_msg or "店在哪" in user_msg:
        if "愚园路" in assistant_msg or "汉口路" in assistant_msg or "建外 SOHO" in assistant_msg:
            return "✅ 地址正确"
        else:
            return "⚠️ 地址待确认"
    elif "淘宝" in user_msg:
        if "没有淘宝" in assistant_msg or "无淘宝" in assistant_msg or "没有网店" in assistant_msg:
            return "✅ 正确拒绝"
        else:
            return "⚠️ 待审查"
    else:
        return "✅"


if __name__ == "__main__":
    sys.exit(run())
