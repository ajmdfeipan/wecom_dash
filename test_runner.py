"""
企业微信智能机器人 — 真实场景全功能测试

连接真实 WebSocket 服务器，通过你在企微端的操作触发各项功能。
脚本会自动记录每个测试场景的通过状态，最终输出测试报告。

使用方法:
  1. 运行本脚本: python test_runner.py
  2. 按照终端中的指引，在企微中与机器人互动
  3. 测试完成后按 Ctrl+C 查看报告
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, Optional

from dotenv import load_dotenv
from aibot import WSClient, WSClientOptions, generate_req_id, MessageType, EventType

load_dotenv()


# ======================== 测试结果记录 ========================


class TestResult:
    def __init__(self):
        self.results: Dict[str, dict] = {}
        self.start_time = time.time()

    def record(self, scenario: str, passed: bool, detail: str = ""):
        if scenario not in self.results:
            self.results[scenario] = {
                "passed": passed,
                "detail": detail,
                "time": datetime.now().strftime("%H:%M:%S"),
                "count": 1,
            }
        else:
            self.results[scenario]["count"] += 1
            if passed:
                self.results[scenario]["passed"] = True
            if detail:
                self.results[scenario]["detail"] = detail

    def print_report(self):
        elapsed = time.time() - self.start_time
        print("\n" + "=" * 60)
        print("  测试报告")
        print("=" * 60)

        passed = sum(1 for r in self.results.values() if r["passed"])
        failed = sum(1 for r in self.results.values() if not r["passed"])
        total = len(self.results)

        for name, result in self.results.items():
            status = "PASS" if result["passed"] else "FAIL"
            icon = "v" if result["passed"] else "x"
            extra = f" ({result['detail']})" if result['detail'] else ""
            count_str = f" x{result['count']}" if result['count'] > 1 else ""
            print(f"  [{icon}] {status}  {name}{count_str}{extra}")

        print("-" * 60)
        print(f"  通过: {passed}/{total}  失败: {failed}/{total}  耗时: {elapsed:.1f}s")
        print("=" * 60)

        if failed == 0 and total > 0:
            print("  全部通过!")
        elif total == 0:
            print("  尚未触发任何测试场景，请按提示操作。")


result = TestResult()


# ======================== 创建客户端 ========================


client = WSClient(
    WSClientOptions(
        bot_id=os.getenv("WECHAT_BOT_ID"),
        secret=os.getenv("WECHAT_BOT_SECRET"),
    )
)


# ======================== 连接事件 ========================


@client.on("connected")
def on_connected():
    print("\n[连接] WebSocket 已建立")
    result.record("WS连接建立", True)


@client.on("authenticated")
def on_authenticated():
    print("[认证] 认证成功")
    result.record("认证成功", True)
    print_guide()


@client.on("disconnected")
def on_disconnected(reason):
    print(f"[断开] 连接断开: {reason}")
    result.record("连接保活/断开", False, reason)


@client.on("reconnecting")
def on_reconnecting(attempt):
    print(f"[重连] 第 {attempt} 次重连...")


@client.on("error")
def on_error(error):
    print(f"[错误] {error}")


# ======================== 文本消息 + 流式回复 ========================


@client.on("message.text")
async def on_text(frame):
    body = frame.get("body", {})
    content = body.get("text", {}).get("content", "")
    user = body.get("from", {}).get("userid", "unknown")
    print(f"\n[文本] {user}: {content}")
    result.record("接收文本消息", True, f"content={content[:30]}")

    stream_id = generate_req_id("stream")

    try:
        # 中间帧
        await client.reply_stream(frame, stream_id, "**正在思考中...**", finish=False)
        result.record("流式回复-中间帧", True)

        await asyncio.sleep(1)

        # 最终帧
        await client.reply_stream(
            frame, stream_id,
            f'你说了: "{content}"\n\n这是一条**Markdown**格式的流式回复。',
            finish=True,
            feedback={"satisfycrm": True},
        )
        result.record("流式回复-最终帧", True, f"stream_id={stream_id[:20]}...")
    except Exception as e:
        result.record("流式回复", False, str(e))


# ======================== 图片消息 + 文件下载解密 ========================


@client.on("message.image")
async def on_image(frame):
    body = frame.get("body", {})
    image = body.get("image", {})
    user = body.get("from", {}).get("userid", "unknown")
    url = image.get("url", "N/A")
    aeskey = image.get("aeskey")
    print(f"\n[图片] {user}: url={url[:60]}...")
    result.record("接收图片消息", True)

    try:
        buffer, filename = await client.download_file(url, aeskey)
        print(f"  -> 下载解密成功: {filename}, {len(buffer)} bytes")
        result.record("文件下载+AES解密", True, f"size={len(buffer)}")
    except Exception as e:
        print(f"  -> 下载失败: {e}")
        result.record("文件下载+AES解密", False, str(e))

    try:
        stream_id = generate_req_id("stream")
        await client.reply_stream(
            frame, stream_id,
            f"已收到图片 ({len(buffer) if 'buffer' in dir() else '?'} bytes)",
            finish=True,
        )
        result.record("图片消息-流式回复", True)
    except Exception as e:
        result.record("图片消息-流式回复", False, str(e))


# ======================== 语音消息 ========================


@client.on("message.voice")
async def on_voice(frame):
    body = frame.get("body", {})
    voice = body.get("voice", {})
    user = body.get("from", {}).get("userid", "unknown")
    print(f"\n[语音] {user}: url={voice.get('url', 'N/A')[:60]}...")
    result.record("接收语音消息", True)

    try:
        stream_id = generate_req_id("stream")
        await client.reply_stream(frame, stream_id, "已收到语音消息", finish=True)
        result.record("语音消息-流式回复", True)
    except Exception as e:
        result.record("语音消息-流式回复", False, str(e))


# ======================== 文件消息 ========================


@client.on("message.file")
async def on_file(frame):
    body = frame.get("body", {})
    file_info = body.get("file", {})
    user = body.get("from", {}).get("userid", "unknown")
    fname = file_info.get("filename", "unknown")
    aeskey = file_info.get("aeskey")
    url = file_info.get("url", "N/A")
    print(f"\n[文件] {user}: {fname}")
    result.record("接收文件消息", True, f"filename={fname}")

    try:
        buffer, filename = await client.download_file(url, aeskey)
        print(f"  -> 下载解密成功: {filename}, {len(buffer)} bytes")
        result.record("文件下载(文件类型)", True, f"size={len(buffer)}")
    except Exception as e:
        print(f"  -> 下载失败: {e}")
        result.record("文件下载(文件类型)", False, str(e))

    try:
        stream_id = generate_req_id("stream")
        await client.reply_stream(
            frame, stream_id,
            f"已收到文件: {fname}",
            finish=True,
        )
        result.record("文件消息-流式回复", True)
    except Exception as e:
        result.record("文件消息-流式回复", False, str(e))


# ======================== 图文混排消息 ========================


@client.on("message.mixed")
async def on_mixed(frame):
    body = frame.get("body", {})
    mixed = body.get("mixed", {})
    user = body.get("from", {}).get("userid", "unknown")
    items = mixed.get("item", [])
    print(f"\n[混排] {user}: {len(items)} 项内容")
    for i, item in enumerate(items):
        print(f"  [{i}] type={item.get('type', 'unknown')}")
    result.record("接收图文混排消息", True, f"items={len(items)}")

    try:
        stream_id = generate_req_id("stream")
        await client.reply_stream(
            frame, stream_id,
            f"已收到图文混排消息（共 {len(items)} 项）",
            finish=True,
        )
        result.record("混排消息-流式回复", True)
    except Exception as e:
        result.record("混排消息-流式回复", False, str(e))


# ======================== 进入会话 + 欢迎语(模板卡片) ========================


@client.on("event.enter_chat")
async def on_enter_chat(frame):
    body = frame.get("body", {})
    user = body.get("from", {}).get("userid", "unknown")
    print(f"\n[进入会话] {user} 进入会话")
    result.record("接收进入会话事件", True)

    try:
        await client.reply_welcome(frame, {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "text_notice",
                "source": {
                    "icon_url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0",
                    "desc": "测试机器人",
                },
                "main_title": {"title": "欢迎使用测试机器人"},
                "emphasis_content": {
                    "desc": "请在下方输入消息进行测试",
                },
                "card_action": {
                    "type": 1,
                    "url": "https://work.weixin.qq.com",
                },
            },
        })
        result.record("欢迎语-模板卡片", True)
    except Exception as e:
        result.record("欢迎语-模板卡片", False, str(e))


# ======================== 模板卡片事件 + 更新卡片 ========================


@client.on("event.template_card_event")
async def on_template_card_event(frame):
    body = frame.get("body", {})
    event = body.get("event", {})
    user = body.get("from", {}).get("userid", "unknown")
    task_id = event.get("task_id", "unknown")
    print(f"\n[卡片事件] {user} 操作了卡片 task_id={task_id}")
    result.record("接收模板卡片事件", True, f"task_id={task_id}")

    try:
        await client.update_template_card(frame, {
            "card_type": "text_notice",
            "main_title": {"title": "操作已确认"},
            "sub_title_text": f"Task {task_id} 已完成处理",
        })
        result.record("更新模板卡片", True)
    except Exception as e:
        result.record("更新模板卡片", False, str(e))


# ======================== 用户反馈事件 ========================


@client.on("event.feedback_event")
async def on_feedback_event(frame):
    body = frame.get("body", {})
    event = body.get("event", {})
    user = body.get("from", {}).get("userid", "unknown")
    feedback = event.get("feedback", {})
    print(f"\n[反馈] {user}: {json.dumps(feedback, ensure_ascii=False)}")
    result.record("接收用户反馈事件", True, f"feedback={feedback}")

    try:
        await client.reply_template_card(frame, {
            "card_type": "text_notice",
            "main_title": {"title": "感谢您的反馈"},
            "sub_title_text": "我们已收到您的评价，感谢参与测试！",
        })
        result.record("反馈事件-卡片回复", True)
    except Exception as e:
        result.record("反馈事件-卡片回复", False, str(e))


# ======================== 通用事件记录 ========================


@client.on("message")
def on_any_message(frame):
    body = frame.get("body", {})
    msgtype = body.get("msgtype", "unknown")
    cmd = frame.get("cmd", "unknown")
    print(f"  [通用] cmd={cmd}, msgtype={msgtype}")


@client.on("event")
def on_any_event(frame):
    body = frame.get("body", {})
    event = body.get("event", {})
    etype = event.get("eventtype", "unknown") if isinstance(event, dict) else "unknown"
    print(f"  [通用事件] eventtype={etype}")


# ======================== 操作指南 ========================


GUIDE = """
+--------------------------------------------------------------+
|           请在企微中按以下步骤操作（可任意顺序）             |
+--------------------------------------------------------------+

 场景1 - 进入会话 (触发欢迎语)
   打开与机器人的对话窗口（当天首次进入）

 场景2 - 文本消息 (触发流式回复)
   发送任意文本，如: 你好

 场景3 - 图片消息 (触发文件下载+解密)
   发送一张图片

 场景4 - 语音消息
   按住说话，发送一条语音

 场景5 - 文件消息 (触发文件下载+解密)
   发送一个文件（如文档、PDF等）

 场景6 - 图文混排消息
   在聊天中粘贴或发送包含图文的内容

 场景7 - 主动推送消息
   发送文本 "推送测试" 触发主动推送

 场景8 - 流式+卡片组合回复
   发送文本 "组合回复"

 场景9 - 模板卡片回复
   发送文本 "卡片回复"

