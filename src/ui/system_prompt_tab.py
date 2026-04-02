"""
系统提示词标签页。
以只读方式展示当前生效的系统提示词内容。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SystemPromptTab(QWidget):
    """系统提示词展示页面（只读）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("系统提示词")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("当前生效的系统提示词内容，仅供查看，默认不允许修改。")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText("暂无提示词内容")
        layout.addWidget(self.text_edit, 1)

    def set_content(self, text: str) -> None:
        self.text_edit.setPlainText(text)
