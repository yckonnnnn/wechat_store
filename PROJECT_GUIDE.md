# 微信小店 AI 客服系统 - 项目指南

> **当前版本**: v1.8.5 (LLM-first 架构)
> **最后更新**: 2026-03-29
> **技术栈**: Python 3.13 + PySide6 + QWebEngine + 大语言模型

---

## 一、项目概述

### 1.1 产品定位

这是一个运行在桌面的 AI 客服系统，专门为**微信小店**设计。系统通过内嵌浏览器加载微信小店客服后台，自动检测未读消息、抓取对话内容、调用大语言模型生成回复并自动发送。

**核心价值**：
- 🤖 **自动回复**：识别用户意图，调用 LLM 或知识库生成自然回复
- 📍 **智能发图**：根据对话内容自动发送地址图/联系方式图
- 🧠 **会话记忆**：跨重启持久化，记住用户已确认的门店、城市、已发媒体
- 🔀 **多模型支持**：ChatGPT、Gemini、阿里千问、DeepSeek、豆包、Kimi

### 1.2 核心主链路

```
┌──────────────────────────────────────────────────────────────────┐
│                         自动回复主流程                            │
└──────────────────────────────────────────────────────────────────┘

  ┌─────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │  定时器  │───>│  扫描未读    │───>│  点击进入    │───>│  抓取消息    │
  │ (4 秒)   │    │  消息       │    │  会话       │    │  记录       │
  └─────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                              │
  ┌─────────┐    ┌─────────────┐    ┌─────────────┐          │
  │  发送   │<───│  注入 JS     │<───│  Agent       │<─────────┘
  │  回复   │    │  发送消息   │    │  决策       │
  └─────────┘    └─────────────┘    └─────────────┘
```

---

## 二、系统架构图

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        表现层 (UI)                               │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ MainWindow │ │ BrowserTab │ │KnowledgeTab│ │ModelConfigTab│ │
│  │ 主窗口     │ │ 浏览器标签 │ │ 知识库管理 │ │ 模型配置     │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                        业务逻辑层 (Core)                         │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │MessageProc │ │PrivateCS   │ │ LLMDecision│ │SystemPrompt  │ │
│  │ 消息编排器 │ │Agent 决策   │ │Engine 决策  │ │Builder 提示词│ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │AgentMedia  │ │AgentRule   │ │SessionState│ │MemoryStore   │ │
│  │ 媒体决策   │ │Engine 规则  │ │Unified 状态│ │ 记忆存储     │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                        服务层 (Services)                         │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │LLMService  │ │BrowserSvc  │ │KnowledgeSvc│ │Conversation  │ │
│  │LLM API 调用 │ │浏览器控制  │ │知识库检索  │ │Logger 日志   │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                        数据层 (Data)                             │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                  │
│  │ConfigManager│ │Knowledge   │ │ 用户记忆   │                  │
│  │ 配置管理    │ │Repository  │ │ (按用户分) │                  │
│  └────────────┘ └────────────┘ └────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心模块依赖关系

```
                    ┌─────────────────┐
                    │   main.py       │
                    │   程序入口      │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────▼────────┐    │    ┌─────────▼────────┐
    │   MainWindow     │    │    │  ConfigManager   │
    │   (UI 编排)       │    │    │  (配置加载)       │
    └─────────┬────────┘    │    └──────────────────┘
              │             │
    ┌─────────▼─────────────▼─────────┐
    │      MessageProcessor           │
    │      (消息编排核心)              │
    └─────────┬───────────────────────┘
              │
    ┌─────────▼─────────────┐
    │   CustomerServiceAgent│
    │   (决策大脑)           │
    └─────────┬─────────────┘
              │
    ┌─────────┼───────────────────────┐
    │         │                       │
┌───▼───┐ ┌───▼──────┐      ┌────────▼────────┐
│ LLM   │ │知识库    │      │ AgentMedia      │
│决策引擎│ │服务      │      │ (媒体决策)       │
└───────┘ └──────────┘      └─────────────────┘
```

---

