# Issue: 第一阶段重构 `private_cs_agent.py`，抽离类型、Prompt 构造与 Guardrails

## 背景

当前 [private_cs_agent.py](/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev/src/core/private_cs_agent.py) 长期承担过多职责，包括：

- Agent 决策主入口
- LLM Prompt 构造
- 对话状态摘要
- 回复文本清洗
- Guardrails 保护逻辑
- 媒体裁判与媒体状态
- 记忆与去重辅助

该文件已超过 4000 行，后续继续在单文件里增加功能，会显著提升维护成本和回归风险。

## 第一阶段目标

在**不改变现有功能行为**的前提下，先完成最稳定、最独立的职责抽离，让核心代码进入可持续拆分状态。

本阶段只做：

- 抽离类型定义
- 抽离 LLM Prompt 构造逻辑
- 抽离回复文本清洗与 Guardrails 逻辑

本阶段**不做**：

- 不调整现有业务规则
- 不改变主回复逻辑
- 不修改媒体发送策略
- 不拆 `message_processor.py`

## 本阶段改动

新增模块：

- [agent_types.py](/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev/src/core/agent_types.py)
  - `AgentDecision`
  - `MediaJudgeDecision`
  - `_SafeDict`

- [agent_prompt_builder.py](/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev/src/core/agent_prompt_builder.py)
  - `build_general_llm_prompt(...)`
  - `summarize_llm_conversation_state(...)`

- [agent_guardrails.py](/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev/src/core/agent_guardrails.py)
  - `normalize_reply_text(...)`
  - `apply_llm_reply_guardrails(...)`

兼容方式：

- [private_cs_agent.py](/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev/src/core/private_cs_agent.py) 仍保留原方法名
- 外部接口不变
- 原有调用方无需改动
- 内部改为薄封装并转发到独立模块

## 验收标准

### 结构验收

- `private_cs_agent.py` 中的类型定义、Prompt 构造、Guardrails 不再直接堆叠在主类里
- 新模块职责单一、边界清晰
- 后续第二阶段可继续拆出 `agent_media.py`

### 功能验收

- `CustomerServiceAgent.decide(...)` 对外接口保持不变
- 现有主回复、Fallback、文本清洗、Guardrails 行为不因拆分而改变
- 语法检查通过

## 风险说明

- 真实 DeepSeek 回归结果会受网络波动影响，不能单独作为结构拆分是否正确的唯一依据
- 本阶段重点是“结构不变行为”，不是“功能优化”

## 下一阶段建议

第二阶段继续拆 [private_cs_agent.py](/Users/yckonnnn/Desktop/Coding/github-project/weixin_store_dev/src/core/private_cs_agent.py)，优先拆出：

- `agent_media.py`

建议迁移内容：

- 后置媒体裁判
- 文本后媒体计划构建
- 媒体状态写回
- 联系方式/地址图片选择
- 首轮视频与媒体补偿逻辑

原因：

- 媒体链已与 LLM 主回复解耦
- 相比先拆 `agent_llm_reply.py`，媒体模块边界更清晰、风险更低
