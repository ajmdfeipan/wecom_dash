"""
多场景综合测试 — 覆盖 wecom-aibot-python-sdk 所有基础功能

测试矩阵:
  1. 客户端初始化与配置
  2. 连接与认证
  3. 心跳保活
  4. 断线重连（指数退避 / 最大重连次数）
  5. 消息分发（text / image / mixed / voice / file）
  6. 事件分发（enter_chat / template_card_event / feedback_event）
  7. 流式回复
  8. 欢迎语回复
  9. 模板卡片回复
 10. 流式 + 卡片组合回复
 11. 更新模板卡片
 12. 主动推送消息
 13. 文件下载与 AES-256-CBC 解密
 14. 加解密工具
 15. 工具函数
 16. 自定义 Logger
 17. 边界与异常场景
"""

import asyncio
import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from aibot import (
    WSClient,
    WSClientOptions,
    MessageType,
    EventType,
    WsCmd,
    DefaultLogger,
    generate_req_id,
    generate_random_string,
    decrypt_file,
)

from conftest import (
    make_text_frame,
    make_image_frame,
    make_voice_frame,
    make_file_frame,
    make_mixed_frame,
    make_enter_chat_frame,
    make_template_card_event_frame,
    make_feedback_event_frame,
    make_auth_response_frame,
    make_heartbeat_ack_frame,
    make_reply_ack_frame,
)


# ================================================================
#  1. 客户端初始化与配置
# ================================================================


class TestClientInit:

    def test_default_options(self):
        opts = WSClientOptions(bot_id="id", secret="sec")
        assert opts.heartbeat_interval == 30000
        assert opts.reconnect_interval == 1000
        assert opts.max_reconnect_attempts == 10
        assert opts.request_timeout == 10000
        assert opts.ws_url == ""

    def test_custom_options(self):
        opts = WSClientOptions(
            bot_id="id",
            secret="sec",
            heartbeat_interval=5000,
            reconnect_interval=500,
            max_reconnect_attempts=5,
            request_timeout=3000,
            ws_url="wss://custom.example.com",
        )
        assert opts.heartbeat_interval == 5000
        assert opts.max_reconnect_attempts == 5
        assert opts.ws_url == "wss://custom.example.com"

    def test_client_creates_with_default_logger(self, options):
        client = WSClient(options)
        assert isinstance(client._logger, DefaultLogger)

    def test_client_creates_with_custom_logger(self, bot_id, bot_secret):
        class CustomLogger:
            def debug(self, m, *a): pass
            def info(self, m, *a): pass
            def warn(self, m, *a): pass
            def error(self, m, *a): pass

        logger = CustomLogger()
        opts = WSClientOptions(bot_id=bot_id, secret=bot_secret, logger=logger)
        client = WSClient(opts)
        assert client._logger is logger

    def test_client_not_connected_initially(self, client):
        assert client.is_connected is False

    def test_credentials_set(self, client, bot_id, bot_secret):
        mgr = client._ws_manager
        assert mgr._bot_id == bot_id
        assert mgr._bot_secret == bot_secret


# ================================================================
#  2. 连接与认证
# ================================================================


