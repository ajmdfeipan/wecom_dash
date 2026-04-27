"""
企业微信智能机器人后端

基于 wecom-aibot-python-sdk，处理所有消息类型和事件回调，
支持流式回复、模板卡片、主动推送、文件下载等完整功能。
"""

import asyncio
import os

from dotenv import load_dotenv
from aibot import WSClient, WSClientOptions, generate_req_id

load_dotenv()

ws_client = WSClient(
    WSClientOptions(
        bot_id=os.getenv("WECHAT_BOT_ID"),
        secret=os.getenv("WECHAT_BOT_SECRET"),
    )
)


# ======================== 连接生命周期 ========================


@ws_client.on("connected")
def on_connected():
    print("[Event] WebSocket 连接已建立")


@ws_client.on("authenticated")
def on_authenticated():
    print("[Event] 认证成功，机器人已就绪")


@ws_client.on("disconnected")
def on_disconnected(reason):
    print(f"[Event] 连接断开: {reason}")


@ws_client.on("reconnecting")
def on_reconnecting(attempt):
    print(f"[Event] 正在重连 (第 {attempt} 次)")


@ws_client.on("error")
def on_error(error):
    print(f"[Event] 发生错误: {error}")


# ======================== 文本消息 ========================


@ws_client.on("message.text")
async def on_text(frame):
    body = frame.get("body", {})
    text = body.get("text", {})
    content = text.get("content", "")
    user = body.get("from", {}).get("userid", "unknown")
    print(f"[Text] {user}: {content}")

    stream_id = generate_req_id("stream")

    await ws_client.reply_stream(
        frame, stream_id,
        "正在处理您的请求...",
        finish=False,
    )

    await asyncio.sleep(0.5)

    await ws_client.reply_stream(
        frame, stream_id,
        f'收到您的消息："{content}"',
        finish=True,
        feedback={"satisfycrm": True},
    )


# ======================== 图片消息 ========================


@ws_client.on("message.image")
async def on_image(frame):
    body = frame.get("body", {})
    image = body.get("image", {})
    user = body.get("from", {}).get("userid", "unknown")
    print(f"[Image] {user}: imageUrl={image.get('url', 'N/A')}")

    try:
        buffer, filename = await ws_client.download_file(
            image.get("url"), image.get("aeskey")
        )
        print(f"  -> 已下载: {filename}, 大小: {len(buffer)} bytes")
    except Exception as e:
        print(f"  -> 下载失败: {e}")

    await ws_client.reply_stream(
        frame,
        generate_req_id("stream"),
        f"已收到您发送的图片",
        finish=True,
    )


# ======================== 语音消息 ========================


@ws_client.on("message.voice")
async def on_voice(frame):
    body = frame.get("body", {})
    voice = body.get("voice", {})
    user = body.get("from", {}).get("userid", "unknown")
    print(f"[Voice] {user}: voiceUrl={voice.get('url', 'N/A')}")

    await ws_client.reply_stream(
        frame,
        generate_req_id("stream"),
        "已收到语音消息",
        finish=True,
    )


# ======================== 文件消息 ========================


@ws_client.on("message.file")
async def on_file(frame):
    body = frame.get("body", {})
    file_info = body.get("file", {})
    user = body.get("from", {}).get("userid", "unknown")
    print(f"[File] {user}: {file_info.get('filename', 'N/A')}")

    try:
        buffer, filename = await ws_client.download_file(
            file_info.get("url"), file_info.get("aeskey")
        )
        print(f"  -> 已下载: {filename}, 大小: {len(buffer)} bytes")
    except Exception as e:
        print(f"  -> 下载失败: {e}")

    await ws_client.reply_stream(
        frame,
        generate_req_id("stream"),
        f"已收到文件: {file_info.get('filename', 'unknown')}",
        finish=True,
    )


# ======================== 图文混排消息 ========================


@ws_client.on("message.mixed")
async def on_mixed(frame):
    body = frame.get("body", {})
    mixed = body.get("mixed", {})
    user = body.get("from", {}).get("userid", "unknown")
    item_count = len(mixed.get("item", []))
    print(f"[Mixed] {user}: 图文混排 ({item_count} 项)")

    await ws_client.reply_stream(
        frame,
        generate_req_id("stream"),
        f"已收到图文混排消息（{item_count} 项内容）",
        finish=True,
    )


# ======================== 进入会话事件 ========================


@ws_client.on("event.enter_chat")
async def on_enter_chat(frame):
    body = frame.get("body", {})
    user = body.get("from", {}).get("userid", "unknown")
    print(f"[EnterChat] {user} 进入会话")

    await ws_client.reply_welcome(frame, {
        "msgtype": "template_card",
        "template_card": {
            "card_type": "text_notice",
            "main_title": {"title": "欢迎使用智能助手"},
            "emphasis_content": {
                "desc": "有什么可以帮您的？",
            },
            "card_action": {
                "type": 1,
                "url": "https://work.weixin.qq.com",
            },
        },
    })


# ======================== 模板卡片事件 ========================


@ws_client.on("event.template_card_event")
async def on_template_card_event(frame):
    body = frame.get("body", {})
    event = body.get("event", {})
    user = body.get("from", {}).get("userid", "unknown")
    task_id = event.get("task_id", "unknown")
    print(f"[CardEvent] {user} 操作了卡片 task_id={task_id}")

    await ws_client.update_template_card(frame, {
        "card_type": "text_notice",
        "main_title": {"title": "已处理"},
        "sub_title_text": f"Task {task_id} 已完成",
    })


# ======================== 用户反馈事件 ========================


@ws_client.on("event.feedback_event")
async def on_feedback_event(frame):
    body = frame.get("body", {})
    event = body.get("event", {})
    user = body.get("from", {}).get("userid", "unknown")
    feedback = event.get("feedback", {})
    print(f"[Feedback] {user}: {feedback}")

    await ws_client.reply_template_card(frame, {
        "card_type": "text_notice",
        "main_title": {"title": "感谢反馈"},
        "sub_title_text": "我们已收到您的评价",
    })


if __name__ == "__main__":
    print("启动机器人...")
    ws_client.run()
