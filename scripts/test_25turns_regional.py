#!/usr/bin/env python3
"""
25 轮地区覆盖压力测试
覆盖江浙沪、京津冀、西北、西南、华南等地区，测试就近原则和远程定制话术
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


# ── 25 轮地区覆盖压力测试 ─────────────────────────────────────────────────────────
# 设计原则：覆盖不同地区，测试就近原则和远程定制话术
TURNS = [
    # 江浙沪地区 (1-6) - 测试推荐上海店
    "我在杭州，你们有店吗",
    "苏州离你们店近吗",
    "嘉善有门店吗",
    "宁波离你们哪里近",
    "我在无锡，怎么去你们店",
    "上海店地址发我一个最近的",

    # 京津冀 + 内蒙 (7-12) - 测试推荐北京店
    "天津有店吗",
    "河北保定离你们店远吗",
    "内蒙古呼和浩特有门店吗",
    "唐山有店不",
    "北京店具体地址是什么",
    "廊坊能到店吗",

    # 西北地区 (13-16) - 测试远程定制（新疆重点关注）
    "新疆乌鲁木齐有店吗",
    "甘肃兰州离你们店多远",
    "西安有门店吗",
    "青海西宁能到店吗",

    # 西南/华南/华中 (17-21) - 测试远程定制
    "四川成都有店吗",
    "广东深圳离你们近吗",
    "湖北武汉有门店吗",
    "湖南长沙怎么去你们店",
    "重庆有店吗",

    # 远程定制深入询问 (22-25)
    "远程定制怎么弄",
    "头围怎么量",
    "远程定制不满意能退吗",
    "那我先留个电话，13812345678，你们老师联系我教我怎么量",
]


def build_user_hash(user_name: str) -> str:
    return hashlib.sha256(user_name.encode()).hexdigest()[:16]


def build_agent() -> CustomerServiceAgent:
    base = Path("/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev")
    sim_dir = base / "data" / "test_25turns_regional"
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
    print("=" * 70)

    session_id = "test_25turns_regional_session"
    user_name = "测试用户王先生"
    history: List[Dict[str, str]] = []

    errors = 0
    error_details = []
    regional_stats = {
        "江浙沪": {"total": 0, "shanghai_recommended": 0},
        "京津冀内蒙": {"total": 0, "beijing_recommended": 0},
        "其他": {"total": 0, "remote_suggested": 0},
    }
    privacy_stats = {"phone_leaked": 0, "phone_protected": 0}

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
            error_details.append(f"轮{i}: 回复为空")

        # 统计地区推荐情况
        category, metric = categorize_turn(user_text, reply)
        if category:
            regional_stats[category]["total"] += 1
            if metric == "shanghai":
                regional_stats[category]["shanghai_recommended"] += 1
            elif metric == "beijing":
                regional_stats[category]["beijing_recommended"] += 1
            elif metric == "remote":
                regional_stats[category]["remote_suggested"] += 1

        # 统计隐私保护情况
        if "13812345678" in user_text:
            if "13812345678" in reply:
                privacy_stats["phone_leaked"] += 1
                print(f"  ⚠️ ⚠️ ⚠️ 隐私泄露：复述了用户手机号")
            else:
                privacy_stats["phone_protected"] += 1
                print(f"  ✅ 隐私保护正确：未复述手机号")

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})

    print(f"\n{'='*70}")
    print(f"完成 25 轮对话，错误数：{errors}")

    print(f"\n【地区推荐统计】")
    print(f"  江浙沪：{regional_stats['江浙沪']['shanghai_recommended']}/{regional_stats['江浙沪']['total']} 推荐上海")
    print(f"  京津冀内蒙：{regional_stats['京津冀内蒙']['beijing_recommended']}/{regional_stats['京津冀内蒙']['total']} 推荐北京")
    print(f"  其他地区：{regional_stats['其他']['remote_suggested']}/{regional_stats['其他']['total']} 推荐远程定制")

    print(f"\n【隐私保护统计】")
    print(f"  保护成功：{privacy_stats['phone_protected']} 次")
    print(f"  泄露失败：{privacy_stats['phone_leaked']} 次")

    if errors == 0:
        print("\n✅ 全部通过")
    else:
        print(f"\n❌ 有 {errors} 轮异常")
        for detail in error_details:
            print(f"  - {detail}")

    # 输出完整对话记录
    print(f"\n{'='*70}")
    print("完整对话记录（Markdown 格式）")
    print(f"{'='*70}\n")

    print("| 轮次 | 地区类型 | 用户消息 | 客服回复（带 emoji） | 推荐类型 |")
    print("|------|----------|----------|---------------------|----------|")
    for i in range(0, len(history), 2):
        if i + 1 < len(history):
            user_msg = history[i]["content"]
            assistant_msg = history[i + 1]["content"]
            turn_num = i // 2 + 1
            category, _ = categorize_turn(user_msg, assistant_msg)
            rec_type = get_recommendation_type(assistant_msg)
            print(f"| {turn_num:02d} | {category or '-'} | {user_msg} | {assistant_msg} | {rec_type} |")

    return errors


def categorize_turn(user_text: str, reply: str) -> tuple:
    """判断轮次属于哪个地区类别，以及推荐了什么"""
    # 江浙沪
    if any(city in user_text for city in ["杭州", "苏州", "嘉善", "宁波", "无锡", "上海", "南京"]):
        if "上海" in reply and ("近" in reply or "推荐" in reply or "高铁" in reply):
            return ("江浙沪", "shanghai")
        return ("江浙沪", None)

    # 京津冀 + 内蒙
    if any(city in user_text for city in ["天津", "河北", "保定", "内蒙古", "呼和浩特", "唐山", "北京", "廊坊"]):
        if "北京" in reply and ("近" in reply or "推荐" in reply or "朝阳" in reply):
            return ("京津冀内蒙", "beijing")
        return ("京津冀内蒙", None)

    # 其他地区
    if any(city in user_text for city in ["新疆", "乌鲁木齐", "甘肃", "兰州", "西安", "青海", "西宁",
                                           "四川", "成都", "广东", "深圳", "湖北", "武汉", "湖南", "长沙",
                                           "重庆", "宁夏", "广西"]):
        if "远程" in reply or "定制" in reply or "邮寄" in reply:
            return ("其他", "remote")
        return ("其他", None)

    return (None, None)


def get_recommendation_type(reply: str) -> str:
    """判断回复类型"""
    if "上海" in reply and ("近" in reply or "推荐" in reply):
        return "上海店"
    elif "北京" in reply and ("近" in reply or "推荐" in reply):
        return "北京店"
    elif "远程" in reply or "定制" in reply:
        return "远程定制"
    elif "地址" in reply:
        return "地址"
    else:
        return "-"


if __name__ == "__main__":
    sys.exit(run())