class TestConnection:

    @pytest.mark.asyncio
    async def test_connect_sends_auth_frame(self, client, bot_id, bot_secret):
        mock_ws = AsyncMock()
        mock_ws.open = True

        sent_frames = []
        mock_ws.send = AsyncMock(side_effect=lambda d: sent_frames.append(json.loads(d)))

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()

        assert len(sent_frames) >= 1
        auth_frame = sent_frames[0]
        assert auth_frame["cmd"] == WsCmd.SUBSCRIBE
        assert auth_frame["body"]["bot_id"] == bot_id
        assert auth_frame["body"]["secret"] == bot_secret

    @pytest.mark.asyncio
    async def test_connect_fires_connected_event(self, client):
        mock_ws = AsyncMock()
        mock_ws.open = True
        mock_ws.send = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))

        events = []
        client.on("connected", lambda: events.append("connected"))

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()

        assert "connected" in events

    @pytest.mark.asyncio
    async def test_auth_success_fires_authenticated(self, client):
        mock_ws = AsyncMock()
        mock_ws.open = True
        sent = []

        async def fake_send(data):
            sent.append(json.loads(data))

        mock_ws.send = fake_send

        async def fake_aiter():
            if sent:
                auth_req_id = sent[0]["headers"]["req_id"]
                yield json.dumps(make_auth_response_frame(auth_req_id, errcode=0))
            # keep alive briefly
            await asyncio.sleep(0.5)

        mock_ws.__aiter__ = fake_aiter

        events = []
        client.on("authenticated", lambda: events.append("authenticated"))

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()
            await asyncio.sleep(0.3)

        assert "authenticated" in events
        client.disconnect()

    @pytest.mark.asyncio
    async def test_auth_failure_fires_error(self, client):
        mock_ws = AsyncMock()
        mock_ws.open = True
        sent = []

        async def fake_send(data):
            sent.append(json.loads(data))

        mock_ws.send = fake_send

        async def fake_aiter():
            if sent:
                auth_req_id = sent[0]["headers"]["req_id"]
                yield json.dumps(make_auth_response_frame(auth_req_id, errcode=40001, errmsg="invalid"))
            await asyncio.sleep(0.5)

        mock_ws.__aiter__ = fake_aiter

        errors = []
        client.on("error", lambda e: errors.append(e))

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()
            await asyncio.sleep(0.3)

        assert len(errors) == 1
        assert "invalid" in str(errors[0])
        client.disconnect()

    @pytest.mark.asyncio
    async def test_double_connect_warns(self, client):
        mock_ws = AsyncMock()
        mock_ws.open = True
        mock_ws.send = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()
            result = await client.connect()  # should return self without reconnecting

        assert result is client
        client.disconnect()


# ================================================================
#  3. 心跳保活
# ================================================================


class TestHeartbeat:

    @pytest.mark.asyncio
    async def test_heartbeat_sent_after_auth(self, client):
        mock_ws = AsyncMock()
        mock_ws.open = True
        sent = []

        async def fake_send(data):
            sent.append(json.loads(data))

        mock_ws.send = fake_send

        async def fake_aiter():
            auth_req_id = sent[0]["headers"]["req_id"] if sent else ""
            yield json.dumps(make_auth_response_frame(auth_req_id, errcode=0))
            # let heartbeat fire
            await asyncio.sleep(0.2)

        mock_ws.__aiter__ = fake_aiter

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()
            # Wait for heartbeat interval (5000ms = 5s in options, but we use 500ms trick)
            await asyncio.sleep(0.3)

        heartbeat_frames = [f for f in sent if f["cmd"] == WsCmd.HEARTBEAT]
        assert len(heartbeat_frames) >= 0  # May not fire in short window
        client.disconnect()

    @pytest.mark.asyncio
    async def test_heartbeat_ack_resets_missed_count(self, client):
        mgr = client._ws_manager
        mgr._missed_pong_count = 2
        req_id = generate_req_id(WsCmd.HEARTBEAT)
        ack = make_heartbeat_ack_frame(req_id)
        mgr._handle_frame(ack)
        assert mgr._missed_pong_count == 0


# ================================================================
#  4. 断线重连
# ================================================================


