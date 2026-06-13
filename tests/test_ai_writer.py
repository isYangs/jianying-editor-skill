# ruff: noqa: E402

import json
import os
import sys
import unittest
from unittest.mock import patch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(CURRENT_DIR)
SCRIPTS_PATH = os.path.join(SKILL_ROOT, "scripts")
if SCRIPTS_PATH not in sys.path:
    sys.path.insert(0, SCRIPTS_PATH)

from jianying_ai_writer import (
    FRONTIER_SERVICE,
    AiWriterResult,
    AiWriterStreamAccumulator,
    JianYingAiWriterCredentials,
    build_chat_request,
    build_frontier_url,
    decode_frontier_frame,
    discover_jianying_ai_writer_credentials,
    encode_frontier_frame,
    generate_ai_script,
)


class TestAiWriterProtocol(unittest.TestCase):
    def test_build_chat_request_enables_deep_reasoning(self):
        envelope = build_chat_request(
            "写一段关于存钱的口播稿",
            task_id="task-123",
            model="deepseek-r1",
            need_reasoning=True,
        )

        self.assertEqual(envelope["req_key"], "smart_text_v2")
        self.assertEqual(envelope["task_id"], "task-123")
        self.assertEqual(envelope["status"], "create")

        request = json.loads(envelope["req_payload"])
        self.assertEqual(
            json.loads(request["messages"][0]["content"])["text"],
            "写一段关于存钱的口播稿",
        )
        self.assertEqual(request["messages"][0]["content_type"], 2001)
        self.assertEqual(request["completion_option"]["model"], "deepseek-r1")
        self.assertIs(request["completion_option"]["need_reasoning"], True)
        self.assertIs(request["completion_option"]["ignore_record"], True)

    def test_stream_accumulator_combines_reasoning_and_text_chunks(self):
        accumulator = AiWriterStreamAccumulator(model="deepseek-r1")

        first = accumulator.feed(
            {
                "conversation_id": "conversation-1",
                "is_finish": False,
                "message_id": "message-1",
                "message": {
                    "content": json.dumps(
                        {"reasoning": "先分析问题，", "text": "完整"},
                        ensure_ascii=False,
                    )
                },
            }
        )
        second = accumulator.feed(
            {
                "conversation_id": "conversation-1",
                "is_finish": True,
                "message_id": "message-1",
                "finish_reason": "finish",
                "message": {
                    "content": json.dumps(
                        {"reasoning": "再组织表达。", "text": "文案"},
                        ensure_ascii=False,
                    )
                },
            }
        )

        self.assertIsNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(second.text, "完整文案")
        self.assertEqual(second.reasoning, "先分析问题，再组织表达。")
        self.assertEqual(second.model, "deepseek-r1")
        self.assertEqual(second.conversation_id, "conversation-1")
        self.assertEqual(second.message_id, "message-1")

    def test_frontier_frame_round_trip_preserves_chat_payload(self):
        payload = json.dumps(
            {"task_id": "task-123", "req_key": "smart_text_v2"},
            ensure_ascii=False,
        ).encode("utf-8")

        encoded = encode_frontier_frame(
            payload,
            seq_id=7,
            log_id=123456789,
            service=FRONTIER_SERVICE,
            method=2001,
            headers={"appvr": "8.6.0"},
            payload_type="application/json",
        )
        decoded = decode_frontier_frame(encoded)

        self.assertEqual(decoded.seq_id, 7)
        self.assertEqual(decoded.log_id, 123456789)
        self.assertEqual(decoded.service, FRONTIER_SERVICE)
        self.assertEqual(decoded.method, 2001)
        self.assertEqual(decoded.headers, {"appvr": "8.6.0"})
        self.assertEqual(decoded.payload_type, "application/json")
        self.assertEqual(decoded.payload, payload)
        self.assertEqual(json.loads(decoded.text_payload)["task_id"], "task-123")

    def test_frontier_url_contains_required_authentication_parameters(self):
        credentials = JianYingAiWriterCredentials(
            device_id="device-123",
            user_id="user-456",
            session_id="session with spaces",
        )

        url = build_frontier_url(credentials)

        self.assertTrue(url.startswith("wss://frontier.snssdk.com/ws/v2?"))
        self.assertIn("fpid=73", url)
        self.assertIn("aid=3704", url)
        self.assertIn("device_id=device-123", url)
        self.assertIn("uid=user-456", url)
        self.assertIn("sid=session+with+spaces", url)
        self.assertRegex(url, r"access_key=[0-9a-f]{32}")
        self.assertNotIn("cbc53549d0ac9963f17a96669f8e27c4", url)

    def test_generate_ai_script_uses_frontier_and_returns_finished_text(self):
        credentials = JianYingAiWriterCredentials(
            device_id="device-123",
            user_id="user-456",
            session_id="session-789",
        )
        fake_socket = _FakeWebSocket()
        connector = _FakeConnector(fake_socket)

        with patch("jianying_ai_writer.uuid.uuid4", return_value=_FixedUuid()):
            result = _run_async(
                generate_ai_script(
                    "写一段口播稿",
                    credentials=credentials,
                    connect=connector,
                    timeout=5,
                )
            )

        self.assertIsInstance(result, AiWriterResult)
        self.assertEqual(result.text, "生成完成")
        self.assertEqual(result.reasoning, "正在思考")
        self.assertEqual(connector.subprotocols, ["pbbp2"])
        self.assertEqual(len(fake_socket.sent), 1)

        sent_frame = decode_frontier_frame(fake_socket.sent[0])
        self.assertEqual(sent_frame.service, FRONTIER_SERVICE)
        self.assertEqual(sent_frame.method, 2001)
        sent_payload = json.loads(sent_frame.text_payload)
        self.assertEqual(sent_payload["task_id"], "task-fixed")
        self.assertEqual(sent_payload["req_key"], "smart_text_v2")

    def test_credentials_only_require_local_device_id(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("jianying_ai_writer._read_device_id", return_value="device-123"),
            patch("jianying_ai_writer.uuid.uuid4", return_value=_FixedUuid()),
        ):
            credentials = discover_jianying_ai_writer_credentials()

        self.assertEqual(credentials.device_id, "device-123")
        self.assertEqual(credentials.user_id, "0")
        self.assertEqual(credentials.session_id, "task-fixed")


