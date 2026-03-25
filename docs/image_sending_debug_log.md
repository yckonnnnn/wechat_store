# WeChat 图片自动发送功能调试记录

## 概述

本文档记录了在实现微信客服系统中"自动发送图片"功能时遇到的问题、尝试的解决方案，以及最终成功的解决过程。

## 功能需求

当用户发送包含特定关键词（如"地址在哪里"）的消息时，系统需要自动发送一张预设的图片作为回复，跳过大模型处理。

## 技术背景

- **框架**: PySide6 (Qt for Python)
- **浏览器组件**: QWebEngineView (基于 Chromium)
- **目标网站**: 微信客服网页版

## 问题描述

微信网页版的图片发送流程是一个**两步操作**：
1. 点击图片按钮，选择文件
2. 弹出确认对话框，需要点击"发送 (1)"按钮或按 Enter 键确认

原始代码只完成了第一步，没有处理确认弹窗，导致图片无法实际发送出去。

---

## 调试历程

### 阶段一：JavaScript 点击方案（失败）

**尝试方法**：
```javascript
// 尝试用 JavaScript 直接点击发送按钮
document.querySelector('button.weui-desktop-btn_primary').click();
```

**失败原因**：
- JavaScript 触发的 `click()` 事件是"不可信事件"（untrusted event）
- 现代 Web 框架（如 Vue/React）可以区分真实用户点击和脚本模拟的点击
- 网页可以通过 `event.isTrusted` 属性检测并忽略合成事件

### 阶段二：JavaScript 模拟键盘事件（失败）

**尝试方法**：
```javascript
// 尝试用 JavaScript 模拟 Enter 键
document.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter',
    keyCode: 13,
    bubbles: true
}));
```

**失败原因**：
- 同样的问题：JavaScript 创建的 KeyboardEvent 也是不可信事件
- 浏览器安全机制阻止脚本模拟用户输入

### 阶段三：Qt 原生键盘事件（部分成功）

**尝试方法**：
```python
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import Qt, QCoreApplication

key_press = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
QCoreApplication.sendEvent(self.web_view.focusProxy(), key_press)
```

**结果**：Enter 键事件没有生效

**失败原因分析**：
- 此时图片按钮还是用 JavaScript `click()` 触发的
- JavaScript 的点击可能没有正确打开文件选择对话框
- 或者触发了但焦点不在正确的位置

### 阶段四：Qt 原生鼠标点击 + 按钮检测（部分成功）

**尝试方法**：
```python
from PySide6.QtGui import QMouseEvent

# 获取按钮位置后，使用 Qt 原生鼠标点击
press_event = QMouseEvent(
    QMouseEvent.MouseButtonPress,
    local_pos, global_pos_f,
    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
)
QCoreApplication.sendEvent(target_widget, press_event)
```

**结果**：
- ✅ Qt 鼠标点击**成功触发**了图片按钮，弹出了确认对话框
- ❌ 但后续点击"发送"按钮失败

**失败原因**：
1. **按钮检测错误**：页面上有多个包含"发送"文字的按钮
   - 正确按钮：弹窗内的 `发送 (1)`
   - 错误按钮：页面右侧的 `发送优惠券`

2. **坐标返回 (0,0)**：`getBoundingClientRect()` 返回了无效坐标，可能是因为：
   - 弹窗还未完全渲染
   - 找到的是隐藏的按钮

3. **时间问题**：设置了 3 秒延迟，但弹窗实际上只停留约 1 秒就自动关闭了

### 阶段五：简化方案 - Qt 鼠标点击 + Qt Enter 键（成功！）

**最终解决方案**：

```python
def send_image(self, image_path: str, callback: Callable = None):
    """发送图片 - 使用 Qt 原生鼠标点击和键盘事件"""

    # Step 1: 用 JavaScript 获取图片按钮位置
    # Step 2: 用 Qt 原生鼠标点击图片按钮
    # Step 3: 等待 500ms 让弹窗出现
    # Step 4: 发送 Qt 原生 Enter 键确认发送

    def send_enter_key():
        self.web_view.setFocus()
        target_widget = self.web_view.focusProxy()

        key_press = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        QCoreApplication.sendEvent(target_widget, key_press)

        key_release = QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Return, Qt.NoModifier)
        QCoreApplication.sendEvent(target_widget, key_release)

    # 等待 500ms（弹窗只停留约 1 秒，要快！）
    QTimer.singleShot(500, send_enter_key)
```

**成功关键点**：
1. **全程使用 Qt 原生事件**：鼠标点击和键盘事件都使用 Qt API，产生"可信事件"
2. **正确的时间控制**：延迟从 3 秒改为 500ms，在弹窗关闭前发送 Enter
3. **简化逻辑**：放弃复杂的按钮检测，直接用 Enter 键确认（和用户手动操作一致）

---

## 核心教训

### 1. 浏览器安全机制

| 事件类型 | `isTrusted` | 能否触发 UI 操作 |
|---------|-------------|----------------|
| JavaScript 合成事件 | `false` | ❌ 可能被忽略 |
| Qt 原生事件 | N/A (底层) | ✅ 被视为真实用户输入 |

### 2. QWebEngineView 的事件目标

```python
# 错误：直接发送到 web_view
QCoreApplication.sendEvent(self.web_view, event)

# 正确：发送到 focusProxy()（实际处理输入的子组件）
target_widget = self.web_view.focusProxy()
QCoreApplication.sendEvent(target_widget, event)
```

### 3. 时间控制的重要性

- 延迟太短：弹窗还未出现
- 延迟太长：弹窗已经关闭
- 最终方案：500ms 是最佳平衡点

### 4. 简单方案往往更可靠

复杂的按钮检测逻辑容易出错：
- 页面上可能有多个相似按钮
- 动态渲染的元素坐标可能不准确
- Enter 键是更通用、更可靠的确认方式

---

## 最终代码流程

```
┌─────────────────────────────────────────────────────┐
│  1. JavaScript 获取图片按钮位置                      │
│     document.querySelector('div[title="图片"]')     │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│  2. Qt 原生鼠标点击图片按钮                          │
│     QMouseEvent → QCoreApplication.sendEvent()      │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│  3. 等待 500ms                                      │
│     QTimer.singleShot(500, send_enter_key)          │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│  4. Qt 原生 Enter 键确认发送                         │
│     QKeyEvent → QCoreApplication.sendEvent()        │
└─────────────────────────────────────────────────────┘
```

---

## 相关文件

- `src/services/browser_service.py` - `send_image()` 方法
- `src/core/message_processor.py` - `_send_image()` 调用和日志记录

## 日期

- 调试开始：2026-02-06 11:00
- 成功解决：2026-02-06 12:03
- 总耗时：约 1 小时
