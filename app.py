"""
企业微信智能机器人 — Web 管理面板入口

启动方式: python app.py
面板地址: http://localhost:8080
"""

import asyncio
import json
import os
import time
import uuid

from aiohttp import web
from dotenv import load_dotenv

from aibot import WSClient, WSClientOptions, generate_req_id, MessageType, EventType
from dashboard.state import BotState
from dashboard.server import create_app
from dashboard.db import init_db, insert_message

load_dotenv()

FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files")
os.makedirs(FILES_DIR, exist_ok=True)

init_db()

# ======================== 共享状态 ========================

state = BotState()
state.bot_id = os.getenv("WECHAT_BOT_ID", "")
state.heartbeat_interval = 30000

# ======================== 创建 Bot ========================

bot = WSClient(
    WSClientOptions(
        bot_id=os.getenv("WECHAT_BOT_ID"),
        secret=os.getenv("WECHAT_BOT_SECRET"),
    )
)


# ======================== 辅助函数 ========================


def _user(frame: dict) -> str:
    return frame.get("body", {}).get("from", {}).get("userid", "unknown")


def _chatid(frame: dict) -> str:
    body = frame.get("body", {})
    if body.get("chattype") == "group":
        return body.get("chatid", "")
    cid = body.get("chatid", "")
    if cid:
        return cid
    return body.get("from", {}).get("userid", "")


def _time() -> float:
    return time.time()


def _save_file(buffer: bytes, filename: str) -> str:
    ext = os.path.splitext(filename or "file")[1] or ".bin"
    unique = f"{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    path = os.path.join(FILES_DIR, unique)
    with open(path, "wb") as f:
        f.write(buffer)
    return unique


def log_inbound(msgtype: str, user: str, content: str, detail: str = "", chatid: str = "", file_url: str = ""):
    state.add_message({
        "direction": "inbound", "msgtype": msgtype, "user": user,
        "content": content, "detail": detail, "time": _time(),
        "chatid": chatid, "file_url": file_url,
    })
    insert_message("inbound", msgtype, user, chatid, content, detail, file_url)


def log_outbound(msgtype: str, content: str, detail: str = "", chatid: str = ""):
    state.add_reply({
        "direction": "outbound", "msgtype": msgtype,
        "content": content, "detail": detail, "time": _time(),
        "chatid": chatid,
    })
    insert_message("outbound", msgtype, "", chatid, content, detail)


# ======================== 连接事件 ========================


@bot.on("connected")
def on_connected():
    state.update_status(connected=True)
    log_inbound("system", "", "WebSocket 连接已建立")


@bot.on("authenticated")
def on_authenticated():
    state.update_status(authenticated=True)
    log_inbound("system", "", "认证成功，机器人已就绪")


@bot.on("disconnected")
def on_disconnected(reason):
    state.update_status(connected=False, authenticated=False)
    log_inbound("system", "", f"连接断开: {reason}")


@bot.on("reconnecting")
def on_reconnecting(attempt):
    log_inbound("system", "", f"正在重连 (第 {attempt} 次)")


@bot.on("error")
def on_error(error):
    log_inbound("system", "", f"错误: {error}")


# ======================== 文本消息 ========================


@bot.on("message.text")
async def on_text(frame):
    body = frame.get("body", {})
    content = body.get("text", {}).get("content", "")
    user = _user(frame)
    chatid = _chatid(frame)
    log_inbound("text", user, content, chatid=chatid)

    stream_id = generate_req_id("stream")

    await bot.reply_stream(frame, stream_id, "**正在思考中...**", finish=False)
    log_outbound("stream", "正在思考中...", "中间帧", chatid=chatid)

    await asyncio.sleep(1)

    reply = f'你说了: "{content}"\n\n这是一条**Markdown**格式的流式回复。'
    await bot.reply_stream(
        frame, stream_id, reply, finish=True,
        feedback={"satisfycrm": True},
        msg_item=[
            {"type": "image", "image": {"url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0"}},
            {"type": "text", "text": {"content": "以上是机器人头像"}},
        ],
    )
    log_outbound("stream", reply, "最终帧 + msg_item 图文混排", chatid=chatid)


