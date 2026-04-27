"""
数据库模块 — SQLite 持久化消息历史和联系人
"""

import os
import time
from typing import List, Optional

# 优先使用内置 sqlite3，DLL 缺失时回退 pysqlite3
try:
    import sqlite3
    conn_test = sqlite3.connect(":memory:")
    conn_test.close()
except Exception:
    from pysqlite3 import dbapi2 as sqlite3  # type: ignore

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            time        REAL NOT NULL,
            direction   TEXT NOT NULL,
            msgtype     TEXT NOT NULL DEFAULT '',
            user_id     TEXT NOT NULL DEFAULT '',
            chatid      TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            detail      TEXT NOT NULL DEFAULT '',
            file_url    TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_msg_time ON messages(time);
        CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id);
        CREATE INDEX IF NOT EXISTS idx_msg_chatid ON messages(chatid);
        CREATE INDEX IF NOT EXISTS idx_msg_msgtype ON messages(msgtype);

        CREATE TABLE IF NOT EXISTS contacts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            first_seen  REAL NOT NULL,
            last_seen   REAL NOT NULL,
            user_id     TEXT NOT NULL,
            chatid      TEXT NOT NULL,
            chattype    TEXT NOT NULL DEFAULT 'single',
            msg_count   INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, chatid)
        );
        CREATE INDEX IF NOT EXISTS idx_contact_user ON contacts(user_id);
        CREATE INDEX IF NOT EXISTS idx_contact_chatid ON contacts(chatid);
    """)
    conn.commit()
    conn.close()


def insert_message(direction: str, msgtype: str, user_id: str, chatid: str,
                   content: str, detail: str = "", file_url: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (time, direction, msgtype, user_id, chatid, content, detail, file_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (time.time(), direction, msgtype, user_id, chatid, content, detail, file_url),
    )
    conn.commit()
    conn.close()

    # Update contacts
    if user_id or chatid:
        _upsert_contact(user_id, chatid, chattype="group" if "@" not in chatid and chatid.startswith("wr") else "single")


def _upsert_contact(user_id: str, chatid: str, chattype: str):
    conn = get_conn()
    now = time.time()
    existing = conn.execute(
        "SELECT id, msg_count FROM contacts WHERE user_id=? AND chatid=?",
        (user_id, chatid),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE contacts SET last_seen=?, msg_count=? WHERE id=?",
            (now, existing["msg_count"] + 1, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO contacts (first_seen, last_seen, user_id, chatid, chattype, msg_count) VALUES (?, ?, ?, ?, ?, 1)",
            (now, now, user_id, chatid, chattype),
        )
    conn.commit()
    conn.close()


def query_messages(
    keyword: str = "",
    user_id: str = "",
    chatid: str = "",
    msgtype: str = "",
    direction: str = "",
    limit: int = 100,
    offset: int = 0,
) -> List[dict]:
    conn = get_conn()
    clauses = []
    params = []

    if keyword:
        clauses.append("(content LIKE ? OR detail LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if chatid:
        clauses.append("chatid = ?")
        params.append(chatid)
    if msgtype:
        clauses.append("msgtype = ?")
        params.append(msgtype)
    if direction:
        clauses.append("direction = ?")
        params.append(direction)

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT * FROM messages WHERE {where} ORDER BY time DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_contacts(
    keyword: str = "",
    limit: int = 100,
) -> List[dict]:
    conn = get_conn()
    if keyword:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE user_id LIKE ? OR chatid LIKE ? ORDER BY last_seen DESC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM contacts ORDER BY last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_messages(**filters) -> int:
    conn = get_conn()
    clauses = []
    params = []
    for key, val in filters.items():
        if val:
            clauses.append(f"{key} = ?")
            params.append(val)
    where = " AND ".join(clauses) if clauses else "1=1"
    row = conn.execute(f"SELECT COUNT(*) as cnt FROM messages WHERE {where}", params).fetchone()
    conn.close()
    return row["cnt"] if row else 0
