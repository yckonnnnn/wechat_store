import json
import tempfile
import unittest
from pathlib import Path

from src.data.memory_store import MemoryStore


class MemoryStoreTestCase(unittest.TestCase):
    def test_migrates_legacy_global_memory_into_per_user_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy_path = root / "agent_memory.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "version": 5,
                        "updated_at": "2026-03-26T12:00:00",
                        "sessions": {
                            "user_a_session": {
                                "session_id": "user_a_session",
                                "user_hash": "user_a",
                                "last_target_store": "beijing_chaoyang",
                            },
                            "user_b_session": {
                                "session_id": "user_b_session",
                                "user_hash": "user_b",
                                "last_target_store": "sh_hongkou",
                            },
                        },
                        "users": {
                            "user_a": {
                                "user_hash": "user_a",
                                "recent_reply_hashes": ["a1"],
                            },
                            "user_b": {
                                "user_hash": "user_b",
                                "recent_reply_hashes": ["b1"],
                            },
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            store = MemoryStore(legacy_path)

            self.assertFalse(legacy_path.exists())
            backups = list(root.glob("agent_memory.legacy_backup_*.json"))
            self.assertTrue(backups)
            self.assertEqual(
                store.get_session_state("user_a_session", user_hash="user_a").get("last_target_store"),
                "beijing_chaoyang",
            )
            self.assertEqual(
                store.get_user_state("user_b").get("recent_reply_hashes"),
                ["b1"],
            )
            self.assertTrue((root / "memory" / "users" / "user_a.json").exists())
            self.assertTrue((root / "memory" / "users" / "user_b.json").exists())

    def test_user_memory_is_isolated_per_user_file(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.json")

            store.update_session_state(
                "same_session",
                {"last_target_store": "beijing_chaoyang"},
                user_hash="user_a",
            )
            store.update_user_state("user_a", {"recent_reply_hashes": ["a1"]})
            store.update_session_state(
                "same_session",
                {"last_target_store": "sh_xuhui"},
                user_hash="user_b",
            )
            store.update_user_state("user_b", {"recent_reply_hashes": ["b1"]})
            self.assertTrue(store.save())

            reloaded = MemoryStore(Path(td) / "memory.json")
            self.assertEqual(
                reloaded.get_session_state("same_session", user_hash="user_a").get("last_target_store"),
                "beijing_chaoyang",
            )
            self.assertEqual(
                reloaded.get_session_state("same_session", user_hash="user_b").get("last_target_store"),
                "sh_xuhui",
            )
            self.assertEqual(reloaded.get_user_state("user_a").get("recent_reply_hashes"), ["a1"])
            self.assertEqual(reloaded.get_user_state("user_b").get("recent_reply_hashes"), ["b1"])

    def test_corrupted_user_file_only_resets_that_user(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.json")
            store.update_session_state("session_a", {"last_target_store": "sh_jingan"}, user_hash="user_a")
            store.update_session_state("session_b", {"last_target_store": "sh_hongkou"}, user_hash="user_b")
            self.assertTrue(store.save())

            user_a_file = Path(td) / "memory" / "users" / "user_a.json"
            user_a_file.write_text("{broken", encoding="utf-8")

            reloaded = MemoryStore(Path(td) / "memory.json")
            self.assertEqual(reloaded.get_session_state("session_a", user_hash="user_a").get("last_target_store"), "")
            self.assertEqual(
                reloaded.get_session_state("session_b", user_hash="user_b").get("last_target_store"),
                "sh_hongkou",
            )


if __name__ == "__main__":
    unittest.main()
