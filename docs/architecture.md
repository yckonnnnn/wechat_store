# AI 微信小店客服系统 - 架构设计文档

## 1. 项目概述

这是一个基于 Python + PySide6 开发的 AI 智能客服系统，专门为微信小店设计。系统通过内嵌浏览器加载微信小店客服页面，利用 JavaScript 注入技术自动抓取用户消息，调用大语言模型生成回复，并自动发送给用户。

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                        表现层 (UI)                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ 主窗口       │ │ 知识库管理   │ │ 模型配置界面         │ │
│  │ MainWindow   │ │ KnowledgeBase│ │ ModelConfig          │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                        业务逻辑层 (Core)                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ 消息处理器   │ │ 回复生成器   │ │ 会话管理器           │ │
│  │ Message      │ │ Reply        │ │ Session              │ │
│  │ Handler      │ │ Generator    │ │ Manager              │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                        服务层 (Services)                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ LLM 服务      │ │ 浏览器服务   │ │ 知识库服务           │ │
│  │ LLMService   │ │ Browser      │ │ KnowledgeService     │ │
│  │              │ │ Service      │ │                      │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                        数据层 (Data)                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ 配置管理     │ │ 知识库存储   │ │ 聊天记录缓存         │ │
│  │ Config       │ │ Knowledge    │ │ ChatCache            │ │
│  │ Manager      │ │ Repository   │ │                      │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 核心类 |
|------|------|--------|
| **ui** | 用户界面展示和交互 | MainWindow, KnowledgeTab, ModelConfigTab |
| **core** | 业务流程控制和状态管理 | MessageProcessor, ReplyCoordinator, SessionManager |
| **services** | 外部服务和底层操作 | LLMService, BrowserService, KnowledgeService |
| **data** | 数据持久化和配置管理 | ConfigManager, KnowledgeRepository |
| **utils** | 工具函数和常量 | constants, helpers, logger |

## 3. 核心流程

### 3.1 自动回复流程

```
┌─────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  定时器  │───>│  扫描未读    │───>│  点击进入    │───>│  抓取消息    │
│ (4 秒)   │    │  消息       │    │  会话       │    │             │
└─────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                            │
┌─────────┐    ┌─────────────┐    ┌─────────────┐          │
│  发送   │<───│  注入 JS     │<───│  生成回复    │<─────────┘
│  回复   │    │  发送消息   │    │  (LLM/知识库)│
└─────────┘    └─────────────┘    └─────────────┘
```

### 3.2 消息处理流程

```
用户消息 -> 去重检查 -> 知识库匹配 -> [匹配成功] -> 返回知识库回复
                    |
                    -> [匹配失败] -> LLM 生成回复 -> 返回 AI 回复
```

## 4. 目录结构

```
wx_store_index/
├── main.py                      # 程序入口
├── requirements.txt             # 依赖列表
├── README.md                    # 项目说明
│
├── config/                      # 配置文件目录
│   ├── model_settings.json      # 模型配置
│   └── knowledge_base.json      # 知识库数据
│
├── src/                         # 源代码目录
│   ├── __init__.py
│   │
│   ├── ui/                      # 表现层
│   │   ├── __init__.py
│   │   ├── main_window.py       # 主窗口
│   │   ├── left_panel.py        # 左侧面板
│   │   ├── browser_tab.py       # 浏览器标签页
│   │   ├── knowledge_tab.py     # 知识库标签页
│   │   └── model_config_tab.py  # 模型配置标签页
│   │
│   ├── core/                    # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── message_processor.py # 消息处理器
│   │   ├── reply_coordinator.py # 回复协调器
│   │   └── session_manager.py   # 会话管理器
│   │
│   ├── services/                # 服务层
│   │   ├── __init__.py
│   │   ├── llm_service.py       # LLM API 服务
│   │   ├── browser_service.py   # 浏览器控制服务
│   │   └── knowledge_service.py # 知识库服务
│   │
│   ├── data/                    # 数据层
│   │   ├── __init__.py
│   │   ├── config_manager.py    # 配置管理器
│   │   └── knowledge_repository.py # 知识库存储
│   │
│   └── utils/                   # 工具模块
│       ├── __init__.py
│       ├── constants.py         # 常量定义
│       ├── helpers.py           # 辅助函数
│       └── logger.py            # 日志工具
│
└── docs/                        # 文档目录
    ├── architecture.md          # 架构设计文档
    ├── api.md                   # API 接口文档
    └── usage.md                 # 使用说明
```