## 三、目录结构

```
weixin_store_dev/
├── main.py                          # 程序入口
├── requirements.txt                 # Python 依赖
├── PROJECT_GUIDE.md                 # 本文件（项目指南）
├── README.md                        # 快速开始
│
├── config/                          # 业务配置文件
│   ├── model_settings.json          # LLM API 配置（API Key 等）
│   ├── knowledge_base.json          # 知识库（问答对）
│   ├── image_categories.json        # 图片分类配置
│   ├── address.json                 # 地址图片路径映射
│   ├── media_whitelist.json         # 媒体白名单
│   └── reply_templates.json         # 回复模板
│
├── data/                            # 运行时数据（自动生成）
│   ├── conversations/               # 会话日志（JSONL）
│   ├── memory/users/                # 按用户拆分的记忆文件
│   └── acceptance_suite_report.md   # 验收测试报告
│
├── docs/                            # 设计文档
│   ├── architecture.md              # 旧架构文档
│   ├── media_send_stability_fix_plan.md
│   ├── 2026-03-24_refactoring_summary.md
│   └── ...
│
├── scripts/                         # 调试/测试脚本
│   ├── chat_simulator.py            # 聊天模拟器（调试用）
│   ├── test_full_conversation.py    # 完整对话测试
│   └── ...
│
├── src/                             # 源代码
│   ├── core/                        # 业务逻辑层（决策 + 状态）
│   ├── services/                    # 服务层（LLM/浏览器/知识库）
│   ├── ui/                          # 表现层（PySide6 UI）
│   ├── data/                        # 数据层（配置 + 记忆）
│   └── utils/                       # 工具模块
│
└── tests/                           # 单元测试
    ├── test_system_prompt_builder.py
    ├── test_media_execution.py
    └── ...
```

---

## 四、核心模块详解

### 4.1 表现层 (UI)

| 文件 | 类 | 职责 |
|------|-----|------|
| `ui/main_window.py` | `MainWindow` | 主窗口，编排所有 Tab 和侧边栏 |
| `ui/browser_tab.py` | `BrowserTab` | 内嵌 QWebEngineView，加载微信小店客服页 |
| `ui/knowledge_tab.py` | `KnowledgeTab` | 知识库管理（增删改查/导入导出） |
| `ui/model_config_tab.py` | `ModelConfigTab` | LLM 模型配置（API Key/模型选择） |
| `ui/agent_status_tab.py` | `AgentStatusTab` | Agent 状态监控（会话状态/记忆） |

**关键代码位置**:
```python
# src/ui/main_window.py:44
class MainWindow(QWidget):
    def __init__(self, config_manager, knowledge_repository):
        # 创建BrowserTab, KnowledgeTab, ModelConfigTab等
        # 初始化MessageProcessor, CustomerServiceAgent
```

---

### 4.2 业务逻辑层 (Core)

#### 4.2.1 MessageProcessor - 消息编排器

**职责**: 定时扫描未读消息，协调整个回复流程

**核心方法**:
```python
# src/core/message_processor.py
class MessageProcessor(QObject):
    def _poll_cycle(self):
        """定时循环：检测未读 -> 处理回复"""

    def _process_unread_and_decide(self):
        """主链路：点击进入 -> 抓取消息 -> Agent 决策 -> 发送"""
```

**关键流程**:
```
_poll_cycle()
  └─> _process_unread_and_decide()
       ├─> browser.click_first_unread_session()  # 点击进入
       ├─> browser.grab_chat_history()           # 抓取消息
       ├─> agent.decide(...)                     # Agent 决策
       ├─> media_hooks.send_media(...)           # 发送媒体
       └─> browser.send_text(...)                # 发送文字
```

---

#### 4.2.2 CustomerServiceAgent - 决策大脑

**职责**: 统一决策逻辑，整合规则引擎 + LLM + 媒体决策

