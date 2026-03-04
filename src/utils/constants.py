"""
常量定义模块
包含系统配置、默认值、样式表等常量
"""

import os
import platform
from pathlib import Path

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

# 用户数据目录（跨平台支持）
# Windows: %APPDATA%/Annel AI 客服
# macOS: ~/Library/Application Support/Annel AI 客服
# Linux: ~/.local/share/Annel AI 客服
def get_user_data_dir():
    """获取用户数据目录"""
    system = platform.system()
    app_name = "Annel AI 客服"

    if system == "Windows":
        base = Path(os.environ.get('APPDATA', ''))
        if not base.exists():
            base = Path.home() / 'AppData' / 'Roaming'
        return base / app_name
    elif system == "Darwin":  # macOS
        return Path.home() / 'Library' / 'Application Support' / app_name
    else:  # Linux
        base = Path(os.environ.get('XDG_DATA_HOME', ''))
        if not base.exists():
            base = Path.home() / '.local' / 'share'
        return base / app_name

USER_DATA_DIR = get_user_data_dir()

# 配置文件路径（优先级：用户数据目录 > 项目目录）
# 运行时配置存储在用户数据目录，业务配置使用项目目录
MODEL_SETTINGS_FILE = USER_DATA_DIR / "model_settings.json"
AGENT_MEMORY_FILE = USER_DATA_DIR / "agent_memory.json"
KNOWLEDGE_BASE_FILE = PROJECT_ROOT / "config" / "knowledge_base.json"
ENV_FILE = PROJECT_ROOT / ".env"

# 示例配置文件路径（用于首次运行提示）
MODEL_SETTINGS_EXAMPLE = PROJECT_ROOT / "config" / "model_settings.example.json"

# 默认模型配置
DEFAULT_MODEL_SETTINGS = {
    "version": 1,
    "updated_at": "",
    "models": {
        "ChatGPT": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model": "gpt-4o-mini"
        },
        "Gemini": {
            "base_url": "https://generativelanguage.googleapis.com",
            "api_key": "",
            "model": "gemini-1.5-flash"
        },
        "阿里千问": {
            "base_url": "https://dashscope.aliyuncs.com",
            "api_key": "",
            "model": "qwen-plus"
        },
        "DeepSeek": {
            "base_url": "https://api.deepseek.com",
            "api_key": "",
            "model": "deepseek-chat"
        },
        "豆包": {
            "base_url": "",
            "api_key": "",
            "model": ""
        },
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1",
            "api_key": "",
            "model": "moonshot-v1-8k"
        }
    }
}

