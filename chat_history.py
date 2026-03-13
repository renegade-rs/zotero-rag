from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "data" / "chat_history.db"
DB_PATH.parent.mkdir(exist_ok=True, mode=0o755)


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            message_idx INTEGER DEFAULT 0,
            source_data TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_username ON chats(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
    
    conn.commit()
    conn.close()


def get_user_chats(username: str) -> list[dict]:
    """Get all chats for a user, sorted by most recent."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, title, created_at, updated_at
        FROM chats
        WHERE username = ?
        ORDER BY updated_at DESC
    """, (username,))
    
    chats = []
    for row in cursor.fetchall():
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages WHERE chat_id = ? AND role = 'user'
        """, (row['id'],))
        msg_count = cursor.fetchone()['count']
        
        chats.append({
            'id': row['id'],
            'title': row['title'] or 'New chat',
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'message_count': msg_count
        })
    
    conn.close()
    return chats


def get_chat(chat_id: str, username: str) -> Optional[dict]:
    """Get a single chat with all messages."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, title, created_at, updated_at
        FROM chats
        WHERE id = ? AND username = ?
    """, (chat_id, username))
    
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    
    cursor.execute("""
        SELECT role, content
        FROM messages
        WHERE chat_id = ?
        ORDER BY created_at ASC
    """, (chat_id,))
    
    messages = []
    for msg in cursor.fetchall():
        messages.append({
            'role': msg['role'],
            'content': msg['content']
        })
    
    cursor.execute("""
        SELECT source_data
        FROM sources
        WHERE chat_id = ?
        ORDER BY id ASC
    """, (chat_id,))
    
    sources = []
    for src in cursor.fetchall():
        try:
            sources.append(json.loads(src['source_data']))
        except json.JSONDecodeError:
            pass
    
    conn.close()
    
    return {
        'id': row['id'],
        'title': row['title'] or 'New chat',
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'messages': messages,
        'sources': sources
    }


def create_chat(chat_id: str, username: str, title: Optional[str] = None) -> dict:
    """Create a new chat."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO chats (id, username, title, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, username, title or 'New chat', now, now))
    
    conn.commit()
    conn.close()
    
    return {
        'id': chat_id,
        'title': title or 'New chat',
        'created_at': now,
        'updated_at': now
    }


def add_message(chat_id: str, role: str, content: str) -> None:
    """Add a message to a chat."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO messages (chat_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (chat_id, role, content, now))
    
    cursor.execute("""
        UPDATE chats SET updated_at = ? WHERE id = ?
    """, (now, chat_id))
    
    conn.commit()
    conn.close()


def update_chat_title(chat_id: str, title: str) -> None:
    """Update a chat's title."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        UPDATE chats SET title = ?, updated_at = ? WHERE id = ?
    """, (title, now, chat_id))
    
    conn.commit()
    conn.close()


def save_sources(chat_id: str, sources: list[dict]) -> None:
    """Save sources for a chat."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM sources WHERE chat_id = ?", (chat_id,))
    
    for source in sources:
        cursor.execute("""
            INSERT INTO sources (chat_id, source_data)
            VALUES (?, ?)
        """, (chat_id, json.dumps(source)))
    
    conn.commit()
    conn.close()


def delete_chat(chat_id: str, username: str) -> bool:
    """Delete a chat."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM chats WHERE id = ? AND username = ?
    """, (chat_id, username))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def sync_chat(chat_id: str, username: str, title: str, messages: list[dict], sources: list[dict]) -> None:
    """Sync a complete chat (create or update)."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM chats WHERE id = ?", (chat_id,))
    exists = cursor.fetchone() is not None
    
    now = datetime.utcnow().isoformat()
    
    if exists:
        cursor.execute("""
            UPDATE chats SET title = ?, updated_at = ? WHERE id = ?
        """, (title, now, chat_id))
        
        cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM sources WHERE chat_id = ?", (chat_id,))
    else:
        cursor.execute("""
            INSERT INTO chats (id, username, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, username, title, now, now))
    
    for msg in messages:
        cursor.execute("""
            INSERT INTO messages (chat_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (chat_id, msg['role'], msg['content'], now))
    
    for source in sources:
        cursor.execute("""
            INSERT INTO sources (chat_id, source_data)
            VALUES (?, ?)
        """, (chat_id, json.dumps(source)))
    
    conn.commit()
    conn.close()


init_db()