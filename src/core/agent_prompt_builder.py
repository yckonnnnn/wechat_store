"""
LLM-First Prompt 构建器（Phase 1 极简版）

职责：
  - 生成系统提示词（品牌人设 + 知识库参考）
  - 对话历史清洗（过滤空消息、确保 role 合法）
"""

from __future__ import annotations

from typing import Dict, List


# ── 系统提示词 ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT_BASE = """\
你是艾耐儿假发品牌的专属顾问，请注意以下几点：

1. 客户画像：主要是 50-70 岁的女性，要有耐心，默认称呼"姐姐"（若对方明确为男性则改称"帅哥"）。
2. 回复风格：结论导向，简洁自然，30-50 字为宜。
3. Emoji：每条回复结尾带 2-3 个随机 emoji，每次组合要有变化，不要每次都一样。
4. 上下文连贯：基于完整对话历史来回答。如果用户是在追问或确认上一条内容（例如"地址是这个吗"），\
简短回应即可，不要重复完整的标准答案。
5. 知识库参考：如果系统提供了参考内容，请结合上下文自然融入，不要生硬照搬原文。\
"""


def build_system_prompt(kb_context: str = "") -> str:
    """
    组装系统提示词。

    如果有知识库检索结果，将其追加到提示词末尾供 LLM 参考；否则直接返回基础提示词。
    """
    if not kb_context:
        return SYSTEM_PROMPT_BASE

    return (
        f"{SYSTEM_PROMPT_BASE}\n\n"
        "---\n"
        "## 知识库参考（根据上下文自行判断是否采用，不要生硬照搬）：\n"
        f"{kb_context}"
    )


def build_conversation_messages(
    conversation_history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """
    对 message_processor 传入的对话历史做安全过滤，返回可直接传给 LLMService 的列表。

    message_processor_support.convert_history() 已经把末尾用户消息去掉了，
    所以这里只做防御性清洗（过滤空内容、确保 role 合法）。
    """
    result: List[Dict[str, str]] = []
    for msg in (conversation_history or []):
        role = str(msg.get("role", "") or "").strip()
        content = str(msg.get("content", "") or "").strip()
        if role in {"user", "assistant"} and content:
            result.append({"role": role, "content": content})
    return result
