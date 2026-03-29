"""
Emoji 工具模块

为回复文本随机添加 emoji 表情
"""

import random


# ── Emoji 池 ──────────────────────────────────────────────────────────────

# 温馨/友好类 emoji
EMOJI_WARM = [
    "💗", "💖", "💕", "💞", "💓", "💝", "💟", "💘",
    "🌹", "🌷", "🌸", "🌺", "🌻", "🌼", "💐",
    "✨", "⭐", "🌟", "💫", "🌙", "☀️", "🌈",
    "😊", "😄", "😃", "😁", "😆", "😍", "🥰", "😘",
    "👍", "👌", "🤝", "🙏", "💪",
]

# 女性向 emoji（针对 50-70 岁女性客户）
EMOJI_FEMALE = [
    "💗", "💖", "💕", "🌹", "🌷", "🌸", "🌺", "🌻",
    "💐", "✨", "🌟", "💫", "🥰", "😊", "😍",
]

# 男性向 emoji（针对男性客户）
EMOJI_MALE = [
    "💪", "👍", "🤝", "✨", "⭐", "🌟", "💫", "😊", "😄", "👌",
]

# 地址/位置相关 emoji
EMOJI_ADDRESS = ["📍", "🗺️", "🚇", "🚗", "🏢", "🏪", "📍", "📌"]

# 价格/金钱相关 emoji
EMOJI_PRICE = ["💰", "💵", "💎", "✨", "⭐", "🌟"]

# 预约/时间相关 emoji
EMOJI_APPOINTMENT = ["📅", "🕐", "⏰", "📆", "🗓️", "✨"]

# 售后/服务相关 emoji
EMOJI_SERVICE = ["🤝", "💖", "✨", "👍", "🌟", "💫", "🙏"]


# ── 工具函数 ──────────────────────────────────────────────────────────────

def add_random_emoji(text: str, context: str = "general", gender: str = "female") -> str:
    """
    为文本随机添加 2-3 个 emoji 表情。

    Args:
        text: 原始文本
        context: 上下文类型（general/address/price/appointment/service）
        gender: 客户性别（female/male）

    Returns:
        添加 emoji 后的文本
    """
    if not text or not isinstance(text, str):
        return text or ""

    # 如果文本已经有 emoji，不再添加
    if _has_emoji(text):
        return text

    # 基础 emoji 池（根据性别选择）
    if gender == "male":
        base_pool = EMOJI_MALE
    else:
        base_pool = EMOJI_FEMALE

    # 根据上下文添加特定 emoji
    context_pool = _get_context_pool(context)

    # 合并 emoji 池
    combined_pool = list(set(base_pool + context_pool))

    # 随机选择 2-3 个 emoji
    count = random.randint(2, 3)
    selected = random.sample(combined_pool, min(count, len(combined_pool)))

    # 随机打乱顺序
    random.shuffle(selected)

    # 添加到文本末尾
    return text + "".join(selected)


def _has_emoji(text: str) -> bool:
    """检查文本是否已包含 emoji"""
    emoji_ranges = [
        (0x1F300, 0x1F9FF),  # Miscellaneous Symbols and Pictographs + Emoticons
        (0x2600, 0x26FF),    # Miscellaneous Symbols
        (0x2700, 0x27BF),    # Dingbats
        (0x1F600, 0x1F64F),  # Emoticons
        (0x1F680, 0x1F6FF),  # Transport and Map Symbols
    ]
    for char in text:
        code = ord(char)
        for start, end in emoji_ranges:
            if start <= code <= end:
                return True
    return False


def _get_context_pool(context: str) -> list:
    """根据上下文返回特定 emoji 池"""
    pools = {
        "address": EMOJI_ADDRESS,
        "price": EMOJI_PRICE,
        "appointment": EMOJI_APPOINTMENT,
        "service": EMOJI_SERVICE,
        "shipping": EMOJI_ADDRESS,
        "general": [],
    }
    return pools.get(context, [])