**核心方法**:
```python
# src/core/private_cs_agent.py
class CustomerServiceAgent:
    def decide(self, session_id, user_name, text, history, state):
        """
        决策入口
        返回：AgentDecision(reply_text, intent, media_plan, target_store, ...)
        """
        # 1. 状态同步
        # 2. 规则引擎
        # 3. LLM 决策
        # 4. 媒体决策
        # 5. 记忆更新
```

**决策流程**:
```
┌─────────────────────────────────────────────────────────┐
│                  CustomerServiceAgent.decide()          │
├─────────────────────────────────────────────────────────┤
│  1. _sync_unified_state()    ← 融合三层状态              │
│  2. agent_rule_engine.check() ← 规则引擎（地址/知识）    │
│  3. LLMDecisionEngine.decide() ← LLM 决策                │
│  4. agent_media.execute()    ← 媒体决策                  │
│  5. _update_state_after_decision() ← 记忆更新            │
└─────────────────────────────────────────────────────────┘
```

---

#### 4.2.3 LLMDecisionEngine - LLM 决策引擎

**职责**: 构建 Prompt，调用 LLM，解析 JSON 回复

**核心方法**:
```python
# src/core/llm_decision_engine.py
class LLMDecisionEngine:
    def decide(self, session_id, user_name, latest_user_text,
               conversation_history, session_state):
        # 1. 准备对话历史（最近 40 条）
        # 2. 构建 System Prompt
        # 3. 调用 LLM
        # 4. 解析 JSON 回复
```

**Prompt 结构**（2026-03-27 重构后）:
```
## 身份              ← 1 行
## 回复原则           ← 16 条规则
## 门店信息           ← 6 家门店
## 推荐规则           ← 8 条规则
## 产品知识库         ← 大量文本
## 媒体发送规则       ← 3 条规则
─────────────────────────────────────
## 当前用户           ← 用户名 + 本轮消息
## 当前会话状态        ← 对话进展 + 上一轮目标 + 城市/门店/媒体状态
## 本轮任务           ← 建议/避免/综合判断 ← 紧贴输出格式
## 输出格式           ← JSON Schema
```

---

#### 4.2.4 AgentMedia - 媒体决策

**职责**: 地址图/联系方式图的发送控制和排队

**核心函数**:
```python
# src/core/agent_media.py
def execute_media_from_decision(agent, decision, session_state):
    """执行 LLM 的媒体决策"""

def queue_address_image(agent, session_id, session_state, target_store, ...):
    """地址图入队检查（总额度/单店额度/冷却）"""

def queue_contact_image(agent, session_id, text, intent, ...):
    """联系方式图入队检查（额度/冷却/explicit_resend）"""
```

**发送限制规则** (2026-03-27 更新):
| 媒体类型 | 总额度 | 单店上限 | 冷却时间 |
|---------|--------|---------|---------|
| 地址图 | `max(3, 门店数×2)` | 2 次 | 30 秒 |
| 联系方式图 | 2 次 | N/A | 30 秒 |

---

#### 4.2.5 MemoryStore - 记忆存储

**职责**: 跨重启持久化，按用户拆分文件

**核心设计**:
```python
# src/data/memory_store.py
class MemoryStore:
    """
    目录结构:
    data/memory/users/
    ├── __anonymous__.json    # 匿名用户
    ├── abc123def.json        # 按 user_hash 拆分
    └── xyz789uvw.json
    """
```

**关键字段** (`session_state`):
```python
{
    "confirmed_city": "上海",
    "confirmed_district": "静安",
    "confirmed_store": "sh_jingan",
    "address_image_sent_count": 1,
    "address_image_sent_count_by_store": {"sh_jingan": 1},
    "address_image_last_sent_at_by_store": {"sh_jingan": "2026-03-27T10:30:00"},
    "contact_image_sent_count": 0,
    "contact_captured": False,  # 用户是否已留电话
    "turn_count": 4,
    "last_intent": "address",
    "last_reply_goal": "发送地址",
}
```

---

### 4.3 服务层 (Services)

