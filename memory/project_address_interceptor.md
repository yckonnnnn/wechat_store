---
name: 地址拦截器实现（2026-03-30）
description: 单门店地址自动拦截替换 + 地址图片路由实现细节
type: project
---

**实现时间**: 2026-03-30

**核心功能**:
- 检测 LLM 输出中的单门店地址（6 家店）并拦截替换为"地址看图片中的位置"
- 多门店地址（2 个+）不拦截，保留原文
- 拦截后自动触发对应门店的地址图片发送

**关键文件**:
- `src/services/address_interceptor.py`: 拦截器服务，STORE_ADDRESS_PATTERNS 定义 6 家店地址正则
- `src/core/private_cs_agent.py`: _address_index 字典、pick_address_image()、_infer_store_from_name()
- `src/core/message_processor.py`: _interceptor_store_to_index_key 映射，集成拦截器调用 pick_address_image()

**门店映射**:
- 静安店 → sh_jingan（愚园路）
- 人民广场店 → sh_renmin（汉口路）
- 虹口店 → sh_hongkou（花园路）
- 五角场店 → sh_wujiaochang（政通路）
- 徐汇店 → sh_xuhui（漕溪北路）
- 北京店 → beijing_chaoyang（建外 SOHO）

**测试结果**:
- 单元测试 14/14 通过
- 地址图片索引加载 205 张（6 家店各 30+ 张）
- 20 轮压力测试：单店地址 13 轮全部拦截，多店/无地址全部不拦截

**参考分支**: 085164d7461436bc9094f3ba7ce38e8fb97e10b8

**详细文档**: `docs/address_interceptor_implementation.md`
