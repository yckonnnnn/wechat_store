# 地址拦截器实现报告

**完成时间**: 2026-03-30
**参考分支**: 085164d7461436bc9094f3ba7ce38e8fb97e10b8

---

## 实现目标

1. 检测 LLM 输出中的具体地址（6 家店的地址）
2. 仅当恰好匹配到 1 个地址时才拦截替换
3. 多门店地址（2 个+）不拦截，保留原样
4. 拦截后触发对应门店的地址图片发送
5. JSON 日志记录原始 LLM 输出（由调用方负责）

---

## 核心修改

### 1. 新增文件

#### `src/services/address_interceptor.py`
地址拦截器服务（单门店地址拦截版）

**核心功能**:
- `AddressInterceptor` 类：地址拦截器
- `STORE_ADDRESS_PATTERNS`: 6 家店的地址模式配置
- `intercept(text)`: 拦截并替换地址（仅单门店地址）
- `_deduplicate_matches()`: 去重匹配结果

**拦截规则**:
1. 仅拦截恰好 1 个门店地址的情况
2. 多门店地址（2 个+）不拦截，保留原样
3. 只匹配 6 家店的已知地址模式

**6 家店地址模式**:
| 门店名称 | 地址关键词 | 正则模式 |
|---------|-----------|---------|
| 静安店 | 愚园路 | `愚园路\s*\d+\s*号(?:\s*环球世界大厦(?:\s*[A-Z] 座)?)?` |
| 人民广场店 | 汉口路 | `汉口路\s*\d+\s*号(?:\s*亚洲大厦(?:\s*[A-Z] 座)?)?` |
| 虹口店 | 花园路 | `花园路\s*\d+\s*号(?:\s*嘉和国际大厦(?:\s*(?:东楼 \| 西楼 \| 南楼 \| 北楼))?)?` |
| 五角场店 | 政通路、五角场 | `政通路\s*\d+\s*号...` |
| 徐汇店 | 漕溪北路 | `漕溪北路\s*\d+\s*号...` |
| 北京店 | 建外 SOHO、朝阳 | `建外\s*SOHO...` |

---

### 2. 修改文件

#### `src/core/private_cs_agent.py`

**新增字段**:
```python
self._address_index: Dict[str, List[str]] = {
    "beijing_chaoyang": [],
    "sh_xuhui": [],
    "sh_jingan": [],
    "sh_hongkou": [],
    "sh_wujiaochang": [],
    "sh_renmin": [],
}
```

**新增方法**:
- `_infer_store_from_name(filename)`: 从文件名推断门店 key
- `pick_address_image(target_store, session_state, exclude_paths)`: 从门店地址图片池中选择图片

**修改方法**:
- `reload_media_library()`: 增加地址图片索引构建逻辑
  - 从 `image_categories.json` 的 `店铺地址` 分类读取
  - 优先使用 `store_targets` 配置
  - 配置未命中时从文件名推断
  - 无法识别时归入人民广场店兜底

- `get_status()`: 更新 `address_image_count` 为实际统计值

---

#### `src/core/message_processor.py`

**新增字段**:
```python
self._interceptor_store_to_index_key = {
    "静安店": "sh_jingan",
    "人民广场店": "sh_renmin",
    "虹口店": "sh_hongkou",
    "五角场店": "sh_wujiaochang",
    "徐汇店": "sh_xuhui",
    "北京店": "beijing_chaoyang",
}
```

**修改逻辑** (`send_text_and_remaining_media` 函数):
```python
intercept_result = self._address_interceptor.intercept(decision.reply_text)

if intercept_result.is_intercepted:
    # 将拦截器的 target_store 转换为索引 key
    store_key = self._interceptor_store_to_index_key.get(intercept_result.target_store)
    if store_key:
        # 获取 session_state 用于避重
        user_hash = self.agent._hash_user(user_name or session_id)
        session_state = self.agent.memory_store.get_session_state(session_id, user_hash=user_hash)
        # 调用 pick_address_image 选择图片
        image_path = self.agent.pick_address_image(store_key, session_state=session_state)
        if image_path:
            address_media_item = {
                "type": "address_image",
                "path": image_path,
                "trigger_source": "address_interceptor",
                "target_store": store_key,
            }
            planned_media_items.insert(0, address_media_item)
```

---

### 3. 新增测试文件

#### `scripts/test_address_interceptor.py`
单轮测试脚本，验证拦截器基本功能

#### `scripts/test_address_interceptor_20turns.py`
20 轮压力测试，混合单门店、多门店、无地址场景

#### `scripts/test_address_image_routing.py`
地址图片路由集成测试，验证：
- `_address_index` 加载
- `pick_address_image()` 功能
- 拦截器与图片路由集成

#### `tests/test_address_interceptor.py`
pytest 单元测试（14 个测试用例）

---

## 测试结果