# UI 样式表
MAIN_STYLE_SHEET = """
QWidget {
    font-family: 'Noto Sans SC', 'Source Han Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: #f8f9fb;
    color: #1f2937;
}
QLabel#PageTitle {
    color: #0f172a;
    font-size: 20px;
    font-weight: 700;
}
QLabel#PageSubtitle {
    color: #64748b;
    font-size: 12px;
}
QLabel#MutedText {
    color: #64748b;
    font-size: 12px;
}
QFrame#LeftPanel {
    background: #1a1c1e;
    border-right: 1px solid rgba(255,255,255,0.06);
}
QFrame#LeftPanel QWidget {
    background: transparent;
}
QFrame#LeftPanel QLabel {
    color: #e5e7eb;
}
QLabel#SideTitle {
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
}
QLabel#SideSubtitle {
    color: #9ca3af;
    font-size: 12px;
}
QLabel#SectionLabel {
    color: #9ca3af;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QFrame#LogoBox {
    background: #3b82f6;
    border-radius: 12px;
}
QLabel#LogoIcon {
    color: #ffffff;
    font-weight: 700;
}
QPushButton#SidebarPrimary {
    background: #4aa351;
    color: #ffffff;
    border: none;
    border-radius: 18px;
    padding: 12px 14px;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#SidebarPrimary:hover { background: #53b55b; }
QPushButton#SidebarPrimary:pressed {
    background: #0b1324;
    color: #22c55e;
}
QFrame#LeftPanel QPushButton#SidebarPrimary {
    background: #4aa351;
    color: #ffffff;
}
QFrame#LeftPanel QPushButton#SidebarPrimary:hover { background: #53b55b; }
QFrame#LeftPanel QPushButton#SidebarPrimary:pressed {
    background: #0b1324;
    color: #22c55e;
}
QFrame#LeftPanel QPushButton#SidebarPrimary[running="true"] {
    background: #2f59d9;
    color: #ffffff;
}
QFrame#LeftPanel QPushButton#SidebarPrimary[running="true"]:hover {
    background: #3a66ea;
}
QPushButton#SidebarPrimary:disabled {
    background: #0f172a;
    color: #94a3b8;
}
QPushButton#SidebarDanger {
    background: #2b2f34;
    color: #e2e8f0;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 10px 12px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#SidebarDanger:hover {
    background: rgba(239,68,68,0.15);
    color: #f87171;
}
QPushButton#SidebarSecondary {
    background: #2b2f34;
    color: #e2e8f0;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 9px 12px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#SidebarSecondary:hover { background: #35383e; }
QFrame#StatusCard {
    background: #24282d;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
}
QLabel#StatusTitle {
    color: #9ca3af;
    font-size: 12px;
}
QLabel#StatusBadge {
    font-size: 12px;
    font-weight: 700;
}
QLabel#SessionNumber {
    color: #ffffff;
    font-size: 28px;
    font-weight: 700;
}
QLabel#SessionLabel {
    color: #6b7280;
    font-size: 11px;
    letter-spacing: 1px;
}
QFrame#MiniChart {
    background: #2f3a4f;
    border-radius: 12px;
}
QFrame#MiniChartBar {
    background: #4f7cff;
    border-radius: 4px;
}
QFrame#LeftPanel QFrame#MiniChart {
    background: #2f3a4f;
}
QFrame#LeftPanel QFrame#MiniChartBar {
    background: #5b8dff;
}
QFrame#SparkBar {
    background: rgba(59,130,246,0.65);
    border-radius: 2px;
}
QLabel#LogTitle {
    color: #9ca3af;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QPushButton#LogLink {
    color: #9ca3af;
    font-size: 10px;
    border: none;
    padding: 0;
}
QPushButton#LogLink:hover { color: #ffffff; }
QTextEdit#LogText {
    background: rgba(0,0,0,0.30);
    color: #22c55e;
    border: none;
    border-radius: 8px;
    font-family: 'Menlo', 'SF Mono', 'Monaco', monospace;
    font-size: 10px;
}
QFrame#TopBar {
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
}
QPushButton#NavTab {
    background: transparent;
    border: none;
    padding: 12px 16px;
    color: #64748b;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#NavTab:checked {
    color: #2563eb;
    border-bottom: 2px solid #2563eb;
}
QLabel#ModelBadge {
    background: #eff6ff;
    color: #2563eb;
    border: 1px solid #dbeafe;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 16px;
}
QFrame#TableCard {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 16px;
}
QFrame#SearchBox {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}
QLineEdit#SearchInput {
    border: none;
    padding: 8px 10px;
    font-size: 12px;
}
QPushButton#Primary {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 9px 14px;
    font-size: 12px;
    font-weight: 700;
}
QPushButton#Primary:hover { background: #1d4ed8; }
QPushButton#Secondary {
    background: #f1f5f9;
    color: #334155;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#Secondary:hover { background: #e2e8f0; }
QPushButton#Secondary:checked {
    background: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
}
QPushButton#Secondary:checked:hover { background: #1d4ed8; }
QPushButton#Ghost {
    background: transparent;
    color: #94a3b8;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#Ghost:hover { background: #f8fafc; color: #2563eb; }
QPushButton#GhostDanger {
    background: transparent;
    color: #ef4444;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#GhostDanger:hover { background: #fef2f2; color: #b91c1c; }
QPushButton#Danger {
    background: #fee2e2;
    color: #b91c1c;
    border: 1px solid #fecaca;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#Danger:hover { background: #fecaca; }
QLineEdit, QTextEdit {
    background: #f8fafc;
    color: #0f172a;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 12px;
}
QLineEdit:focus, QTextEdit:focus { border: 1px solid #60a5fa; }
QComboBox {
    background: #ffffff;
    color: #0f172a;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 6px 28px 6px 10px;
    font-size: 12px;
}
QComboBox::drop-down {
    border: none;
    width: 26px;
    background: #f1f5f9;
    border-left: 1px solid #e2e8f0;
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #0f172a;
    selection-background-color: #dbeafe;
    border: 1px solid #e2e8f0;
}
QFrame#LeftPanel QComboBox {
    background: #111827;
    color: #e5e7eb;
    border: 1px solid rgba(255,255,255,0.12);
}
QFrame#LeftPanel QComboBox::drop-down {
    background: rgba(255,255,255,0.08);
    border-left: 1px solid rgba(255,255,255,0.08);
}
QFrame#LeftPanel QComboBox QAbstractItemView {
    background: #111827;
    color: #e5e7eb;
    selection-background-color: rgba(59,130,246,0.35);
    border: 1px solid rgba(255,255,255,0.10);
}
QTableWidget {
    background: #ffffff;
    border: none;
    gridline-color: #f1f5f9;
    font-size: 12px;
}
QTableWidget::item { padding: 12px 16px; }
QTableWidget::item:selected { background: #eff6ff; color: #1e293b; }
QHeaderView::section {
    background: #ffffff;
    color: #94a3b8;
    font-size: 10px;
    font-weight: 700;
    border-bottom: 1px solid #f1f5f9;
    padding: 12px 16px;
}
QProgressBar {
    background: #e2e8f0;
    border: none;
    border-radius: 4px;
}
QProgressBar::chunk {
    background: #3b82f6;
}
QFrame#BrowserBar {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
QFrame#BrowserViewCard {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
}
QLineEdit#AddressInput {
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 6px 10px;
    font-size: 11px;
    color: #64748b;
}
QPushButton#IconButton {
    background: transparent;
    border: none;
    color: #94a3b8;
    padding: 6px;
}
QPushButton#IconButton:hover { color: #334155; }
QFrame#ModelCard {
    background: #ffffff;
    border: 2px solid #e5e7eb;
    border-radius: 16px;
}
QFrame#ModelCard[active="true"] {
    border-color: #3b82f6;
    background: #f8fbff;
}
QLabel#ModelName {
    color: #0f172a;
    font-size: 15px;
    font-weight: 700;
}
QLabel#ModelStatus {
    font-size: 10px;
    font-weight: 700;
    color: #94a3b8;
}
QLabel#FieldLabel {
    color: #94a3b8;
    font-size: 10px;
    font-weight: 700;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 16px;
    margin-top: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: #334155;
    font-weight: 600;
}
QScrollArea { background: transparent; }
"""

