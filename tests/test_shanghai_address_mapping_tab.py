import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.shanghai_address_mapping_tab import ShanghaiAddressMappingTab


class FakeKnowledgeService:
    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]
        self.saved_rows = None

    def reload_shanghai_route_aliases(self):
        return None

    def get_shanghai_route_alias_rows(self):
        return [dict(row) for row in self._rows]

    def get_shanghai_store_options(self):
        return [
            ("sh_jingan", "上海静安门店"),
            ("sh_renmin", "上海人民广场门店"),
            ("sh_hongkou", "上海虹口门店"),
            ("sh_wujiaochang", "上海五角场门店"),
            ("sh_xuhui", "上海徐汇门店"),
        ]

    def save_shanghai_route_alias_rows(self, rows):
        self.saved_rows = [dict(row) for row in rows]
        self._rows = [dict(row) for row in rows]

    def reset_shanghai_route_alias_rows(self):
        self._rows = []


class ShanghaiAddressMappingTabTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build_rows(self, count):
        return [
            {
                "keyword": f"路名{i + 1}",
                "target_store": "sh_renmin" if i % 2 == 0 else "sh_jingan",
                "note": f"备注{i + 1}",
            }
            for i in range(count)
        ]

    def _create_tab(self, count):
        service = FakeKnowledgeService(self._build_rows(count))
        tab = ShanghaiAddressMappingTab(service)
        return tab, service

    def test_paginates_rows_in_groups_of_ten(self):
        tab, _service = self._create_tab(24)

        self.assertEqual(tab.page_size, 10)
        self.assertEqual(tab.current_page, 1)
        self.assertEqual(tab._get_total_pages(), 3)
        self.assertEqual(len(tab._row_widgets), 10)
        self.assertEqual(tab._row_widgets[0]["keyword"].text(), "路名1")

        tab._go_to_page(3)

        self.assertEqual(tab.current_page, 3)
        self.assertEqual(len(tab._row_widgets), 4)
        self.assertEqual(tab._row_widgets[0]["keyword"].text(), "路名21")

        tab.deleteLater()

    def test_page_switch_preserves_edits(self):
        tab, _service = self._create_tab(24)

        tab._go_to_page(2)
        tab._row_widgets[0]["keyword"].setText("已修改路名")
        tab._row_widgets[0]["note"].setText("已修改备注")

        tab._go_to_page(1)
        tab._go_to_page(2)

        self.assertEqual(tab._row_widgets[0]["keyword"].text(), "已修改路名")
        self.assertEqual(tab._row_widgets[0]["note"].text(), "已修改备注")
        self.assertEqual(tab._all_rows[10]["keyword"], "已修改路名")
        self.assertEqual(tab._all_rows[10]["note"], "已修改备注")

        tab.deleteLater()

    def test_add_empty_row_inserts_at_top_and_jumps_to_first_page(self):
        tab, _service = self._create_tab(24)

        tab._go_to_page(3)
        tab._add_empty_row()

        self.assertEqual(tab.current_page, 1)
        self.assertEqual(tab._all_rows[0], {"keyword": "", "target_store": "", "note": ""})
        self.assertEqual(tab._row_widgets[0]["keyword"].text(), "")
        self.assertEqual(len(tab._row_widgets), 10)

        tab.deleteLater()

    def test_delete_row_clamps_current_page(self):
        tab, _service = self._create_tab(11)

        tab._go_to_page(2)
        tab._remove_row(10)

        self.assertEqual(tab.current_page, 1)
        self.assertEqual(tab._get_total_pages(), 1)
        self.assertEqual(len(tab._all_rows), 10)
        self.assertEqual(len(tab._row_widgets), 10)

        tab.deleteLater()

    def test_save_rows_keeps_global_order(self):
        tab, service = self._create_tab(12)

        tab._go_to_page(2)
        tab._row_widgets[0]["keyword"].setText("第11条已修改")

        tab._go_to_page(1)
        tab._add_empty_row()
        tab._row_widgets[0]["keyword"].setText("新置顶")
        tab._row_widgets[0]["note"].setText("第一条")
        tab._row_widgets[0]["target_store"].setCurrentIndex(1)

        tab.save_rows()

        self.assertIsNotNone(service.saved_rows)
        self.assertEqual(service.saved_rows[0]["keyword"], "新置顶")
        self.assertEqual(service.saved_rows[0]["target_store"], "sh_renmin")
        self.assertEqual(service.saved_rows[10]["keyword"], "路名10")
        self.assertEqual(service.saved_rows[11]["keyword"], "第11条已修改")
        self.assertEqual(service.saved_rows[12]["keyword"], "路名12")

        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
