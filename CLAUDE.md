# 微信小店自动化客服助手 - Claude 协作指南

## 项目概述

基于 **PySide6 + QWebEngine** 的微信小店自动化客服系统，通过内嵌浏览器加载微信小店客服页面，利用 JavaScript 注入自动抓取消息、调用 LLM 生成回复并自动发送。

## 核心主链路

```
自动扫描未读 -> 自动点击进入 -> 抓取聊天记录 -> Agent 决策 -> 发送文本/媒体 -> 记忆持久化
```

## 项目结构

```
weixin_store_dev/
├── main.py                          # 程序入口
├── requirements.txt                 # 依赖列表
├── config/                          # 配置文件
│   ├── model_settings.json          # 模型配置
│   ├── knowledge_base.json          # 知识库数据
│   └── agent_memory.json            # 会话记忆 (自动生成)
├── src/
│   ├── ui/                          # 表现层 (PySide6 UI)
│   │   ├── main_window.py
│   │   ├── browser_tab.py
│   │   ├── knowledge_tab.py
│   │   └── model_config_tab.py
│   ├── core/                        # 业务逻辑层
│   │   ├── message_processor.py
│   │   ├── reply_coordinator.py
│   │   └── session_manager.py
│   ├── services/                    # 服务层
│   │   ├── llm_service.py
│   │   ├── browser_service.py       # JavaScript 注入
│   │   └── knowledge_service.py
│   ├── data/                        # 数据层
│   │   ├── config_manager.py
│   │   └── knowledge_repository.py
│   └── utils/                       # 工具模块
├── scripts/
│   └── chat_simulator.py            # 聊天模拟器 (调试用)
└── docs/                            # 文档
    ├── architecture.md              # 架构设计
    ├── system_prompt_private_ai_customer_service.md
    └── private_ai_customer_service_playbook.md
```

## 运行与调试

### 启动应用
```bash
pip install -r requirements.txt
python3 main.py
```

### 快速调试 (不走微信)
```bash
# 单条消息测试
python3 scripts/chat_simulator.py -m "不同价格有什么区别啊？" --no-llm

# 交互模式测试
python3 scripts/chat_simulator.py --no-llm
```

## Agent 策略

1. **地址问题**: 优先走地址路由
2. **非地址问题**: 优先命中知识库，未命中再调用 LLM
3. **媒体决策**: Agent 统一决策 (地址图 / 联系方式图 / 延迟视频)
4. **会话记忆**: 跨重启持久化，TTL 默认 30 天

## 核心配置文件

| 文件 | 说明 |
|------|------|
| `docs/system_prompt_private_ai_customer_service.md` | 系统提示词 |
| `docs/private_ai_customer_service_playbook.md` | 客服回复规则 |
| `config/knowledge_base.json` | 知识库 |
| `config/model_settings.json` | 模型配置 |
| `config/agent_memory.json` | 记忆文件 (自动生成) |

## 支持模型

ChatGPT, Gemini, 阿里千问，DeepSeek, 豆包，Kimi

## 关键技术点

- **JavaScript 注入**: 通过 QWebEngineView 注入 JS 实现消息检测、抓取、发送
- **去重机制**: 消息级去重 (内容哈希) + 会话级去重 (会话 ID+ 时间戳)
- **并发控制**: 全局锁 `window.__ai_global_busy` + Python 层 Inflight 标志

## 开发约定

- 修改核心逻辑前请阅读 `docs/architecture.md`
- 调试优先使用 `chat_simulator.py` 避免污染真实会话
- 知识库修改需同步更新 `config/knowledge_base.json`
- 新增模型需在 `LLMService` 和 UI 中同时添加配置