| 文件 | 类 | 职责 |
|------|-----|------|
| `services/llm_service.py` | `LLMService` | 统一封装各 LLM API，支持切换模型 |
| `services/browser_service.py` | `BrowserService` | 控制 QWebEngineView，注入 JS |
| `services/knowledge_service.py` | `KnowledgeService` | 知识库检索（向量 + 关键词） |
| `services/conversation_logger.py` | `ConversationLogger` | 会话日志（JSONL 格式） |

**BrowserService 关键 JS**:
```javascript
// 未读检测
document.querySelector('.unread-badge')?.textContent

// 消息抓取
Walker 遍历 DOM，提取.user-message 节点

// 消息发送
input.value = message; input.dispatchEvent(new KeyEvent('Enter'))
```

---

### 4.4 数据层 (Data)

| 文件 | 类 | 职责 |
|------|-----|------|
| `data/config_manager.py` | `ConfigManager` | 加载/保存 JSON 配置，支持 `.env` |
| `data/knowledge_repository.py` | `KnowledgeRepository` | 知识库 CRUD，支持导入导出 |
| `data/memory_store.py` | `MemoryStore` | 按用户拆分的记忆文件 |

---

## 五、配置说明

### 5.1 模型配置 (`config/model_settings.json`)

```json
{
  "selected_model": "deepseek",
  "models": {
    "deepseek": {
      "api_key": "sk-xxx",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat",
      "temperature": 0.7,
      "max_tokens": 1000
    },
    "gpt": { ... },
    "gemini": { ... }
  }
}
```

### 5.2 知识库配置 (`config/knowledge_base.json`)

```json
[
  {
    "question": "不同价格有什么区别？",
    "answer": "3000 元是化纤发丝，5000 元是真人发丝...",
    "tags": ["价格", "材质"],
    "confidence_threshold": 0.85
  }
]
```

### 5.3 媒体配置

**地址图片** (`config/address.json`):
```json
{
  "sh_jingan": "images/shanghai_jingan_address.png",
  "sh_renmin": "images/shanghai_renmin_address.png",
  ...
}
```

**图片分类** (`config/image_categories.json`):
```json
{
  "address_images": ["images/shanghai_jingan_address.png", ...],
  "contact_images": ["images/contact_qr_1.png", ...]
}
```

---

## 六、运行与调试

### 6.1 启动应用

```bash
pip install -r requirements.txt
python3 main.py
```

### 6.2 快速调试（不走微信）

```bash
# 单条消息测试
python3 scripts/chat_simulator.py -m "不同价格有什么区别？" --no-llm

# 交互模式（多轮对话）
python3 scripts/chat_simulator.py --no-llm
```

**输出示例**:
```
=== 第 1 轮 ===
用户消息：我在上海，准备过来
决策结果:
  - reply_source: llm
  - intent: general
  - route_reason: llm_general
  - media_plan: none
  - target_store: unknown
  - reply_text: 好的呀~您在上海哪个区域呢？
```

### 6.3 运行测试套件

```bash
# 单元测试
pytest tests/ -v

# 特定测试
pytest tests/test_system_prompt_builder.py -v
pytest tests/test_media_execution.py -v
```

---

## 七、状态流转图

### 7.1 地址图交付状态

```
not_delivered ──[LLM 决策 address_image]──> first_sent
                    │
                    └──[用户再次索要]──> resent
```

**状态字段**: `address_delivery_stage_by_store: Dict[str, str]`

### 7.2 联系方式交付状态

```
not_delivered ──[用户明确要联系方式]──> first_sent
                    │
                    └──[用户再次索要]──> resent
                    │
                    └──[用户留电话]──> contact_captured=True
```

### 7.3 对话主线类型

| 主线 | 触发条件 |
|------|---------|
| `business_answer` | 普通业务问答 |
| `address_delivery` | 地址交付中 |
| `contact_delivery` | 联系方式交付中 |
| `store_recommendation` | 门店推荐中 |
| `conversation_repair` | 会话修复（用户质疑） |

---

## 八、关键设计决策

### 8.1 LLM-first 架构（2026-03-27 重构）