# ======================== 指令分发（覆盖所有回复类型） ========================


@bot.on("message.text")
async def on_commands(frame):
    body = frame.get("body", {})
    content = body.get("text", {}).get("content", "").strip()
    user = _user(frame)
    chatid = _chatid(frame)

    # 卡片回复 — reply_template_card
    if content == "卡片回复":
        log_inbound("text", user, content, chatid=chatid)
        await bot.reply_template_card(frame, {
            "card_type": "text_notice",
            "source": {
                "icon_url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0",
                "desc": "测试机器人",
            },
            "main_title": {"title": "模板卡片回复测试"},
            "emphasis_content": {"desc": "这是一条 reply_template_card 回复"},
            "sub_title_text": "如果你看到这条卡片，说明独立模板卡片回复功能正常",
            "card_action": {"type": 1, "url": "https://work.weixin.qq.com"},
        }, feedback={"satisfycrm": True})
        log_outbound("template_card", "独立模板卡片回复 (text_notice)")

    # 组合回复 — reply_stream_with_card
    elif content == "组合回复":
        log_inbound("text", user, content, chatid=chatid)
        stream_id = generate_req_id("stream")
        await bot.reply_stream_with_card(
            frame, stream_id,
            "这是**流式内容**部分，支持 Markdown\n\n- 项目 A\n- 项目 B",
            finish=True,
            stream_feedback={"satisfycrm": True},
            template_card={
                "card_type": "news_notice",
                "source": {
                    "icon_url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0",
                    "desc": "测试机器人",
                },
                "main_title": {"title": "组合回复附带卡片"},
                "main_image": {"url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0"},
                "sub_title_text": "news_notice 图文展示卡片",
                "card_action": {"type": 1, "url": "https://work.weixin.qq.com"},
            },
            card_feedback={"satisfycrm": True},
        )
        log_outbound("stream", "流式+卡片组合回复 (stream_with_card + news_notice)")

    # 投票卡片 — 通过主动推送 vote_interaction
    elif content == "投票":
        log_inbound("text", user, content, chatid=chatid)
        result = await bot.send_message(chatid or user, {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "vote_interaction",
                "task_id": f"vote_{int(time.time())}",
                "source": {
                    "icon_url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0",
                    "desc": "测试机器人",
                },
                "main_title": {"title": "投票测试"},
                "checkbox": {"question_key": "vote1", "option_list": [
                    {"id": "a", "text": "选项 A — Python"},
                    {"id": "b", "text": "选项 B — Go"},
                    {"id": "c", "text": "选项 C — Rust"},
                ], "mode": 0},
                "submit_button": {"text": "提交投票", "key": "submit_vote"},
            },
        })
        ok = result.get("errcode", -1) == 0
        log_outbound("push" if ok else "system",
                      "投票卡片已推送 (vote_interaction)" if ok else f"投票推送失败: {result}")

    # 多项选择卡片
    elif content == "多选":
        log_inbound("text", user, content, chatid=chatid)
        result = await bot.send_message(chatid or user, {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "multiple_interaction",
                "task_id": f"multi_{int(time.time())}",
                "source": {
                    "icon_url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0",
                    "desc": "调研",
                },
                "main_title": {"title": "功能优先级调研（多选）"},
                "select_list": [
                    {
                        "question_key": "feat_priority",
                        "title": {"text": "请选择优先开发的功能"},
                        "option_list": [
                            {"id": "1", "text": "实时协作编辑"},
                            {"id": "2", "text": "AI 智能推荐"},
                            {"id": "3", "text": "离线模式"},
                        ],
                    }
                ],
                "button_list": [
                    {"text": "确认提交", "style": 1, "key": "submit_multi"},
                ],
            },
        })
        ok = result.get("errcode", -1) == 0
        log_outbound("push" if ok else "system",
                      "多选卡片已推送 (multiple_interaction)" if ok else f"多选推送失败: {result}")

    # 欢迎文本 — reply_welcome with text (仅单聊首次进会话)
    elif content == "欢迎文本":
        log_inbound("text", user, content, chatid=chatid)
        try:
            await bot.reply_welcome(frame, {
                "msgtype": "text",
                "text": {"content": "这是一条纯文本欢迎语测试 (reply_welcome)"},
            })
            log_outbound("stream", "纯文本欢迎语回复")
        except Exception as e:
            log_outbound("system", f"欢迎文本回复失败: {e}")
            await bot.reply_stream(frame, generate_req_id("stream"),
                                   f"欢迎文本回复失败(需在进入会话5s内调用): {e}", finish=True)
            log_outbound("stream", f"回退流式回复: {e}")

    # 推送测试
    elif content == "推送测试":
        log_inbound("text", user, content, chatid=chatid)
        result = await bot.send_message(chatid or user, {
            "msgtype": "markdown",
            "markdown": {"content": "这是一条**主动推送**的测试消息\n\n> 通过 `send_message` 发送"},
        })
        ok = result.get("errcode", -1) == 0
        log_outbound("push" if ok else "system",
                      "Markdown 主动推送成功" if ok else f"推送失败: {result}")


