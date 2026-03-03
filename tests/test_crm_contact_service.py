import json
import tempfile
import unittest
from pathlib import Path

from src.services.crm_contact_service import CRMContactService


def _append_jsonl(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class CRMContactServiceTestCase(unittest.TestCase):
    def test_extract_phone_normalization_from_user_message_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_path = root / "conversations" / "s1.jsonl"
            _append_jsonl(
                log_path,
                [
                    {
                        "timestamp": "2026-03-03T10:00:00",
                        "session_id": "s1",
                        "event_type": "user_message",
                        "payload": {"user_name": "张三", "text": "我的手机号是 +86 13812345678"},
                    },
                    {
                        "timestamp": "2026-03-03T10:00:01",
                        "session_id": "s1",
                        "event_type": "assistant_reply",
                        "payload": {"text": "请留手机号"},
                    },
                ],
            )

            service = CRMContactService(
                conversation_dir=root / "conversations",
                followup_file=root / "crm_followup_status.json",
            )
            records = service.load_records()

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].contact_type, "phone")
            self.assertEqual(records[0].contact_value, "13812345678")
            self.assertEqual(records[0].user_name, "张三")

    def test_extract_wechat_strict_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_path = root / "conversations" / "s2.jsonl"
            _append_jsonl(
                log_path,
                [
                    {
                        "timestamp": "2026-03-03T10:00:00",
                        "session_id": "s2",
                        "event_type": "user_message",
                        "payload": {"user_name": "李四", "text": "我的微信号：abc_12345"},
                    },
                    {
                        "timestamp": "2026-03-03T10:00:01",
                        "session_id": "s2",
                        "event_type": "user_message",
                        "payload": {"user_name": "李四", "text": "加微信聊一下"},
                    },
                    {
                        "timestamp": "2026-03-03T10:00:02",
                        "session_id": "s2",
                        "event_type": "user_message",
                        "payload": {"user_name": "李四", "text": "微信：中文账号"},
                    },
                ],
            )

            service = CRMContactService(
                conversation_dir=root / "conversations",
                followup_file=root / "crm_followup_status.json",
            )
            records = service.load_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].contact_type, "wechat")
            self.assertEqual(records[0].contact_value, "abc_12345")

    def test_dedupe_and_last_seen_update(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_path = root / "conversations" / "s3.jsonl"
            _append_jsonl(
                log_path,
                [
                    {
                        "timestamp": "2026-03-03T10:00:00",
                        "session_id": "s3",
                        "event_type": "user_message",
                        "payload": {"user_name": "王五", "text": "电话 13900001111"},
                    },
                    {
                        "timestamp": "2026-03-03T10:02:00",
                        "session_id": "s3",
                        "event_type": "user_message",
                        "payload": {"user_name": "王五", "text": "再发一次 13900001111"},
                    },
                ],
            )

            service = CRMContactService(
                conversation_dir=root / "conversations",
                followup_file=root / "crm_followup_status.json",
            )
            records = service.load_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].first_seen_at, "2026-03-03T10:00:00")
            self.assertEqual(records[0].last_seen_at, "2026-03-03T10:02:00")

    def test_followup_status_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_path = root / "conversations" / "s4.jsonl"
            _append_jsonl(
                log_path,
                [
                    {
                        "timestamp": "2026-03-03T10:00:00",
                        "session_id": "s4",
                        "event_type": "user_message",
                        "payload": {"user_name": "赵六", "text": "手机 13612345678"},
                    }
                ],
            )

            followup_file = root / "crm_followup_status.json"
            service = CRMContactService(conversation_dir=root / "conversations", followup_file=followup_file)
            records = service.load_records()
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0].followed_up)

            service.set_followup(records[0].record_key, True)

            service2 = CRMContactService(conversation_dir=root / "conversations", followup_file=followup_file)
            records2 = service2.load_records()
            self.assertTrue(records2[0].followed_up)
            persisted = json.loads(followup_file.read_text(encoding="utf-8"))
            self.assertIn(records[0].record_key, persisted.get("status_map", {}))

    def test_missing_user_name_fallback_to_session_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_path = root / "conversations" / "sim_session.jsonl"
            _append_jsonl(
                log_path,
                [
                    {
                        "timestamp": "2026-03-03T10:00:00",
                        "session_id": "sim_session",
                        "event_type": "user_message",
                        "payload": {"text": "微信 wx_id778899"},
                    },
                    {
                        "timestamp": "2026-03-03T10:00:01",
                        "session_id": "sim_session",
                        "event_type": "user_message",
                        "payload": "broken_payload",
                    },
                ],
            )

            service = CRMContactService(
                conversation_dir=root / "conversations",
                followup_file=root / "crm_followup_status.json",
            )
            records = service.load_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].user_name, "sim_session")
            self.assertEqual(records[0].contact_type, "wechat")
            self.assertEqual(records[0].contact_value, "wx_id778899")


if __name__ == "__main__":
    unittest.main()