### 单元测试 (14/14 通过)
```
✅ test_intercept_single_store_jingan
✅ test_intercept_single_store_hongkou
✅ test_intercept_single_store_huangpu
✅ test_no_intercept_multiple_stores
✅ test_no_intercept_three_stores
✅ test_no_address
✅ test_empty_text
✅ test_none_text
✅ test_same_address_multiple_patterns
✅ test_overlapping_addresses
✅ test_partial_address_not_matched
✅ test_has_single_store_address_true
✅ test_has_single_store_address_false
✅ test_address_match_creation
```

### 地址图片索引加载测试
```
✅ beijing_chaoyang: 33 张图片
✅ sh_xuhui: 35 张图片
✅ sh_jingan: 32 张图片
✅ sh_hongkou: 34 张图片
✅ sh_wujiaochang: 36 张图片
✅ sh_renmin: 35 张图片

总计：205 张地址图片
```

### pick_address_image() 功能测试
```
✅ 单次选择：成功返回图片路径
✅ 多次选择：5 次选择结果不同（随机性验证通过）
✅ 避重功能：所有图片已发送时返回 None
✅ 上海门店兜底：sh_wujiaochang 有图片时正常返回
```

### 拦截器门店映射测试
```
✅ 静安店：拦截器识别为'静安店' → 索引 key 'sh_jingan'
✅ 虹口店：拦截器识别为'虹口店' → 索引 key 'sh_hongkou'
✅ 人民广场店：拦截器识别为'人民广场店' → 索引 key 'sh_renmin'
✅ 五角场店：拦截器识别为'五角场店' → 索引 key 'sh_wujiaochang'
✅ 徐汇店：拦截器识别为'徐汇店' → 索引 key 'sh_xuhui'
✅ 北京店：拦截器识别为'北京店' → 索引 key 'beijing_chaoyang'
```

### 20 轮压力测试
```
场景分布:
- 单店地址：13 轮 → 全部拦截 ✅
- 多店地址：4 轮 → 全部不拦截 ✅
- 无地址：3 轮 → 全部不拦截 ✅

拦截规则验证:
✅ 单门店地址 → 拦截替换 + 触发对应门店地址图片
✅ 多门店地址 (2 个+) → 保留原文，不触发图片
✅ 无地址 → 保留原文，不触发图片
```

---

## 工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. LLM 生成回复（包含具体地址）                                   │
│    例："姐姐，静安店在愚园路 172 号环球世界大厦 A 座。"              │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. AddressInterceptor.intercept()                               │
│    - 匹配地址模式                                                │
│    - 去重匹配结果                                                │
│    - 判断是否拦截（match_count == 1）                              │
└─────────────────────┬───────────────────────────────────────────┘
                      │
         ┌────────────┴────────────┐
         │ 是，单门店地址          │ 否，多门店/无地址
         ▼                         ▼
┌────────────────────┐    ┌────────────────────┐
│ 3. 替换为占位符     │    │ 保留原文           │
│ "地址看图片中的位置"│    │ 不触发图片         │
└─────────┬──────────┘    └────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. 映射 target_store → store_key                                │
│    "静安店" → "sh_jingan"                                       │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. agent.pick_address_image(store_key, session_state)           │
│    - 获取该门店图片池                                            │
│    - 避开已发送的图片                                            │
│    - 随机选择一张                                                │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. 添加到 planned_media_items                                   │
│    {                                                            │
│      "type": "address_image",                                   │
│      "path": "/path/to/image.jpg",                              │
│      "target_store": "sh_jingan",                               │
│      "trigger_source": "address_interceptor"                    │
│    }                                                            │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. 发送给用户                                                   │
│    文本："姐姐，静安店在地址看图片中的位置。"                       │
│    图片：[静安店地址图片]                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 设计原则

1. **LLM-First**: 不干扰 LLM 正常输出，仅作为后处理器
2. **精准拦截**: 仅拦截单门店地址，多门店地址保留原文
3. **避重机制**: 已发送的图片不会重复选择
4. **兜底策略**: 上海门店图片不足时使用人民广场店图片兜底
5. **日志完整**: JSON 日志记录原始 LLM 输出，便于追溯

---

## 注意事项

1. **门店命名**: 拦截器返回的 `target_store` 是中文名称（如"静安店"），需要通过 `_interceptor_store_to_index_key` 映射到索引 key（如"sh_jingan"）
2. **地址图片文件命名**: 图片文件名应包含门店关键词（如"静安"、"虹口"等），以便 `_infer_store_from_name()` 正确推断
3. **避重依赖 session_state**: `address_image_sent_paths_by_store` 字段记录已发送的图片路径，需确保 `MemoryStore` 正确持久化

---

## 后续优化建议

1. **地址图片计数**: 在 `get_status()` 中增加各门店图片数量详情
2. **图片选择策略**: 当前为随机选择，可优化为轮询或最少使用优先
3. **地址模式扩展**: 如需支持更多地址模式，在 `STORE_ADDRESS_PATTERNS` 中添加即可
