import json
import unittest

from src.services.browser_service import BrowserService


class BrowserServiceVisualVerificationTest(unittest.TestCase):
    def test_visual_media_requires_new_media_count_or_new_message(self):
        baseline = {"kf_media_count": 1, "kf_total_count": 3}

        self.assertFalse(
            BrowserService._is_expected_new_visual_media(
                None,
                baseline,
                {
                    "found": True,
                    "type": "image",
                    "kf_media_count": 1,
                    "kf_total_count": 3,
                    "last_is_expected_media": True,
                },
                "image",
            )
        )

        self.assertFalse(
            BrowserService._is_expected_new_visual_media(
                None,
                baseline,
                {
                    "found": True,
                    "type": "image",
                    "kf_media_count": 2,
                    "kf_total_count": 4,
                    "last_is_expected_media": True,
                },
                "video",
            )
        )

        self.assertTrue(
            BrowserService._is_expected_new_visual_media(
                None,
                baseline,
                {
                    "found": True,
                    "type": "image",
                    "kf_media_count": 2,
                    "kf_total_count": 4,
                    "last_is_expected_media": True,
                },
                "image",
            )
        )

    def test_visual_verification_uses_current_chat_message_structure(self):
        captured = {}

        class DummyBrowserService:
            def _parse_js_payload(self, payload):
                return BrowserService._parse_js_payload(None, payload)

            def _is_expected_new_visual_media(self, baseline, visual, expected_type):
                return BrowserService._is_expected_new_visual_media(None, baseline, visual, expected_type)

            def run_javascript(self, script, callback):
                captured["script"] = script
                callback(
                    True,
                    json.dumps(
                        {
                            "found": True,
                            "type": "video",
                            "kf_media_count": 2,
                            "kf_total_count": 4,
                            "last_is_expected_media": True,
                        }
                    ),
                )

        result = {}
        BrowserService._verify_media_visually(
            DummyBrowserService(),
            "video",
            {"kf_media_count": 1, "kf_total_count": 3},
            lambda found, visual: result.update({"found": found, "visual": visual}),
        )

        self.assertIn(".message-item", captured["script"])
        self.assertIn("justify-end", captured["script"])
        self.assertNotIn(".kf-message", captured["script"])
        self.assertTrue(result["found"])
        self.assertEqual(result["visual"]["type"], "video")


if __name__ == "__main__":
    unittest.main()