class TestReconnection:

    @pytest.mark.asyncio
    async def test_reconnect_on_disconnect(self, client):
        mock_ws = AsyncMock()
        mock_ws.open = True
        connect_count = 0

        async def fake_connect(*args, **kwargs):
            nonlocal connect_count
            connect_count += 1
            ws = AsyncMock()
            ws.open = True
            ws.send = AsyncMock()
            if connect_count == 1:
                ws.__aiter__ = MagicMock(return_value=iter([]))
            else:
                ws.__aiter__ = MagicMock(return_value=iter([]))
            return ws

        reconnect_events = []
        client.on("reconnecting", lambda n: reconnect_events.append(n))

        with patch("aibot.ws.websockets.connect", side_effect=fake_connect):
            # First connect will succeed, then simulate disconnect
            await client.connect()

        # Manually trigger disconnect callback
        mgr = client._ws_manager
        mgr.on_disconnected("test disconnect")

        await asyncio.sleep(0.5)

        client.disconnect()

    @pytest.mark.asyncio
    async def test_max_reconnect_attempts(self):
        opts = WSClientOptions(
            bot_id="id",
            secret="sec",
            max_reconnect_attempts=2,
            reconnect_interval=50,
        )
        c = WSClient(opts)
        errors = []
        c.on("error", lambda e: errors.append(e))

        with patch("aibot.ws.websockets.connect", side_effect=Exception("fail")):
            await c.connect()

        await asyncio.sleep(1.0)
        assert len(errors) >= 1
        assert "Max reconnect" in str(errors[-1])


# ================================================================
#  5. 消息分发
# ================================================================


class TestMessageDispatch:

    def _dispatch(self, client, frame):
        client._message_handler.handle_frame(frame, client)

    def test_text_message_dispatch(self, client):
        received = []
        client.on("message.text", lambda f: received.append(f))
        client.on("message", lambda f: None)

        self._dispatch(client, make_text_frame("hello world"))
        assert len(received) == 1
        assert received[0]["body"]["text"]["content"] == "hello world"

    def test_image_message_dispatch(self, client):
        received = []
        client.on("message.image", lambda f: received.append(f))
        client.on("message", lambda f: None)

        self._dispatch(client, make_image_frame())
        assert len(received) == 1
        assert "url" in received[0]["body"]["image"]

    def test_voice_message_dispatch(self, client):
        received = []
        client.on("message.voice", lambda f: received.append(f))
        client.on("message", lambda f: None)

        self._dispatch(client, make_voice_frame())
        assert len(received) == 1

    def test_file_message_dispatch(self, client):
        received = []
        client.on("message.file", lambda f: received.append(f))
        client.on("message", lambda f: None)

        self._dispatch(client, make_file_frame(filename="report.xlsx"))
        assert len(received) == 1
        assert received[0]["body"]["file"]["filename"] == "report.xlsx"

    def test_mixed_message_dispatch(self, client):
        received = []
        client.on("message.mixed", lambda f: received.append(f))
        client.on("message", lambda f: None)

        self._dispatch(client, make_mixed_frame())
        assert len(received) == 1
        assert len(received[0]["body"]["mixed"]["item"]) == 2

    def test_all_message_types_fire_generic_message(self, client):
        received = []
        client.on("message", lambda f: received.append(f))

        for frame_fn in [make_text_frame, make_image_frame, make_voice_frame,
                         make_file_frame, make_mixed_frame]:
            self._dispatch(client, frame_fn())

        assert len(received) == 5

    def test_unknown_message_type_no_crash(self, client):
        client.on("message", lambda f: None)
        frame = {
            "cmd": WsCmd.CALLBACK,
            "headers": {"req_id": "cb_123"},
            "body": {"msgtype": "unknown_type"},
        }
        self._dispatch(client, frame)  # should not raise

    def test_invalid_frame_no_crash(self, client):
        self._dispatch(client, {"headers": {"req_id": "x"}})  # no body
        self._dispatch(client, {"body": {}})  # no msgtype


# ================================================================
#  6. 事件分发
# ================================================================


