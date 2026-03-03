"""
客户信息管理标签页。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.crm_contact_service import CRMContactRecord, CRMContactService


class CRMManagerTab(QWidget):
    """客户信息管理页面。"""

    log_message = Signal(str)

    def __init__(self, service: CRMContactService | None = None, parent=None):
        super().__init__(parent)
        self.service = service or CRMContactService(
            conversation_dir=Path("data") / "conversations",
            followup_file=Path("data") / "crm_followup_status.json",
        )
        self._search_text = ""
        self._all_records: List[CRMContactRecord] = []
        self._filtered_records: List[CRMContactRecord] = []
        self._setup_ui()
        self.reload_records()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        header_layout = QHBoxLayout()
        title_wrap = QVBoxLayout()
        title = QLabel("客户信息管理")
        title.setObjectName("PageTitle")
        title_wrap.addWidget(title)
        subtitle = QLabel("自动汇总聊天中用户主动提供的手机号与微信")
        subtitle.setObjectName("PageSubtitle")
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        content_card = QFrame()
        content_card.setObjectName("TableCard")
        content_layout = QVBoxLayout(content_card)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setStyleSheet("border-bottom: 1px solid #e2e8f0; background: #f8fafc; border-top-left-radius: 16px; border-top-right-radius: 16px;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 12, 16, 12)
        toolbar_layout.setSpacing(12)

        search_wrap = QWidget()
        search_wrap.setObjectName("SearchBox")
        search_wrap.setMaximumWidth(420)
        search_layout = QHBoxLayout(search_wrap)
        search_layout.setContentsMargins(12, 6, 12, 6)

        search_icon = QLabel("🔍")
        search_icon.setStyleSheet("color: #94a3b8; font-size: 14px;")
        search_layout.addWidget(search_icon)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("搜索用户名、手机号、微信...")
        self.search_input.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_input)
        toolbar_layout.addWidget(search_wrap)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("Secondary")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.reload_records)
        toolbar_layout.addWidget(self.refresh_btn)

        toolbar_layout.addStretch()

        self.stats_label = QLabel("共 0 条")
        self.stats_label.setObjectName("MutedText")
        toolbar_layout.addWidget(self.stats_label)

        content_layout.addWidget(toolbar)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["用户名", "联系方式", "操作"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 180)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.table.setStyleSheet(
            """
            QTableWidget {
                background: #ffffff;
                border: none;
                gridline-color: transparent;
            }
            QTableWidget::item {
                padding: 12px 16px;
                border-bottom: 1px solid #f1f5f9;
            }
            QHeaderView::section {
                background: #ffffff;
                color: #f97316;
                font-size: 13px;
                font-weight: 700;
                border: none;
                border-bottom: 2px solid #f1f5f9;
                padding: 12px 16px;
            }
            """
        )
        content_layout.addWidget(self.table)

        self.empty_label = QLabel("暂无可解析的客户联系方式")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("MutedText")
        self.empty_label.setVisible(False)
        content_layout.addWidget(self.empty_label)

        layout.addWidget(content_card)

    def reload_records(self):
        try:
            self._all_records = self.service.refresh()
        except Exception as e:
            self.log_message.emit(f"❌ CRM 数据加载失败: {str(e)}")
            self._all_records = []
        self._apply_filter()
        self.log_message.emit(f"✅ CRM 数据已刷新: {len(self._all_records)} 条")

    def _on_search(self, text: str):
        self._search_text = (text or "").strip().lower()
        self._apply_filter()

    def _apply_filter(self):
        if not self._search_text:
            self._filtered_records = list(self._all_records)
        else:
            keyword = self._search_text
            self._filtered_records = [
                r
                for r in self._all_records
                if keyword in r.user_name.lower()
                or keyword in r.contact_display.lower()
                or keyword in r.contact_value.lower()
            ]
        self._render_table()

    def _render_table(self):
        records = self._filtered_records
        self.table.setRowCount(len(records))
        self.empty_label.setVisible(len(records) == 0)
        self.stats_label.setText(f"共 {len(records)} 条")

        for row, record in enumerate(records):
            name_item = QTableWidgetItem(record.user_name)
            name_item.setToolTip(record.user_name)
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, 0, name_item)

            contact_item = QTableWidgetItem(record.contact_display)
            contact_item.setToolTip(
                f"{record.contact_display}\n最近出现: {record.last_seen_at or '-'}\n会话: {record.session_id}"
            )
            contact_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, 1, contact_item)

            btn = QPushButton()
            btn.setObjectName("Secondary")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setChecked(bool(record.followed_up))
            self._apply_followup_button_text(btn)
            btn.toggled.connect(
                lambda checked, key=record.record_key, button=btn: self._on_toggle_followup(key, checked, button)
            )

            wrap = QWidget()
            wrap_layout = QHBoxLayout(wrap)
            wrap_layout.setContentsMargins(0, 0, 16, 0)
            wrap_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            wrap_layout.addWidget(btn)
            self.table.setCellWidget(row, 2, wrap)

    def _on_toggle_followup(self, record_key: str, checked: bool, button: QPushButton):
        try:
            self.service.set_followup(record_key, checked)
            for record in self._all_records:
                if record.record_key == record_key:
                    record.followed_up = checked
                    break
            self._apply_followup_button_text(button)
            self.log_message.emit(f"✅ 客户跟进状态已更新: {'已跟进' if checked else '未跟进'}")
        except Exception as e:
            button.blockSignals(True)
            button.setChecked(not checked)
            button.blockSignals(False)
            self._apply_followup_button_text(button)
            self.log_message.emit(f"❌ 更新跟进状态失败: {str(e)}")

    def _apply_followup_button_text(self, button: QPushButton):
        button.setText("已跟进" if button.isChecked() else "未跟进")
