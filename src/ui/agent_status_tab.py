"""
Agent 策略与状态页
用于查看当前 Agent 规则状态并调整关键参数。
"""

from __future__ import annotations

import json
from typing import Any, Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class AgentStatusTab(QWidget):
    reload_prompt_clicked = Signal()
    reload_media_clicked = Signal()
    options_changed = Signal(bool, float, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Agent 策略与状态")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("统一查看规则文档加载状态、媒体资源计数与最近决策。")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("ModelCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.use_kb_checkbox = QCheckBox("优先知识库")
        self.use_kb_checkbox.setChecked(True)
        row.addWidget(self.use_kb_checkbox)

        self.first_reply_video_checkbox = QCheckBox("首轮回复后直接触发视频")
        self.first_reply_video_checkbox.setChecked(False)
        row.addWidget(self.first_reply_video_checkbox)

        row.addWidget(QLabel("知识库阈值"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.6)
        row.addWidget(self.threshold_spin)

        self.apply_btn = QPushButton("应用参数")
        self.apply_btn.setObjectName("Secondary")
        self.apply_btn.clicked.connect(self._emit_options)
        row.addWidget(self.apply_btn)

        row.addStretch()
        card_layout.addLayout(row)

        action_row = QHBoxLayout()
        self.reload_prompt_btn = QPushButton("重载规则文档")
        self.reload_prompt_btn.setObjectName("Secondary")
        self.reload_prompt_btn.clicked.connect(self.reload_prompt_clicked.emit)
        action_row.addWidget(self.reload_prompt_btn)

        self.reload_media_btn = QPushButton("重载媒体索引")
        self.reload_media_btn.setObjectName("Secondary")
        self.reload_media_btn.clicked.connect(self.reload_media_clicked.emit)
        action_row.addWidget(self.reload_media_btn)

        action_row.addStretch()
        card_layout.addLayout(action_row)

        self.status_label = QLabel("状态：等待初始化")
        self.status_label.setObjectName("MutedText")
        card_layout.addWidget(self.status_label)

        layout.addWidget(card)

        self.decision_view = QTextEdit()
        self.decision_view.setReadOnly(True)
        self.decision_view.setPlaceholderText("最近 Agent 决策会显示在这里")
        self.decision_view.setMinimumHeight(260)
        layout.addWidget(self.decision_view, 1)

    def _emit_options(self):
        self.options_changed.emit(
            self.use_kb_checkbox.isChecked(),
            float(self.threshold_spin.value()),
            self.first_reply_video_checkbox.isChecked(),
        )

    def update_status(self, status: Dict[str, Any]):
        use_kb = bool(status.get("use_knowledge_first", True))
        threshold = float(status.get("knowledge_threshold", 0.6))
        first_reply_video_enabled = bool(status.get("first_reply_video_enabled", False))
        reply_mode = str(status.get("reply_mode", "legacy") or "legacy")
        self.use_kb_checkbox.setChecked(use_kb)
        self.threshold_spin.setValue(threshold)
        self.first_reply_video_checkbox.setChecked(first_reply_video_enabled)

        self.status_label.setText(
            " | ".join(
                [
                    f"Prompt: {'已加载' if status.get('system_prompt_loaded') else '缺失'}",
                    f"Playbook: {'已加载' if status.get('playbook_loaded') else '缺失'}",
                    f"品牌知识: {'已加载' if status.get('brand_knowledge_loaded') else '缺失'}",
                    f"回复模式: {reply_mode}",
                    f"地址图: {status.get('address_image_count', 0)}",
                    f"联系方式图: {status.get('contact_image_count', 0)}",
                    f"视频: {status.get('video_media_count', 0)}",
                    f"首轮视频: {'开' if first_reply_video_enabled else '关'}",
                    f"模板: {'已加载' if status.get('template_loaded') else '缺失'}",
                    f"白名单: {status.get('media_whitelist_count', 0)}",
                    f"远程控制: {status.get('remote_control_user_count', 0)}",
                    f"AI状态: {status.get('runtime_status', 'unknown')}",
                    f"TTL: {status.get('memory_ttl_days', 30)}天",
                ]
            )
        )

    def append_decision(self, decision: Dict[str, Any]):
        text = json.dumps(decision, ensure_ascii=False, indent=2)
        self.decision_view.append(text)
        self.decision_view.append("-" * 40)