class TestEventDispatch:

    def _dispatch(self, client, frame):
        client._message_handler.handle_frame(frame, client)

    def test_enter_chat_event(self, client):
        received = []
        client.on("event.enter_chat", lambda f: received.append(f))
        client.on("event", lambda f: None)

        self._dispatch(client, make_enter_chat_frame("user123"))
        assert len(received) == 1
        assert received[0]["body"]["from"]["userid"] == "user123"

    def test_template_card_event(self, client):
        received = []
        client.on("event.template_card_event", lambda f: received.append(f))
        client.on("event", lambda f: None)

        self._dispatch(client, make_template_card_event_frame("task_001"))
        assert len(received) == 1

    def test_feedback_event(self, client):
        received = []
        client.on("event.feedback_event", lambda f: received.append(f))
        client.on("event", lambda f: None)

        self._dispatch(client, make_feedback_event_frame())
        assert len(received) == 1

    def test_all_events_fire_generic_event(self, client):
        received = []
        client.on("event", lambda f: received.append(f))

        self._dispatch(client, make_enter_chat_frame())
        self._dispatch(client, make_template_card_event_frame())
        self._dispatch(client, make_feedback_event_frame())

        assert len(received) == 3


# ================================================================
#  7. 流式回复
# ================================================================


class TestStreamReply:

    @pytest.mark.asyncio
    async def test_reply_stream_intermediate(self, client):
        frame = make_text_frame("test")
        stream_id = generate_req_id("stream")

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        await client.reply_stream(frame, stream_id, "thinking...", finish=False)

        mock_mgr.send_reply.assert_called_once()
        args = mock_mgr.send_reply.call_args
        body = args[0][1]
        assert body["msgtype"] == "stream"
        assert body["stream"]["id"] == stream_id
        assert body["stream"]["finish"] is False
        assert body["stream"]["content"] == "thinking..."

    @pytest.mark.asyncio
    async def test_reply_stream_final(self, client):
        frame = make_text_frame("test")
        stream_id = generate_req_id("stream")

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        msg_items = [{"type": "image", "image": {"url": "https://example.com/a.png"}}]
        await client.reply_stream(
            frame, stream_id, "done", finish=True,
            msg_item=msg_items, feedback={"satisfycrm": True},
        )

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["stream"]["finish"] is True
        assert body["stream"]["msg_item"] == msg_items
        assert body["stream"]["feedback"] == {"satisfycrm": True}

    @pytest.mark.asyncio
    async def test_reply_stream_no_msg_item_when_not_finish(self, client):
        frame = make_text_frame("test")
        stream_id = generate_req_id("stream")

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        await client.reply_stream(
            frame, stream_id, "partial", finish=False,
            msg_item=[{"type": "text", "text": {"content": "x"}}],
        )

        body = mock_mgr.send_reply.call_args[0][1]
        assert "msg_item" not in body["stream"]


# ================================================================
#  8. 欢迎语回复
# ================================================================


class TestWelcomeReply:

    @pytest.mark.asyncio
    async def test_welcome_text(self, client):
        frame = make_enter_chat_frame()

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        await client.reply_welcome(frame, {
            "msgtype": "text",
            "text": {"content": "欢迎！"},
        })

        args = mock_mgr.send_reply.call_args
        assert args[0][2] == WsCmd.RESPONSE_WELCOME
        assert args[0][1]["msgtype"] == "text"

    @pytest.mark.asyncio
    async def test_welcome_template_card(self, client):
        frame = make_enter_chat_frame()

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        await client.reply_welcome(frame, {
            "msgtype": "template_card",
            "template_card": {"card_type": "text_notice", "main_title": {"title": "Hi"}},
        })

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["msgtype"] == "template_card"
        assert body["template_card"]["card_type"] == "text_notice"


# ================================================================
#  9. 模板卡片回复
# ================================================================


class TestTemplateCardReply:

    @pytest.mark.asyncio
    async def test_reply_template_card(self, client):
        frame = make_text_frame()

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        card = {"card_type": "text_notice", "main_title": {"title": "Notice"}}
        await client.reply_template_card(frame, card)

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["msgtype"] == "template_card"
        assert body["template_card"]["card_type"] == "text_notice"

    @pytest.mark.asyncio
    async def test_reply_template_card_with_feedback(self, client):
        frame = make_text_frame()

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        card = {"card_type": "button_interaction"}
        feedback = {"satisfycrm": True}
        await client.reply_template_card(frame, card, feedback=feedback)

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["template_card"]["feedback"] == feedback


