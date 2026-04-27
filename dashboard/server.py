"""
Web 服务器 — aiohttp 路由

提供:
  GET  /              → 管理面板（需登录）
  GET  /login         → 登录页
  POST /login         → 登录验证
  GET  /files/{name}  → 下载的文件
  GET  /api/events    → SSE 实时推送
  GET  /api/messages  → 内存历史消息
  GET  /api/history   → SQLite 历史查询
  GET  /api/contacts  → 联系人列表
  GET  /api/status    → 连接/心跳状态
  POST /api/push      → 主动推送消息
"""

import asyncio
import hashlib
import json
import os
import time

from aiohttp import web

from .state import BotState
from .db import query_messages, query_contacts, count_messages

FILES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "files")

# 简单登录凭证
USERNAME = os.getenv("ADMIN_USER", "admin")
PASSWORD = os.getenv("ADMIN_PASS", "wecom2026")
_TOKEN = hashlib.sha256(f"{USERNAME}:{PASSWORD}".encode()).hexdigest()

# MIME 类型映射
MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".txt": "text/plain", ".csv": "text/csv",
}


def _check_auth(request: web.Request) -> bool:
    token = request.cookies.get("token", "")
    return token == _TOKEN


def create_app(state: BotState, bot) -> web.Application:
    app = web.Application()
    app["state"] = state
    app["bot"] = bot

    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_post)
    app.router.add_get("/logout", logout)
    app.router.add_get("/", index)
    app.router.add_get("/files/{name}", serve_file)
    app.router.add_get("/api/events", sse_events)
    app.router.add_get("/api/messages", get_messages)
    app.router.add_get("/api/history", get_history)
    app.router.add_get("/api/contacts", get_contacts)
    app.router.add_get("/api/status", get_status)
    app.router.add_post("/api/push", push_message)

    return app


async def login_page(request: web.Request) -> web.Response:
    html = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Login</title>
<style>body{background:#0f1117;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif}
.box{background:#1a1d27;padding:32px 40px;border-radius:12px;border:1px solid #2e3348;width:340px}
h2{color:#e0e2ec;margin:0 0 24px;text-align:center}
input{width:100%;padding:10px 12px;background:#232734;border:1px solid #2e3348;border-radius:6px;color:#e0e2ec;font-size:14px;margin-bottom:12px;box-sizing:border-box}
button{width:100%;padding:10px;background:#60a5fa;color:#fff;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer}
.err{color:#f87171;font-size:13px;text-align:center;margin-top:8px;display:none}
</style></head><body><div class="box"><h2>WeCom Bot</h2>
<form method="post" action="/login"><input name="user" placeholder="用户名" autofocus>
<input name="pass" type="password" placeholder="密码"><button type="submit">登录</button></form>
<div class="err" id="e">用户名或密码错误</div></div></body></html>"""
    return web.Response(text=html, content_type="text/html")


async def login_post(request: web.Request) -> web.Response:
    data = await request.post()
    if data.get("user", "") == USERNAME and data.get("pass", "") == PASSWORD:
        resp = web.HTTPFound("/")
        resp.set_cookie("token", _TOKEN, max_age=86400 * 30, httponly=True)
        return resp
    html = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>alert('用户名或密码错误');history.back();</script></body></html>"""
    return web.Response(text=html, content_type="text/html", status=403)


async def logout(request: web.Request) -> web.Response:
    resp = web.HTTPFound("/login")
    resp.del_cookie("token")
    return resp


async def index(request: web.Request) -> web.Response:
    if not _check_auth(request):
        raise web.HTTPFound("/login")
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    return web.FileResponse(html_path)


async def serve_file(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    safe_name = os.path.basename(name)
    filepath = os.path.join(FILES_DIR, safe_name)

    if not os.path.isfile(filepath):
        return web.Response(status=404, text="File not found")

    ext = os.path.splitext(safe_name)[1].lower()
    content_type = MIME_MAP.get(ext, "application/octet-stream")

    with open(filepath, "rb") as f:
        data = f.read()

    disposition = "inline" if content_type.startswith(("image/", "application/pdf")) else "attachment"
    return web.Response(
        body=data,
        content_type=content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


async def sse_events(request: web.Request) -> web.StreamResponse:
    state: BotState = request.app["state"]

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    init_data = json.dumps({"type": "init", "data": state.get_status()}, ensure_ascii=False)
    await resp.write(f"event: init\ndata: {init_data}\n\n".encode())

    q = state.subscribe()
    try:
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=30)
                await resp.write(f"data: {payload}\n\n".encode())
            except asyncio.TimeoutError:
                await resp.write(b": keepalive\n\n")
    except (ConnectionResetError, ConnectionError):
        pass
    finally:
        state.unsubscribe(q)

    return resp


async def get_messages(request: web.Request) -> web.Response:
    state: BotState = request.app["state"]
    return web.json_response(state.get_messages())


async def get_history(request: web.Request) -> web.Response:
    keyword = request.query.get("keyword", "")
    user_id = request.query.get("user_id", "")
    chatid = request.query.get("chatid", "")
    msgtype = request.query.get("msgtype", "")
    direction = request.query.get("direction", "")
    limit = int(request.query.get("limit", "100"))
    offset = int(request.query.get("offset", "0"))

    rows = query_messages(
        keyword=keyword, user_id=user_id, chatid=chatid,
        msgtype=msgtype, direction=direction,
        limit=limit, offset=offset,
    )
    total = count_messages()
    return web.json_response({"total": total, "rows": rows})


async def get_contacts(request: web.Request) -> web.Response:
    keyword = request.query.get("keyword", "")
    rows = query_contacts(keyword=keyword)
    return web.json_response(rows)


async def get_status(request: web.Request) -> web.Response:
    state: BotState = request.app["state"]
    return web.json_response(state.get_status())


async def push_message(request: web.Request) -> web.Response:
    state: BotState = request.app["state"]
    bot = request.app["bot"]

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    chatid = body.get("chatid", "").strip()
    msgtype = body.get("msgtype", "markdown").strip()
    content = body.get("content", "").strip()

    if not chatid:
        return web.json_response({"ok": False, "error": "chatid is required"}, status=400)
    if not content:
        return web.json_response({"ok": False, "error": "content is required"}, status=400)

    try:
        if msgtype == "markdown":
            msg_body = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
        elif msgtype == "template_card":
            try:
                card = json.loads(content)
            except json.JSONDecodeError:
                card = {
                    "card_type": "text_notice",
                    "main_title": {"title": content},
                }
            msg_body = {
                "msgtype": "template_card",
                "template_card": card,
            }
        else:
            return web.json_response({"ok": False, "error": f"Unsupported msgtype: {msgtype}"}, status=400)

        result = await bot.send_message(chatid, msg_body)

        state.add_reply({
            "direction": "push", "msgtype": msgtype,
            "chatid": chatid, "content": content[:200],
            "time": time.time(),
            "result": "ok" if result.get("errcode", -1) == 0 else f"errcode={result.get('errcode')}",
        })

        return web.json_response({"ok": True, "result": result})

    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)
