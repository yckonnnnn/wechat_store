import unittest

from src.ui.image_management_tab import ImageManagementTab


class ImageManagementTabLogicTestCase(unittest.TestCase):
    def test_infer_store_target_from_filename(self):
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("客服静安图.jpg"), "sh_jingan")
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("客服人广图.jpg"), "sh_renmin")
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("客服人民广场图.jpg"), "sh_renmin")
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("客服五角场图.jpg"), "sh_wujiaochang")
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("客服虹口图.jpg"), "sh_hongkou")
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("客服徐家汇图.jpg"), "sh_xuhui")
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("客服北京图.jpg"), "beijing_chaoyang")
        self.assertEqual(ImageManagementTab.infer_store_target_from_filename("未知图.jpg"), "")

    def test_migrate_store_targets_for_filenames(self):
        filenames = [
            "客服静安图.jpg",
            "客服人广图.jpg",
            "客服五角场图.jpg",
            "无法识别图.jpg",
        ]
        existing = {
            "客服静安图.jpg": "sh_jingan",
            "invalid.jpg": "not_valid",
        }
        updated, unresolved, changed = ImageManagementTab.migrate_store_targets_for_filenames(
            filenames=filenames,
            existing_targets=existing,
        )

        self.assertTrue(changed)
        self.assertEqual(updated.get("客服静安图.jpg"), "sh_jingan")
        self.assertEqual(updated.get("客服人广图.jpg"), "sh_renmin")
        self.assertEqual(updated.get("客服五角场图.jpg"), "sh_wujiaochang")
        self.assertNotIn("invalid.jpg", updated)
        self.assertEqual(unresolved, ["无法识别图.jpg"])

    def test_resolve_store_target_for_store_address(self):
        self.assertEqual(
            ImageManagementTab.resolve_store_target_for_store_address("北京", "sh_xuhui"),
            "beijing_chaoyang",
        )
        self.assertEqual(
            ImageManagementTab.resolve_store_target_for_store_address("上海", "sh_hongkou"),
            "sh_hongkou",
        )
        self.assertEqual(
            ImageManagementTab.resolve_store_target_for_store_address("上海", "invalid"),
            "",
        )

    def test_matches_shanghai_store_target(self):
        targets = {
            "a.jpg": "sh_jingan",
            "b.jpg": "sh_xuhui",
        }
        self.assertTrue(ImageManagementTab._matches_shanghai_store_target("a.jpg", "sh_jingan", targets))
        self.assertFalse(ImageManagementTab._matches_shanghai_store_target("a.jpg", "sh_xuhui", targets))
        self.assertFalse(ImageManagementTab._matches_shanghai_store_target("c.jpg", "sh_jingan", targets))
        self.assertTrue(ImageManagementTab._matches_shanghai_store_target("c.jpg", "", targets))


if __name__ == "__main__":
    unittest.main()