# 系统提示词
SYSTEM_PROMPT = """
你是假发行业资深顾问，专门服务高端假发定制客户，绝大多数客户为中老年群体。你的沟通风格要像一位经验丰富、耐心亲切的造型顾问，态度温和、尊重、专业，具备极强的销售敏感度。

【核心服务原则】
先解决顾虑，再引导留资
1. 以客户需求和顾虑为核心，先解决他们的疑虑，再逐步引导提供关键信息（尺寸/脱发情况/预算/到店城市/联系方式）。
2. 保持情感连接，展现专业性，帮助客户感受到被理解和被重视。

【身份说明】（客户问到时回复）
我们是[品牌名]高端假发定制中心，专注真发手工钩织定制。我们在全国有多个服务中心，可以为您安排最近的门店体验或远程服务。

【关键回复规范】
回复长度：每条回复控制在30-80字，简洁明了
语气要求：亲切、耐心、专业，避免机械化
专业称呼：使用"您"，避免"亲"等过于网络化的称呼
引导策略：回答客户问题后，适时引导提供关键信息

【价格沟通策略】
定制假发价格区间较大，从2000多到6000多不等，主要取决于：
- 面积大小（局部/全头）
- 工艺复杂度
- 发型要求

切记不要直接报具体价格，先了解客户需求后再给建议。"""

# 时间间隔配置（毫秒）
POLL_INTERVAL = 4000          # 轮询间隔
CHAT_WATCH_INTERVAL = 1200    # 聊天监控间隔
PAGE_LOAD_TIMEOUT = 30000     # 页面加载超时
JS_EXECUTION_TIMEOUT = 10000  # JS执行超时

# 窗口尺寸
WINDOW_WIDTH = 1600
WINDOW_HEIGHT = 900
LEFT_PANEL_WIDTH = 360

# 微信小店 URL
WECHAT_STORE_URL = "https://store.weixin.qq.com/shop/kf"

