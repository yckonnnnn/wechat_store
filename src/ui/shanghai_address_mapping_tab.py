"""
上海地址推荐门店映射页。
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..services.knowledge_service import KnowledgeService


class ShanghaiAddressMappingTab(QWidget):
    """上海地址推荐门店映射配置页面。"""

    log_message = Signal(str)
    mapping_updated = Signal()

    def __init__(self, knowledge_service: KnowledgeService, parent=None):
        super().__init__(parent)
        self.knowledge_service = knowledge_service
        self.page_size = 10
        self.current_page = 1
        self._all_rows: List[Dict[str, str]] = []
        self._row_widgets: List[Dict[str, object]] = []
        self._setup_ui()
        self.reload_rows()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        header_layout = QHBoxLayout()
        title_wrap = QVBoxLayout()
        title = QLabel("上海地址推荐门店映射")
        title.setObjectName("PageTitle")
        title_wrap.addWidget(title)
        subtitle = QLabel("一线客服可直接维护上海路名与门店映射，保存后立即生效")
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
        toolbar.setStyleSheet(
            "border-bottom: 1px solid #e2e8f0; background: #f8fafc; border-top-left-radius: 16px; border-top-right-radius: 16px;"
        )
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 12, 16, 12)
        toolbar_layout.setSpacing(12)

        self.add_btn = QPushButton("新增映射")
        self.add_btn.setObjectName("Secondary")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._add_empty_row)
        toolbar_layout.addWidget(self.add_btn)

        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("Secondary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self.save_rows)
        toolbar_layout.addWidget(self.save_btn)

        self.reload_btn = QPushButton("重新加载")
        self.reload_btn.setObjectName("Secondary")
        self.reload_btn.setCursor(Qt.PointingHandCursor)
        self.reload_btn.clicked.connect(self.reload_rows)
        toolbar_layout.addWidget(self.reload_btn)

        self.reset_btn = QPushButton("恢复默认")
        self.reset_btn.setObjectName("Secondary")
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.clicked.connect(self.reset_rows)
        toolbar_layout.addWidget(self.reset_btn)

        toolbar_layout.addStretch()

        self.stats_label = QLabel("共 0 条")
        self.stats_label.setObjectName("MutedText")
        toolbar_layout.addWidget(self.stats_label)

        content_layout.addWidget(toolbar)

        header_row = QFrame()
        header_row.setStyleSheet("background: #ffffff; border-bottom: 1px solid #f1f5f9;")
        header_layout2 = QHBoxLayout(header_row)
        header_layout2.setContentsMargins(20, 14, 20, 14)
        header_layout2.setSpacing(16)
        for text, stretch in (("关键词/路名", 2), ("推荐门店", 2), ("备注", 3), ("操作", 1)):
            label = QLabel(text)
            label.setStyleSheet("color: #f97316; font-size: 13px; font-weight: 700;")
            header_layout2.addWidget(label, stretch)
        content_layout.addWidget(header_row)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background: #ffffff;")

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(16, 12, 16, 16)
        self.rows_layout.setSpacing(12)
        self.rows_layout.addStretch()
        self.scroll_area.setWidget(self.rows_container)
        content_layout.addWidget(self.scroll_area)

        self.pagination_wrap = QWidget()
        pagination_layout = QHBoxLayout(self.pagination_wrap)
        pagination_layout.setContentsMargins(16, 0, 16, 16)
        pagination_layout.setSpacing(8)
        pagination_layout.addStretch()

        self.prev_page_btn = QPushButton("上一页")
        self.prev_page_btn.setObjectName("Secondary")
        self.prev_page_btn.setCursor(Qt.PointingHandCursor)
        self.prev_page_btn.clicked.connect(self._prev_page)
        pagination_layout.addWidget(self.prev_page_btn)

        self.page_buttons_layout = QHBoxLayout()
        self.page_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.page_buttons_layout.setSpacing(6)
        pagination_layout.addLayout(self.page_buttons_layout)

        self.next_page_btn = QPushButton("下一页")
        self.next_page_btn.setObjectName("Secondary")
        self.next_page_btn.setCursor(Qt.PointingHandCursor)
        self.next_page_btn.clicked.connect(self._next_page)
        pagination_layout.addWidget(self.next_page_btn)

        pagination_layout.addStretch()
        self.pagination_wrap.setVisible(False)
        content_layout.addWidget(self.pagination_wrap)

        self.empty_label = QLabel("暂无映射，点击“新增映射”开始配置")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("MutedText")
        self.empty_label.setVisible(False)
        content_layout.addWidget(self.empty_label)

        layout.addWidget(content_card)

    def _clear_rows(self):
        self._row_widgets.clear()
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _clear_layout_widgets(self, layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _create_row_widget(self, row: Dict[str, str] | None = None, row_index: int = 0):
        row = row or {}
        wrap = QFrame()
        wrap.setStyleSheet("background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px;")
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        keyword_input = QLineEdit()
        keyword_input.setPlaceholderText("例如：常德路、汉口路、静安寺")
        keyword_input.setText(str(row.get("keyword", "") or ""))
        layout.addWidget(keyword_input, 2)

        store_combo = QComboBox()
        for store_key, store_name in self.knowledge_service.get_shanghai_store_options():
            store_combo.addItem(store_name, store_key)
        current_index = max(store_combo.findData(str(row.get("target_store", "") or "")), 0)
        store_combo.setCurrentIndex(current_index)
        layout.addWidget(store_combo, 2)

        note_input = QLineEdit()
        note_input.setPlaceholderText("备注，可选")
        note_input.setText(str(row.get("note", "") or ""))
        layout.addWidget(note_input, 3)

        delete_btn = QPushButton("删除")
        delete_btn.setObjectName("Secondary")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.clicked.connect(lambda: self._remove_row(row_index))
        layout.addWidget(delete_btn, 1)

        self._row_widgets.append(
            {
                "row_index": row_index,
                "wrap": wrap,
                "keyword": keyword_input,
                "target_store": store_combo,
                "note": note_input,
            }
        )
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, wrap)

    def _add_empty_row(self):
        self._sync_current_page_to_model()
        self._all_rows.insert(0, {"keyword": "", "target_store": "", "note": ""})
        self.current_page = 1
        self._render_current_page()

    def _remove_row(self, row_index: int):
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定删除这条上海地址映射吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._sync_current_page_to_model()
        if 0 <= row_index < len(self._all_rows):
            self._all_rows.pop(row_index)
        self.current_page = min(self.current_page, self._get_total_pages())
        self._render_current_page()

    def _get_page_slice(self) -> List[Dict[str, str]]:
        start = max(0, (self.current_page - 1) * self.page_size)
        end = start + self.page_size
        return self._all_rows[start:end]

    def _get_total_pages(self) -> int:
        if not self._all_rows:
            return 1
        return (len(self._all_rows) + self.page_size - 1) // self.page_size

    def _sync_current_page_to_model(self):
        for row in self._row_widgets:
            row_index = int(row["row_index"])
            if 0 <= row_index < len(self._all_rows):
                self._all_rows[row_index] = {
                    "keyword": str(row["keyword"].text()).strip(),
                    "target_store": str(row["target_store"].currentData() or "").strip(),
                    "note": str(row["note"].text()).strip(),
                }

    def _render_current_page(self):
        self._clear_rows()
        for offset, row in enumerate(self._get_page_slice()):
            row_index = (self.current_page - 1) * self.page_size + offset
            self._create_row_widget(row, row_index=row_index)
        self.scroll_area.verticalScrollBar().setValue(0)
        self._refresh_state()

    def _render_pagination(self):
        self._clear_layout_widgets(self.page_buttons_layout)

        has_multiple_pages = len(self._all_rows) > self.page_size
        self.pagination_wrap.setVisible(has_multiple_pages)
        self.prev_page_btn.setEnabled(has_multiple_pages and self.current_page > 1)
        self.next_page_btn.setEnabled(has_multiple_pages and self.current_page < self._get_total_pages())
        if not has_multiple_pages:
            return

        total_pages = self._get_total_pages()
        for page in range(1, total_pages + 1):
            btn = QPushButton(str(page))
            btn.setObjectName("Secondary")
            btn.setCheckable(True)
            btn.setChecked(page == self.current_page)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, p=page: self._go_to_page(p))
            self.page_buttons_layout.addWidget(btn)

    def _go_to_page(self, page: int):
        target = max(1, min(page, self._get_total_pages()))
        if target == self.current_page:
            return
        self._sync_current_page_to_model()
        self.current_page = target
        self._render_current_page()

    def _prev_page(self):
        self._go_to_page(self.current_page - 1)

    def _next_page(self):
        self._go_to_page(self.current_page + 1)

    def _refresh_state(self):
        count = len(self._all_rows)
        self.stats_label.setText(f"共 {count} 条")
        self.empty_label.setVisible(count == 0)
        self.scroll_area.setVisible(count > 0)
        self._render_pagination()

    def reload_rows(self):
        self.knowledge_service.reload_shanghai_route_aliases()
        rows = self.knowledge_service.get_shanghai_route_alias_rows()
        self._all_rows = [dict(row) for row in rows]
        self.current_page = 1
        self._render_current_page()
        self.log_message.emit(f"✅ 上海地址映射已加载: {len(rows)} 条")

    def _collect_rows(self) -> List[Dict[str, str]]:
        self._sync_current_page_to_model()
        return [dict(row) for row in self._all_rows]

    def save_rows(self):
        rows = self._collect_rows()
        if any(not row.get("keyword") for row in rows):
            QMessageBox.warning(self, "保存失败", "关键词/路名不能为空。")
            return
        try:
            self.knowledge_service.save_shanghai_route_alias_rows(rows)
            self.reload_rows()
            QMessageBox.information(self, "保存成功", "上海地址映射已保存并立即生效。")
            self.mapping_updated.emit()
            self.log_message.emit("✅ 上海地址映射已保存并立即生效")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            self.log_message.emit(f"❌ 上海地址映射保存失败: {str(e)}")

    def reset_rows(self):
        reply = QMessageBox.question(
            self,
            "恢复默认",
            "确定恢复默认的上海地址映射吗？当前手动修改会被覆盖。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.knowledge_service.reset_shanghai_route_alias_rows()
            self.reload_rows()
            self.mapping_updated.emit()
            self.log_message.emit("✅ 上海地址映射已恢复默认")
        except Exception as e:
            QMessageBox.warning(self, "恢复失败", str(e))
            self.log_message.emit(f"❌ 上海地址映射恢复默认失败: {str(e)}")