**旧架构**: 规则引擎优先，LLM 作为 fallback
**新架构**: LLM 优先决策，规则引擎补全（地址问题/知识库命中）

**优势**:
- 回复更自然，不像机械问答
- 多轮对话理解更好
- 规则只在必要时介入（如地址冷却/额度限制）

### 8.2 状态融合机制

**三层状态来源**:
1. `SessionManager` - 内存状态（优先级最低）
2. `MemoryStore` - 持久化记忆（优先级中）
3. `ConversationLogger` - 从日志回溯（优先级最高）

**融合代码**:
```python
# src/core/session_state_unified.py
merged = {**session_state, **memory_state, **logger_state}
```

### 8.3 Prompt 设计原则（2026-03-27 更新）

**背景参考放前面，本轮任务放最后**:
```
┌────────────────────┐
│  背景参考（先读）   │
│  - 身份/规则/知识库 │
├────────────────────┤
│  本轮任务（后读）   │  ← 最靠近生成位置，注意力最集中
│  - 用户消息         │
│  - 会话状态         │
│  - 本轮建议/避免    │
│  - 输出格式         │
└────────────────────┘
```

---

## 九、已知限制与改进方向

### 9.1 当前限制

| 问题 | 影响 | 临时方案 |
|------|------|---------|
| 对话历史硬截断 40 条 | 超长对话早期信息丢失 | 依赖 `会话状态` 字段补偿 |
| 冷却时间全局计时 | 快速切换门店时可能误拦 | 等待 30 秒 |
| 意图识别靠关键词 | 复杂语义可能识别错误 | 依赖 LLM 兜底 |

### 9.2 待改进方向

1. **对话摘要**: 每 20 轮自动摘要，替代硬截断
2. **分门店冷却**: 地址图冷却按门店独立计时
3. **多轮焦点追踪**: 记录 `topic_turn_count`，避免同一问题追问过久

---

## 十、故障排查

### 10.1 常见错误

**错误**: `LLM API 调用失败`
**排查**:
1. 检查 `config/model_settings.json` 中 API Key 是否正确
2. 运行 `python3 scripts/check_config.py` 验证配置
3. 查看日志：`data/logs/app.log`

**错误**: `地址图不发`
**排查**:
1. 检查 `config/address.json` 中路径是否存在
2. 查看 `data/memory/users/*.json` 中 `address_image_sent_count` 是否超限
3. 检查冷却时间（30 秒）

### 10.2 日志位置

| 日志类型 | 位置 |
|---------|------|
| 应用日志 | `data/logs/app.log` |
| 会话日志 | `data/conversations/*.jsonl` |
| 记忆文件 | `data/memory/users/*.json` |

---

## 十一、版本历史

| 版本 | 日期 | 关键改动 |
|------|------|---------|
| v1.8.5 | 2026-03-29 | 高频问法与回归验证增强：补充男士假发知识问法、放宽媒体重试次数并新增完整对话与三用户焦点仿真脚本 |
| v1.8.5 | 2026-03-27 | 媒体发送校验修复 |
| v1.8.5 | 2026-03-27 | 回复护栏调整 |
| v1.8.5 | 2026-03-27 | 固定回复轮换增强 |
| v1.8.5 | 2026-03-27 | 地址交付增强 |
| v1.8.5 | 2026-03-27 | 测试覆盖增强 |
| v1.8.5 | 2026-03-27 | 护栏和意图识别增强 |
| v1.8.5 | 2026-03-27 | 主线状态机与地址交付重构 |

---

## 十二、快速上手 CheckList

- [ ] 配置 `config/model_settings.json`（填入 API Key）
- [ ] 配置 `config/knowledge_base.json`（导入问答对）
- [ ] 配置 `config/address.json`（地址图片路径）
- [ ] 运行 `python3 main.py`
- [ ] 在 UI 中加载微信小店客服页面 URL
- [ ] 点击"启动服务"
- [ ] 观察日志输出，确认自动回复正常

---

**维护者**: yckonnnn
**协作指南**: 参考 `CLAUDE.md` 和 `~/.claude/rules/`
