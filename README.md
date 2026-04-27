# WeCom Bot Dashboard

基于 [wecom-aibot-python-sdk](https://github.com/WecomTeam/wecom-aibot-python-sdk) 的企业微信智能机器人 Web 管理面板。

## 功能

- WebSocket 长连接 + 自动认证 + 心跳保活
- 实时消息日志（文本/图片/语音/文件/图文混排）
- 图片内联预览 + 文件下载链接
- 流式回复（中间帧 + 最终帧 + msg_item 图文混排）
- 欢迎语回复（模板卡片 / 纯文本）
- 模板卡片回复 / 流式+卡片组合回复
- 卡片按钮交互 → 事件回调 → 实时更新卡片
- 主动推送 Markdown / 模板卡片（6 种卡片类型预设）
- 心跳监控（30s 倒计时进度条）
- SQLite 持久化消息历史 + 联系人记录
- 历史消息关键词搜索 + 联系人筛选
- Web 登录保护

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/ajmdfeipan/wecom_dash.git
cd wecom_dash

# 2. 创建虚拟环境
python -m venv venv
source venv/Scripts/activate   # Windows
# source venv/bin/activate    # Linux/Mac

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置
cp .env.example .env
# 编辑 .env 填入 bot_id 和 secret

# 5. 启动
python app.py
```

浏览器打开 **http://localhost:8080**

## 登录

| 项目 | 默认值 |
|------|--------|
| 用户名 | `admin` |
| 密码 | `wecom2026` |

可在 `.env` 中通过 `ADMIN_USER` / `ADMIN_PASS` 修改。

## 企微端指令

在企微中向机器人发送以下文本触发对应功能：

| 指令 | 触发的 SDK 方法 |
|------|----------------|
| 任意文字 | `reply_stream` 流式回复（含 msg_item） |
| `卡片回复` | `reply_template_card` text_notice 卡片 |
| `组合回复` | `reply_stream_with_card` 流式+news_notice 卡片 |
| `投票` | `send_message` vote_interaction 卡片 |
| `多选` | `send_message` multiple_interaction 卡片 |
| `欢迎文本` | `reply_welcome` 纯文本欢迎语 |
| `推送测试` | `send_message` Markdown 主动推送 |

群聊中需 **@机器人** 才能触发。

## 项目结构

```
├── app.py              # 主入口：启动 bot + web server
├── bot.py              # 纯后端模式（无面板）
├── dashboard/
│   ├── __init__.py
│   ├── server.py       # aiohttp 路由（SSE/API/登录）
│   ├── state.py        # 内存共享状态 + SSE 广播
│   ├── db.py           # SQLite 持久化
│   └── index.html      # 前端单页面
├── test_runner.py      # 全功能真实场景测试
├── test_all.py         # 单元测试（mock）
├── conftest.py         # 测试 fixture
├── requirements.txt
├── .env.example
└── .gitignore
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/login` | GET/POST | 登录页 |
| `/api/status` | GET | 连接状态 + 心跳信息 |
| `/api/events` | GET (SSE) | 实时事件流 |
| `/api/messages` | GET | 内存最近 200 条消息 |
| `/api/history` | GET | SQLite 历史查询（支持 keyword/user_id/chatid/msgtype 参数） |
| `/api/contacts` | GET | 联系人列表 |
| `/api/push` | POST | 主动推送消息 |
| `/files/{name}` | GET | 下载的图片/文件 |

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `WECHAT_BOT_ID` | 是 | 机器人 ID |
| `WECHAT_BOT_SECRET` | 是 | 机器人 Secret |
| `ADMIN_USER` | 否 | 面板用户名，默认 `admin` |
| `ADMIN_PASS` | 否 | 面板密码，默认 `wecom2026` |

## License

MIT
