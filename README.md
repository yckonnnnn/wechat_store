# 微信小店自动化客服助手（PySide6 Agent 版）

> **当前版本**: v1.8.5 (LLM-first 架构)
> **最后更新**: 2026-03-29
> **技术栈**: Python 3.13 + PySide6 + QWebEngine + 大语言模型

这是一个基于 **PySide6 + QWebEngine** 的微信小店自动化客服系统。系统通过内嵌浏览器加载微信小店客服后台，自动检测未读消息、抓取对话内容、调用大语言模型生成回复并自动发送。

## 核心功能

- 🤖 **自动回复**: 识别用户意图，调用 LLM 或知识库生成自然回复
- 📍 **智能发图**: 根据对话内容自动发送地址图/联系方式图
- 🧠 **会话记忆**: 跨重启持久化，记住用户已确认的门店、城市、已发媒体
- 🔀 **多模型支持**: ChatGPT、Gemini、阿里千问、DeepSeek、豆包、Kimi

## 核心主链路

```
自动扫描未读 -> 自动点击进入 -> 抓取聊天记录 -> Agent 决策 -> 发送文本/媒体 -> 记忆持久化
```

## 核心配置文件

| 文件 | 说明 |
|------|------|
| `docs/system_prompt_private_ai_customer_service.md` | 系统提示词 |
| `docs/private_ai_customer_service_playbook.md` | 客服回复规则 |
| `config/knowledge_base.json` | 知识库（问答对） |
| `config/model_settings.json` | 模型配置（API Key 等） |
| `config/address.json` | 地址图片路径映射 |
| `data/memory/users/*.json` | 用户记忆（按用户拆分） |

## Agent 策略

1. **地址问题**: 城市未知时先反问，城市明确后推荐门店 + 发图
2. **非地址问题**: 优先命中知识库，未命中再调用 LLM
3. **媒体决策**: 地址图/联系方式图/延迟视频，由 Agent 统一决策
4. **会话记忆**: 跨重启持久化，TTL 默认 30 天

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置模型

编辑 `config/model_settings.json`，填入你的 API Key：

```json
{
  "selected_model": "deepseek",
  "models": {
    "deepseek": {
      "api_key": "sk-your-api-key-here",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat"
    }
  }
}
```

### 3. 启动应用

```bash
python3 main.py
```

### 4. 加载微信小店

在 UI 中输入微信小店客服后台 URL，点击"启动服务"

## 快速调试（不走微信）

```bash
# 单条消息：只看策略命中和回复
python3 scripts/chat_simulator.py -m "不同价格有什么区别啊？" --no-llm

# 交互模式：连续多轮测试（输入 /exit 退出）
python3 scripts/chat_simulator.py --no-llm
```

输出包含：
- `reply_source` / `intent` / `route_reason` / `rule_id`
- `media_plan` / `reply_text`
- 媒体触发摘要：`视频=是/否 | 地址图片=是/否 | 联系方式图片=是/否`

## 运行测试

```bash
# 单元测试
pytest tests/ -v

# 特定测试
pytest tests/test_system_prompt_builder.py -v
```

## UI 页面

- **微信小店**: 内嵌浏览器，加载客服后台
- **知识库管理**: 增删改查问答对
- **模型配置**: 切换 LLM 模型，配置 API Key
- **图片与视频管理**: 管理地址图/联系方式图
- **Agent 状态**: 监控会话状态/记忆

## 架构说明

系统采用分层架构：

```
表现层 (UI)      -> PySide6 窗口和浏览器
业务逻辑层 (Core) -> Agent 决策 + 状态管理
服务层 (Services) -> LLM API + 浏览器控制 + 知识库
数据层 (Data)    -> 配置文件 + 记忆存储
```

详细文档请查看 [PROJECT_GUIDE.md](PROJECT_GUIDE.md)

## 版本历史

| 版本 | 日期 | 关键改动 |
|------|------|---------|
| v1.8.5 | 2026-03-29 | 合并 present 分支：高频问法与回归验证增强 |
| v1.8.5 | 2026-03-27 | 媒体发送校验修复 |
| v1.8.5 | 2026-03-27 | 回复护栏调整 |

## 说明

- 已移除 Flask 测试架构
- 已移除旧关键词并行触发链路，统一由 Agent 决策
- 地址推荐改用 LLM 判断 + Guardrail 约束，不再硬编码城市规则
