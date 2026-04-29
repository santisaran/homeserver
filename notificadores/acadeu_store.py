import os
import sqlite3
from datetime import datetime


class AcadeuStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    def _connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nt_sent_messages (
                    message_key TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nt_debate_threads (
                    conversation_key TEXT PRIMARY KEY,
                    root_message_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def already_sent(self, message_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM nt_sent_messages WHERE message_key = ?",
                (message_key,),
            )
            return cur.fetchone() is not None

    def mark_sent(self, message_key: str):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO nt_sent_messages(message_key, sent_at) VALUES (?, ?)",
                (message_key, datetime.now().isoformat()),
            )
            conn.commit()

    def get_debate_root_message_id(self, conversation_key: str) -> int | None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT root_message_id FROM nt_debate_threads WHERE conversation_key = ?",
                (conversation_key,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def set_debate_root_message_id(self, conversation_key: str, root_message_id: int):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO nt_debate_threads(conversation_key, root_message_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(conversation_key)
                DO UPDATE SET root_message_id = excluded.root_message_id,
                              updated_at = excluded.updated_at
                """,
                (conversation_key, root_message_id, datetime.now().isoformat()),
            )
            conn.commit()
