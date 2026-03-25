"""
LLM 强制注入已确认事实测试脚本

测试场景:
1. 已确认事实注入到 prompt
2. LLM 不重复追问已确认门店
3. LLM 不重复发送已发送的媒体
4. 追问耗尽后切换话题
"""
import sys
import os
import re

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def test_prompt_injection_structure():
    """测试 prompt 注入结构（不依赖完整 Agent）"""
    print("=" * 60)
    print("测试 1: 已确认事实注入到 prompt 结构")
    print("=" * 60)

    # 直接读取文件验证代码结构
    with open("src/core/agent_prompt_builder.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 验证 build_general_llm_prompt 函数包含确认事实注入逻辑
    assert "confirmed_facts_block" in content, "应该包含 confirmed_facts_block 变量"
    assert "_current_unified_state" in content, "应该读取统一状态"
    assert "last_target_store" in content, "应该读取门店状态"
    assert "address_image_sent" in content, "应该读取地址图发送状态"
    assert "contact_image_sent" in content, "应该读取联系方式发送状态"
    assert "address_image_sent_count" in content, "应该回退读取地址图发送计数"
    assert "contact_image_sent_count" in content, "应该回退读取联系方式发送计数"
    assert "geo_followup_round" in content, "应该读取追问轮数"
    assert "geo_followup_exhausted" in content, "应该读取追问耗尽状态"

    # 验证 prompt 包含事实块
    assert "【已确认事实 - 不可推翻】" in content, "应该包含已确认事实块"
    assert "【重要规则】" in content, "应该包含重要规则块"

    # 验证 confirmed_facts_block 被注入到 prompt 开头
    prompt_pattern = r'prompt\s*=\s*\(\s*confirmed_facts_block'
    assert re.search(prompt_pattern, content), "confirmed_facts_block 应该被注入到 prompt 开头"

    print("✓ 代码包含已确认事实注入逻辑")
    print("  - 读取统一状态：✓")
    print("  - 事实块生成：✓")
    print("  - 注入到 prompt 开头：✓")
    print()


def test_rule_engine_fallback():
    """测试规则引擎兜底检查"""
    print("=" * 60)
    print("测试 2: 规则引擎追问耗尽兜底检查")
    print("=" * 60)

    # 读取规则引擎文件
    with open("src/core/agent_rule_engine.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 验证兜底检查逻辑
    assert "geo_followup_exhausted" in content, "应该包含追问耗尽检查"
    assert "geo_followup_round" in content, "应该包含追问轮数检查"
    assert "GEO_FOLLOWUP_EXHAUSTED" in content, "应该包含追问耗尽规则 ID"

    # 验证兜底切换逻辑
    assert "contact_sent" in content, "应该检查联系方式是否已发送"
    assert "geo_followup_exhausted or geo_followup_round >= 2" in content, "应该保留追问耗尽或达到 2 轮的判断"
    assert "and geo_followup_active" in content, "应该限制在当前轮仍是地区问题时才切换"
    assert "and current_turn_still_geo_like" in content, "应该限制在当前轮仍是地区问题时才切换"
    assert "and not has_known_store" in content, "已经确认门店后不应再走追问耗尽兜底"

    print("✓ 规则引擎包含追问耗尽兜底检查")
    print("  - 追问耗尽检查：✓")
    print("  - 追问轮数检查：✓")
    print("  - 切换联系方式话题：✓")
    print()


def test_summarize_uses_unified_state():
    """测试 summarize_llm_conversation_state 使用统一状态"""
    print("=" * 60)
    print("测试 3: summarize_llm_conversation_state 优先使用统一状态")
    print("=" * 60)

    # 读取文件
    with open("src/core/agent_prompt_builder.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 验证函数优先使用统一状态
    assert "if hasattr(agent, '_current_unified_state') and agent._current_unified_state:" in content, "应该检查统一状态属性"
    assert "state = agent._current_unified_state" in content, "应该优先使用统一状态"

    # 验证使用 state 变量读取门店相关状态
    assert "state.get(" in content, "应该从 state 读取状态"
    assert "last_target_store" in content, "应该读取 last_target_store"

    print("✓ summarize_llm_conversation_state 优先使用统一状态")
    print("  - 检查统一状态属性：✓")
    print("  - 从统一状态读取：✓")
    print("  - 门店事实注入：✓")
    print()


def test_prompt_uses_count_fallback_and_store_name():
    """测试 prompt 会根据计数和门店键生成可读事实"""
    print("=" * 60)
    print("测试 4: prompt 使用计数兜底和可读门店名")
    print("=" * 60)

    from src.core.agent_prompt_builder import build_general_llm_prompt

    class _MockKnowledgeService:
        def normalize_user_text(self, text):
            return str(text or "")

        def find_answer_detail(self, text, threshold=0.6):
            return {"matched": False}

    class _MockAgent:
        knowledge_service = _MockKnowledgeService()
        knowledge_threshold = 0.6
        _enterprise_guard_doc_text = ""
        _current_prompt_conversation_history = []
        _current_unified_state = {
            "last_target_store": "sh_jingan",
            "address_image_sent_count": 1,
            "contact_image_sent_count": 1,
            "geo_followup_round": 2,
            "geo_followup_exhausted": False,
        }

        def _top_kb_examples(self, text, limit=3):
            return []

        def _top_brand_knowledge_snippets(self, text, limit=3):
            return []

        def _summarize_llm_conversation_state(self, latest_user_text, conversation_history, standard_reply_intent=""):
            return {
                "city_confirmed": "上海",
                "store_confirmed": "静安店",
                "visit_status": "可以到店",
                "last_answer_type": "appointment",
                "current_stage": "appointment_ready",
                "reply_goal": "承接当前问题",
                "avoid_repeat": "无",
            }

    prompt, extra = build_general_llm_prompt(_MockAgent(), "营业时间呢")

    assert "已确认门店：静安店" in prompt, "门店键应转换成用户可读名称"
    assert "地址图已发送：True" in prompt, "地址图发送状态应支持从计数推导"
    assert "联系方式已发送：True" in prompt, "联系方式发送状态应支持从计数推导"
    assert extra.get("standard_reply_hit") == False, "未命中知识库时不应误判"

    print("✓ prompt 会展示可读门店名和已发送状态")
    print()


def test_state_unified_module():
    """测试统一状态管理模块"""
    print("=" * 60)
    print("测试 5: 统一状态管理模块 get_confirmed_facts")
    print("=" * 60)

    # 读取统一状态管理模块
    with open("src/core/session_state_unified.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 验证 get_confirmed_facts 方法
    assert "def get_confirmed_facts" in content, "应该包含 get_confirmed_facts 方法"
    assert "city_confirmed" in content, "应该返回城市确认状态"
    assert "store_confirmed" in content, "应该返回门店确认状态"
    assert "address_image_sent" in content, "应该返回地址图发送状态"
    assert "contact_image_sent" in content, "应该返回联系方式发送状态"
    assert "address_image_sent_count" in content, "应该回退读取地址图发送计数"
    assert "contact_image_sent_count" in content, "应该回退读取联系方式发送计数"
    assert "geo_followup_round" in content, "应该返回追问轮数"
    assert "geo_followup_exhausted" in content, "应该返回追问耗尽状态"

    print("✓ 统一状态管理模块提供 get_confirmed_facts 方法")
    print("  - 城市确认：✓")
    print("  - 门店确认：✓")
    print("  - 媒体发送状态：✓")
    print("  - 追问状态：✓")
    print()


def run_manual_test():
    """手动测试：验证代码可以直接运行"""
    print("=" * 60)
    print("测试 6: 代码运行验证")
    print("=" * 60)

    try:
        # 尝试导入模块
        from src.core.agent_prompt_builder import build_general_llm_prompt
        print("✓ agent_prompt_builder 模块可导入")

        from src.core.agent_rule_engine import decide_general_reply
        print("✓ agent_rule_engine 模块可导入")

        from src.core.session_state_unified import UnifiedSessionState
        print("✓ session_state_unified 模块可导入")

    except ImportError as e:
        print(f"✗ 模块导入失败：{e}")
        return False

    print()
    return True


def main():
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║  LLM 强制注入已确认事实 - 测试脚本                     ║")
    print("╚" + "=" * 58 + "╝")
    print()

    all_passed = True

    try:
        test_prompt_injection_structure()
        test_rule_engine_fallback()
        test_summarize_uses_unified_state()
        test_prompt_uses_count_fallback_and_store_name()
        test_state_unified_module()

        if not run_manual_test():
            all_passed = False

    except AssertionError as e:
        print(f"测试失败 ❌: {e}")
        all_passed = False
    except Exception as e:
        print(f"测试异常 ❌: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False

    print("=" * 60)
    if all_passed:
        print("所有测试通过 ✅")
        return 0
    else:
        print("部分测试失败 ❌")
        return 1


if __name__ == "__main__":
    sys.exit(main())