# ======================== 图片消息 ========================


@bot.on("message.image")
async def on_image(frame):
    body = frame.get("body", {})
    image = body.get("image", {})
    user = _user(frame)
    chatid = _chatid(frame)
    file_url = ""

    try:
        buffer, filename = await bot.download_file(image.get("url"), image.get("aeskey"))
        saved = _save_file(buffer, filename or "image.png")
        file_url = f"/files/{saved}"
        detail = f"下载解密成功: {filename}, {len(buffer)} bytes"
        log_inbound("image", user, f"[图片] {filename or 'image.png'}", detail, chatid=chatid, file_url=file_url)
    except Exception as e:
        log_inbound("image", user, "[图片] 下载失败", str(e), chatid=chatid)
        buffer = None

    reply = f"已收到图片 ({len(buffer)} bytes)" if buffer else "已收到图片 (下载失败)"
    await bot.reply_stream(frame, generate_req_id("stream"), reply, finish=True)
    log_outbound("stream", reply)


# ======================== 语音消息 ========================


@bot.on("message.voice")
async def on_voice(frame):
    body = frame.get("body", {})
    voice = body.get("voice", {})
    user = _user(frame)
    chatid = _chatid(frame)
    asr = voice.get("content", "")
    log_inbound("voice", user, asr or "[语音消息]", chatid=chatid)

    await bot.reply_stream(frame, generate_req_id("stream"), "已收到语音消息", finish=True)
    log_outbound("stream", "已收到语音消息")


# ======================== 文件消息 ========================


@bot.on("message.file")
async def on_file(frame):
    body = frame.get("body", {})
    file_info = body.get("file", {})
    user = _user(frame)
    chatid = _chatid(frame)
    fname = file_info.get("filename", "unknown")
    file_url = ""

    try:
        buffer, filename = await bot.download_file(file_info.get("url"), file_info.get("aeskey"))
        saved = _save_file(buffer, filename or fname)
        file_url = f"/files/{saved}"
        detail = f"下载解密成功: {filename}, {len(buffer)} bytes"
    except Exception as e:
        detail = f"下载失败: {e}"
        buffer = None

    log_inbound("file", user, f"[文件] {fname}", detail, chatid=chatid, file_url=file_url)

    await bot.reply_stream(frame, generate_req_id("stream"), f"已收到文件: {fname}", finish=True)
    log_outbound("stream", f"已收到文件: {fname}")


# ======================== 图文混排消息 ========================


@bot.on("message.mixed")
async def on_mixed(frame):
    body = frame.get("body", {})
    mixed = body.get("mixed", {})
    user = _user(frame)
    chatid = _chatid(frame)
    items = mixed.get("item", mixed.get("msg_item", []))

    # 下载混排中的图片
    file_urls = []
    for item in items:
        img = item.get("image")
        if img and img.get("url"):
            try:
                buf, fn = await bot.download_file(img.get("url"), img.get("aeskey"))
                saved = _save_file(buf, fn or "image.png")
                file_urls.append(f"/files/{saved}")
            except Exception:
                pass

    log_inbound("mixed", user, f"图文混排 ({len(items)} 项)", chatid=chatid, file_url=file_urls[0] if file_urls else "")

    await bot.reply_stream(frame, generate_req_id("stream"), f"已收到图文混排消息（{len(items)} 项）", finish=True)
    log_outbound("stream", f"已收到图文混排消息（{len(items)} 项）")