## 5. 类设计

### 5.1 UI 层

```python
class MainWindow(QWidget)
├── 属性：browser_service, message_processor, config_manager
├── 方法：setup_ui(), start_service(), stop_service()
├── 信号：log_message, status_changed

class LeftPanel(QFrame)
├── 属性：control_buttons, status_labels, log_view
├── 方法：update_status(), append_log()

class BrowserTab(QWidget)
├── 属性：web_view, url_input
├── 方法：load_url(), run_js(), refresh()

class KnowledgeTab(QWidget)
├── 属性：table_widget, search_input
├── 方法：add_item(), edit_item(), delete_item(), import_file(), export_file()

class ModelConfigTab(QWidget)
├── 属性：model_forms, api_key_inputs
├── 方法：load_settings(), save_settings(), test_connection()
```

### 5.2 Core 层

```python
class MessageProcessor(QObject)
├── 属性：browser_service, llm_service, knowledge_service
├── 方法：start_polling(), stop_polling(), process_message()
├── 信号：message_received, reply_sent, error_occurred

class ReplyCoordinator(QObject)
├── 属性：message_processor, session_manager
├── 方法：coordinate_reply(), should_reply(), format_reply()
├── 信号：reply_ready, reply_sent

class SessionManager(QObject)
├── 属性：active_sessions, message_history
├── 方法：get_session(), update_session(), clear_history()
```

### 5.3 Services 层

```python
class LLMService
├── 属性：config_manager, current_model
├── 方法：generate_reply(), set_model(), test_connection()
├── 支持：ChatGPT, Gemini, 阿里千问，DeepSeek, 豆包，Kimi

class BrowserService(QObject)
├── 属性：web_view, page_ready
├── 方法：navigate(), run_javascript(), inject_script()
├── 方法：find_unread(), enter_session(), send_message()
├── 信号：page_loaded, js_result, error_occurred

class KnowledgeService
├── 属性：repository, cache
├── 方法：search(), add(), update(), delete(), best_match()
```

### 5.4 Data 层

```python
class ConfigManager
├── 属性：config_file, settings_cache
├── 方法：load(), save(), get(), set()
├── 方法：get_model_config(), set_model_config()

class KnowledgeRepository
├── 属性：data_file, items
├── 方法：load(), save(), add(), update(), delete()
├── 方法：search(), export(), import_file()
```

## 6. 关键技术点

### 6.1 JavaScript 注入

系统通过 QWebEngineView 注入 JavaScript 代码实现：
- 未读消息检测（红色角标识别）
- 会话列表操作（点击进入）
- 消息内容抓取（DOM TreeWalker）
- 消息发送（模拟输入和回车事件）

### 6.2 去重机制

- **消息级去重**: 基于消息内容哈希
- **会话级去重**: 基于会话 ID 和时间戳
- **本地存储**: 使用 localStorage 持久化已回复记录

### 6.3 并发控制

- **全局锁**: `window.__ai_global_busy` 防止同时处理多个会话
- **Inflight 标志**: Python 层防止重复调用
- **定时器管理**: QTimer 控制检测频率

## 7. 扩展性设计

### 7.1 添加新模型

1. 在 `LLMService` 中添加模型配置
2. 实现对应的 API 调用方法
3. 在 UI 中添加模型选项

### 7.2 添加新功能

- **多轮对话**: 扩展 `SessionManager` 维护对话上下文
- **情感分析**: 在 `MessageProcessor` 中添加预处理模块
- **数据统计**: 添加 `AnalyticsService` 收集回复数据

## 8. 安全考虑

- API 密钥存储在本地 JSON 文件中
- 支持 `.env` 文件加载环境变量
- JavaScript 注入操作在微信小店页面执行，需谨慎处理
- 建议添加操作确认机制防止误操作
