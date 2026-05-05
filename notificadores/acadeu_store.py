import os
import sqlite3
from datetime import datetime, timedelta


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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nt_retry_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
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

    def get_retry_attempts(self, conversation_id: str) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT attempts FROM nt_retry_conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def schedule_retry(self, conversation_id: str, error: str = "", delay_minutes: int = 5):
        now = datetime.now()
        next_retry_at = (now + timedelta(minutes=max(1, delay_minutes))).isoformat()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO nt_retry_conversations(conversation_id, attempts, next_retry_at, last_error, updated_at)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(conversation_id)
                DO UPDATE SET attempts = nt_retry_conversations.attempts + 1,
                              next_retry_at = excluded.next_retry_at,
                              last_error = excluded.last_error,
                              updated_at = excluded.updated_at
                """,
                (conversation_id, next_retry_at, error[:500], now.isoformat()),
            )
            conn.commit()

    def clear_retry(self, conversation_id: str):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM nt_retry_conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.commit()

    def get_due_retries(self, limit: int = 20) -> list[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT conversation_id
                FROM nt_retry_conversations
                WHERE next_retry_at <= ?
                ORDER BY next_retry_at ASC
                LIMIT ?
                """,
                (datetime.now().isoformat(), limit),
            )
            return [str(row[0]) for row in cur.fetchall()]