def _run_async(awaitable):
    import asyncio

    return asyncio.run(awaitable)


class _FixedUuid:
    hex = "task-fixed"


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.responses = []

    async def send(self, data):
        self.sent.append(data)
        request = decode_frontier_frame(data)
        envelope = json.loads(request.text_payload)
        response_chunk = {
            "conversation_id": "conversation-1",
            "message_id": "message-1",
            "is_finish": True,
            "finish_reason": "finish",
            "message": {
                "content": json.dumps(
                    {"reasoning": "正在思考", "text": "生成完成"},
                    ensure_ascii=False,
                )
            },
        }
        outer = {
            "code": 0,
            "task_id": envelope["task_id"],
            "resp_payload": json.dumps(response_chunk, ensure_ascii=False),
        }
        self.responses.append(
            encode_frontier_frame(
                json.dumps(outer, ensure_ascii=False).encode("utf-8"),
                seq_id=request.seq_id,
                log_id=request.log_id,
                service=request.service,
                method=request.method,
                payload_type="application/json",
            )
        )

    async def recv(self):
        return self.responses.pop(0)


class _FakeConnectionContext:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnector:
    def __init__(self, socket):
        self.socket = socket
        self.url = None
        self.subprotocols = None
        self.kwargs = None

    def __call__(self, url, *, subprotocols, **kwargs):
        self.url = url
        self.subprotocols = subprotocols
        self.kwargs = kwargs
        return _FakeConnectionContext(self.socket)


if __name__ == "__main__":
    unittest.main()
