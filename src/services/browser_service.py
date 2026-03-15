"""
浏览器服务模块
负责与QWebEngineView的交互，注入JavaScript执行页面操作
"""

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from PySide6.QtCore import QObject, Signal, QTimer, Qt, QCoreApplication, QPointF
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QWidget


class BrowserService(QObject):
    """浏览器服务，封装QWebEngineView的操作"""

    page_loaded = Signal(bool)          # 页面加载完成
    message_received = Signal(dict)     # 收到消息
    js_execution_result = Signal(str, object)  # JS执行结果 (id, result)
    error_occurred = Signal(str)        # 错误信号
    url_changed = Signal(str)           # URL变化信号

    def __init__(self, web_view: QWebEngineView):
        super().__init__()
        self.web_view = web_view
        self.page = web_view.page()
        self._page_ready = False
        self._pending_callbacks: dict = {}
        self._last_url = ""
        self.media_debug_hook: Optional[Callable[[Dict[str, Any]], None]] = None

        # 配置浏览器设置
        self._setup_browser()

        # 连接信号
        self.page.loadFinished.connect(self._on_load_finished)
        self.page.urlChanged.connect(self._on_url_changed)
    
    def _on_url_changed(self, url: QUrl):
        """URL变化回调"""
        url_str = url.toString()
        if url_str != self._last_url:
            self._last_url = url_str
            self.url_changed.emit(url_str)

    def _setup_browser(self):
        """配置浏览器设置"""
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.web_view.setMouseTracking(True)
        focus_proxy = self.web_view.focusProxy()
        if focus_proxy is not None:
            focus_proxy.setMouseTracking(True)

    def _on_load_finished(self, success: bool):
        """页面加载完成回调"""
        self._page_ready = success
        self.page_loaded.emit(success)

    def navigate(self, url: str):
        """导航到指定URL"""
        self._page_ready = False
        self.web_view.setUrl(QUrl(url))

    def reload(self):
        """刷新页面"""
        self.web_view.reload()

    def is_ready(self) -> bool:
        """检查页面是否加载完成"""
        return self._page_ready

    def run_javascript(self, script: str, callback: Callable = None,
                       timeout_ms: int = 10000) -> Optional[str]:
        """执行JavaScript代码

        Args:
            script: JavaScript代码
            callback: 回调函数，接收执行结果 (success, data/error)
            timeout_ms: 超时时间（毫秒）

        Returns:
            如果没有callback，返回执行ID用于追踪
        """
        import uuid
        exec_id = str(uuid.uuid4())[:8]

        if callback:
            self._pending_callbacks[exec_id] = callback

            def handle_result(result):
                if exec_id in self._pending_callbacks:
                    cb = self._pending_callbacks.pop(exec_id)
                    # JavaScript 执行成功，将结果传递给 callback
                    # result 可能是 dict, list, str, int, None 等
                    # 如果是字符串且以 { 开头，尝试解析 JSON
                    if isinstance(result, str) and result.strip().startswith('{'):
                        try:
                            import json as json_mod
                            parsed = json_mod.loads(result)
                            cb(True, parsed)
                        except Exception:
                            cb(True, result)
                    else:
                        cb(True, result)

            # PySide6 的 runJavaScript 可以直接接受回调函数
            # 它会在 JavaScript 执行完成并序列化结果后调用回调
            try:
                self.page.runJavaScript(script, handle_result)
            except Exception as e:
                if exec_id in self._pending_callbacks:
                    self._pending_callbacks.pop(exec_id)
                callback(False, str(e))

            # 设置超时
            if timeout_ms > 0:
                QTimer.singleShot(timeout_ms, lambda: self._on_timeout(exec_id))

            return exec_id
        else:
            # 没有回调，直接执行
            self.page.runJavaScript(script)
            return exec_id

    def _on_timeout(self, exec_id: str):
        """处理超时"""
        if exec_id in self._pending_callbacks:
            callback = self._pending_callbacks.pop(exec_id)
            callback(False, "执行超时")

    def _parse_js_payload(self, payload: Any) -> Dict[str, Any]:
        """统一解析 runJavaScript 返回结果。"""
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        return {}

    def _emit_media_debug(
        self,
        message: str,
        *,
        media_type: str = "delayed_video",
        level: str = "info",
        step: str = "",
        **extra: Any,
    ) -> None:
        hook = getattr(self, "media_debug_hook", None)
        if not callable(hook):
            return
        payload: Dict[str, Any] = {
            "message": str(message or ""),
            "media_type": str(media_type or ""),
            "level": str(level or "info"),
            "step": str(step or ""),
        }
        payload.update(extra)
        try:
            hook(payload)
        except Exception:
            return

    def _native_left_click(self, x: float, y: float) -> tuple[bool, str]:
        """在 WebView 内发送原生左键点击。"""
        try:
            target_widget = self.web_view.focusProxy() or self.web_view
            local_pos = QPointF(float(x), float(y))
            global_pos = target_widget.mapToGlobal(local_pos.toPoint())
            global_pos_f = QPointF(global_pos.x(), global_pos.y())

            press_event = QMouseEvent(
                QMouseEvent.MouseButtonPress,
                local_pos,
                global_pos_f,
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            QCoreApplication.sendEvent(target_widget, press_event)

            release_event = QMouseEvent(
                QMouseEvent.MouseButtonRelease,
                local_pos,
                global_pos_f,
                Qt.LeftButton,
                Qt.NoButton,
                Qt.NoModifier,
            )
            QCoreApplication.sendEvent(target_widget, release_event)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _native_mouse_move(self, x: float, y: float) -> tuple[bool, str]:
        """在 WebView 内发送原生鼠标移动，用于触发真实 hover。"""
        try:
            target_widget = self.web_view.focusProxy() or self.web_view
            target_widget.setMouseTracking(True)
            local_pos = QPointF(float(x), float(y))
            global_pos = target_widget.mapToGlobal(local_pos.toPoint())
            global_pos_f = QPointF(global_pos.x(), global_pos.y())

            move_event = QMouseEvent(
                QMouseEvent.MouseMove,
                local_pos,
                global_pos_f,
                Qt.NoButton,
                Qt.NoButton,
                Qt.NoModifier,
            )
            QCoreApplication.sendEvent(target_widget, move_event)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _native_mouse_drag_move(self, x: float, y: float) -> tuple[bool, str]:
        """在按住左键状态下发送原生鼠标移动，用于真实拖拽。"""
        try:
            target_widget = self.web_view.focusProxy() or self.web_view
            target_widget.setMouseTracking(True)
            local_pos = QPointF(float(x), float(y))
            global_pos = target_widget.mapToGlobal(local_pos.toPoint())
            global_pos_f = QPointF(global_pos.x(), global_pos.y())

            move_event = QMouseEvent(
                QMouseEvent.MouseMove,
                local_pos,
                global_pos_f,
                Qt.NoButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            QCoreApplication.sendEvent(target_widget, move_event)
            QCoreApplication.processEvents()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _native_left_press(self, x: float, y: float) -> tuple[bool, str]:
        """在 WebView 内发送原生左键按下。"""
        try:
            target_widget = self.web_view.focusProxy() or self.web_view
            local_pos = QPointF(float(x), float(y))
            global_pos = target_widget.mapToGlobal(local_pos.toPoint())
            global_pos_f = QPointF(global_pos.x(), global_pos.y())

            press_event = QMouseEvent(
                QMouseEvent.MouseButtonPress,
                local_pos,
                global_pos_f,
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            QCoreApplication.sendEvent(target_widget, press_event)
            QCoreApplication.processEvents()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _native_left_release(self, x: float, y: float) -> tuple[bool, str]:
        """在 WebView 内发送原生左键释放。"""
        try:
            source_widget = self.web_view.focusProxy() or self.web_view
            source_local_pos = QPointF(float(x), float(y))
            global_pos = source_widget.mapToGlobal(source_local_pos.toPoint())
            target_widget = QApplication.widgetAt(global_pos) or source_widget
            local_point = target_widget.mapFromGlobal(global_pos)
            local_pos = QPointF(float(local_point.x()), float(local_point.y()))
            global_pos_f = QPointF(global_pos.x(), global_pos.y())

            release_event = QMouseEvent(
                QMouseEvent.MouseButtonRelease,
                local_pos,
                global_pos_f,
                Qt.LeftButton,
                Qt.NoButton,
                Qt.NoModifier,
            )
            QCoreApplication.sendEvent(target_widget, release_event)
            grabber = QWidget.mouseGrabber()
            if grabber is not None:
                grabber.releaseMouse()
            source_widget.releaseMouse()
            if target_widget is not source_widget:
                target_widget.releaseMouse()
            QCoreApplication.processEvents()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _native_hover_sweep(self, x: float, y: float) -> tuple[bool, str]:
        """在目标点附近做一次轻微悬停扫过，提升 hover-only 控件触发率。"""
        offsets = [
            (0, 0),
            (-8, -6),
            (8, -6),
            (0, 0),
            (6, 6),
            (0, 0),
        ]
        last_error = ""
        moved = False
        for dx, dy in offsets:
            ok, err = self._native_mouse_move(float(x) + dx, float(y) + dy)
            if ok:
                moved = True
            elif err:
                last_error = err
        return moved, last_error

    def _native_drag_and_drop(self, start_x: float, start_y: float, end_x: float, end_y: float) -> tuple[bool, str]:
        """在 WebView 内执行原生拖拽。"""
        self._native_mouse_move(start_x, start_y)
        QCoreApplication.processEvents()
        pressed, err = self._native_left_press(start_x, start_y)
        if not pressed:
            return False, err

        time.sleep(0.08)
        # 先跨过拖拽阈值，避免页面把它当作普通点击。
        self._native_mouse_drag_move(start_x + 4, start_y + 4)
        QCoreApplication.processEvents()
        time.sleep(0.03)

        last_err = ""
        steps = 18
        for idx in range(1, steps + 1):
            ratio = idx / steps
            x = start_x + (end_x - start_x) * ratio
            y = start_y + (end_y - start_y) * ratio
            moved, move_err = self._native_mouse_drag_move(x, y)
            if not moved and move_err:
                last_err = move_err
            QCoreApplication.processEvents()
            time.sleep(0.01)

        released, release_err = self._native_left_release(end_x, end_y)
        if not released:
            return False, release_err

        # 仅发送 release 还不够稳定，补一个“松手后的无按键轻微移动”，
        # 模拟人工松开鼠标后的自然收手动作，避免页面一直停留在拖拽态。
        QCoreApplication.processEvents()
        time.sleep(0.02)
        settle_points = [
            (end_x - 4.0, end_y),
            (end_x - 8.0, end_y + 2.0),
            (end_x - 2.0, end_y - 2.0),
        ]
        for settle_x, settle_y in settle_points:
            self._native_mouse_move(settle_x, settle_y)
            QCoreApplication.processEvents()
            time.sleep(0.015)
        QCoreApplication.processEvents()
        time.sleep(0.05)
        return True, last_err

    def _native_press_enter(self) -> tuple[bool, str]:
        """在 WebView 内发送原生 Enter 键。"""
        try:
            self.web_view.setFocus()
            target_widget = self.web_view.focusProxy() or self.web_view

            key_press = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
            QCoreApplication.sendEvent(target_widget, key_press)

            key_release = QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Return, Qt.NoModifier)
            QCoreApplication.sendEvent(target_widget, key_release)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _get_media_dialog_state(self, callback: Callable):
        """检测媒体发送确认弹窗状态。"""
        script = r"""
        (function() {
            function safeText(el) {
                return (el && (el.textContent || el.innerText) || "").trim();
            }
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }
            function collectDialogRoots() {
                var selectors = [
                    '.weui-desktop-dialog__wrp',
                    '.weui-desktop-dialog_wrp',
                    '.weui-desktop-dialog',
                    '.weui-desktop-dialog__ft',
                    '.weui-desktop-dialog__bd',
                    '.weui-desktop-modal',
                    '.weui-dialog',
                    '.modal',
                    '.dialog',
                    '[role="dialog"]',
                    '[class*="dialog"]',
                    '[class*="modal"]'
                ];
                var roots = [];
                for (var s = 0; s < selectors.length; s++) {
                    var nodes = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < nodes.length; i++) {
                        var node = nodes[i];
                        if (!isVisible(node)) continue;
                        if (roots.indexOf(node) === -1) {
                            roots.push(node);
                        }
                    }
                }
                return roots;
            }
            function rankSendButtonCandidates(nodes) {
                var candidates = [];
                for (var j = 0; j < nodes.length; j++) {
                    var node = nodes[j];
                    var text = safeText(node).replace(/\s+/g, '');
                    if (!text || !/^发送/.test(text)) continue;
                    if (text.indexOf('优惠券') !== -1) continue;
                    var rect = node.getBoundingClientRect();
                    if (!rect || rect.width < 20 || rect.height < 16) continue;
                    candidates.push({
                        text: text,
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                        area: rect.width * rect.height,
                        bottomBias: rect.top + rect.height / 2,
                        rightBias: rect.left + rect.width / 2
                    });
                }
                if (!candidates.length) {
                    return { found: false };
                }
                candidates.sort(function(a, b) {
                    var aHasCount = /\(\d+\)/.test(a.text);
                    var bHasCount = /\(\d+\)/.test(b.text);
                    if (aHasCount !== bHasCount) return aHasCount ? -1 : 1;
                    if (Math.abs(a.bottomBias - b.bottomBias) > 8) return b.bottomBias - a.bottomBias;
                    if (Math.abs(a.rightBias - b.rightBias) > 8) return b.rightBias - a.rightBias;
                    return b.area - a.area;
                });
                return {
                    found: true,
                    text: candidates[0].text,
                    x: candidates[0].x,
                    y: candidates[0].y
                };
            }
            function findSendButtonInDialogs(dialogRoots) {
                var scopedNodes = [];
                for (var i = 0; i < dialogRoots.length; i++) {
                    var root = dialogRoots[i];
                    var nodes = Array.from(root.querySelectorAll('button, [role="button"], a, div, span')).filter(isVisible);
                    scopedNodes = scopedNodes.concat(nodes);
                }
                var ranked = rankSendButtonCandidates(scopedNodes);
                if (ranked.found) return ranked;

                var globalNodes = Array.from(document.querySelectorAll('button, [role="button"], a, div, span')).filter(isVisible);
                return rankSendButtonCandidates(globalNodes);
            }

            var dialogRoots = collectDialogRoots();
            var sendBtn = findSendButtonInDialogs(dialogRoots);
            return JSON.stringify({
                found: true,
                dialog_visible: dialogRoots.length > 0 || !!sendBtn.found,
                dialog_count: dialogRoots.length,
                send_button_in_dialog_visible: !!sendBtn.found,
                send_button_text: sendBtn.text || '',
                send_button_x: sendBtn.x || 0,
                send_button_y: sendBtn.y || 0
            });
        })()
        """
        self.run_javascript(script, callback)

    def _get_chat_media_signature(self, callback: Callable):
        """抓取当前会话媒体发送签名，用于确认图片是否真正发出。"""
        script = r"""
        (function() {
            function safeText(el) {
                return (el && (el.textContent || el.innerText) || "").trim();
            }
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }
            function hasMediaNode(item) {
                var mediaClass = item.querySelector(
                    '.img-msg, .image-msg, .video-msg, [class*="img-msg"], [class*="image-msg"], [class*="video-msg"], [class*="img_msg"], [class*="image_msg"], [class*="video_msg"]'
                );
                if (mediaClass) return true;

                var nodes = Array.from(item.querySelectorAll('img,video,canvas'));
                for (var i = 0; i < nodes.length; i++) {
                    var node = nodes[i];
                    var cls = String(node.className || '').toLowerCase();
                    var src = String((node.getAttribute && node.getAttribute('src')) || '').toLowerCase();
                    var token = cls + ' ' + src;
                    if (token.indexOf('avatar') !== -1 || token.indexOf('head') !== -1 || token.indexOf('profile') !== -1) {
                        continue;
                    }
                    var parentToken = '';
                    if (node.parentElement) {
                        parentToken = String(node.parentElement.className || '').toLowerCase();
                    }
                    if (parentToken.indexOf('avatar') !== -1 || parentToken.indexOf('head') !== -1 || parentToken.indexOf('profile') !== -1) {
                        continue;
                    }
                    var rect = node.getBoundingClientRect();
                    if (rect && rect.width >= 72 && rect.height >= 60) {
                        return true;
                    }
                }
                return false;
            }
            function collectDialogRoots() {
                var selectors = [
                    '.weui-desktop-dialog__wrp',
                    '.weui-desktop-dialog_wrp',
                    '.weui-desktop-dialog',
                    '.weui-desktop-modal',
                    '.weui-dialog',
                    '.modal',
                    '.dialog',
                    '[role="dialog"]'
                ];
                var roots = [];
                for (var s = 0; s < selectors.length; s++) {
                    var nodes = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < nodes.length; i++) {
                        var node = nodes[i];
                        if (!isVisible(node)) continue;
                        if (roots.indexOf(node) === -1) {
                            roots.push(node);
                        }
                    }
                }
                return roots;
            }
            function findMediaSendButton(dialogRoots) {
                var candidates = [];
                for (var i = 0; i < dialogRoots.length; i++) {
                    var root = dialogRoots[i];
                    var nodes = Array.from(root.querySelectorAll('button, [role="button"], a, div, span')).filter(isVisible);
                    for (var j = 0; j < nodes.length; j++) {
                        var node = nodes[j];
                        var text = safeText(node).replace(/\s+/g, '');
                        if (!text || !/^发送/.test(text)) continue;
                        if (text.indexOf('优惠券') !== -1) continue;
                        var rect = node.getBoundingClientRect();
                        if (!rect || rect.width < 20 || rect.height < 16) continue;
                        candidates.push({
                            text: text,
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2,
                            area: rect.width * rect.height
                        });
                    }
                }
                if (!candidates.length) {
                    return { found: false };
                }
                candidates.sort(function(a, b) {
                    var aHasCount = /\(\d+\)/.test(a.text);
                    var bHasCount = /\(\d+\)/.test(b.text);
                    if (aHasCount !== bHasCount) return aHasCount ? -1 : 1;
                    return b.area - a.area;
                });
                return {
                    found: true,
                    text: candidates[0].text,
                    x: candidates[0].x,
                    y: candidates[0].y
                };
            }

            var chatScrollView = document.getElementById('chat-scroll-view') || document.querySelector('.chat-scroll-view');
            var dialogRoots = collectDialogRoots();
            var pendingBtn = findMediaSendButton(dialogRoots);
            if (!chatScrollView) {
                return JSON.stringify({
                    found: false,
                    error: '未找到聊天滚动容器',
                    dialog_visible: dialogRoots.length > 0,
                    pending_media_send_visible: !!pendingBtn.found,
                    pending_media_send_text: pendingBtn.text || ''
                });
            }

            var items = Array.from(chatScrollView.querySelectorAll('.message-item')).filter(isVisible);
            var kfItems = items.filter(function(item) {
                return (item.className || '').indexOf('justify-end') !== -1;
            });

            var kfMediaCount = 0;
            var lastKfText = '';
            var lastKfHasText = false;
            for (var i = 0; i < kfItems.length; i++) {
                var item = kfItems[i];
                var textEl = item.querySelector('.text-msg');
                var text = safeText(textEl);
                var hasText = !!text;
                if (hasMediaNode(item)) {
                    kfMediaCount += 1;
                }
                lastKfText = text;
                lastKfHasText = hasText;
            }

            return JSON.stringify({
                found: true,
                total_count: items.length,
                kf_total_count: kfItems.length,
                kf_media_count: kfMediaCount,
                last_kf_text: lastKfText,
                last_kf_has_text: lastKfHasText,
                dialog_visible: dialogRoots.length > 0,
                pending_media_send_visible: !!pendingBtn.found,
                pending_media_send_text: pendingBtn.text || ''
            });
        })()
        """
        self.run_javascript(script, callback)

    def _find_media_send_button(self, callback: Callable):
        """查找媒体确认发送按钮位置。"""
        script = r"""
        (function() {
            function safeText(el) {
                return (el && (el.textContent || el.innerText) || "").trim();
            }
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }
            function collectDialogRoots() {
                var selectors = [
                    '.weui-desktop-dialog__wrp',
                    '.weui-desktop-dialog_wrp',
                    '.weui-desktop-dialog',
                    '.weui-desktop-dialog__ft',
                    '.weui-desktop-dialog__bd',
                    '.weui-desktop-modal',
                    '.weui-dialog',
                    '.modal',
                    '.dialog',
                    '[role="dialog"]',
                    '[class*="dialog"]',
                    '[class*="modal"]'
                ];
                var roots = [];
                for (var s = 0; s < selectors.length; s++) {
                    var nodes = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < nodes.length; i++) {
                        var node = nodes[i];
                        if (!isVisible(node)) continue;
                        if (roots.indexOf(node) === -1) {
                            roots.push(node);
                        }
                    }
                }
                return roots;
            }
            function rankSendButtonCandidates(nodes) {
                var candidates = [];
                for (var j = 0; j < nodes.length; j++) {
                    var node = nodes[j];
                    var text = safeText(node).replace(/\s+/g, '');
                    if (!text || !/^发送/.test(text)) continue;
                    if (text.indexOf('优惠券') !== -1) continue;
                    var rect = node.getBoundingClientRect();
                    if (!rect || rect.width < 20 || rect.height < 16) continue;
                    candidates.push({
                        text: text,
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                        area: rect.width * rect.height,
                        bottomBias: rect.top + rect.height / 2,
                        rightBias: rect.left + rect.width / 2
                    });
                }
                if (!candidates.length) {
                    return { found: false };
                }
                candidates.sort(function(a, b) {
                    var aHasCount = /\(\d+\)/.test(a.text);
                    var bHasCount = /\(\d+\)/.test(b.text);
                    if (aHasCount !== bHasCount) return aHasCount ? -1 : 1;
                    if (Math.abs(a.bottomBias - b.bottomBias) > 8) return b.bottomBias - a.bottomBias;
                    if (Math.abs(a.rightBias - b.rightBias) > 8) return b.rightBias - a.rightBias;
                    return b.area - a.area;
                });
                return {
                    found: true,
                    text: candidates[0].text,
                    x: candidates[0].x,
                    y: candidates[0].y
                };
            }

            var dialogRoots = collectDialogRoots();
            var scopedNodes = [];
            for (var i = 0; i < dialogRoots.length; i++) {
                var root = dialogRoots[i];
                var nodes = Array.from(root.querySelectorAll('button, [role="button"], a, div, span')).filter(isVisible);
                scopedNodes = scopedNodes.concat(nodes);
            }
            var ranked = rankSendButtonCandidates(scopedNodes);
            if (!ranked.found) {
                var globalNodes = Array.from(document.querySelectorAll('button, [role="button"], a, div, span')).filter(isVisible);
                ranked = rankSendButtonCandidates(globalNodes);
            }
            if (!ranked.found) {
                return JSON.stringify({ found: false, error: '未找到媒体发送按钮' });
            }
            return JSON.stringify({
                found: true,
                text: ranked.text,
                x: ranked.x,
                y: ranked.y
            });
        })()
        """
        self.run_javascript(script, callback)

    def _media_send_confirmed(self, baseline: Dict[str, Any], current: Dict[str, Any]) -> bool:
        """判断媒体是否已真实发出。"""
        if not current.get("found"):
            return False

        try:
            base_media = int(baseline.get("kf_media_count", -1))
            curr_media = int(current.get("kf_media_count", 0))
            if base_media >= 0 and curr_media > base_media:
                return True
        except Exception:
            pass

        # 弱确认：部分页面媒体节点类名会变化，kf_media_count 可能不涨；
        # 若客服消息总数增长且最后一条客服消息非文本，通常就是图片已送达。
        try:
            base_total = int(baseline.get("kf_total_count", -1))
            curr_total = int(current.get("kf_total_count", 0))
            last_kf_has_text = bool(current.get("last_kf_has_text", True))
            if base_total >= 0 and curr_total > base_total and not last_kf_has_text:
                return True
        except Exception:
            pass

        return False

    def find_and_click_first_unread(self, callback: Callable):
        """查找并点击第一个未读消息

        Args:
            callback: 回调函数，接收 (success, info)
        """
        script = r"""
        (function() {
            function safeText(el) { return (el && (el.textContent || el.innerText) || "").trim(); }
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 3 || rect.height < 3) return false;
                return true;
            }
            function parseCssColorToRgb(colorStr) {
                if (!colorStr) return null;
                colorStr = String(colorStr).trim();
                var m = colorStr.match(/^rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([0-9.]+))?\)$/i);
                if (m) {
                    var r = parseInt(m[1], 10), g = parseInt(m[2], 10), b = parseInt(m[3], 10);
                    var a = (m[4] === undefined) ? 1 : parseFloat(m[4]);
                    return { r: r, g: g, b: b, a: a };
                }
                return null;
            }
            function isRedColor(rgb) {
                if (!rgb) return false;
                if (rgb.a !== undefined && rgb.a === 0) return false;
                return (rgb.r > 180 && rgb.g < 140 && rgb.b < 140);
            }
            function findRedStyleInfo(el) {
                var cur = el;
                for (var i = 0; i < 4 && cur; i++) {
                    var st = window.getComputedStyle(cur);
                    if (st) {
                        var bg = st.backgroundColor || '';
                        var bc = st.borderColor || '';
                        var bgRgb = parseCssColorToRgb(bg);
                        if (bgRgb && isRedColor(bgRgb)) return { type: 'background', value: bg, level: i };
                        var bcRgb = parseCssColorToRgb(bc);
                        if (bcRgb && isRedColor(bcRgb)) return { type: 'border', value: bc, level: i };
                    }
                    cur = cur.parentElement;
                }
                return null;
            }
            function findClickableAncestor(el) {
                if (!el) return null;
                var cur = el;
                for (var i = 0; i < 12 && cur; i++) {
                    var tag = (cur.tagName || '').toUpperCase();
                    var role = (cur.getAttribute && cur.getAttribute('role')) ? cur.getAttribute('role') : '';

                    // 强优先：会话列表项通常是 LI / role=listitem
                    if (tag === 'LI' || role === 'listitem') return cur;

                    // 常见：data-id / data-session-id 之类的可点击会话容器
                    try {
                        var did = cur.getAttribute && (cur.getAttribute('data-id') || cur.getAttribute('data-session-id') || cur.getAttribute('data-chat-id'));
                        if (did) return cur;
                    } catch (e) {}

                    // 其次：按钮/链接
                    if (tag === 'A' || tag === 'BUTTON' || role === 'button' || role === 'link') return cur;

                    // 兜底：pointer 且尺寸合理（避免选到整页容器）
                    var st = window.getComputedStyle(cur);
                    var r = cur.getBoundingClientRect ? cur.getBoundingClientRect() : null;
                    if (st && (st.cursor === 'pointer' || st.cursor === 'hand') && r) {
                        var tooBig = (r.width >= window.innerWidth * 0.8) || (r.height >= window.innerHeight * 0.6);
                        var tooSmall = (r.width < 120) || (r.height < 30);
                        var inLeftPane = (r.left < window.innerWidth * 0.55);
                        if (!tooBig && !tooSmall && inLeftPane && isVisible(cur)) return cur;
                    }

                    cur = cur.parentElement;
                }

                return null;
            }

            function isActiveSessionItem(el) {
                if (!el) return false;
                var cur = el;
                for (var i = 0; i < 6 && cur; i++) {
                    try {
                        var token = [
                            String(cur.className || ''),
                            String((cur.getAttribute && cur.getAttribute('aria-current')) || ''),
                            String((cur.getAttribute && cur.getAttribute('aria-selected')) || ''),
                            String((cur.getAttribute && cur.getAttribute('data-active')) || ''),
                            String((cur.getAttribute && cur.getAttribute('data-selected')) || ''),
                        ].join(' ').toLowerCase();
                        if (/(active|current|selected|select|focus|focused|aria-current|true)/.test(token)) {
                            return true;
                        }
                    } catch (e) {}
                    cur = cur.parentElement;
                }
                return false;
            }

            function findSessionListItem(badgeEl) {
                // 从徽标向上查找真正的会话列表项（通常包含用户名和预览）
                var cur = badgeEl;
                for (var i = 0; i < 8 && cur; i++) {
                    var r = cur.getBoundingClientRect();
                    // 会话项通常宽度较大（>100px）且高度适中（>30px）
                    if (r && r.width > 100 && r.height > 30) {
                        var tag = (cur.tagName || '').toUpperCase();
                        if (tag === 'LI' || tag === 'DIV') {
                            // 检查是否包含用户名或预览文本（排除纯徽标）
                            var txt = safeText(cur);
                            if (txt && txt.length > 2 && !/^\d+$/.test(txt)) {
                                return cur;
                            }
                        }
                    }
                    cur = cur.parentElement;
                }
                return null;
            }

            function extractSessionPreviewInfo(sessionEl, badgeEl) {
                if (!sessionEl) {
                    return { previewText: '', previewType: '' };
                }

                function containsToken(text, patterns) {
                    for (var i = 0; i < patterns.length; i++) {
                        if (patterns[i].test(text)) return true;
                    }
                    return false;
                }

                var text = safeText(sessionEl);
                var previewText = '';
                var previewType = '';
                var normalized = String(text || '').toLowerCase();

                if (containsToken(normalized, [/\[图片\]/, /图片/, /照片/, /photo/, /image/, /img/])) {
                    previewType = 'image';
                    previewText = '[图片]';
                } else if (containsToken(normalized, [/\[视频\]/, /视频/, /video/, /短片/])) {
                    previewType = 'video';
                    previewText = '[视频]';
                } else if (containsToken(normalized, [/\[表情\]/, /表情/, /emoji/, /emoticon/])) {
                    previewType = 'emoji';
                    previewText = '[表情]';
                }

                if (!previewType) {
                    var descendants = Array.from(sessionEl.querySelectorAll('svg, img, i, em, span, div'));
                    for (var j = 0; j < descendants.length; j++) {
                        var node = descendants[j];
                        if (!isVisible(node) || node === badgeEl) continue;
                        var token = [
                            String(node.className || ''),
                            String((node.getAttribute && node.getAttribute('aria-label')) || ''),
                            String((node.getAttribute && node.getAttribute('data-testid')) || ''),
                            String((node.getAttribute && node.getAttribute('title')) || ''),
                        ].join(' ').toLowerCase();
                        if (/(avatar|head|profile|portrait)/.test(token)) continue;
                        if (/(video|play|播放器|视频)/.test(token)) {
                            previewType = 'video';
                            previewText = '[视频]';
                            break;
                        }
                        if (/(image|img|pic|photo|图片|照片|preview)/.test(token)) {
                            previewType = 'image';
                            previewText = '[图片]';
                            break;
                        }
                        if (/(emoji|emoticon|sticker|expression|face|表情)/.test(token)) {
                            previewType = 'emoji';
                            previewText = '[表情]';
                            break;
                        }
                    }
                }

                return {
                    previewText: previewText,
                    previewType: previewType,
                    sessionText: text
                };
            }

            function isProbablyNumberBadge(el) {
                if (!el || !isVisible(el)) return false;
                var t = safeText(el);
                if (!t || !/^\d+$/.test(t)) return false;
                var num = parseInt(t, 10);
                if (!num || num <= 0 || num > 999) return false;
                var r = el.getBoundingClientRect();
                if (!r) return false;
                if (r.width > 90 || r.height > 90) return false;
                if (r.width < 4 || r.height < 4) return false;
                if (r.left > window.innerWidth * 0.7) return false;
                return true;
            }
            function isProbablyDotBadge(el) {
                if (!el || !isVisible(el)) return false;
                var t = safeText(el);
                if (t) return false;
                var r = el.getBoundingClientRect();
                if (!r) return false;
                if (r.width > 20 || r.height > 20) return false;
                if (r.width < 4 || r.height < 4) return false;
                if (r.left > window.innerWidth * 0.7) return false;
                return true;
            }

            try {
                var allNodes = Array.from(document.querySelectorAll('span,div,i,em,strong,sup,b'));
                var debugInfo = { totalNodes: allNodes.length, candidates: [] };
                var candidates = [];

                for (var idx = 0; idx < allNodes.length; idx++) {
                    var n = allNodes[idx];
                    var isNum = isProbablyNumberBadge(n);
                    var isDot = !isNum && isProbablyDotBadge(n);
                    if (!isNum && !isDot) continue;

                    var redInfo = findRedStyleInfo(n);
                    if (!redInfo) continue;

                    var rect = n.getBoundingClientRect();

                    // 过滤：左侧导航栏上的红点/数字（通常非常靠左且较靠上）
                    if (rect && rect.left < 60 && rect.top < 120) {
                        continue;
                    }

                    var sessionEl = findClickableAncestor(n);
                    var sessionRect = null;
                    var hasSession = false;
                    var previewInfo = { previewText: '', previewType: '', sessionText: '' };
                    if (sessionEl && sessionEl.getBoundingClientRect) {
                        sessionRect = sessionEl.getBoundingClientRect();
                        previewInfo = extractSessionPreviewInfo(sessionEl, n);
                        if (sessionRect) {
                            var tooBig = (sessionRect.width >= window.innerWidth * 0.8) || (sessionRect.height >= window.innerHeight * 0.6);
                            var tooSmall = (sessionRect.width < 120) || (sessionRect.height < 30);
                            var inLeftPane = (sessionRect.left < window.innerWidth * 0.55);
                            var notHeader = (sessionRect.top > 90);
                            if (!tooBig && !tooSmall && inLeftPane && notHeader) {
                                hasSession = true;
                            }
                        }
                    }

                    candidates.push({
                        rectTop: rect.top,
                        rectLeft: rect.left,
                        badgeText: isNum ? safeText(n) : 'dot',
                        red: redInfo,
                        hasSession: hasSession,
                        sessionRect: sessionRect,
                        previewText: previewInfo.previewText,
                        previewType: previewInfo.previewType,
                        sessionText: previewInfo.sessionText
                    });

                    if (debugInfo.candidates.length < 10) {
                        var st = window.getComputedStyle(n);
                        debugInfo.candidates.push({
                            text: isNum ? safeText(n) : '',
                            bg: st ? st.backgroundColor : '',
                            border: st ? st.borderColor : '',
                            rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
                            red: redInfo
                        });
                    }
                }

                if (candidates.length === 0) {
                    return JSON.stringify({ found: false, clicked: false, reason: 'no_unread', debug: debugInfo });
                }

                // 优先选择“确认为会话项”的未读
                var preferred = candidates.filter(function(c) { return !!c.hasSession; });
                var usable = preferred.length ? preferred : candidates;
                usable.sort(function(a, b) {
                    var at = (a.sessionRect && a.sessionRect.top) ? a.sessionRect.top : a.rectTop;
                    var bt = (b.sessionRect && b.sessionRect.top) ? b.sessionRect.top : b.rectTop;
                    return at - bt;
                });
                var target = usable[0];

                // 重新定位一次目标节点（避免闭包里对象被序列化）
                var badgeNodes = Array.from(document.querySelectorAll('span,div,i,em,strong,sup,b'));
                var bestEl = null;
                var bestDist = 1e9;
                for (var j = 0; j < badgeNodes.length; j++) {
                    var el = badgeNodes[j];
                    if (!isVisible(el)) continue;
                    var br = el.getBoundingClientRect();
                    if (br && br.left < 60 && br.top < 120) continue;
                    var t = safeText(el);
                    if (target.badgeText !== 'dot') {
                        if (t !== target.badgeText) continue;
                        if (!/^\d+$/.test(t)) continue;
                    } else {
                        if (t) continue;
                    }
                    var ri = findRedStyleInfo(el);
                    if (!ri) continue;
                    // 优先选择具有合理会话祖先的徽标
                    var sEl = findClickableAncestor(el);
                    if (target.hasSession && !sEl) continue;
                    var r2 = el.getBoundingClientRect();
                    var dist = Math.abs(r2.top - target.rectTop) + Math.abs(r2.left - target.rectLeft);
                    if (dist < bestDist) { bestDist = dist; bestEl = el; }
                }

                if (!bestEl) {
                    return JSON.stringify({
                        found: true,
                        clicked: false,
                        reason: 'badge_node_lost',
                        badgeText: target.badgeText,
                        totalUnread: candidates.length,
                        debug: debugInfo
                    });
                }

                // 参考 hari_main.py：点击“会话项”本身
                // 如果能找到合理的会话容器，优先点击容器；否则才点击徽标
                var sessionClickEl = findClickableAncestor(bestEl);
                var clickEl = sessionClickEl ? sessionClickEl : bestEl;
                var alreadyActive = !!isActiveSessionItem(clickEl);
                if (clickEl && clickEl.scrollIntoView) {
                    try { clickEl.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                }
                if (clickEl) {
                    var clicked = false;
                    if (!alreadyActive) {
                        try {
                            // 方式1：直接点击会话项（参考 hari_main.py）
                            clickEl.click();
                            clicked = true;
                        } catch (e1) {
                            // 方式2：基于坐标的点击（会话项中心）
                            var rect = clickEl.getBoundingClientRect();
                            var centerX = rect.left + rect.width / 2;
                            var centerY = rect.top + rect.height / 2;
                            try {
                                var targetEl = document.elementFromPoint(centerX, centerY);
                                if (targetEl) {
                                    targetEl.click();
                                    clicked = true;
                                }
                            } catch (e2) {}
                        }
                        // 方式3：模拟鼠标事件
                        try {
                            var rect = clickEl.getBoundingClientRect();
                            var centerX = rect.left + rect.width / 2;
                            var centerY = rect.top + rect.height / 2;
                            var downEvt = new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: centerX, clientY: centerY });
                            var upEvt = new MouseEvent('mouseup', { bubbles: true, cancelable: true, clientX: centerX, clientY: centerY });
                            var clickEvt = new MouseEvent('click', { bubbles: true, cancelable: true, clientX: centerX, clientY: centerY });
                            clickEl.dispatchEvent(downEvt);
                            clickEl.dispatchEvent(upEvt);
                            clickEl.dispatchEvent(clickEvt);
                            clicked = true;
                        } catch (e3) {}
                    }
                    return JSON.stringify({
                        found: true,
                        clicked: clicked || alreadyActive,
                        activeMatched: alreadyActive,
                        badgeText: target.badgeText,
                        totalUnread: candidates.length,
                        previewText: target.previewText || '',
                        previewType: target.previewType || '',
                        sessionText: target.sessionText || '',
                        debug: Object.assign({}, debugInfo, {
                            clickTarget: {
                                tagName: clickEl.tagName,
                                rect: { left: clickEl.getBoundingClientRect().left, top: clickEl.getBoundingClientRect().top, width: clickEl.getBoundingClientRect().width, height: clickEl.getBoundingClientRect().height },
                                point: { x: clickEl.getBoundingClientRect().left + clickEl.getBoundingClientRect().width / 2, y: clickEl.getBoundingClientRect().top + clickEl.getBoundingClientRect().height / 2 },
                                isSessionItem: !!sessionClickEl
                            }
                        })
                    });
                }

                return JSON.stringify({
                    found: true,
                    clicked: false,
                    reason: 'no_clickable',
                    badgeText: target.badgeText,
                    totalUnread: candidates.length,
                    debug: debugInfo
                });
            } catch (e) {
                return JSON.stringify({
                    found: false,
                    clicked: false,
                    reason: 'exception',
                    error: String(e && (e.stack || e.message || e))
                });
            }
        })()
        """;
        self.run_javascript(script, callback)

    def find_and_click_unread_by_usernames(self, user_names: list[str], callback: Callable):
        normalized = [str(x).strip() for x in (user_names or []) if str(x).strip()]
        if not normalized:
            callback(True, {"found": False, "clicked": False, "reason": "empty_remote_whitelist"})
            return
        names_json = json.dumps(normalized, ensure_ascii=False)
        script = f"""
        (function() {{
            var allowedNames = {names_json};
            function safeText(el) {{ return (el && (el.textContent || el.innerText) || "").trim(); }}
            function isVisible(el) {{
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 3 || rect.height < 3) return false;
                return true;
            }}
            function parseCssColorToRgb(colorStr) {{
                if (!colorStr) return null;
                colorStr = String(colorStr).trim();
                var m = colorStr.match(/^rgba?\\((\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([0-9.]+))?\\)$/i);
                if (!m) return null;
                return {{ r: parseInt(m[1], 10), g: parseInt(m[2], 10), b: parseInt(m[3], 10), a: (m[4] === undefined ? 1 : parseFloat(m[4])) }};
            }}
            function isRedColor(rgb) {{
                if (!rgb) return false;
                if (rgb.a !== undefined && rgb.a === 0) return false;
                return (rgb.r > 180 && rgb.g < 140 && rgb.b < 140);
            }}
            function findRedStyleInfo(el) {{
                var cur = el;
                for (var i = 0; i < 4 && cur; i++) {{
                    var st = window.getComputedStyle(cur);
                    if (st) {{
                        var bgRgb = parseCssColorToRgb(st.backgroundColor || '');
                        var bcRgb = parseCssColorToRgb(st.borderColor || '');
                        if (bgRgb && isRedColor(bgRgb)) return true;
                        if (bcRgb && isRedColor(bcRgb)) return true;
                    }}
                    cur = cur.parentElement;
                }}
                return false;
            }}
            function findClickableAncestor(el) {{
                var cur = el;
                for (var i = 0; i < 12 && cur; i++) {{
                    var tag = (cur.tagName || '').toUpperCase();
                    var role = (cur.getAttribute && cur.getAttribute('role')) ? cur.getAttribute('role') : '';
                    if (tag === 'LI' || role === 'listitem') return cur;
                    try {{
                        var did = cur.getAttribute && (cur.getAttribute('data-id') || cur.getAttribute('data-session-id') || cur.getAttribute('data-chat-id'));
                        if (did) return cur;
                    }} catch (e) {{}}
                    cur = cur.parentElement;
                }}
                return null;
            }}
            var allNodes = Array.from(document.querySelectorAll('span,div,i,em,strong,sup,b'));
            var candidates = [];
            for (var idx = 0; idx < allNodes.length; idx++) {{
                var n = allNodes[idx];
                if (!isVisible(n) || !findRedStyleInfo(n)) continue;
                var sessionEl = findClickableAncestor(n);
                if (!sessionEl || !isVisible(sessionEl)) continue;
                var text = safeText(sessionEl);
                if (!text) continue;
                var matchedName = '';
                for (var j = 0; j < allowedNames.length; j++) {{
                    if (text.indexOf(allowedNames[j]) !== -1) {{
                        matchedName = allowedNames[j];
                        break;
                    }}
                }}
                if (!matchedName) continue;
                var rect = sessionEl.getBoundingClientRect();
                candidates.push({{
                    matchedName: matchedName,
                    top: rect.top,
                    element: sessionEl
                }});
            }}
            if (!candidates.length) {{
                return JSON.stringify({{ found: false, clicked: false, reason: 'no_remote_unread' }});
            }}
            candidates.sort(function(a, b) {{ return a.top - b.top; }});
            var target = candidates[0].element;
            try {{ target.scrollIntoView({{ block: 'center', inline: 'nearest' }}); }} catch (e) {{}}
            var clicked = false;
            try {{ target.click(); clicked = true; }} catch (e1) {{}}
            if (!clicked) {{
                try {{
                    var rect = target.getBoundingClientRect();
                    var centerX = rect.left + rect.width / 2;
                    var centerY = rect.top + rect.height / 2;
                    var clickEvt = new MouseEvent('click', {{ bubbles: true, cancelable: true, clientX: centerX, clientY: centerY }});
                    target.dispatchEvent(clickEvt);
                    clicked = true;
                }} catch (e2) {{}}
            }}
            return JSON.stringify({{
                found: true,
                clicked: clicked,
                matchedName: candidates[0].matchedName
            }});
        }})()
        """
        self.run_javascript(script, callback)

    def enter_session(self, element_info: dict, callback: Callable = None):
        """点击进入会话

        Args:
            element_info: 元素位置信息 {x, y}
            callback: 回调函数
        """
        script = f"""
        (function() {{
            var el = document.elementFromPoint({element_info.get('x', 0)}, {element_info.get('y', 0)});
            if (el) {{
                var clickable = el;
                for (var i = 0; i < 8 && clickable; i++) {{
                    if (clickable.tagName === 'LI' || clickable.getAttribute('role') === 'listitem' ||
                        typeof clickable.onclick === 'function') {{
                        break;
                    }}
                    clickable = clickable.parentElement;
                }}
                if (clickable) {{
                    clickable.click();
                    return true;
                }}
            }}
            return false;
        }})()
        """
        if callback:
            self.run_javascript(script, callback)
        else:
            self.page.runJavaScript(script)

    def grab_chat_data(self, callback: Callable):
        """抓取聊天数据 - 基于微信小店DOM结构

        Args:
            callback: 回调函数，接收 (success, data)
        """
        script = r"""
        (function() {
            function safeText(el) {
                if (!el) return "";
                return (el.textContent || el.innerText || "").trim();
            }

            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }

            function getCurrentChatUser() {
                // 从 .chat-customer-name 获取用户名
                var nameEl = document.querySelector('.chat-customer-name');
                if (nameEl && isVisible(nameEl)) {
                    var name = safeText(nameEl);
                    if (name && name.length > 0) {
                        return { name: name, method: 'chat-customer-name' };
                    }
                }
                
                // 兜底：从标题区域查找
                var headings = document.querySelectorAll('h1, h2, h3, h4, .title, .name');
                for (var i = 0; i < headings.length; i++) {
                    var h = headings[i];
                    if (!isVisible(h)) continue;
                    var text = safeText(h);
                    if (text && text.length > 0 && text.length < 30) {
                        return { name: text, method: 'heading' };
                    }
                }
                
                return { name: "未知用户", method: 'fallback' };
            }

            function getSessionKeyFromNode(node) {
                if (!node) return "";
                var keys = [
                    node.getAttribute && node.getAttribute('data-session-id'),
                    node.getAttribute && node.getAttribute('data-chat-id'),
                    node.getAttribute && node.getAttribute('data-id'),
                    node.id
                ];
                for (var i = 0; i < keys.length; i++) {
                    var key = keys[i];
                    if (key && String(key).trim()) return String(key).trim();
                }
                return "";
            }

            function buildSessionFingerprint(node, userName) {
                if (!node) {
                    var fallbackName = String(userName || '').trim();
                    return fallbackName ? ("name:" + fallbackName) : "";
                }

                var parts = [];
                function pushPart(prefix, value) {
                    if (value === undefined || value === null) return;
                    var text = String(value).trim();
                    if (!text) return;
                    parts.push(prefix + text);
                }

                var attrs = [
                    "data-session-id",
                    "data-chat-id",
                    "data-id",
                    "id",
                    "aria-label",
                    "title"
                ];
                for (var i = 0; i < attrs.length; i++) {
                    var attrName = attrs[i];
                    try {
                        pushPart(attrName + "=", node.getAttribute && node.getAttribute(attrName));
                    } catch (e) {}
                }

                var classTokens = String(node.className || "")
                    .split(/\s+/)
                    .filter(function(token) {
                        if (!token) return false;
                        return ["active", "current", "selected", "unread"].indexOf(String(token).toLowerCase()) === -1;
                    })
                    .sort();
                if (classTokens.length) {
                    pushPart("class=", classTokens.join(","));
                }

                var parent = node.parentElement;
                if (parent) {
                    pushPart("parent_id=", parent.id || "");
                    pushPart("parent_data_id=", parent.getAttribute && parent.getAttribute("data-id"));
                }

                pushPart("node_tag=", node.tagName || "");
                pushPart("name=", userName || "");

                return parts.join("|").slice(0, 320);
            }

            function findActiveSessionNode() {
                var selectors = [
                    'li[role="listitem"]',
                    '.session-item',
                    '[data-session-id]',
                    '[data-chat-id]',
                    '[data-id]'
                ];
                for (var s = 0; s < selectors.length; s++) {
                    var nodes = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < nodes.length; i++) {
                        var node = nodes[i];
                        if (!isVisible(node)) continue;
                        var cls = String(node.className || '').toLowerCase();
                        var isActive = (
                            cls.indexOf('active') !== -1 ||
                            cls.indexOf('current') !== -1 ||
                            cls.indexOf('selected') !== -1 ||
                            node.getAttribute('aria-selected') === 'true'
                        );
                        if (isActive) return node;
                    }
                }
                return null;
            }

            function findSessionByUserName(userName) {
                var name = String(userName || '').trim();
                if (!name) return null;
                var candidates = document.querySelectorAll('[data-session-id], [data-chat-id], [data-id], li[role="listitem"], .session-item');
                for (var i = 0; i < candidates.length; i++) {
                    var node = candidates[i];
                    if (!isVisible(node)) continue;
                    var text = safeText(node);
                    if (text && text.indexOf(name) !== -1) {
                        return node;
                    }
                }
                return null;
            }

            function getCurrentSessionKey(userName) {
                var active = findActiveSessionNode();
                var key = getSessionKeyFromNode(active);
                if (key) {
                    return {
                        key: key,
                        method: 'active_node',
                        fingerprint: buildSessionFingerprint(active, userName)
                    };
                }
                var byName = findSessionByUserName(userName);
                key = getSessionKeyFromNode(byName);
                if (key) {
                    return {
                        key: key,
                        method: 'name_match',
                        fingerprint: buildSessionFingerprint(byName, userName)
                    };
                }
                return {
                    key: "",
                    method: "fallback",
                    fingerprint: buildSessionFingerprint(active || byName, userName)
                };
            }

            function getChatMessages() {
                var result = { messages: [], userMessages: [], kfMessages: [], debug: [] };

                function isLikelyAvatarNode(node) {
                    if (!node) return false;
                    var token = '';
                    try {
                        token = [
                            String(node.className || ''),
                            String((node.getAttribute && node.getAttribute('src')) || ''),
                            String((node.getAttribute && node.getAttribute('alt')) || ''),
                        ].join(' ').toLowerCase();
                    } catch (e) {}
                    if (/(avatar|head|profile|portrait)/.test(token)) return true;
                    var parent = node.parentElement;
                    if (!parent) return false;
                    var parentToken = String(parent.className || '').toLowerCase();
                    return /(avatar|head|profile|portrait)/.test(parentToken);
                }

                function detectMediaInfo(item) {
                    if (!item) return null;

                    function hasBackgroundImage(node) {
                        if (!node) return false;
                        try {
                            var style = window.getComputedStyle(node);
                            var bg = String((style && style.backgroundImage) || '').toLowerCase();
                            return !!bg && bg !== 'none';
                        } catch (e) {
                            return false;
                        }
                    }

                    function looksLikeMediaContainer(node) {
                        if (!node || !isVisible(node)) return false;
                        if (isLikelyAvatarNode(node)) return false;
                        var token = '';
                        try {
                            token = [
                                String(node.className || ''),
                                String(node.id || ''),
                                String((node.getAttribute && node.getAttribute('data-testid')) || ''),
                                String((node.getAttribute && node.getAttribute('role')) || ''),
                                String((node.getAttribute && node.getAttribute('aria-label')) || ''),
                            ].join(' ').toLowerCase();
                        } catch (e) {}

                        var rect = null;
                        try {
                            rect = node.getBoundingClientRect();
                        } catch (e) {}
                        var width = rect && rect.width ? rect.width : 0;
                        var height = rect && rect.height ? rect.height : 0;

                        if (/(video|play|播放器|视频)/.test(token) && width >= 48 && height >= 48) {
                            return 'video';
                        }
                        if (/(image|img|pic|photo|media|preview|cover|upload|图片|照片)/.test(token) && width >= 72 && height >= 60) {
                            return 'image';
                        }
                        if (hasBackgroundImage(node) && width >= 72 && height >= 60) {
                            return 'image';
                        }
                        return '';
                    }

                    function hasLargeVisualBlock(root) {
                        if (!root) return false;
                        var blocks = Array.from(root.querySelectorAll('div, span, a, section, article'));
                        for (var b = 0; b < blocks.length; b++) {
                            var block = blocks[b];
                            if (!isVisible(block) || isLikelyAvatarNode(block)) continue;
                            var rect = null;
                            try {
                                rect = block.getBoundingClientRect();
                            } catch (e) {}
                            var width = rect && rect.width ? rect.width : 0;
                            var height = rect && rect.height ? rect.height : 0;
                            if (width < 120 || height < 120) continue;

                            var text = safeText(block);
                            if (text && text.length > 0) continue;

                            if (hasBackgroundImage(block)) return true;

                            var token = '';
                            try {
                                token = [
                                    String(block.className || ''),
                                    String(block.id || ''),
                                    String((block.getAttribute && block.getAttribute('data-testid')) || ''),
                                    String((block.getAttribute && block.getAttribute('role')) || ''),
                                    String((block.getAttribute && block.getAttribute('aria-label')) || ''),
                                ].join(' ').toLowerCase();
                            } catch (e) {}
                            if (/(image|img|pic|photo|media|preview|cover|upload|图片|照片|thumb)/.test(token)) {
                                return true;
                            }

                            var childMedia = block.querySelector('img, canvas, video');
                            if (childMedia && !isLikelyAvatarNode(childMedia)) {
                                return true;
                            }
                        }
                        return false;
                    }

                    var videoNode = item.querySelector(
                        '.video-msg, [class*="video-msg"], [class*="video_msg"], video, [data-testid*="video"], [class*="play-icon"], [class*="playIcon"]'
                    );
                    if (videoNode && !isLikelyAvatarNode(videoNode)) {
                        return { type: 'video', text: '[视频]' };
                    }

                    var nodes = Array.from(item.querySelectorAll('img, video, canvas, svg'));
                    var hasEmoji = false;
                    var hasImage = false;

                    for (var j = 0; j < nodes.length; j++) {
                        var node = nodes[j];
                        if (isLikelyAvatarNode(node)) continue;

                        var rect = null;
                        try {
                            rect = node.getBoundingClientRect();
                        } catch (e) {}
                        var width = rect && rect.width ? rect.width : 0;
                        var height = rect && rect.height ? rect.height : 0;
                        var token = [
                            String(node.className || ''),
                            String((node.getAttribute && node.getAttribute('src')) || ''),
                            String((node.getAttribute && node.getAttribute('alt')) || ''),
                            String((node.getAttribute && node.getAttribute('aria-label')) || ''),
                            String((node.getAttribute && node.getAttribute('data-testid')) || ''),
                        ].join(' ').toLowerCase();

                        if (/(emoji|emoticon|sticker|expression|face)/.test(token)) {
                            hasEmoji = true;
                            continue;
                        }

                        if (node.tagName === 'SVG' && width <= 48 && height <= 48) {
                            hasEmoji = true;
                            continue;
                        }

                        if (width >= 72 && height >= 60) {
                            hasImage = true;
                            continue;
                        }

                        if (node.tagName === 'IMG' && width > 0 && height > 0) {
                            if (width <= 64 && height <= 64) {
                                hasEmoji = true;
                            } else {
                                hasImage = true;
                            }
                        }
                    }

                    var mediaCandidates = Array.from(item.querySelectorAll('div, span, a, section'));
                    for (var k = 0; k < mediaCandidates.length; k++) {
                        var mediaType = looksLikeMediaContainer(mediaCandidates[k]);
                        if (mediaType === 'video') {
                            return { type: 'video', text: '[视频]' };
                        }
                        if (mediaType === 'image') {
                            hasImage = true;
                        }
                    }

                    if (hasLargeVisualBlock(item)) {
                        return { type: 'image', text: '[图片]' };
                    }

                    if (hasImage) return { type: 'image', text: '[图片]' };
                    if (hasEmoji) return { type: 'emoji', text: '[表情]' };
                    return null;
                }

                function extractMessageContent(item) {
                    var textMsg = item.querySelector('.text-msg');
                    var text = '';
                    if (textMsg) {
                        text = safeText(textMsg);
                    } else {
                        text = safeText(item);
                    }

                    if (text && text.length > 0) {
                        return { type: 'text', text: text };
                    }

                    return detectMediaInfo(item);
                }
                
                // 查找聊天消息容器：#chat-scroll-view 或 .chat-scroll-view
                var chatScrollView = document.getElementById('chat-scroll-view') || document.querySelector('.chat-scroll-view');
                if (!chatScrollView) {
                    result.debug.push("未找到聊天滚动容器");
                    return result;
                }
                
                // 查找所有消息项：.message-item
                var messageItems = chatScrollView.querySelectorAll('.message-item');
                result.debug.push("找到消息项: " + messageItems.length);
                
                for (var i = 0; i < messageItems.length; i++) {
                    var item = messageItems[i];
                    if (!isVisible(item)) continue;
                    
                    // 判断是客服还是用户消息
                    // justify-end 表示客服消息（右侧）
                    var classList = item.className || '';
                    var isKf = classList.indexOf('justify-end') !== -1;
                    var isUser = !isKf;
                    
                    var content = extractMessageContent(item);
                    if (!content) {
                        try {
                            var itemRect = item.getBoundingClientRect();
                            result.debug.push(
                                "跳过消息#" + i +
                                " class=" + String(item.className || '').slice(0, 120) +
                                " size=" + Math.round(itemRect.width || 0) + "x" + Math.round(itemRect.height || 0) +
                                " text=" + safeText(item).slice(0, 60)
                            );
                        } catch (e) {
                            result.debug.push("跳过消息#" + i + "（无法解析结构）");
                        }
                        continue;
                    }
                    var text = content.text || '';
                    
                    // 过滤空消息
                    if (!text || text.length === 0) continue;
                    if (text.length > 500) continue;
                    
                    // 过滤时间戳和系统消息
                    if (/^\d{1,2}:\d{2}$/.test(text)) continue;
                    if (/^(昨天|今天|星期[一二三四五六日])\s*\d{1,2}:\d{2}$/.test(text)) continue;
                    if (/(用户超时未回|会话已结束|两天内仍可再次联系)/.test(text)) continue;
                    
                    var msg = {
                        text: text,
                        message_type: content.type || 'text',
                        is_user: isUser,
                        is_kf: isKf
                    };
                    
                    result.messages.push(msg);
                    if (isUser) {
                        result.userMessages.push(msg);
                    } else {
                        result.kfMessages.push(msg);
                    }
                }
                
                result.debug.push("有效消息: " + result.messages.length);
                result.debug.push("用户消息: " + result.userMessages.length);
                result.debug.push("客服消息: " + result.kfMessages.length);
                
                return result;
            }

            var userResult = getCurrentChatUser();
            var msgResult = getChatMessages();
            var sessionResult = getCurrentSessionKey(userResult.name);

            return JSON.stringify({
                timestamp: new Date().toISOString(),
                user_name: userResult.name,
                user_method: userResult.method,
                chat_session_key: sessionResult.key,
                chat_session_method: sessionResult.method,
                chat_session_fingerprint: sessionResult.fingerprint,
                messages: msgResult.messages,
                user_messages: msgResult.userMessages,
                kf_messages: msgResult.kfMessages,
                debug: msgResult.debug
            });
        })()
        """
        self.run_javascript(script, callback)

    def send_message(self, text: str, callback: Callable = None):
        """发送消息 - 参考 hari_main.py 实现

        Args:
            text: 要发送的文本
            callback: 回调函数
        """
        # 转义文本中的特殊字符
        escaped_text = json.dumps(text)

        script = f"""
        (function() {{
            function isVisible(el) {{
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }}

            function findComposer() {{
                // 微信小店输入框：直接使用 id="input-textarea"
                var inputTextarea = document.getElementById('input-textarea');
                if (inputTextarea && isVisible(inputTextarea)) return inputTextarea;

                // 兜底：class="text-area"
                var textAreaClass = document.querySelector('.text-area');
                if (textAreaClass && isVisible(textAreaClass)) return textAreaClass;

                // 参考 hari_main.py：优先查找 role=textbox
                var roleBox = document.querySelector('[role="textbox"]');
                if (roleBox && isVisible(roleBox)) return roleBox;

                // textarea
                var textareas = Array.from(document.querySelectorAll('textarea')).filter(isVisible);
                if (textareas.length) return textareas[0];

                // input
                var inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
                    .filter(function(el) {{ return isVisible(el) && !el.disabled && !el.readOnly; }});
                if (inputs.length) return inputs[0];

                // contenteditable
                var ceList = Array.from(document.querySelectorAll('[contenteditable="true"]')).filter(isVisible);
                if (ceList.length) return ceList[0];

                return null;
            }}

            function setComposerValue(el, text) {{
                if (!el) return false;
                try {{
                    el.focus();
                    
                    // 对于 textarea 元素，直接设置 value
                    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {{
                        // 使用原生 value setter 触发框架监听
                        var proto = Object.getPrototypeOf(el);
                        var desc = Object.getOwnPropertyDescriptor(proto, 'value');
                        if (desc && desc.set) {{
                            desc.set.call(el, text);
                        }} else {{
                            el.value = text;
                        }}
                    }} else if (el.isContentEditable) {{
                        // 参考 hari_main.py：更像用户输入
                        try {{
                            document.execCommand('selectAll', false, null);
                            document.execCommand('insertText', false, text);
                        }} catch (e) {{
                            el.innerText = text;
                        }}
                    }} else {{
                        el.value = text;
                    }}
                    
                    // 触发事件让框架感知变化
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }} catch (e) {{
                    return false;
                }}
            }}

            function clickSend(composer) {{
                // 参考 hari_main.py：微信小店只使用Enter发送
                if (!composer) return false;
                try {{
                    composer.focus();
                    // 只按一次Enter键
                    var enterEvent = new KeyboardEvent('keydown', {{
                        bubbles: true,
                        cancelable: true,
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13
                    }});
                    composer.dispatchEvent(enterEvent);
                    return true;
                }} catch (e) {{
                    return false;
                }}
            }}

            var composer = findComposer();
            if (!composer) {{
                return JSON.stringify({{ success: false, error: '未找到输入框' }});
            }}

            var setSuccess = setComposerValue(composer, {escaped_text});
            if (!setSuccess) {{
                return JSON.stringify({{ success: false, error: '设置文本失败' }});
            }}

            // 等待文本设置完成后再发送
            setTimeout(function() {{
                clickSend(composer);
            }}, 300);

            return JSON.stringify({{ 
                success: true, 
                composer_tag: composer.tagName,
                composer_editable: composer.isContentEditable || false
            }});
        }})()
        """
        if callback:
            self.run_javascript(script, callback)
        else:
            self.page.runJavaScript(script)

    def clear_message_input(self, callback: Callable = None):
        """清空聊天输入框，避免媒体确认阶段误把上一条文本再次发出。"""
        script = r"""
        (function() {
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }

            function findComposer() {
                var inputTextarea = document.getElementById('input-textarea');
                if (inputTextarea && isVisible(inputTextarea)) return inputTextarea;

                var textAreaClass = document.querySelector('.text-area');
                if (textAreaClass && isVisible(textAreaClass)) return textAreaClass;

                var roleBox = document.querySelector('[role="textbox"]');
                if (roleBox && isVisible(roleBox)) return roleBox;

                var textareas = Array.from(document.querySelectorAll('textarea')).filter(isVisible);
                if (textareas.length) return textareas[0];

                var inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
                    .filter(function(el) { return isVisible(el) && !el.disabled && !el.readOnly; });
                if (inputs.length) return inputs[0];

                var ceList = Array.from(document.querySelectorAll('[contenteditable="true"]')).filter(isVisible);
                if (ceList.length) return ceList[0];

                return null;
            }

            function clearComposerValue(el) {
                if (!el) return false;
                try {
                    el.focus();
                    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                        var proto = Object.getPrototypeOf(el);
                        var desc = Object.getOwnPropertyDescriptor(proto, 'value');
                        if (desc && desc.set) {
                            desc.set.call(el, '');
                        } else {
                            el.value = '';
                        }
                    } else if (el.isContentEditable) {
                        el.innerText = '';
                        el.textContent = '';
                    } else {
                        el.value = '';
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                } catch (e) {
                    return false;
                }
            }

            var composer = findComposer();
            if (!composer) {
                return JSON.stringify({ success: false, error: '未找到输入框' });
            }

            var cleared = clearComposerValue(composer);
            return JSON.stringify({
                success: cleared,
                composer_tag: composer.tagName,
                composer_editable: composer.isContentEditable || false
            });
        })()
        """
        if callback:
            self.run_javascript(script, callback)
        else:
            self.page.runJavaScript(script)

    def send_image(self, image_path: str, callback: Callable = None):
        """发送图片并验证是否真正出现在会话中。"""
        if not image_path or not Path(image_path).exists():
            if callback:
                callback(False, {"error": "图片路径不存在", "failure_code": "missing_media_path"})
            return

        # 预设文件选择（CustomWebEnginePage 支持）
        if hasattr(self.page, "next_file_selection"):
            self.page.next_file_selection = [str(Path(image_path).resolve())]

        state: Dict[str, Any] = {
            "done": False,
            "baseline": {},
            "trigger_method": "unknown",
            "verify_attempt": 0,
            "confirm_clicked": False,
            "enter_error": "",
            "enter_attempt": 0,
            "dialog_closed": False,
            "saw_pending_or_dialog": False,
            "retriggered": False,
            "image_button_x": 0.0,
            "image_button_y": 0.0,
        }
        max_verify_attempts = 20
        max_enter_attempts = 2

        def build_failure_payload(message: str, step: str, **extra: Any) -> Dict[str, Any]:
            mapping = {
                "locate_image_button": "locate_image_button_failed",
                "native_click_image_button": "native_click_image_button_failed",
                "confirm_click": "confirm_click_failed",
                "confirm_click_after_enter": "confirm_click_after_enter_failed",
                "verify_timeout": "verify_timeout",
                "verified_soft_timeout": "verified_soft_timeout",
            }
            payload: Dict[str, Any] = {
                "error": message,
                "step": step,
                "failure_code": mapping.get(step, step or "unknown_media_failure"),
            }
            payload.update(extra)
            return payload

        def finish(success: bool, payload: Dict[str, Any]):
            if state["done"]:
                return
            state["done"] = True
            if callback:
                callback(success, payload)

        def confirm_with_enter():
            if state["done"]:
                return
            state["enter_attempt"] += 1
            entered, enter_err = self._native_press_enter()
            if not entered:
                state["enter_error"] = enter_err

            def on_dialog_state(checked_success, checked_result):
                dialog_state = self._parse_js_payload(checked_result) if checked_success else {}
                dialog_visible = bool(dialog_state.get("dialog_visible", False))
                send_btn_visible = bool(dialog_state.get("send_button_in_dialog_visible", False))

                if dialog_visible:
                    state["saw_pending_or_dialog"] = True

                if not dialog_visible:
                    state["dialog_closed"] = True
                    QTimer.singleShot(300, poll_delivery)
                    return

                # Enter 后弹窗仍未关闭：继续重试，不直接当成功。
                if state["enter_attempt"] < max_enter_attempts:
                    QTimer.singleShot(220, confirm_with_enter)
                    return

                if not send_btn_visible:
                    # 弹窗还在但按钮未就绪，进入轮询等待，不当成功。
                    QTimer.singleShot(320, poll_delivery)
                    return

                # Enter 多次后仍在弹窗，改为精准点击弹窗内“发送*”按钮。
                state["confirm_clicked"] = True
                clicked_confirm, confirm_err = self._native_left_click(
                    dialog_state.get("send_button_x", 0),
                    dialog_state.get("send_button_y", 0),
                )
                if not clicked_confirm:
                    finish(
                        False,
                        build_failure_payload(
                            f"弹窗内发送按钮点击失败: {confirm_err}",
                            "confirm_click_after_enter",
                            triggerMethod=state["trigger_method"],
                        ),
                    )
                    return

                QTimer.singleShot(320, poll_delivery)

            QTimer.singleShot(280, lambda: self._get_media_dialog_state(on_dialog_state))

        def trigger_pick_and_confirm():
            if state["done"]:
                return
            x = float(state.get("image_button_x", 0) or 0)
            y = float(state.get("image_button_y", 0) or 0)
            clicked, click_err = self._native_left_click(x, y)
            if not clicked:
                finish(
                    False,
                    build_failure_payload(
                        f"点击图片按钮失败: {click_err}",
                        "native_click_image_button",
                        triggerMethod=state.get("trigger_method", "unknown"),
                    ),
                )
                return
            # 让文件选择与弹层渲染完成后再确认发送（此前 1000ms 容易错过确认窗口）。
            QTimer.singleShot(500, confirm_with_enter)

        def poll_delivery():
            if state["done"]:
                return
            state["verify_attempt"] += 1

            def on_signature_result(success, result):
                signature = self._parse_js_payload(result) if success else {}
                pending_visible = bool(signature.get("pending_media_send_visible", False))
                dialog_visible = bool(signature.get("dialog_visible", False))
                if pending_visible or dialog_visible:
                    state["saw_pending_or_dialog"] = True
                if not pending_visible and not dialog_visible:
                    state["dialog_closed"] = True

                if (
                    self._media_send_confirmed(state.get("baseline", {}), signature)
                    and not pending_visible
                    and not dialog_visible
                    and state.get("dialog_closed", False)
                ):
                    finish(
                        True,
                        {
                            "success": True,
                            "step": "verified",
                            "triggerMethod": state.get("trigger_method", "unknown"),
                            "verifyAttempts": state["verify_attempt"],
                            "sendMethod": "native_click_enter_with_delivery_check",
                            "signature": signature,
                        },
                    )
                    return

                if pending_visible and not state["confirm_clicked"]:
                    state["confirm_clicked"] = True

                    def on_find_confirm_btn(btn_success, btn_result):
                        btn_data = self._parse_js_payload(btn_result) if btn_success else {}
                        if btn_data.get("found"):
                            clicked, click_err = self._native_left_click(
                                btn_data.get("x", 0),
                                btn_data.get("y", 0),
                            )
                            if not clicked:
                                finish(
                                    False,
                                    build_failure_payload(
                                        f"点击媒体发送按钮失败: {click_err}",
                                        "confirm_click",
                                        triggerMethod=state.get("trigger_method", "unknown"),
                                    ),
                                )
                                return
                            # 部分页面确认后仍要求回车，再补一次 Enter 提高稳定性。
                            QTimer.singleShot(250, self._native_press_enter)

                        if state["verify_attempt"] >= max_verify_attempts:
                            finish(
                                False,
                                build_failure_payload(
                                    "图片疑似仅被选择，未确认发送",
                                    "verify_timeout",
                                    triggerMethod=state.get("trigger_method", "unknown"),
                                    signature=signature,
                                ),
                            )
                            return
                        QTimer.singleShot(600, poll_delivery)

                    self._find_media_send_button(on_find_confirm_btn)
                    return

                if state["verify_attempt"] >= max_verify_attempts:
                    # 首次超时且没看到可确认状态：自动重试一次点击图片按钮，降低偶发点击丢失带来的失败率。
                    if (
                        not state.get("retriggered", False)
                        and not state.get("confirm_clicked", False)
                        and not pending_visible
                        and not dialog_visible
                    ):
                        state["retriggered"] = True
                        state["verify_attempt"] = 0
                        state["enter_attempt"] = 0
                        state["dialog_closed"] = False
                        state["enter_error"] = ""
                        QTimer.singleShot(280, trigger_pick_and_confirm)
                        return

                    # 如果确认后签名未变化，交给上层补偿，不在浏览器层判定为成功。
                    if (
                        state.get("confirm_clicked", False)
                        and state.get("saw_pending_or_dialog", False)
                        and not pending_visible
                        and not dialog_visible
                        and state.get("dialog_closed", False)
                    ):
                        finish(
                            False,
                            build_failure_payload(
                                "确认发送后签名未变化，转入补偿队列",
                                "verified_soft_timeout",
                                detail="signature_not_changed_after_confirm",
                                triggerMethod=state.get("trigger_method", "unknown"),
                                verifyAttempts=state["verify_attempt"],
                                sendMethod="native_click_enter_with_delivery_check",
                                signature=signature,
                            ),
                        )
                        return

                    finish(
                        False,
                        build_failure_payload(
                            "图片未检测到实际发送结果",
                            "verify_timeout",
                            triggerMethod=state.get("trigger_method", "unknown"),
                            verifyAttempts=state["verify_attempt"],
                            enterAttempts=state.get("enter_attempt", 0),
                            confirmClicked=bool(state.get("confirm_clicked", False)),
                            sawPendingOrDialog=bool(state.get("saw_pending_or_dialog", False)),
                            signature=signature,
                        ),
                    )
                    return

                QTimer.singleShot(450, poll_delivery)

            self._get_chat_media_signature(on_signature_result)

        # Step 1: 获取图片按钮的位置
        get_position_script = r"""
        (function() {
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }
            var selectors = [
                ['div[title="图片"]', 'div_title'],
                ['button[title="图片"]', 'button_title'],
                ['[aria-label="图片"]', 'aria_label'],
                ['[data-testid="chat-image-button"]', 'testid'],
                ['#file1', 'file1_input'],
                ['input[type="file"]', 'file_input']
            ];
            for (var i = 0; i < selectors.length; i++) {
                var entry = selectors[i];
                var node = document.querySelector(entry[0]);
                if (!node) continue;
                var target = node;
                if (node.tagName === 'INPUT' && node.parentElement) {
                    target = node.parentElement;
                }
                if (!isVisible(target)) continue;
                var rect = target.getBoundingClientRect();
                return JSON.stringify({
                    found: true,
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    method: entry[1],
                    selector: entry[0]
                });
            }
            return JSON.stringify({ found: false, error: '未找到图片按钮' });
        })()
        """

        def on_position_result(success, result):
            pos_data = self._parse_js_payload(result) if success else {}
            if not pos_data.get("found"):
                finish(
                    False,
                    build_failure_payload(
                        pos_data.get("error", "获取按钮位置失败"),
                        "locate_image_button",
                    ),
                )
                return

            x = pos_data.get("x", 0)
            y = pos_data.get("y", 0)
            state["trigger_method"] = pos_data.get("method", "unknown")
            state["image_button_x"] = float(x or 0)
            state["image_button_y"] = float(y or 0)
            trigger_pick_and_confirm()

        def on_baseline_signature(success, result):
            baseline = self._parse_js_payload(result) if success else {}
            state["baseline"] = baseline if baseline.get("found") else {}
            self.run_javascript(get_position_script, on_position_result)

        self._get_chat_media_signature(on_baseline_signature)

    def send_video_from_material_library(self, callback: Callable = None):
        """从页面素材库拖拽第一个可见视频到聊天区，并确认发送。"""
        state: Dict[str, Any] = {
            "done": False,
            "baseline": {},
            "verify_attempt": 0,
            "item_rect": {},
            "drop_rect": {},
            "drop_target_data": {},
            "drop_candidates": [],
            "drag_attempt": 0,
            "confirm_attempt": 0,
        }
        max_verify_attempts = 20
        max_confirm_attempts = 10

        def build_failure_payload(message: str, step: str, **extra: Any) -> Dict[str, Any]:
            mapping = {
                "locate_material_library": "locate_material_library_failed",
                "click_material_library": "locate_material_library_failed",
                "locate_video_tab": "locate_video_tab_failed",
                "click_video_tab": "locate_video_tab_failed",
                "locate_video_item": "locate_video_item_failed",
                "locate_chat_drop_target": "locate_chat_drop_target_failed",
                "drag_video_to_chat": "drag_video_to_chat_failed",
                "confirm_click": "confirm_click_failed",
                "verify_timeout": "video_verify_timeout",
            }
            payload: Dict[str, Any] = {
                "error": message,
                "step": step,
                "failure_code": mapping.get(step, step or "video_send_failed"),
            }
            payload.update(extra)
            return payload

        def finish(success: bool, payload: Dict[str, Any]):
            if state["done"]:
                return
            state["done"] = True
            if callback:
                callback(success, payload)

        self._emit_media_debug("开始执行视频发送链路", step="start")

        locate_material_library_script = r"""
        (function() {
            function safeText(el) { return (el && (el.textContent || el.innerText) || "").trim(); }
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }
            function locateSidebarMaterialLibrary() {
                var panelTabs = Array.from(document.querySelectorAll('.panel-tab, .tabs, .tab-list')).filter(isVisible);
                for (var p = 0; p < panelTabs.length; p++) {
                    var root = panelTabs[p];
                    var text = safeText(root);
                    if (text.indexOf('用户信息') === -1 || text.indexOf('商品') === -1 || text.indexOf('快捷语') === -1) continue;
                    var nodes = Array.from(root.querySelectorAll('li, button, div, span, a')).filter(isVisible);
                    for (var i = 0; i < nodes.length; i++) {
                        var node = nodes[i];
                        if (safeText(node) !== '素材库') continue;
                        var rect = node.getBoundingClientRect();
                        return {
                            found: true,
                            action: 'material_library',
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2
                        };
                    }
                }
                return { found: false };
            }
            function locateBackFromProductPanel() {
                var nodes = Array.from(document.querySelectorAll('button, div, span, a, i, svg')).filter(isVisible);
                var titleNode = null;
                for (var i = 0; i < nodes.length; i++) {
                    if (safeText(nodes[i]) === '发送一起买') {
                        titleNode = nodes[i];
                        break;
                    }
                }
                if (!titleNode) return { found: false };

                var titleRect = titleNode.getBoundingClientRect();
                var best = null;
                for (var j = 0; j < nodes.length; j++) {
                    var node = nodes[j];
                    if (node === titleNode) continue;
                    var rect = node.getBoundingClientRect();
                    if (!rect || rect.width < 8 || rect.height < 8) continue;
                    var centerX = rect.left + rect.width / 2;
                    var centerY = rect.top + rect.height / 2;
                    if (centerY < titleRect.top - 30 || centerY > titleRect.bottom + 30) continue;
                    if (centerX >= titleRect.left) continue;
                    var distance = titleRect.left - centerX;
                    if (!best || distance < best.distance) {
                        best = { x: centerX, y: centerY, distance: distance };
                    }
                }
                if (!best) return { found: false };
                return {
                    found: true,
                    action: 'back_from_send_with_buy',
                    x: best.x,
                    y: best.y
                };
            }

            var panelResult = locateSidebarMaterialLibrary();
            if (panelResult.found) {
                return JSON.stringify(panelResult);
            }

            var backResult = locateBackFromProductPanel();
            if (backResult.found) {
                return JSON.stringify(backResult);
            }

            return JSON.stringify({ found: false, error: '未找到素材库Tab' });
        })()
        """

        locate_video_tab_script = r"""
        (function() {
            function safeText(el) { return (el && (el.textContent || el.innerText) || "").trim(); }
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 5 || rect.height < 5) return false;
                return true;
            }
            var roots = Array.from(document.querySelectorAll('.quick-resp-panel, .panel-content, body')).filter(isVisible);
            for (var r = 0; r < roots.length; r++) {
                var root = roots[r];
                var nodes = Array.from(root.querySelectorAll('li, button, div, span, a')).filter(isVisible);
                for (var i = 0; i < nodes.length; i++) {
                    var node = nodes[i];
                    if (safeText(node) !== '视频') continue;
                    var rect = node.getBoundingClientRect();
                    return JSON.stringify({
                        found: true,
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2
                    });
                }
            }
            return JSON.stringify({ found: false, error: '未找到视频Tab' });
        })()
        """

        locate_first_video_item_script = r"""
        (function() {
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 20 || rect.height < 20) return false;
                return true;
            }
            function materialRoot() {
                var roots = Array.from(document.querySelectorAll('.quick-resp-panel, .qr-panel-content, .panel-content')).filter(isVisible);
                for (var i = 0; i < roots.length; i++) {
                    if (roots[i].innerText.indexOf('默认分组') !== -1) return roots[i];
                }
                return document.body;
            }
            var root = materialRoot();
            var items = Array.from(root.querySelectorAll('.item-container')).filter(isVisible);
            if (!items.length) {
                return JSON.stringify({ found: false, error: '未找到视频素材项' });
            }
            var item = items[0];
            var preview = item.querySelector('.preview, img, video, canvas');
            try {
                item.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, cancelable: true, view: window }));
                item.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, view: window }));
            } catch (e) {}
            var rect = item.getBoundingClientRect();
            var previewRect = preview ? preview.getBoundingClientRect() : rect;
            return JSON.stringify({
                found: true,
                item_x: rect.left + rect.width / 2,
                item_y: rect.top + rect.height / 2,
                item_left: rect.left,
                item_top: rect.top,
                item_width: rect.width,
                item_height: rect.height,
                preview_x: previewRect.left + previewRect.width / 2,
                preview_y: previewRect.top + previewRect.height / 2,
                preview_left: previewRect.left,
                preview_top: previewRect.top,
                preview_width: previewRect.width,
                preview_height: previewRect.height
            });
        })()
        """

        locate_chat_drop_target_script = r"""
        (function() {
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                var rect = el.getBoundingClientRect();
                if (!rect || rect.width < 20 || rect.height < 20) return false;
                return true;
            }
            function collectTargets() {
                var selectors = [
                    ['#chat-scroll-view', 'chat_scroll'],
                    ['.chat-scroll-view', 'chat_scroll'],
                    ['.chat-msg-list', 'chat_list'],
                    ['.msg-list', 'chat_list'],
                    ['.message-list', 'chat_list'],
                    ['#input-textarea', 'textbox'],
                    ['.text-area', 'textbox'],
                    ['[role="textbox"]', 'textbox']
                ];
                var targets = [];
                for (var i = 0; i < selectors.length; i++) {
                    var selector = selectors[i][0];
                    var kind = selectors[i][1];
                    var node = document.querySelector(selector);
                    if (!isVisible(node)) continue;
                    var rect = node.getBoundingClientRect();
                    targets.push({
                        selector: selector,
                        kind: kind,
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height
                    });
                }
                return targets;
            }
            var targets = collectTargets();
            if (!targets.length) {
                return JSON.stringify({ found: false, error: '未找到聊天拖拽区域' });
            }
            return JSON.stringify({
                found: true,
                candidates: targets
            });
        })()
        """

        def build_drop_candidates(data: Dict[str, Any], item_rect: Dict[str, Any]) -> list[Dict[str, float]]:
            candidates: list[Dict[str, float]] = []
            seen: set[tuple[int, int]] = set()
            preview_left = float(item_rect.get("preview_left", item_rect.get("item_left", 0)) or 0)
            preview_top = float(item_rect.get("preview_top", item_rect.get("item_top", 0)) or 0)
            preview_width = float(item_rect.get("preview_width", item_rect.get("item_width", 0)) or 0)
            preview_height = float(item_rect.get("preview_height", item_rect.get("item_height", 0)) or 0)
            preview_center_y = float(item_rect.get("preview_y", item_rect.get("item_y", 0)) or 0)

            def add_candidate(x: float, y: float, kind: str):
                if x <= 40 or y <= 20:
                    return
                key = (int(round(x)), int(round(y)))
                if key in seen:
                    return
                seen.add(key)
                candidates.append({"x": float(x), "y": float(y), "kind": kind})

            # 第一优先级：先试“向左轻拖一点点”的近距离落点。
            if preview_left > 0 and preview_width > 0 and preview_height > 0:
                left_shift = min(72.0, max(42.0, preview_width * 0.28))
                near_points = [
                    (preview_left - left_shift, preview_top + preview_height * 0.50, "left_shift_near"),
                    (preview_left - left_shift - 18.0, preview_top + preview_height * 0.46, "left_shift_mid"),
                    (preview_left - left_shift - 32.0, preview_top + preview_height * 0.54, "left_shift_far"),
                ]
                for x, y, point_kind in near_points:
                    add_candidate(x, y, point_kind)

            # 第二优先级：聊天接收区右边缘附近的落点。
            for raw in data.get("candidates", []) or []:
                left = float(raw.get("left", 0) or 0)
                top = float(raw.get("top", 0) or 0)
                width = float(raw.get("width", 0) or 0)
                height = float(raw.get("height", 0) or 0)
                kind = str(raw.get("kind", "") or "")
                if width <= 0 or height <= 0:
                    continue
                if kind not in ("chat_scroll", "chat_list"):
                    continue
                right = left + width
                edge_x = right - min(120.0, max(56.0, width * 0.10))
                min_y = top + 36.0
                max_y = top + max(40.0, height - 36.0)
                edge_y = min(max(preview_center_y, min_y), max_y)
                add_candidate(edge_x, edge_y, "chat_edge_primary")
                add_candidate(edge_x - 28.0, edge_y - 18.0, "chat_edge_upper")
                add_candidate(edge_x - 36.0, edge_y + 22.0, "chat_edge_lower")

            for raw in data.get("candidates", []) or []:
                left = float(raw.get("left", 0) or 0)
                top = float(raw.get("top", 0) or 0)
                width = float(raw.get("width", 0) or 0)
                height = float(raw.get("height", 0) or 0)
                kind = str(raw.get("kind", "") or "")
                if width <= 0 or height <= 0:
                    continue
                if kind == "chat_scroll" or kind == "chat_list":
                    points = [
                        (left + width * 0.40, top + height * 0.65, kind),
                        (left + width * 0.50, top + height * 0.50, kind),
                        (left + width * 0.32, top + height * 0.78, kind),
                    ]
                else:
                    points = [
                        (left + width * 0.50, top + height * 0.50, kind),
                    ]
                for x, y, point_kind in points:
                    add_candidate(x, y, point_kind)
            return candidates

        def poll_delivery():
            if state["done"]:
                return
            state["verify_attempt"] += 1

            def on_signature_result(success, result):
                signature = self._parse_js_payload(result) if success else {}
                pending_visible = bool(signature.get("pending_media_send_visible", False))
                dialog_visible = bool(signature.get("dialog_visible", False))

                if (
                    self._media_send_confirmed(state.get("baseline", {}), signature)
                    and not pending_visible
                    and not dialog_visible
                ):
                    self._emit_media_debug("视频发送确认成功", level="success", step="verified")
                    finish(
                        True,
                        {
                            "success": True,
                            "step": "verified",
                            "triggerMethod": "material_library_video_drag",
                            "verifyAttempts": state["verify_attempt"],
                            "sendMethod": "material_library_drag_first_video",
                            "signature": signature,
                        },
                    )
                    return

                if state["verify_attempt"] >= max_verify_attempts:
                    finish(
                        False,
                        build_failure_payload(
                            "视频未检测到实际发送结果",
                            "verify_timeout",
                            triggerMethod="material_library_video_drag",
                            verifyAttempts=state["verify_attempt"],
                            signature=signature,
                        ),
                    )
                    return

                QTimer.singleShot(450, poll_delivery)

            self._get_chat_media_signature(on_signature_result)

        def confirm_send_dialog():
            if state["done"]:
                return
            state["confirm_attempt"] += 1

            def click_confirm_button(btn_x: float, btn_y: float):
                self._emit_media_debug("视频发送确认按钮已定位", step="confirm_button_ready")
                clicked, click_err = self._native_left_click(btn_x, btn_y)
                if not clicked:
                    finish(
                        False,
                        build_failure_payload(
                            f"点击发送按钮失败: {click_err}",
                            "confirm_click",
                            triggerMethod="material_library_video_drag",
                        ),
                    )
                    return
                self._emit_media_debug("视频发送确认按钮点击成功", step="confirm_button_clicked")
                QTimer.singleShot(350, poll_delivery)

            def fallback_find_confirm_button():
                def on_find_confirm_btn(found_success, found_result):
                    btn_data = self._parse_js_payload(found_result) if found_success else {}
                    if btn_data.get("found"):
                        click_confirm_button(
                            float(btn_data.get("x", 0) or 0),
                            float(btn_data.get("y", 0) or 0),
                        )
                        return

                    if state["confirm_attempt"] >= max_confirm_attempts:
                        more_drop_candidates = state.get("drag_attempt", 0) + 1 < len(state.get("drop_candidates", []))
                        if more_drop_candidates:
                            state["confirm_attempt"] = 0
                            state["drag_attempt"] += 1
                            QTimer.singleShot(180, drag_video_to_chat)
                            return
                        finish(
                            False,
                            build_failure_payload(
                                "拖拽后未出现发送确认框",
                                "drag_video_to_chat",
                                triggerMethod="material_library_video_drag",
                                attemptedDrops=len(state.get("drop_candidates", [])),
                            ),
                        )
                        return

                    QTimer.singleShot(250, confirm_send_dialog)

                self._find_media_send_button(on_find_confirm_btn)

            def on_dialog_state(success, result):
                dialog_state = self._parse_js_payload(result) if success else {}
                dialog_visible = bool(dialog_state.get("dialog_visible", False))
                send_btn_visible = bool(dialog_state.get("send_button_in_dialog_visible", False))

                if dialog_visible and send_btn_visible:
                    self._emit_media_debug("已检测到视频发送确认框", step="confirm_dialog_visible")
                    click_confirm_button(
                        float(dialog_state.get("send_button_x", 0) or 0),
                        float(dialog_state.get("send_button_y", 0) or 0),
                    )
                    return

                fallback_find_confirm_button()

            self._get_media_dialog_state(on_dialog_state)

        def dom_drag_video_to_point(end_x: float, end_y: float, callback2: Callable[[bool, Dict[str, Any]], None]):
            script = rf"""
            (function() {{
                function isVisible(el) {{
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    var rect = el.getBoundingClientRect();
                    if (!rect || rect.width < 20 || rect.height < 20) return false;
                    return true;
                }}
                function pickSourceItem() {{
                    var roots = Array.from(document.querySelectorAll('.quick-resp-panel, .qr-panel-content, .panel-content')).filter(isVisible);
                    var root = document.body;
                    for (var i = 0; i < roots.length; i++) {{
                        if ((roots[i].innerText || '').indexOf('默认分组') !== -1) {{
                            root = roots[i];
                            break;
                        }}
                    }}
                    var items = Array.from(root.querySelectorAll('.item-container')).filter(isVisible);
                    return items.length ? items[0] : null;
                }}
                function createDataTransfer() {{
                    try {{
                        var dt = new DataTransfer();
                        dt.effectAllowed = 'all';
                        dt.dropEffect = 'copy';
                        dt.setData('text/plain', 'video-material');
                        return dt;
                    }} catch (e) {{
                        var store = {{}};
                        return {{
                            effectAllowed: 'all',
                            dropEffect: 'copy',
                            files: [],
                            items: [],
                            types: ['text/plain'],
                            setData: function(t, v) {{ store[t] = String(v || ''); if (this.types.indexOf(t) === -1) this.types.push(t); }},
                            getData: function(t) {{ return store[t] || ''; }},
                        }};
                    }}
                }}
                function fireDrag(el, type, x, y, dataTransfer) {{
                    if (!el) return true;
                    var ev;
                    try {{
                        ev = new DragEvent(type, {{
                            bubbles: true,
                            cancelable: true,
                            clientX: x,
                            clientY: y,
                            dataTransfer: dataTransfer
                        }});
                    }} catch (e) {{
                        ev = document.createEvent('CustomEvent');
                        ev.initCustomEvent(type, true, true, null);
                        Object.defineProperty(ev, 'clientX', {{ value: x }});
                        Object.defineProperty(ev, 'clientY', {{ value: y }});
                        Object.defineProperty(ev, 'dataTransfer', {{ value: dataTransfer }});
                    }}
                    return el.dispatchEvent(ev);
                }}
                function fireMouse(el, type, x, y) {{
                    if (!el) return true;
                    try {{
                        return el.dispatchEvent(new MouseEvent(type, {{
                            bubbles: true,
                            cancelable: true,
                            clientX: x,
                            clientY: y,
                            button: 0,
                            buttons: type === 'mouseup' ? 0 : 1,
                            view: window
                        }}));
                    }} catch (e) {{
                        return true;
                    }}
                }}
                function ancestors(node) {{
                    var arr = [];
                    while (node && arr.length < 8) {{
                        arr.push(node);
                        node = node.parentElement;
                    }}
                    return arr;
                }}

                var item = pickSourceItem();
                if (!item) {{
                    return JSON.stringify({{ found: false, error: '未找到视频素材项' }});
                }}
                var source = item.querySelector('.preview, img, video, canvas') || item;
                var sourceRect = source.getBoundingClientRect();
                var sx = sourceRect.left + sourceRect.width / 2;
                var sy = sourceRect.top + sourceRect.height / 2;
                var tx = {float(end_x):.2f};
                var ty = {float(end_y):.2f};
                var target = document.elementFromPoint(tx, ty);
                if (!target) {{
                    return JSON.stringify({{ found: false, error: '未找到拖拽目标', x: tx, y: ty }});
                }}

                var dt = createDataTransfer();
                fireMouse(source, 'mousedown', sx, sy);
                fireDrag(source, 'dragstart', sx, sy, dt);
                fireDrag(source, 'drag', sx, sy, dt);

                var chain = ancestors(target);
                var accepted = false;
                for (var i = 0; i < chain.length; i++) {{
                    var node = chain[i];
                    var enterOk = fireDrag(node, 'dragenter', tx, ty, dt);
                    var overOk = fireDrag(node, 'dragover', tx, ty, dt);
                    var dropOk = fireDrag(node, 'drop', tx, ty, dt);
                    fireMouse(node, 'mouseup', tx, ty);
                    if (enterOk === false || overOk === false || dropOk === false) {{
                        accepted = true;
                        break;
                    }}
                }}

                fireDrag(source, 'dragend', tx, ty, dt);
                fireMouse(source, 'mouseup', tx, ty);

                return JSON.stringify({{
                    found: true,
                    target_tag: String(target.tagName || ''),
                    target_class: String(target.className || ''),
                    accepted: accepted,
                    x: tx,
                    y: ty
                }});
            }})()
            """

            def on_dom_drag(done_success, done_result):
                payload = self._parse_js_payload(done_result) if done_success else {}
                callback2(bool(payload.get("found")), payload)

            self.run_javascript(script, on_dom_drag)

        def drag_video_to_chat():
            if state["done"]:
                return

            item_rect = dict(state.get("item_rect", {}) or {})
            drop_candidates = list(state.get("drop_candidates", []) or [])
            drag_attempt = int(state.get("drag_attempt", 0) or 0)
            drop_rect = dict(drop_candidates[drag_attempt]) if drag_attempt < len(drop_candidates) else {}
            start_x = float(item_rect.get("preview_x", item_rect.get("item_x", 0)) or 0)
            start_y = float(item_rect.get("preview_y", item_rect.get("item_y", 0)) or 0)
            end_x = float(drop_rect.get("x", 0) or 0)
            end_y = float(drop_rect.get("y", 0) or 0)

            if start_x <= 0 or start_y <= 0 or end_x <= 0 or end_y <= 0:
                finish(
                    False,
                    build_failure_payload(
                        "拖拽起点或终点坐标无效",
                        "drag_video_to_chat",
                    ),
                )
                return

            self._emit_media_debug(
                f"开始拖拽视频素材: attempt={drag_attempt + 1}, drop={str(drop_rect.get('kind', '') or 'unknown')}",
                step="drag_video_to_chat",
                dragAttempt=drag_attempt + 1,
                dropKind=str(drop_rect.get("kind", "") or ""),
            )

            def on_dom_drag_result(dragged: bool, payload: Dict[str, Any]):
                if dragged:
                    self._emit_media_debug(
                        "视频拖拽完成，等待发送确认框",
                        step="drag_video_to_chat_done",
                        dragAttempt=drag_attempt + 1,
                        dropKind=str(drop_rect.get("kind", "") or ""),
                    )
                    QTimer.singleShot(520, confirm_send_dialog)
                    return

                more_drop_candidates = drag_attempt + 1 < len(drop_candidates)
                if more_drop_candidates:
                    state["confirm_attempt"] = 0
                    state["drag_attempt"] = drag_attempt + 1
                    QTimer.singleShot(180, drag_video_to_chat)
                    return
                finish(
                    False,
                    build_failure_payload(
                        payload.get("error", "DOM拖拽视频到聊天区失败"),
                        "drag_video_to_chat",
                        triggerMethod="material_library_video_dom_drag",
                        dropKind=drop_rect.get("kind", ""),
                        dragAttempt=drag_attempt + 1,
                        dropTargetClass=str(payload.get("target_class", "") or ""),
                    ),
                )

            dom_drag_video_to_point(end_x, end_y, on_dom_drag_result)

        def open_video_tab():
            if state["done"]:
                return
            self._emit_media_debug("开始查找视频Tab", step="locate_video_tab")

            def on_video_item_ready(success, result):
                data = self._parse_js_payload(result) if success else {}
                if not data.get("found"):
                    finish(
                        False,
                        build_failure_payload(
                            data.get("error", "未找到视频素材项"),
                            "locate_video_item",
                        ),
                    )
                    return
                self._emit_media_debug("视频素材定位成功", step="video_item_ready")
                state["item_rect"] = {
                    "item_x": float(data.get("item_x", 0) or 0),
                    "item_y": float(data.get("item_y", 0) or 0),
                    "item_left": float(data.get("item_left", 0) or 0),
                    "item_top": float(data.get("item_top", 0) or 0),
                    "item_width": float(data.get("item_width", 0) or 0),
                    "item_height": float(data.get("item_height", 0) or 0),
                    "preview_x": float(data.get("preview_x", data.get("item_x", 0)) or 0),
                    "preview_y": float(data.get("preview_y", data.get("item_y", 0)) or 0),
                    "preview_left": float(data.get("preview_left", data.get("item_left", 0)) or 0),
                    "preview_top": float(data.get("preview_top", data.get("item_top", 0)) or 0),
                    "preview_width": float(data.get("preview_width", data.get("item_width", 0)) or 0),
                    "preview_height": float(data.get("preview_height", data.get("item_height", 0)) or 0),
                }
                candidates = build_drop_candidates(
                    state.get("drop_target_data", {}) or {},
                    state.get("item_rect", {}) or {},
                )
                if not candidates:
                    finish(
                        False,
                        build_failure_payload(
                            "未找到可用视频拖拽落点",
                            "locate_chat_drop_target",
                        ),
                    )
                    return
                state["drop_candidates"] = candidates
                state["drop_rect"] = dict(candidates[0])
                state["drag_attempt"] = 0
                self._emit_media_debug(
                    f"视频拖拽落点准备完成: count={len(candidates)}",
                    step="drop_candidates_ready",
                )
                QTimer.singleShot(200, drag_video_to_chat)

            def on_video_tab(success, result):
                data = self._parse_js_payload(result) if success else {}
                if not data.get("found"):
                    finish(
                        False,
                        build_failure_payload(
                            data.get("error", "未找到视频Tab"),
                            "locate_video_tab",
                        ),
                    )
                    return
                clicked, click_err = self._native_left_click(data.get("x", 0), data.get("y", 0))
                if not clicked:
                    finish(
                        False,
                        build_failure_payload(
                            f"点击视频Tab失败: {click_err}",
                            "click_video_tab",
                        ),
                    )
                    return
                self._emit_media_debug("视频Tab点击成功", step="video_tab_clicked")
                QTimer.singleShot(350, lambda: self.run_javascript(locate_first_video_item_script, on_video_item_ready))

            self.run_javascript(locate_video_tab_script, on_video_tab)

        def open_material_library():
            if state["done"]:
                return
            state.setdefault("material_tab_attempt", 0)
            state["material_tab_attempt"] += 1
            self._emit_media_debug(
                f"开始查找素材库Tab: attempt={int(state.get('material_tab_attempt', 0) or 0)}",
                step="locate_material_library",
            )

            def on_material_tab(success, result):
                data = self._parse_js_payload(result) if success else {}
                if not data.get("found"):
                    finish(
                        False,
                        build_failure_payload(
                            data.get("error", "未找到素材库Tab"),
                            "locate_material_library",
                        ),
                    )
                    return
                action = str(data.get("action", "") or "material_library")
                clicked, click_err = self._native_left_click(data.get("x", 0), data.get("y", 0))
                if not clicked:
                    finish(
                        False,
                        build_failure_payload(
                            f"点击素材库Tab失败: {click_err}",
                            "click_material_library",
                        ),
                    )
                    return
                if action == "back_from_send_with_buy":
                    self._emit_media_debug("检测到发送一起买页面，已点击返回", step="back_from_send_with_buy")
                    if int(state.get("material_tab_attempt", 0) or 0) >= 3:
                        finish(
                            False,
                            build_failure_payload(
                                "已返回发送一起买页但仍未恢复到素材库侧栏",
                                "locate_material_library",
                            ),
                        )
                        return
                    QTimer.singleShot(320, open_material_library)
                    return
                self._emit_media_debug("素材库Tab点击成功", step="material_tab_clicked")
                QTimer.singleShot(350, open_video_tab)

            self.run_javascript(locate_material_library_script, on_material_tab)

        def on_baseline_signature(success, result):
            baseline = self._parse_js_payload(result) if success else {}
            state["baseline"] = baseline if baseline.get("found") else {}
            def on_drop_target(success2, result2):
                data = self._parse_js_payload(result2) if success2 else {}
                if not data.get("found"):
                    finish(
                        False,
                        build_failure_payload(
                            data.get("error", "未找到聊天拖拽区域"),
                            "locate_chat_drop_target",
                        ),
                    )
                    return
                state["drop_target_data"] = data
                self._emit_media_debug(
                    f"视频投放区域定位成功: count={len(data.get('candidates', []) or [])}",
                    step="drop_target_ready",
                )
                open_material_library()

            self.run_javascript(locate_chat_drop_target_script, on_drop_target)

        self._get_chat_media_signature(on_baseline_signature)

    def get_page_url(self) -> str:
        """获取当前页面URL"""
        return self.web_view.url().toString()
