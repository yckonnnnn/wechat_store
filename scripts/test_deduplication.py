"""
去重检查机制测试脚本

测试场景：
1. 媒体发送去重（地址图、联系方式）
2. 回复内容去重
3. 追问轮数限制
4. 时间冷却
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.deduplication import DeduplicationChecker
from src.data.memory_store import MemoryStore


def create_mock_memory_store():
    """创建模拟 MemoryStore"""
    return MemoryStore(Path("config") / "agent_memory.json")


def test_media_sent_dedup():
    """测试媒体发送去重"""
    print("=" * 60)
    print("测试 1: 媒体发送去重")
    print("=" * 60)

    memory_store = create_mock_memory_store()
    checker = DeduplicationChecker(memory_store)

    session_id = "test_dedup_001"
    user_hash = "test_user"

    # 测试联系方式去重
    # 设置已发送联系方式
    memory_store.update_session_state(session_id, {
        "contact_image_sent_count": 1,
        "contact_image_sent_paths": ["contact.png"],
    }, user_hash)

    result = checker.check_media_sent(session_id, user_hash, "contact_image")
    print(f"联系方式已发送后检查：{result}")
    assert result == True, "联系方式已发送应返回 True"

    # 测试地址图去重（同一门店）
    memory_store.update_session_state(session_id, {
        "address_image_sent_count": 1,
        "last_target_store": "beijing_chaoyang",
    }, user_hash)

    result = checker.check_media_sent(session_id, user_hash, "address_image", "beijing_chaoyang")
    print(f"同一门店地址图已发送后检查：{result}")
    assert result == True, "同一门店地址图已发送应返回 True"

    # 测试地址图去重（不同门店）
    result = checker.check_media_sent(session_id, user_hash, "address_image", "sh_jingan")
    print(f"不同门店地址图检查：{result}")
    assert result == False, "不同门店地址图应允许发送"

    # 测试未发送情况
    memory_store.update_session_state(session_id, {
        "address_image_sent_count": 0,
        "contact_image_sent_count": 0,
    }, user_hash)

    result = checker.check_media_sent(session_id, user_hash, "address_image")
    print(f"地址图未发送检查：{result}")
    assert result == False, "地址图未发送应返回 False"

    result = checker.check_media_sent(session_id, user_hash, "contact_image")
    print(f"联系方式未发送检查：{result}")
    assert result == False, "联系方式未发送应返回 False"

    print("✅ 测试通过：媒体发送去重正确")
    print()


def test_reply_content_dedup():
    """测试回复内容去重"""
    print("=" * 60)
    print("测试 2: 回复内容去重")
    print("=" * 60)

    memory_store = create_mock_memory_store()
    checker = DeduplicationChecker(memory_store)

    session_id = "test_dedup_002"
    user_hash = "test_user"

    content = "姐姐，地址位置图已经发了，您往上滑看一下哦～♥️"

    # 第一次检查（未发送过）
    result = checker.check_reply_sent(session_id, user_hash, content, window_seconds=600)
    print(f"首次回复检查：{result}")
    assert result == False, "首次回复应返回 False"

    # 第二次检查（同一内容在时间窗口内）
    result = checker.check_reply_sent(session_id, user_hash, content, window_seconds=600)
    print(f"同一内容重复检查：{result}")
    assert result == True, "同一内容在时间窗口内应返回 True"

    # 测试不同内容
    different_content = "姐姐，联系方式已经发了，您往上滑看一下哦～♥️"
    result = checker.check_reply_sent(session_id, user_hash, different_content, window_seconds=600)
    print(f"不同内容检查：{result}")
    assert result == False, "不同内容应返回 False"

    print("✅ 测试通过：回复内容去重正确")
    print()


def test_followup_round_limit():
    """测试追问轮数限制"""
    print("=" * 60)
    print("测试 3: 追问轮数限制")
    print("=" * 60)

    memory_store = create_mock_memory_store()
    checker = DeduplicationChecker(memory_store)

    session_id = "test_dedup_003"
    user_hash = "test_user"

    # 测试未达到限制
    memory_store.update_session_state(session_id, {
        "geo_followup_round": 1,
    }, user_hash)

    result = checker.check_followup_round(session_id, user_hash, "geo", max_rounds=2)
    print(f"追问 1 轮后检查（max=2）：{result}")
    assert result == False, "追问 1 轮未达到限制应返回 False"

    # 测试达到限制
    memory_store.update_session_state(session_id, {
        "geo_followup_round": 2,
    }, user_hash)

    result = checker.check_followup_round(session_id, user_hash, "geo", max_rounds=2)
    print(f"追问 2 轮后检查（max=2）：{result}")
    assert result == True, "追问 2 轮达到限制应返回 True"

    # 测试超过限制
    memory_store.update_session_state(session_id, {
        "geo_followup_round": 3,
    }, user_hash)

    result = checker.check_followup_round(session_id, user_hash, "geo", max_rounds=2)
    print(f"追问 3 轮后检查（max=2）：{result}")
    assert result == True, "追问 3 轮超过限制应返回 True"

    print("✅ 测试通过：追问轮数限制正确")
    print()


def test_time_cooldown():
    """测试时间冷却"""
    print("=" * 60)
    print("测试 4: 时间冷却")
    print("=" * 60)

    memory_store = create_mock_memory_store()
    checker = DeduplicationChecker(memory_store)

    session_id = "test_dedup_004"
    user_hash = "test_user"
    event_type = "contact_prompt"

    # 测试没有记录
    result = checker.check_time_cooldown(session_id, user_hash, event_type)
    print(f"无记录时冷却检查：{result}")
    assert result == False, "无记录应返回 False"

    # 设置 2 分钟前的记录
    two_min_ago = (datetime.now() - timedelta(minutes=2)).isoformat()
    memory_store.update_session_state(session_id, {f"last_{event_type}_time": two_min_ago}, user_hash)

    # 测试 5 分钟冷却时间（2 分钟前在冷却内）
    result = checker.check_time_cooldown(session_id, user_hash, event_type, cooldown_seconds=300)
    print(f"2 分钟前记录，5 分钟冷却：{result}")
    assert result == True, "在冷却时间内应返回 True"

    # 测试 1 分钟冷却时间（2 分钟前已过期）
    result = checker.check_time_cooldown(session_id, user_hash, event_type, cooldown_seconds=60)
    print(f"2 分钟前记录，1 分钟冷却：{result}")
    assert result == False, "冷却时间已过应返回 False"

    print("✅ 测试通过：时间冷却正确")
    print()


def test_increment_followup_round():
    """测试增加追问轮数"""
    print("=" * 60)
    print("测试 5: 增加追问轮数")
    print("=" * 60)

    memory_store = create_mock_memory_store()
    checker = DeduplicationChecker(memory_store)

    session_id = "test_dedup_005"
    user_hash = "test_user"

    # 初始为 0
    memory_store.update_session_state(session_id, {
        "geo_followup_round": 0,
    }, user_hash)

    # 增加一轮
    result = checker.increment_followup_round(session_id, user_hash, "geo")
    print(f"第一次增加追问轮数：{result}")
    assert result == 1, "第一次增加应返回 1"

    # 再增加一轮
    result = checker.increment_followup_round(session_id, user_hash, "geo")
    print(f"第二次增加追问轮数：{result}")
    assert result == 2, "第二次增加应返回 2"

    print("✅ 测试通过：增加追问轮数正确")
    print()


def main():
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║  去重检查机制测试脚本                                   ║")
    print("╚" + "=" * 58 + "╝")
    print()

    all_passed = True

    try:
        test_media_sent_dedup()
        test_reply_content_dedup()
        test_followup_round_limit()
        test_time_cooldown()
        test_increment_followup_round()

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
