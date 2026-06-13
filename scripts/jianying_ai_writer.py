import asyncio
import hashlib
import json
import os
import re
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

import websockets

CHAT_CONTENT_TYPE = 2001
SMART_TEXT_REQUEST_KEY = "smart_text_v2"
DEFAULT_MODEL = "deepseek-r1"
FRONTIER_ENDPOINT = "frontier.snssdk.com"
FRONTIER_SUBPROTOCOL = "pbbp2"
FRONTIER_FP_ID = "73"
FRONTIER_AID = "3704"
FRONTIER_SERVICE = 0x2000199
FRONTIER_METHOD = 2001
FRONTIER_APP_KEY = "cbc53549d0ac9963f17a96669f8e27c4"
FRONTIER_ACCESS_SALT = "f8a69f1719916z"
FRONTIER_APP_VERSION = "8.6.0"


class AiWriterError(RuntimeError):
    """Base error for JianYing AI writer failures."""


class AiWriterAuthenticationError(AiWriterError):
    """Raised when JianYing login data is unavailable or rejected."""


class AiWriterCompatibilityError(AiWriterError):
    """Raised when the installed JianYing protocol is unsupported."""


class AiWriterTimeoutError(AiWriterError):
    """Raised when script generation does not finish before the timeout."""


@dataclass(frozen=True)
class AiWriterResult:
    text: str
    reasoning: str
    model: str
    conversation_id: str = ""
    message_id: str = ""


@dataclass(frozen=True)
class JianYingAiWriterCredentials:
    device_id: str
    user_id: str
    session_id: str

    def __post_init__(self):
        if not self.device_id or not self.user_id or not self.session_id:
            raise AiWriterAuthenticationError(
                "JianYing AI writer requires device_id, user_id, and session_id"
            )


@dataclass(frozen=True)
class FrontierFrame:
    seq_id: int
    log_id: int
    service: int
    method: int
    headers: Dict[str, str]
    payload_encoding: str
    payload_type: str
    payload: bytes

    @property
    def text_payload(self) -> str:
        if self.payload_encoding not in ("", "identity"):
            raise AiWriterCompatibilityError(
                f"Unsupported Frontier payload encoding: {self.payload_encoding}"
            )
        return self.payload.decode("utf-8")