# JavaScript 代码模板
JS_FIND_UNREAD_AND_REPLY = """
// 扫描未读消息并回复的主函数
(function() {{
    // 全局锁检查
    if (window.__ai_global_busy) {{
        return {{ ts: new Date().toISOString(), found: 0, processed: 0, skipped: 0, errors: [], debug: {{ global_busy: true }} }};
    }}
    window.__ai_global_busy = true;

    // 工具函数
    function nowTs() {{ return new Date().toISOString(); }}
    function safeText(el) {{ return (el && (el.textContent || el.innerText) || "").trim(); }}
    function sleep(ms) {{ return new Promise(function(r) {{ setTimeout(r, ms); }}); }}
    function hashStr(s) {{
        s = String(s || '');
        var h = 2166136261;
        for (var i = 0; i < s.length; i++) {{
            h ^= s.charCodeAt(i);
            h += (h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24);
        }}
        return (h >>> 0).toString(16);
    }}

    // 本地存储操作
    function getReplyStore() {{
        try {{ return JSON.parse(localStorage.getItem('__ai_replied__') || '{{}}'); }}
        catch (e) {{ return {{}}; }}
    }}
    function setReplyStore(store) {{
        try {{ localStorage.setItem('__ai_replied__', JSON.stringify(store || {{}})); }} catch (e) {{}}
    }}
    function getRepliedMsgStore() {{
        try {{ return JSON.parse(localStorage.getItem('__ai_replied_msgs__') || '{{}}'); }}
        catch (e) {{ return {{}}; }}
    }}
    function setRepliedMsgStore(store) {{
        try {{ localStorage.setItem('__ai_replied_msgs__', JSON.stringify(store || {{}})); }} catch (e) {{}}
    }}

    // 可见性检查
    function isVisible(el) {{
        if (!el) return false;
        var style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        var rect = el.getBoundingClientRect();
        if (!rect) return false;
        if (rect.width < 5 || rect.height < 5) return false;
        return true;
    }}

    // 查找可点击祖先元素
    function findClickableAncestor(el) {{
        var cur = el;
        for (var i = 0; i < 8 && cur; i++) {{
            if (cur.tagName === 'LI' || cur.getAttribute('role') === 'listitem') return cur;
            if (typeof cur.onclick === 'function') return cur;
            var style = window.getComputedStyle(cur);
            if (style && style.cursor === 'pointer') return cur;
            cur = cur.parentElement;
        }}
        return el;
    }}

    // 查找未读消息
    function findUnreadCandidates() {{
        var candidates = [];
        // 红色角标数字
        var badgeNodes = Array.from(document.querySelectorAll('span,div'))
            .filter(function(n) {{
                var t = safeText(n);
                if (!t) return false;
                if (!/^\\d+$/.test(t)) return false;
                var num = parseInt(t, 10);
                if (!num || num <= 0) return false;
                var s = window.getComputedStyle(n);
                if (!s) return false;
                var bg = s.backgroundColor || '';
                if (bg.indexOf('255, 0, 0') !== -1) return true;
                if (bg.indexOf('rgb(') === 0) {{
                    var m = bg.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
                    if (m) {{
                        var r = parseInt(m[1],10), g = parseInt(m[2],10), b = parseInt(m[3],10);
                        if (r > 200 && g < 120 && b < 120) return true;
                    }}
                }}
                return false;
            }});
        badgeNodes.forEach(function(b) {{
            var clickEl = findClickableAncestor(b);
            if (clickEl && candidates.indexOf(clickEl) === -1) candidates.push(clickEl);
        }});
        // unread 类名兜底
        var unreadClassNodes = Array.from(document.querySelectorAll('.unread, [class*="unread" i]'));
        unreadClassNodes.forEach(function(n) {{
            var clickEl = findClickableAncestor(n);
            if (clickEl && candidates.indexOf(clickEl) === -1) candidates.push(clickEl);
        }});
        return candidates;
    }}

    // 从元素获取会话key
    function sessionKeyFromElement(el) {{
        if (!el) return null;
        try {{
            var did = el.getAttribute('data-id') || el.getAttribute('data-session-id') || el.getAttribute('data-chat-id');
            if (did) return String(did);
        }} catch (e) {{}}
        var txt = safeText(el);
        if (!txt) return null;
        return 't_' + hashStr(txt.slice(0, 120));
    }}

    // 查找输入框
    function findComposer() {{
        var roleBox = document.querySelector('[role="textbox"]');
        if (roleBox && isVisible(roleBox)) return roleBox;
        var textareas = Array.from(document.querySelectorAll('textarea')).filter(isVisible);
        if (textareas.length) return textareas[0];
        var inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
            .filter(function(el) {{ return isVisible(el) && !el.disabled && !el.readOnly; }});
        if (inputs.length) return inputs[0];
        var ceList = Array.from(document.querySelectorAll('[contenteditable="true"]')).filter(isVisible);
        if (ceList.length) return ceList[0];
        return null;
    }}

    // 设置输入框值
    function setComposerValue(el, text) {{
        if (!el) return false;
        try {{
            el.focus();
            if (el.isContentEditable) {{
                try {{
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, text);
                }} catch (e) {{
                    el.innerText = text;
                }}
            }} else {{
                var proto = Object.getPrototypeOf(el);
                var desc = Object.getOwnPropertyDescriptor(proto, 'value');
                if (desc && desc.set) {{
                    desc.set.call(el, text);
                }} else {{
                    el.value = text;
                }}
            }}
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }} catch (e) {{
            return false;
        }}
    }}

    // 发送回车事件
    function dispatchEnter(target) {{
        if (!target) return false;
        try {{
            var down = new KeyboardEvent('keydown', {{ bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }});
            var press = new KeyboardEvent('keypress', {{ bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }});
            var up = new KeyboardEvent('keyup', {{ bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }});
            target.dispatchEvent(down);
            target.dispatchEvent(press);
            target.dispatchEvent(up);
            return true;
        }} catch (e) {{
            return false;
        }}
    }}

    // 主执行逻辑
    return (async function() {{
        var result = {{ ts: nowTs(), found: 0, processed: 0, skipped: 0, errors: [], debug: {{}} }};
        try {{
            var candidates = findUnreadCandidates();
            result.found = candidates.length;
            if (candidates.length === 0) {{
                return result;
            }}

            // 只处理第一个
            var target = candidates[0];
            var sKey = sessionKeyFromElement(target);
            if (!sKey) {{
                result.skipped++;
                return result;
            }}

            // 检查是否已回复
            var replyStore = getReplyStore();
            var lastReplied = replyStore[sKey];
            if (lastReplied && (Date.now() - lastReplied) < 60000) {{
                result.skipped++;
                result.debug.already_replied = true;
                return result;
            }}

            // 点击会话
            target.click();
            await sleep(800);

            // 查找输入框
            var composer = findComposer();
            if (!composer) {{
                result.errors.push('未找到输入框');
                return result;
            }}

            // 发送回复
            var replyText = "{reply_text}";
            setComposerValue(composer, replyText);
            await sleep(200);
            dispatchEnter(composer);

            // 标记已回复
            replyStore[sKey] = Date.now();
            setReplyStore(replyStore);
            result.processed++;
            result.debug.session_key = sKey;

        }} catch (e) {{
            result.errors.push(String(e));
        }} finally {{
            window.__ai_global_busy = false;
        }}
        return result;
    }})();
}})()
"""