# ======================== 进入会话 ========================


@bot.on("event.enter_chat")
async def on_enter_chat(frame):
    user = _user(frame)
    chatid = _chatid(frame)
    log_inbound("event", user, "进入会话", "eventtype=enter_chat", chatid=chatid)

    await bot.reply_welcome(frame, {
        "msgtype": "template_card",
        "template_card": {
            "card_type": "text_notice",
            "main_title": {"title": "欢迎使用测试机器人"},
            "emphasis_content": {"desc": "请在下方输入消息进行测试"},
        },
    })
    log_outbound("template_card", "欢迎语模板卡片")


# ======================== 模板卡片事件 ========================


@bot.on("event.template_card_event")
async def on_template_card_event(frame):
    body = frame.get("body", {})
    user = _user(frame)
    chatid = _chatid(frame)

    event = body.get("event", {})
    card_event = event.get("template_card_event", {})
    task_id = card_event.get("task_id", "")
    event_key = card_event.get("event_key", "")
    card_type = card_event.get("card_type", "")

    button_label = {"approve": "通过", "reject": "驳回", "detail": "查看详情"}.get(event_key, event_key)
    content = f"点击了「{button_label or event_key}」按钮"
    detail = f"task_id={task_id}, card_type={card_type}"

    log_inbound("event", user, content, detail, chatid=chatid)

    try:
        if event_key == "reject":
            new_title, new_sub = "已驳回", f"{user} 驳回了此申请"
        elif event_key == "approve":
            new_title, new_sub = "已通过", f"{user} 通过了此申请"
        else:
            new_title, new_sub = "已查看", f"{user} 查看了详情"

        await bot.update_template_card(frame, {
            "card_type": "text_notice",
            "task_id": task_id,
            "source": {
                "icon_url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0",
                "desc": "审批系统",
            },
            "main_title": {"title": new_title},
            "sub_title_text": new_sub,
            "card_action": {
                "type": 1,
                "url": "https://work.weixin.qq.com",
            },
        })
        log_outbound("template_card", f"卡片已更新: {new_title} (操作人: {user})")
    except Exception as e:
        log_outbound("system", f"更新卡片失败: {e}")


# ======================== 用户反馈事件 ========================


@bot.on("event.feedback_event")
async def on_feedback_event(frame):
    body = frame.get("body", {})
    event = body.get("event", {})
    user = _user(frame)
    feedback = event.get("feedback", {})
    chatid = _chatid(frame)
    log_inbound("event", user, f"反馈: {json.dumps(feedback, ensure_ascii=False)}", "eventtype=feedback_event", chatid=chatid)

    await bot.reply_template_card(frame, {
        "card_type": "text_notice",
        "main_title": {"title": "感谢反馈"},
        "sub_title_text": "我们已收到您的评价",
    })
    log_outbound("template_card", "反馈确认卡片")


# ======================== 心跳钩子 ========================

# monkey-patch ws manager to hook heartbeat events
_orig_send_heartbeat = bot._ws_manager._send_heartbeat


async def _patched_send_heartbeat():
    state.add_heartbeat("sent")
    await _orig_send_heartbeat()


bot._ws_manager._send_heartbeat = _patched_send_heartbeat

_orig_handle_frame = bot._ws_manager._handle_frame


def _patched_handle_frame(frame):
    headers = frame.get("headers", {})
    req_id = headers.get("req_id", "")
    if req_id.startswith("ping"):
        state.add_heartbeat("ack", f"errcode={frame.get('errcode', 0)}")
    _orig_handle_frame(frame)


bot._ws_manager._handle_frame = _patched_handle_frame


# ======================== 启动 ========================


async def main():
    print("=" * 50)
    print("  WeCom Bot Dashboard")
    print(f"  Bot ID: {state.bot_id}")
    print(f"  Panel:  http://localhost:8080")
    print("=" * 50)

    # Start bot
    await bot.connect()

    # Create web app
    app = create_app(state, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print("  Web 面板已启动: http://localhost:8080")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        bot.disconnect()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