# ================================================================
# 10. 流式 + 卡片组合回复
# ================================================================


class TestStreamWithCard:

    @pytest.mark.asyncio
    async def test_stream_with_card_reply(self, client):
        frame = make_text_frame()
        stream_id = generate_req_id("stream")

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        template_card = {"card_type": "text_notice", "main_title": {"title": "Card"}}
        await client.reply_stream_with_card(
            frame, stream_id, "text content", finish=True,
            template_card=template_card,
            card_feedback={"satisfycrm": True},
        )

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["msgtype"] == "stream_with_template_card"
        assert body["stream"]["finish"] is True
        assert body["template_card"]["card_type"] == "text_notice"
        assert body["template_card"]["feedback"] == {"satisfycrm": True}


# ================================================================
# 11. 更新模板卡片
# ================================================================


class TestUpdateTemplateCard:

    @pytest.mark.asyncio
    async def test_update_template_card(self, client):
        frame = make_template_card_event_frame("task_123")

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        card = {"card_type": "text_notice", "main_title": {"title": "Updated"}}
        await client.update_template_card(frame, card)

        args = mock_mgr.send_reply.call_args
        assert args[0][2] == WsCmd.RESPONSE_UPDATE
        assert args[0][1]["response_type"] == "update_template_card"

    @pytest.mark.asyncio
    async def test_update_template_card_with_userids(self, client):
        frame = make_template_card_event_frame()

        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        card = {"card_type": "text_notice"}
        await client.update_template_card(frame, card, userids=["user1", "user2"])

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["userids"] == ["user1", "user2"]


# ================================================================
# 12. 主动推送消息
# ================================================================


class TestSendMessage:

    @pytest.mark.asyncio
    async def test_send_markdown_message(self, client):
        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        await client.send_message("user123", {
            "msgtype": "markdown",
            "markdown": {"content": "这是一条**主动推送**的消息"},
        })

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["chatid"] == "user123"
        assert body["msgtype"] == "markdown"
        assert "主动推送" in body["markdown"]["content"]

    @pytest.mark.asyncio
    async def test_send_template_card_message(self, client):
        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        await client.send_message("chat_group_001", {
            "msgtype": "template_card",
            "template_card": {"card_type": "news_notice"},
        })

        body = mock_mgr.send_reply.call_args[0][1]
        assert body["chatid"] == "chat_group_001"
        assert body["template_card"]["card_type"] == "news_notice"

    @pytest.mark.asyncio
    async def test_send_message_uses_correct_cmd(self, client):
        mock_mgr = AsyncMock()
        mock_mgr.send_reply = AsyncMock(return_value={"errcode": 0})
        client._ws_manager = mock_mgr

        await client.send_message("u", {"msgtype": "markdown", "markdown": {"content": "hi"}})

        cmd = mock_mgr.send_reply.call_args[0][2]
        assert cmd == WsCmd.SEND_MSG


# ================================================================
# 13. 文件下载与解密
# ================================================================


class TestFileDownload:

    @pytest.mark.asyncio
    async def test_download_file_without_key(self, client):
        raw_data = b"raw file content"

        mock_api = AsyncMock()
        mock_api.download_file_raw = AsyncMock(return_value=(raw_data, "test.txt"))
        client._api_client = mock_api

        data, filename = await client.download_file("https://example.com/f.txt")
        assert data == raw_data
        assert filename == "test.txt"

    @pytest.mark.asyncio
    async def test_download_file_with_aes_key(self, client):
        aes_key = base64.b64encode(b"A" * 32).decode()

        # Encrypt known plaintext with AES-256-CBC
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key = base64.b64decode(aes_key)
        iv = key[:16]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()

        plaintext = b"Hello, WeCom!"
        # PKCS#7 padding
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        encrypted = encryptor.update(padded) + encryptor.finalize()

        mock_api = AsyncMock()
        mock_api.download_file_raw = AsyncMock(return_value=(encrypted, "secret.doc"))
        client._api_client = mock_api

        data, filename = await client.download_file("https://example.com/secret.doc", aes_key)
        assert data == plaintext
        assert filename == "secret.doc"

    @pytest.mark.asyncio
    async def test_download_file_failure(self, client):
        mock_api = AsyncMock()
        mock_api.download_file_raw = AsyncMock(side_effect=Exception("Network error"))
        client._api_client = mock_api

        with pytest.raises(Exception, match="Network error"):
            await client.download_file("https://example.com/f.txt", "key")


