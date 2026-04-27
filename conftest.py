"""
Pytest 配置 — 共享 fixture
"""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保使用项目虚拟环境中的 aibot 包
sys.path.insert(0, "venv/Lib/site-packages")

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


# ======================== 基础 fixture ========================


@pytest.fixture
def bot_id():
    return "aibEVpJrf2-Wmk3xgbF00xYb2ldvv29p2WO"


@pytest.fixture
def bot_secret():
    return "7jIKIXuVXkmHMr1pfe9TJvrGE23SGRYwUzGI5hRgnoK"


@pytest.fixture
def options(bot_id, bot_secret):
    return WSClientOptions(
        bot_id=bot_id,
        secret=bot_secret,
        heartbeat_interval=5000,
        reconnect_interval=100,
        max_reconnect_attempts=3,
    )


@pytest.fixture
def client(options):
    return WSClient(options)


# ======================== 模拟帧数据工厂 ========================


def make_text_frame(content="hello", userid="test_user"):
    return {
        "cmd": WsCmd.CALLBACK,
        "headers": {"req_id": generate_req_id("callback")},
        "body": {
            "msgtype": MessageType.Text,
            "text": {"content": content},
            "from": {"userid": userid},
        },
    }


def make_image_frame(url="https://example.com/img.png", aeskey="dGVzdGtleTE2Ynl0ZXM=", userid="test_user"):
    return {
        "cmd": WsCmd.CALLBACK,
        "headers": {"req_id": generate_req_id("callback")},
        "body": {
            "msgtype": MessageType.Image,
            "image": {"url": url, "aeskey": aeskey},
            "from": {"userid": userid},
        },
    }


def make_voice_frame(url="https://example.com/voice.amr", userid="test_user"):
    return {
        "cmd": WsCmd.CALLBACK,
        "headers": {"req_id": generate_req_id("callback")},
        "body": {
            "msgtype": MessageType.Voice,
            "voice": {"url": url},
            "from": {"userid": userid},
        },
    }


def make_file_frame(url="https://example.com/doc.pdf", aeskey="dGVzdGtleTE2Ynl0ZXM=", filename="test.pdf", userid="test_user"):
    return {
        "cmd": WsCmd.CALLBACK,
        "headers": {"req_id": generate_req_id("callback")},
        "body": {
            "msgtype": MessageType.File,
            "file": {"url": url, "aeskey": aeskey, "filename": filename},
            "from": {"userid": userid},
        },
    }


def make_mixed_frame(items=None, userid="test_user"):
    if items is None:
        items = [
            {"type": "text", "text": {"content": "hello"}},
            {"type": "image", "image": {"url": "https://example.com/img.png"}},
        ]
    return {
        "cmd": WsCmd.CALLBACK,
        "headers": {"req_id": generate_req_id("callback")},
        "body": {
            "msgtype": MessageType.Mixed,
            "mixed": {"item": items},
            "from": {"userid": userid},
        },
    }


def make_enter_chat_frame(userid="test_user"):
    return {
        "cmd": WsCmd.EVENT_CALLBACK,
        "headers": {"req_id": generate_req_id("event")},
        "body": {
            "event": {"eventtype": EventType.EnterChat},
            "from": {"userid": userid},
        },
    }


def make_template_card_event_frame(task_id="task_001", userid="test_user"):
    return {
        "cmd": WsCmd.EVENT_CALLBACK,
        "headers": {"req_id": generate_req_id("event")},
        "body": {
            "msgtype": "template_card_event",
            "event": {
                "eventtype": EventType.TemplateCardEvent,
                "task_id": task_id,
            },
            "from": {"userid": userid},
        },
    }


def make_feedback_event_frame(userid="test_user"):
    return {
        "cmd": WsCmd.EVENT_CALLBACK,
        "headers": {"req_id": generate_req_id("event")},
        "body": {
            "msgtype": "feedback_event",
            "event": {
                "eventtype": EventType.FeedbackEvent,
                "feedback": {"score": 5, "comment": "very helpful"},
            },
            "from": {"userid": userid},
        },
    }


def make_auth_response_frame(req_id, errcode=0, errmsg="ok"):
    return {
        "headers": {"req_id": req_id},
        "errcode": errcode,
        "errmsg": errmsg,
    }


def make_heartbeat_ack_frame(req_id, errcode=0):
    return {
        "headers": {"req_id": req_id},
        "errcode": errcode,
        "errmsg": "ok",
    }


def make_reply_ack_frame(req_id, errcode=0, errmsg="ok"):
    return {
        "headers": {"req_id": req_id},
        "errcode": errcode,
        "errmsg": errmsg,
    }