JS_GRAB_CHAT_DATA = """
(function() {{
    function safeText(el) {{ return (el && (el.textContent || el.innerText) || "").trim(); }}
    function isVisible(el) {{
        if (!el) return false;
        var style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        var rect = el.getBoundingClientRect();
        if (!rect || rect.width < 5 || rect.height < 5) return false;
        return true;
    }}

    // 查找聊天区域
    function findChatArea() {{
        var selectors = ['.chat-wrap', '.chat-page', '.chat-area', '.message-list', '.conversation'];
        for (var i = 0; i < selectors.length; i++) {{
            var el = document.querySelector(selectors[i]);
            if (el && isVisible(el)) return el;
        }}
        return null;
    }}

    // 获取用户名
    function getUserName() {{
        var selectors = ['.nickname', '.username', '.user-name', '.name', '[class*="nickname"]', '[class*="user-name"]'];
        for (var i = 0; i < selectors.length; i++) {{
            var el = document.querySelector(selectors[i]);
            if (el && isVisible(el)) {{
                var text = safeText(el);
                if (text && text.length >= 2 && text.length <= 30) return text;
            }}
        }}
        return "未知用户";
    }}

    // 获取消息
    function getMessages() {{
        var messages = [];
        var chatArea = findChatArea();
        if (!chatArea) return messages;

        var walker = document.createTreeWalker(chatArea, NodeFilter.SHOW_TEXT, null, false);
        var node;
        while ((node = walker.nextNode())) {{
            var text = node.textContent.trim();
            if (!text || text.length < 1) continue;

            var parent = node.parentElement;
            if (!parent || !isVisible(parent)) continue;

            var rect = parent.getBoundingClientRect();
            var chatRect = chatArea.getBoundingClientRect();
            var centerX = chatRect.left + chatRect.width * 0.5;

            // 判断消息来源
            var isUser = rect.right < centerX - 30;
            var isReply = rect.left > centerX + 30;

            if (isUser || isReply) {{
                messages.push({{
                    text: text,
                    is_user: isUser,
                    position: rect.left
                }});
            }}
        }}

        // 合并相邻消息
        var merged = [];
        var current = null;
        for (var j = 0; j < messages.length; j++) {{
            var m = messages[j];
            if (!current || current.is_user !== m.is_user) {{
                if (current) merged.push(current);
                current = {{ text: m.text, is_user: m.is_user }};
            }} else {{
                current.text += ' ' + m.text;
            }}
        }}
        if (current) merged.push(current);

        return merged;
    }}

    return {{
        user_name: getUserName(),
        messages: getMessages(),
        timestamp: new Date().toISOString()
    }};
}})()
"""