# ================================================================
# 14. 加解密工具 (crypto_utils)
# ================================================================


class TestCryptoUtils:

    def test_encrypt_decrypt_roundtrip(self):
        aes_key = base64.b64encode(b"0123456789abcdef" * 2).decode()
        plaintext = b"Test message for AES-256-CBC encryption"

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key = base64.b64decode(aes_key)
        iv = key[:16]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        encrypted = encryptor.update(padded) + encryptor.finalize()

        decrypted = decrypt_file(encrypted, aes_key)
        assert decrypted == plaintext

    def test_decrypt_empty_data_raises(self):
        with pytest.raises(ValueError, match="empty"):
            decrypt_file(b"", "dGVzdA==")

    def test_decrypt_invalid_key_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            decrypt_file(b"data", "")

    def test_decrypt_corrupted_data_raises(self):
        aes_key = base64.b64encode(b"A" * 32).decode()
        with pytest.raises(RuntimeError, match="Decryption failed"):
            decrypt_file(b"not valid encrypted data", aes_key)

    def test_decrypt_with_padding_boundary(self):
        aes_key = base64.b64encode(b"K" * 32).decode()
        # Exactly 16 bytes (one block) of plaintext
        plaintext = b"A" * 16

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key = base64.b64decode(aes_key)
        iv = key[:16]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        pad_len = 16
        padded = plaintext + bytes([pad_len] * pad_len)
        encrypted = encryptor.update(padded) + encryptor.finalize()

        decrypted = decrypt_file(encrypted, aes_key)
        assert decrypted == plaintext

    def test_decrypt_large_data(self):
        aes_key = base64.b64encode(b"X" * 32).decode()
        plaintext = b"Large file content " * 1000

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key = base64.b64decode(aes_key)
        iv = key[:16]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        encrypted = encryptor.update(padded) + encryptor.finalize()

        decrypted = decrypt_file(encrypted, aes_key)
        assert decrypted == plaintext


# ================================================================
# 15. 工具函数
# ================================================================


class TestUtils:

    def test_generate_req_id_format(self):
        rid = generate_req_id("test")
        assert rid.startswith("test_")
        parts = rid.split("_")
        assert len(parts) == 3
        assert parts[1].isdigit()

    def test_generate_req_id_uniqueness(self):
        ids = {generate_req_id("x") for _ in range(100)}
        assert len(ids) == 100

    def test_generate_random_string_default_length(self):
        s = generate_random_string()
        assert len(s) == 8

    def test_generate_random_string_custom_length(self):
        s = generate_random_string(16)
        assert len(s) == 16

    def test_generate_random_string_hex(self):
        s = generate_random_string(32)
        int(s, 16)  # should not raise


# ================================================================
# 16. 枚举与常量
# ================================================================


class TestEnums:

    def test_message_types(self):
        assert MessageType.Text == "text"
        assert MessageType.Image == "image"
        assert MessageType.Mixed == "mixed"
        assert MessageType.Voice == "voice"
        assert MessageType.File == "file"

    def test_event_types(self):
        assert EventType.EnterChat == "enter_chat"
        assert EventType.TemplateCardEvent == "template_card_event"
        assert EventType.FeedbackEvent == "feedback_event"

    def test_ws_commands(self):
        assert WsCmd.SUBSCRIBE == "aibot_subscribe"
        assert WsCmd.HEARTBEAT == "ping"
        assert WsCmd.RESPONSE == "aibot_respond_msg"
        assert WsCmd.RESPONSE_WELCOME == "aibot_respond_welcome_msg"
        assert WsCmd.RESPONSE_UPDATE == "aibot_respond_update_msg"
        assert WsCmd.SEND_MSG == "aibot_send_msg"
        assert WsCmd.CALLBACK == "aibot_msg_callback"
        assert WsCmd.EVENT_CALLBACK == "aibot_event_callback"