+--------------------------------------------------------------+
|           完成操作后按 Ctrl+C 退出并查看报告                 |
+--------------------------------------------------------------+
"""


def print_guide():
    print(GUIDE)


# ======================== 特殊指令处理 ========================


@client.on("message.text")
async def on_special_commands(frame):
    body = frame.get("body", {})
    content = body.get("text", {}).get("content", "").strip()

    # 场景7: 主动推送测试
    if content == "推送测试":
        print("\n[指令] 触发主动推送测试...")
        try:
            user = body.get("from", {}).get("userid", "")
            await client.send_message(user, {
                "msgtype": "markdown",
                "markdown": {"content": "这是一条**主动推送**的测试消息"},
            })
            result.record("主动推送消息", True, f"userid={user}")
            print("  -> 主动推送成功")
        except Exception as e:
            result.record("主动推送消息", False, str(e))
            print(f"  -> 主动推送失败: {e}")

    # 场景8: 流式+卡片组合
    elif content == "组合回复":
        print("\n[指令] 触发流式+卡片组合回复...")
        try:
            stream_id = generate_req_id("stream")
            await client.reply_stream_with_card(
                frame,
                stream_id,
                "这是流式内容部分...",
                finish=True,
                template_card={
                    "card_type": "text_notice",
                    "main_title": {"title": "组合回复卡片"},
                    "sub_title_text": "这是附带的模板卡片",
                },
            )
            result.record("流式+卡片组合回复", True)
            print("  -> 组合回复成功")
        except Exception as e:
            result.record("流式+卡片组合回复", False, str(e))
            print(f"  -> 组合回复失败: {e}")

    # 场景9: 模板卡片回复
    elif content == "卡片回复":
        print("\n[指令] 触发模板卡片回复...")
        try:
            await client.reply_template_card(frame, {
                "card_type": "text_notice",
                "source": {
                    "icon_url": "https://wework.qpic.cn/wwpic/252813_j2n94gDpKdoWn2T_1703694978/0",
                    "desc": "测试机器人",
                },
                "main_title": {"title": "模板卡片测试"},
                "emphasis_content": {
                    "desc": "这是一条模板卡片回复",
                },
                "sub_title_text": "如果你看到这条卡片，说明模板卡片回复功能正常",
                "card_action": {
                    "type": 1,
                    "url": "https://work.weixin.qq.com",
                },
            })
            result.record("模板卡片回复", True)
            print("  -> 卡片回复成功")
        except Exception as e:
            result.record("模板卡片回复", False, str(e))
            print(f"  -> 卡片回复失败: {e}")


# ======================== 启动 ========================


async def main():
    print("=" * 60)
    print("  企业微信智能机器人 — 全功能真实场景测试")
    print("=" * 60)
    print(f"  Bot ID: {os.getenv('WECHAT_BOT_ID')}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    await client.connect()

    print("  等待认证完成...")
    await asyncio.sleep(3)

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        result.print_report()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        result.print_report()
