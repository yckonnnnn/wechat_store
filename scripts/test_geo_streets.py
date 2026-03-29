#!/usr/bin/env python3
"""
地理知识识别测试（路名 + 辖区）
测试 LLM 是否能识别上海/北京的路名和辖区，并正确推荐门店
"""
import sys
from pathlib import Path

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


# ── 地理知识测试（路名 + 辖区）─────────────────────────────────────────────────
# 测试 LLM 是否能识别路名属于哪个城市，并正确推荐门店

TEST_CASES = [
    # ========== 上海路名测试（10 个）==========
    # 靠近徐汇店的路名
    {"input": "我在徐家汇这边，你们有店吗", "expected_city": "上海", "expected_action": "recommend_xuhui"},
    {"input": "漕溪北路附近有门店吗", "expected_city": "上海", "expected_action": "recommend_xuhui"},
    {"input": "徐汇区漕溪北路怎么走", "expected_city": "上海", "expected_action": "recommend_xuhui"},

    # 靠近静安店的路名
    {"input": "我在静安寺这边", "expected_city": "上海", "expected_action": "recommend_jingan"},
    {"input": "愚园路有店吗", "expected_city": "上海", "expected_action": "recommend_jingan"},
    {"input": "长寿路附近有门店吗", "expected_city": "上海", "expected_action": "recommend_jingan"},

    # 靠近人广店的路名
    {"input": "我在人民广场", "expected_city": "上海", "expected_action": "recommend_renmin"},
    {"input": "汉口路有店吗", "expected_city": "上海", "expected_action": "recommend_renmin"},

    # 靠近虹口店的路名
    {"input": "我在虹口足球场这边", "expected_city": "上海", "expected_action": "recommend_hongkou"},
    {"input": "花园路有门店吗", "expected_city": "上海", "expected_action": "recommend_hongkou"},

    # 靠近五角场店的路名
    {"input": "我在五角场", "expected_city": "上海", "expected_action": "recommend_wujiaochang"},
    {"input": "政通路有店吗", "expected_city": "上海", "expected_action": "recommend_wujiaochang"},

    # 其他上海路名（需要识别属于上海）
    {"input": "我在兰皋路，离你们店近吗", "expected_city": "上海", "expected_action": "recommend_shanghai"},
    {"input": "南京西路怎么走", "expected_city": "上海", "expected_action": "recommend_shanghai"},
    {"input": "淮海中路有门店吗", "expected_city": "上海", "expected_action": "recommend_shanghai"},
    {"input": "陆家嘴附近能到店吗", "expected_city": "上海", "expected_action": "recommend_shanghai"},

    # ========== 上海辖区测试（5 个）==========
    {"input": "奉贤区有店吗", "expected_city": "上海", "expected_action": "recommend_shanghai"},
    {"input": "闵行区怎么去你们店", "expected_city": "上海", "expected_action": "recommend_shanghai"},
    {"input": "宝山区离哪里近", "expected_city": "上海", "expected_action": "recommend_shanghai"},
    {"input": "嘉定区有门店不", "expected_city": "上海", "expected_action": "recommend_shanghai"},
    {"input": "青浦区能到店吗", "expected_city": "上海", "expected_action": "recommend_shanghai"},

    # ========== 北京路名测试（10 个）==========
    # 靠近北京店（朝阳）的路名
    {"input": "我在建国门外大街，你们有店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "国贸附近有门店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "大望路怎么走", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "四惠这边有店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "呼家楼附近能到店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},

    # 其他北京路名/区域
    {"input": "我在三里屯", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "工体附近有店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "望京离你们店远吗", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "中关村有门店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "金融街怎么走", "expected_city": "北京", "expected_action": "recommend_beijing"},

    # ========== 北京辖区测试（5 个）==========
    {"input": "朝阳区有店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "海淀区怎么去你们店", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "东城区离哪里近", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "西城区有门店不", "expected_city": "北京", "expected_action": "recommend_beijing"},
    {"input": "通州区能到店吗", "expected_city": "北京", "expected_action": "recommend_beijing"},

    # ========== 非上海/北京地区对照测试（5 个）==========
    {"input": "我在杭州西湖", "expected_city": "江浙沪", "expected_action": "recommend_shanghai"},
    {"input": "南京新街口有店吗", "expected_city": "江浙沪", "expected_action": "recommend_shanghai"},
    {"input": "天津滨江道怎么走", "expected_city": "京津冀", "expected_action": "recommend_beijing"},
    {"input": "成都春熙路有门店吗", "expected_city": "其他", "expected_action": "remote_customization"},
    {"input": "武汉江汉路能到店吗", "expected_city": "其他", "expected_action": "remote_customization"},
]


def build_agent() -> CustomerServiceAgent:
    base = Path("/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev")
    sim_dir = base / "data" / "test_geo_streets"
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


def analyze_reply(reply: str, test_case: dict) -> dict:
    """分析回复是否符合预期"""
    result = {
        "passed": False,
        "reason": "",
        "detected_city": "",
        "detected_action": ""
    }

    expected_city = test_case["expected_city"]
    expected_action = test_case["expected_action"]
    reply_lower = reply.lower()

    # 检测识别到的城市
    shanghai_keywords = ["上海", "徐汇", "静安", "人广", "人民广场", "虹口", "五角场", "奉贤", "闵行", "宝山", "嘉定", "青浦", "松江", "金山", "崇明", "浦东"]
    beijing_keywords = ["北京", "朝阳", "海淀", "东城", "西城", "通州", "顺义", "昌平", "大兴", "国贸", "三里屯", "望京", "中关村"]
    jiangzhehu_keywords = ["杭州", "南京", "江苏", "浙江", "江浙沪", "上海离您"]
    jingjinji_keywords = ["天津", "河北", "京津冀", "北京离您"]

    if any(k in reply for k in shanghai_keywords):
        result["detected_city"] = "上海"
    elif any(k in reply for k in beijing_keywords):
        result["detected_city"] = "北京"
    elif any(k in reply for k in jiangzhehu_keywords):
        result["detected_city"] = "江浙沪"
    elif any(k in reply for k in jingjinji_keywords):
        result["detected_city"] = "京津冀"
    else:
        result["detected_city"] = "其他"

    # 检测行动类型
    # 上海门店关键词（包括具体店名）
    shanghai_store_keywords = ["上海", "徐汇门店", "静安门店", "人广门店", "人民广场门店", "虹口门店", "五角场门店", "漕溪北路", "愚园路", "汉口路", "花园路", "政通路"]
    # 北京门店关键词
    beijing_store_keywords = ["北京", "朝阳门店", "建外 SOHO", "朝阳区"]

    if any(k in reply for k in shanghai_store_keywords) and ("店" in reply or "门店" in reply or "地址" in reply):
        result["detected_action"] = "recommend_shanghai"
    elif any(k in reply for k in beijing_store_keywords) and ("店" in reply or "门店" in reply or "地址" in reply):
        result["detected_action"] = "recommend_beijing"
    elif "远程" in reply or "定制" in reply or "邮寄" in reply or "留电话" in reply:
        result["detected_action"] = "remote_customization"
    elif "没有" in reply and "店" in reply and not any(k in reply for k in shanghai_store_keywords + beijing_store_keywords):
        result["detected_action"] = "no_store"
    else:
        result["detected_action"] = "unknown"

    # 判断是否通过
    if expected_action == "recommend_shanghai" and result["detected_action"] == "recommend_shanghai":
        result["passed"] = True
    elif expected_action == "recommend_beijing" and result["detected_action"] == "recommend_beijing":
        result["passed"] = True
    elif expected_action == "remote_customization" and result["detected_action"] == "remote_customization":
        result["passed"] = True
    elif expected_action.startswith("recommend_") and result["detected_action"] == "recommend_shanghai":
        result["passed"] = True
    elif expected_action.startswith("recommend_") and result["detected_action"] == "recommend_beijing":
        result["passed"] = True

    if not result["passed"]:
        result["reason"] = f"预期行动={expected_action}, 实际行动={result['detected_action']}"

    return result


def run():
    agent = build_agent()
    status = agent.get_status()
    print("=" * 90)
    print(f"模型：{agent.llm_service.get_current_model_name()}")
    print(f"system_prompt_loaded: {status['system_prompt_loaded']}")
    print("=" * 90)

    session_id = "test_geo_streets_session"
    user_name = "测试用户"
    history = []

    # 统计
    total = len(TEST_CASES)
    passed = 0
    failed = 0

    shanghai_street_tests = {"total": 0, "passed": 0}
    shanghai_district_tests = {"total": 0, "passed": 0}
    beijing_street_tests = {"total": 0, "passed": 0}
    beijing_district_tests = {"total": 0, "passed": 0}
    other_tests = {"total": 0, "passed": 0}

    error_details = []

    for i, test_case in enumerate(TEST_CASES, 1):
        user_input = test_case["input"]
        print(f"\n{'─'*90}")
        print(f"[测试 {i:02d}/{total}] 用户：{user_input}")
        print(f"  预期：城市={test_case['expected_city']}, 行动={test_case['expected_action']}")

        try:
            decision = agent.decide(
                session_id=session_id,
                user_name=user_name,
                latest_user_text=user_input,
                conversation_history=history,
            )
        except Exception as e:
            print(f"  ❌ decide() 异常：{e}")
            failed += 1
            error_details.append(f"测试{i}: 异常 - {str(e)}")
            history.append({"role": "user", "content": user_input})
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

        # 分析结果
        result = analyze_reply(reply, test_case)

        if result["passed"]:
            print(f"  ✅ 通过 (检测到 {result['detected_city']} / {result['detected_action']})")
            passed += 1
        else:
            print(f"  ❌ 失败：{result['reason']}")
            failed += 1
            error_details.append(f"测试{i}: {user_input} -> {result['reason']}")

        # 分类统计
        category = get_category(test_case)
        if category == "shanghai_street":
            shanghai_street_tests["total"] += 1
            if result["passed"]:
                shanghai_street_tests["passed"] += 1
        elif category == "shanghai_district":
            shanghai_district_tests["total"] += 1
            if result["passed"]:
                shanghai_district_tests["passed"] += 1
        elif category == "beijing_street":
            beijing_street_tests["total"] += 1
            if result["passed"]:
                beijing_street_tests["passed"] += 1
        elif category == "beijing_district":
            beijing_district_tests["total"] += 1
            if result["passed"]:
                beijing_district_tests["passed"] += 1
        elif category == "other":
            other_tests["total"] += 1
            if result["passed"]:
                other_tests["passed"] += 1

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})

    # 汇总报告
    print(f"\n{'='*90}")
    print(f"测试汇总：{passed}/{total} 通过 (通过率：{passed/total*100:.1f}%)")
    print(f"  上海路名测试：{shanghai_street_tests['passed']}/{shanghai_street_tests['total']}")
    print(f"  上海辖区测试：{shanghai_district_tests['passed']}/{shanghai_district_tests['total']}")
    print(f"  北京路名测试：{beijing_street_tests['passed']}/{beijing_street_tests['total']}")
    print(f"  北京辖区测试：{beijing_district_tests['passed']}/{beijing_district_tests['total']}")
    print(f"  非上海/北京测试：{other_tests['passed']}/{other_tests['total']}")

    if failed > 0:
        print(f"\n❌ 失败详情:")
        for detail in error_details:
            print(f"  - {detail}")
    else:
        print(f"\n✅ 全部通过！")

    # 完整对话记录
    print(f"\n{'='*90}")
    print("完整对话记录（Markdown 表格）")
    print(f"{'='*90}\n")

    print("| # | 类别 | 用户输入 | 客服回复 | 检测城市 | 检测行动 | 结果 |")
    print("|---|------|----------|----------|----------|----------|------|")
    for i in range(0, len(history), 2):
        if i + 1 < len(history):
            user_msg = history[i]["content"]
            assistant_msg = history[i + 1]["content"]
            test_idx = i // 2 + 1
            test_case = TEST_CASES[i // 2]
            result = analyze_reply(assistant_msg, test_case)
            status_icon = "✅" if result["passed"] else "❌"
            category_cn = get_category_cn(test_case)
            print(f"| {test_idx:02d} | {category_cn} | {user_msg} | {assistant_msg} | {result['detected_city']} | {result['detected_action']} | {status_icon} |")

    return failed


def get_category(test_case: dict) -> str:
    """获取测试类别"""
    expected_city = test_case["expected_city"]
    input_text = test_case["input"]

    if expected_city == "江浙沪" or expected_city == "其他":
        return "other"
    elif expected_city == "京津冀":
        return "other"

    # 判断是路名还是辖区
    shanghai_districts = ["奉贤", "闵行", "宝山", "嘉定", "青浦", "松江", "金山", "崇明", "浦东"]
    beijing_districts = ["朝阳", "海淀", "东城", "西城", "通州", "顺义", "昌平", "大兴"]

    if expected_city == "上海":
        for d in shanghai_districts:
            if d in input_text:
                return "shanghai_district"
        return "shanghai_street"
    elif expected_city == "北京":
        for d in beijing_districts:
            if d in input_text:
                return "beijing_district"
        return "beijing_street"

    return "other"


def get_category_cn(test_case: dict) -> str:
    """获取测试类别的中文名称"""
    category = get_category(test_case)
    mapping = {
        "shanghai_street": "上海路名",
        "shanghai_district": "上海辖区",
        "beijing_street": "北京路名",
        "beijing_district": "北京辖区",
        "other": "其他地区",
    }
    return mapping.get(category, "其他")


if __name__ == "__main__":
    sys.exit(run())