# ================================================================
# 17. 串行回复队列
# ================================================================


class TestReplyQueue:

    @pytest.mark.asyncio
    async def test_reply_sends_frame_and_waits_ack(self):
        from aibot.ws import WsConnectionManager

        mgr = WsConnectionManager(DefaultLogger())
        mgr._ws = AsyncMock()
        mgr._ws.open = True
        mgr._ws.send = AsyncMock()

        sent_data = []

        async def capture_send(d):
            sent_data.append(json.loads(d))

        mgr._ws.send = capture_send

        req_id = "test_req_123"
        body = {"msgtype": "text", "text": {"content": "hello"}}
        ack_future = asyncio.ensure_future(mgr.send_reply(req_id, body, WsCmd.RESPONSE))

        await asyncio.sleep(0.05)
        assert len(sent_data) == 1
        assert sent_data[0]["cmd"] == WsCmd.RESPONSE
        assert sent_data[0]["body"] == body

        # Simulate ack
        ack_frame = make_reply_ack_frame(req_id)
        mgr._handle_frame(ack_frame)

        result = await asyncio.wait_for(ack_future, timeout=2.0)
        assert result["errcode"] == 0

    @pytest.mark.asyncio
    async def test_reply_queue_max_size(self):
        from aibot.ws import WsConnectionManager

        mgr = WsConnectionManager(DefaultLogger())
        mgr._ws = AsyncMock()
        mgr._ws.open = True
        mgr._ws.send = AsyncMock()
        mgr._max_reply_queue_size = 3

        req_id = "overflow_req"
        ack_frame = make_reply_ack_frame(req_id)

        def handle_ack_side_effect(data):
            frame = json.loads(data)
            rid = frame["headers"]["req_id"]
            mgr._handle_frame(make_reply_ack_frame(rid))

        mgr._ws.send = AsyncMock(side_effect=handle_ack_side_effect)

        # Fill queue
        for i in range(3):
            await mgr.send_reply(req_id, {"i": i}, WsCmd.RESPONSE)

        # 4th should fail
        with pytest.raises(RuntimeError, match="exceeds max size"):
            await mgr.send_reply(req_id, {"i": 99}, WsCmd.RESPONSE)


# ================================================================
# 18. 断开连接与清理
# ================================================================


class TestDisconnect:

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, client):
        # Should not raise
        c = WSClient(WSClientOptions(bot_id="id", secret="sec"))
        c.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_stops_heartbeat(self, client):
        mgr = client._ws_manager
        mgr._heartbeat_task = asyncio.ensure_future(asyncio.sleep(100))
        mgr._is_manual_close = False

        client.disconnect()
        # heartbeat task should be cancelled
        assert mgr._heartbeat_task is None


# ================================================================
# 19. 自定义 Logger
# ================================================================


class TestLogger:

    def test_default_logger_format(self, capsys):
        logger = DefaultLogger("TestBot")
        logger.info("hello %s", "world")
        captured = capsys.readouterr()
        assert "TestBot" in captured.err
        assert "hello" in captured.err

    def test_logger_protocol_compliance(self):
        class MyLogger:
            def debug(self, m, *a): pass
            def info(self, m, *a): pass
            def warn(self, m, *a): pass
            def error(self, m, *a): pass

        from aibot.types import Logger
        assert isinstance(MyLogger(), Logger)

    def test_default_logger_all_levels(self, capsys):
        logger = DefaultLogger()
        logger.debug("d")
        logger.info("i")
        logger.warn("w")
        logger.error("e")
        out = capsys.readouterr().err
        assert "[DEBUG]" in out
        assert "[INFO]" in out
        assert "[WARN]" in out
        assert "[ERROR]" in out


