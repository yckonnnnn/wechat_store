import unittest

from PySide6.QtCore import QRect

from src.ui.main_window import MainWindow


class MainWindowGeometryTestCase(unittest.TestCase):
    def test_compute_initial_window_geometry_clamps_to_available_area(self):
        available = QRect(0, 0, 1280, 800)

        geometry = MainWindow._compute_initial_window_geometry(available)

        self.assertLessEqual(geometry.width(), available.width() - MainWindow.WINDOW_SCREEN_MARGIN * 2)
        self.assertLessEqual(geometry.height(), available.height() - MainWindow.WINDOW_SCREEN_MARGIN * 2)
        self.assertGreaterEqual(geometry.x(), available.x())
        self.assertGreaterEqual(geometry.y(), available.y())
        self.assertLessEqual(geometry.right(), available.right())
        self.assertLessEqual(geometry.bottom(), available.bottom())

    def test_compute_initial_window_geometry_keeps_default_size_when_space_allows(self):
        available = QRect(0, 0, 1920, 1080)

        geometry = MainWindow._compute_initial_window_geometry(available)

        self.assertEqual(geometry.width(), MainWindow.DEFAULT_WINDOW_WIDTH)
        self.assertEqual(geometry.height(), MainWindow.DEFAULT_WINDOW_HEIGHT)


if __name__ == "__main__":
    unittest.main()
