# 微信小店客服助手 - 项目记忆

## 📅 2026-03-30 地址拦截器实现

**详细文档**: [address_interceptor_implementation.md](../docs/address_interceptor_implementation.md)

**核心功能**:
- 检测 LLM 输出中的单门店地址（6 家店）并拦截替换为"地址看图片中的位置"
- 多门店地址（2 个+）不拦截，保留原文
- 拦截后自动触发对应门店的地址图片发送

**关键文件**:
- `src/services/address_interceptor.py`: 拦截器服务
- `src/core/private_cs_agent.py`: _address_index、pick_address_image()
- `src/core/message_processor.py`: 集成拦截器

**测试结果**:
- 单元测试 14/14 通过
- 地址图片索引加载 205 张（6 家店各 30+ 张）
- 20 轮压力测试通过

---

## 📅 2026-03-30 首轮视频修复（必读）

- [project_first_turn_video_fix.md](project_first_turn_video_fix.md) — LLM-First 重构后首轮视频不发的根因 + 两处修复位置

---

## 📅 2026-03-29 LLM-First 重构完成（必读）

**测试验证**:
- 20 轮高频问题测试：✅ 通过
- 25 轮压力测试（联系方式/不耐烦/地址反复追问）：✅ 通过
- 地址一致性：静安店地址重复 9 次完全一致

**核心修改**:
- 移除所有地址/联系方式规则干预，LLM 是唯一回复决策者
- 在 system prompt 中添加企业知识约束（地址硬约束、价格硬约束、禁止输出联系方式）
- 删除 4 个大文件：`agent_rule_engine.py`(1529 行), `agent_media.py`(1742 行), `agent_contact_flow.py`(310 行), `agent_guardrails.py`(540 行)

**修复的问题**:
- 地址幻觉：之前回复"南京西路"，修复后正确回复"汉口路 650 号亚洲大厦"
- 远程定制政策：优先推荐到店，远程不退不换
- 禁止发图：明确告知"不需要发照片"

**详细报告**: `scripts/test_25turns_stress_report.md`

---

## 📅 2026-03-27 LLM-first 重构清理（必读）

**进度记录**: [project_llm_first_refactor.md](project_llm_first_refactor.md)

**完成状态**: Phase 1 全部完成，5 commits 已推送到 `kf_dev` remote

**剩余**: Phase 2（memory_store.py 字段精简）- 可选，有迁移风险，尚未开始

---

## 待修复问题

### P0: 两个严重问题 (2026-03-24 已修复 ✅)

**详细修复方案**: 见 [p0_critical_fixes.md](./p0_critical_fixes.md) 和 [汇总文档](../../docs/2026-03-24_refactoring_summary.md)

**问题 1 - 漏回消息补偿机制竞态条件**:
- 位置：`src/core/message_processor.py:_find_stale_followup_candidate()`
- 根因：遍历多个日志文件时即时更新 `last_event_type`，可能被后续文件覆盖
- 修复：先收集所有事件，按用户聚合后按时间排序，再确定最后事件类型
- **状态**: ✅ 2026-03-24 已修复

**问题 2 - 媒体发送重试导致重复发送**:
- 位置：`src/core/message_processor_media.py:_handle_media_sent()` 和 `_drain_queue()`
- 根因：重试队列无去重检查，`mark_media_sent` 异常时状态未清理
- 修复：队列入口去重、重试前去重检查、回调异常保护
- **状态**: ✅ 2026-03-24 已修复

**实际用时**: 约 3 小时 (含测试)

---

### P1: 长对话智能摘要 (2026-03-24 用户反馈)

**详细修复方案**: 见 [p1_conversation_summary.md](./p1_conversation_summary.md)

**问题描述**:
用户反馈长对话时早期信息丢失，导致重复追问：
- "你刚才不是说过价格了吗，怎么又问？"
- "我之前说了我在上海，为什么还问我城市？"
- "地址图不是发过了吗？"

**解决方案**:
- 每 10 轮对话自动生成摘要
- 摘要存到 MemoryStore
- 发送给大模型时：摘要 + 最近 12 条对话

**修改文件**:
- `src/services/conversation_summarizer.py`（新建）
- `src/data/memory_store.py`
- `src/core/message_processor_support.py`
- `src/core/private_cs_agent.py`
- `src/core/agent_prompt_builder.py`

**预计时间**: 3.5 小时
**成本增加**: ~$0.0006/次对话

---

### 问题：漏回消息补偿机制 (P0 - 高优先级)

**创建时间**: 2026-03-17

**问题描述**:
系统有时会漏回用户消息。从用户提供的截图可以看到，用户"胃不疼"发送了消息"我在北京，准备来上海"，系统已经把未读标记清除了，但是没有回复这条消息。这会导致平台判定响应不积极，影响评分。

**解决方案**:
添加一个补偿机制，当系统空闲时主动检查是否有未回复的用户消息：
1. **触发条件**: 当前页面没有任何未读 AND 没有任何逻辑要触发
2. **等待时间**: 1 分钟后
3. **主动检查**: 拉取当前用户的聊天记录
4. **判断逻辑**: 检查最后一条是不是用户发的
5. **执行动作**: 如果是用户消息，就触发回复

**实施计划**:
- Phase 1: 状态管理和定时器基础设施 (~0.5h)
- Phase 2: 空闲状态检测和定时器控制 (~1h)
- Phase 3: 补偿检查核心逻辑 (~2h)
- Phase 4: 集成到现有流程 (~0.5h)
- Phase 5: 配置和日志 (~1h)

**关键文件**:
- `src/core/message_processor.py` - 主要修改文件

**详细设计文档**:
见 planner agent 输出（ace7fff5fcb927090）

**预计时间**: 4-6 小时开发 + 2-3 小时测试

---

## 已完成的功能

### v5.4 - 优化首轮媒体发送顺序及重试机制

**提交**: d5b2ddd
**时间**: 2026-03-17

**改动内容**:
- 首轮视频优先发送（视频 -> 等待 3 秒 -> 图片 -> 文本）
- 增强视频和图片重试机制，最多重试 2 次
- 增加详细的媒体发送状态日志，显示重试次数
- 避免首轮视频重复发送

**修改文件**:
- `src/core/message_processor.py` (+131, -13)

---

## 用户偏好

**测试报告输出格式**：见 [feedback_test_report_format.md](./feedback_test_report_format.md)

当用户要求"模拟用户测试"或"压力测试"时，必须直接在对话中逐条打印完整对话记录，不要只保存到文档让用户自己翻看。