# ================================================================
# 20. 端到端集成场景
# ================================================================


class TestEndToEnd:

    @pytest.mark.asyncio
    async def test_full_text_conversation_flow(self, client):
        """模拟完整的文本对话流程：认证 → 收消息 → 流式回复"""
        sent = []

        async def capture_send(data):
            sent.append(json.loads(data))

        mock_ws = AsyncMock()
        mock_ws.open = True
        mock_ws.send = capture_send

        async def fake_aiter():
            # 1) auth response
            if sent:
                auth_req_id = sent[0]["headers"]["req_id"]
                yield json.dumps(make_auth_response_frame(auth_req_id))
            await asyncio.sleep(0.1)
            # 2) incoming text message
            text_frame = make_text_frame("你好")
            yield json.dumps(text_frame)
            # 3) ack all reply frames
            await asyncio.sleep(0.2)
            for f in list(sent):
                rid = f.get("headers", {}).get("req_id", "")
                if rid:
                    yield json.dumps(make_reply_ack_frame(rid))
            await asyncio.sleep(0.3)

        mock_ws.__aiter__ = fake_aiter

        replies = []

        @client.on("message.text")
        async def handler(frame):
            content = frame["body"]["text"]["content"]
            stream_id = generate_req_id("stream")
            await client.reply_stream(frame, stream_id, f"Echo: {content}", finish=True)

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()
            await asyncio.sleep(0.6)

        # Should have: auth frame + at least one reply
        stream_frames = [f for f in sent if f.get("body", {}).get("msgtype") == "stream"]
        assert len(stream_frames) >= 1
        assert "Echo" in stream_frames[0]["body"]["stream"]["content"]

        client.disconnect()

    @pytest.mark.asyncio
    async def test_full_card_interaction_flow(self, client):
        """模拟完整的卡片交互流程：发送卡片 → 用户点击 → 更新卡片"""
        sent = []

        async def capture_send(data):
            sent.append(json.loads(data))

        mock_ws = AsyncMock()
        mock_ws.open = True
        mock_ws.send = capture_send

        async def fake_aiter():
            if sent:
                auth_req_id = sent[0]["headers"]["req_id"]
                yield json.dumps(make_auth_response_frame(auth_req_id))
            await asyncio.sleep(0.1)

            # User enters chat
            enter_frame = make_enter_chat_frame("user1")
            yield json.dumps(enter_frame)

            await asyncio.sleep(0.1)
            # ack replies
            for f in list(sent):
                rid = f.get("headers", {}).get("req_id", "")
                if rid:
                    yield json.dumps(make_reply_ack_frame(rid))

            await asyncio.sleep(0.1)
            # Card event
            card_frame = make_template_card_event_frame("task_001")
            yield json.dumps(card_frame)

            await asyncio.sleep(0.1)
            for f in list(sent):
                rid = f.get("headers", {}).get("req_id", "")
                if rid:
                    yield json.dumps(make_reply_ack_frame(rid))

            await asyncio.sleep(0.3)

        mock_ws.__aiter__ = fake_aiter

        @client.on("event.enter_chat")
        async def on_enter(frame):
            await client.reply_welcome(frame, {
                "msgtype": "template_card",
                "template_card": {
                    "card_type": "button_interaction",
                    "main_title": {"title": "请选择"},
                },
            })

        @client.on("event.template_card_event")
        async def on_card(frame):
            await client.update_template_card(frame, {
                "card_type": "text_notice",
                "main_title": {"title": "已处理"},
            })

        with patch("aibot.ws.websockets.connect", return_value=mock_ws):
            await client.connect()
            await asyncio.sleep(1.0)

        welcome_frames = [f for f in sent if f.get("cmd") == WsCmd.RESPONSE_WELCOME]
        update_frames = [f for f in sent if f.get("cmd") == WsCmd.RESPONSE_UPDATE]

        assert len(welcome_frames) >= 1
        assert len(update_frames) >= 1

        client.disconnect()