def build_chat_request(
    prompt: str,
    task_id: str,
    *,
    model: str = DEFAULT_MODEL,
    need_reasoning: bool = True,
    babi_param: Optional[Dict[str, Any]] = None,
    event_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    if not prompt or not prompt.strip():
        raise ValueError("prompt must not be empty")
    if not task_id:
        raise ValueError("task_id must not be empty")

    request = {
        "messages": [
            {
                "content": json.dumps(
                    {"text": prompt.strip()},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "content_type": CHAT_CONTENT_TYPE,
                "attachments": [],
            }
        ],
        "completion_option": {
            "with_suggest": False,
            "ignore_record": True,
            "model": model,
            "need_reasoning": bool(need_reasoning),
        },
        "conversation_id": "",
        "event_params": json.dumps(
            event_params or {},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    return {
        "req_key": SMART_TEXT_REQUEST_KEY,
        "req_payload": json.dumps(request, ensure_ascii=False, separators=(",", ":")),
        "task_id": task_id,
        "babi_param": json.dumps(
            babi_param or {},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "status": "create",
    }


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Frontier varints must be non-negative")
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _encode_field(field_number: int, wire_type: int, value: bytes) -> bytes:
    return _encode_varint((field_number << 3) | wire_type) + value


def _encode_uint_field(field_number: int, value: int) -> bytes:
    return _encode_field(field_number, 0, _encode_varint(value))


def _encode_bytes_field(field_number: int, value: bytes) -> bytes:
    return _encode_field(field_number, 2, _encode_varint(len(value)) + value)


def _encode_text_field(field_number: int, value: str) -> bytes:
    return _encode_bytes_field(field_number, value.encode("utf-8"))


def encode_frontier_frame(
    payload: bytes,
    *,
    seq_id: int,
    log_id: int,
    service: int = FRONTIER_SERVICE,
    method: int = FRONTIER_METHOD,
    headers: Optional[Mapping[str, str]] = None,
    payload_encoding: str = "",
    payload_type: str = "application/json",
) -> bytes:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes or text")

    frame = bytearray()
    frame.extend(_encode_uint_field(1, seq_id))
    frame.extend(_encode_uint_field(2, log_id))
    frame.extend(_encode_uint_field(3, service))
    frame.extend(_encode_uint_field(4, method))
    for key, value in (headers or {}).items():
        header = _encode_text_field(1, str(key)) + _encode_text_field(2, str(value))
        frame.extend(_encode_bytes_field(5, header))
    if payload_encoding:
        frame.extend(_encode_text_field(6, payload_encoding))
    if payload_type:
        frame.extend(_encode_text_field(7, payload_type))
    frame.extend(_encode_bytes_field(8, bytes(payload)))
    return bytes(frame)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift >= 70:
            break
    raise AiWriterCompatibilityError("Invalid Frontier varint")


def _decode_fields(data: bytes):
    offset = 0
    while offset < len(data):
        key, offset = _decode_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x07
        if wire_type == 0:
            value, offset = _decode_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise AiWriterCompatibilityError("Truncated Frontier fixed64 field")
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise AiWriterCompatibilityError("Truncated Frontier bytes field")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise AiWriterCompatibilityError("Truncated Frontier fixed32 field")
            value = data[offset:end]
            offset = end
        else:
            raise AiWriterCompatibilityError(
                f"Unsupported Frontier protobuf wire type: {wire_type}"
            )
        yield field_number, wire_type, value


def _decode_header(data: bytes) -> tuple[str, str]:
    key = ""
    value = ""
    for field_number, wire_type, raw in _decode_fields(data):
        if wire_type != 2:
            continue
        if field_number == 1:
            key = raw.decode("utf-8")
        elif field_number == 2:
            value = raw.decode("utf-8")
    return key, value


def decode_frontier_frame(data: bytes) -> FrontierFrame:
    if not isinstance(data, (bytes, bytearray)):
        raise AiWriterCompatibilityError("Frontier response must be a binary frame")

    values: Dict[str, Any] = {
        "seq_id": 0,
        "log_id": 0,
        "service": 0,
        "method": 0,
        "headers": {},
        "payload_encoding": "",
        "payload_type": "",
        "payload": b"",
    }
    uint_fields = {1: "seq_id", 2: "log_id", 3: "service", 4: "method"}
    text_fields = {6: "payload_encoding", 7: "payload_type"}

    for field_number, wire_type, raw in _decode_fields(bytes(data)):
        if field_number in uint_fields and wire_type == 0:
            values[uint_fields[field_number]] = raw
        elif field_number == 5 and wire_type == 2:
            key, value = _decode_header(raw)
            if key:
                values["headers"][key] = value
        elif field_number in text_fields and wire_type == 2:
            values[text_fields[field_number]] = raw.decode("utf-8")
        elif field_number == 8 and wire_type == 2:
            values["payload"] = raw

    return FrontierFrame(**values)


def _frontier_access_key(device_id: str) -> str:
    source = (
        FRONTIER_FP_ID
        + FRONTIER_APP_KEY
        + device_id
        + FRONTIER_ACCESS_SALT
    )
    return hashlib.md5(source.encode("utf-8")).hexdigest()


def build_frontier_url(credentials: JianYingAiWriterCredentials) -> str:
    query = {
        "device_platform": "web",
        "version_code": "fws_1.0.0",
        "access_key": _frontier_access_key(credentials.device_id),
        "fpid": FRONTIER_FP_ID,
        "aid": FRONTIER_AID,
        "device_id": credentials.device_id,
        "xsack": "0",
        "xaack": "0",
        "xsqos": "0",
        "qos_sdk_version": "2",
        "uid": credentials.user_id,
        "sid": credentials.session_id,
    }
    return f"wss://{FRONTIER_ENDPOINT}/ws/v2?{urllib.parse.urlencode(query)}"


def _read_device_id() -> str:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        return ""
    config_path = (
        Path(local_app_data)
        / "JianyingPro"
        / "User Data"
        / "TTNet"
        / "tt_net_config.config"
    )
    try:
        content = config_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = re.search(r"device_id&#\*(\d+)", content)
    return match.group(1) if match else ""


def discover_jianying_ai_writer_credentials() -> JianYingAiWriterCredentials:
    device_id = os.getenv("JY_AI_WRITER_DID") or _read_device_id()
    if not device_id:
        raise AiWriterAuthenticationError(
            "Unable to discover JianYing device_id. Start JianYing once or set "
            "JY_AI_WRITER_DID."
        )
    user_id = os.getenv("JY_AI_WRITER_UID") or "0"
    session_id = os.getenv("JY_AI_WRITER_SID") or uuid.uuid4().hex
    return JianYingAiWriterCredentials(device_id, user_id, session_id)


def _new_log_id() -> int:
    return int(time.time() * 1000) * 10_000 + int.from_bytes(os.urandom(2), "big") % 10_000


async def generate_ai_script(
    prompt: str,
    *,
    credentials: Optional[JianYingAiWriterCredentials] = None,
    model: str = DEFAULT_MODEL,
    need_reasoning: bool = True,
    timeout: float = 120.0,
    connect: Optional[Callable[..., Any]] = None,
) -> AiWriterResult:
    credentials = credentials or discover_jianying_ai_writer_credentials()
    task_id = uuid.uuid4().hex
    envelope = build_chat_request(
        prompt,
        task_id,
        model=model,
        need_reasoning=need_reasoning,
    )
    payload = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    frame = encode_frontier_frame(
        payload,
        seq_id=0,
        log_id=_new_log_id(),
        headers={"appvr": FRONTIER_APP_VERSION},
    )
    connector = connect or websockets.connect
    accumulator = AiWriterStreamAccumulator(model=model)
    deadline = time.monotonic() + timeout

    try:
        async with connector(
            build_frontier_url(credentials),
            subprotocols=[FRONTIER_SUBPROTOCOL],
            open_timeout=min(timeout, 20.0),
            close_timeout=5,
        ) as websocket:
            await websocket.send(frame)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AiWriterTimeoutError("JianYing AI writer timed out")
                raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                if isinstance(raw, str):
                    if raw == "hi":
                        continue
                    try:
                        outer = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise AiWriterCompatibilityError(
                            "Unexpected Frontier text response"
                        ) from exc
                else:
                    response_frame = decode_frontier_frame(raw)
                    if response_frame.method != FRONTIER_METHOD:
                        continue
                    try:
                        outer = json.loads(response_frame.text_payload)
                    except json.JSONDecodeError as exc:
                        raise AiWriterCompatibilityError(
                            "Frontier returned invalid JSON"
                        ) from exc

                if outer.get("task_id") not in (None, "", task_id):
                    continue
                code = outer.get("code", 0)
                if code not in (0, "0", None):
                    detail = outer.get("message") or outer.get("msg") or f"code {code}"
                    if code in (401, 403, "401", "403"):
                        raise AiWriterAuthenticationError(
                            f"JianYing AI writer authentication failed: {detail}"
                        )
                    raise AiWriterError(f"JianYing AI writer request failed: {detail}")

                response_payload = outer.get("resp_payload")
                if not response_payload:
                    continue
                try:
                    chunk = (
                        json.loads(response_payload)
                        if isinstance(response_payload, str)
                        else response_payload
                    )
                except json.JSONDecodeError as exc:
                    raise AiWriterCompatibilityError(
                        "JianYing AI writer returned invalid stream JSON"
                    ) from exc
                result = accumulator.feed(chunk)
                if result is not None:
                    return result
    except AiWriterError:
        raise
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise AiWriterTimeoutError("JianYing AI writer timed out") from exc
    except Exception as exc:
        message = str(exc)
        if any(token in message.lower() for token in ("401", "403", "unauthorized", "forbidden")):
            raise AiWriterAuthenticationError(
                "JianYing AI writer rejected the current login session"
            ) from exc
        raise AiWriterCompatibilityError(
            f"Unable to connect to JianYing AI writer: {message}"
        ) from exc


class AiWriterStreamAccumulator:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.reasoning = ""
        self.text = ""
        self.conversation_id = ""
        self.message_id = ""

    def feed(self, response: Dict[str, Any]) -> Optional[AiWriterResult]:
        self.conversation_id = response.get("conversation_id") or self.conversation_id
        self.message_id = response.get("message_id") or self.message_id

        message = response.get("message") or {}
        raw_content = message.get("content") or "{}"
        try:
            content = json.loads(raw_content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AiWriterCompatibilityError("AI writer returned invalid message content") from exc

        self.reasoning += content.get("reasoning") or ""
        self.text += content.get("text") or ""

        if not response.get("is_finish"):
            return None
        if response.get("finish_reason") not in (None, "", "finish"):
            reason = response.get("finish_reason")
            detail = response.get("finish_error_tips") or reason
            raise AiWriterError(f"AI writer generation failed: {detail}")
        if not self.text.strip():
            raise AiWriterCompatibilityError("AI writer finished without generated text")

        return AiWriterResult(
            text=self.text.strip(),
            reasoning=self.reasoning.strip(),
            model=self.model,
            conversation_id=self.conversation_id,
            message_id=self.message_id,
        )
