import sqlite3
import discord
from datetime import datetime, timezone

DB_PATH = "backups.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            guild_id INTEGER NOT NULL,
            guild_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backup_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS backup_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            ch_type TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            category TEXT DEFAULT '',
            topic TEXT DEFAULT '',
            bitrate INTEGER DEFAULT 64000,
            user_limit INTEGER DEFAULT 0,
            FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS backup_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            color INTEGER NOT NULL DEFAULT 0,
            hoist INTEGER NOT NULL DEFAULT 0,
            mentionable INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()

def save_backup(name, guild):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()[:19]
    cur = conn.execute(
        "INSERT INTO backups (name, guild_id, guild_name, created_at) VALUES (?, ?, ?, ?)",
        (name, guild.id, guild.name, now)
    )
    backup_id = cur.lastrowid

    for cat in guild.categories:
        conn.execute(
            "INSERT INTO backup_categories (backup_id, name, position) VALUES (?, ?, ?)",
            (backup_id, cat.name, cat.position)
        )

    for ch in guild.channels:
        if isinstance(ch, discord.TextChannel):
            cat_name = ch.category.name if ch.category else ""
            conn.execute(
                "INSERT INTO backup_channels (backup_id, name, ch_type, position, category, topic) VALUES (?, ?, ?, ?, ?, ?)",
                (backup_id, ch.name, "text", ch.position, cat_name, ch.topic or "")
            )
        elif isinstance(ch, discord.VoiceChannel):
            cat_name = ch.category.name if ch.category else ""
            conn.execute(
                "INSERT INTO backup_channels (backup_id, name, ch_type, position, category, bitrate, user_limit) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (backup_id, ch.name, "voice", ch.position, cat_name, ch.bitrate or 64000, ch.user_limit or 0)
            )

    for role in reversed(guild.roles):
        if role.is_default() or role.is_premium_subscriber():
            continue
        conn.execute(
            "INSERT INTO backup_roles (backup_id, name, color, hoist, mentionable, position) VALUES (?, ?, ?, ?, ?, ?)",
            (backup_id, role.name, role.color.value, 1 if role.hoist else 0, 1 if role.mentionable else 0, role.position)
        )

    conn.commit()
    conn.close()
    return backup_id

def list_backups():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM backups ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_backup(backup_id):
    conn = get_conn()
    backup = conn.execute("SELECT * FROM backups WHERE id = ?", (backup_id,)).fetchone()
    if not backup:
        conn.close()
        return None
    categories = conn.execute("SELECT * FROM backup_categories WHERE backup_id = ? ORDER BY position", (backup_id,)).fetchall()
    channels = conn.execute("SELECT * FROM backup_channels WHERE backup_id = ? ORDER BY position", (backup_id,)).fetchall()
    roles = conn.execute("SELECT * FROM backup_roles WHERE backup_id = ? ORDER BY position", (backup_id,)).fetchall()
    conn.close()
    return {
        "backup": dict(backup),
        "categories": [dict(r) for r in categories],
        "channels": [dict(r) for r in channels],
        "roles": [dict(r) for r in roles]
    }

def delete_backup(backup_id):
    conn = get_conn()
    conn.execute("DELETE FROM backup_roles WHERE backup_id = ?", (backup_id,))
    conn.execute("DELETE FROM backup_channels WHERE backup_id = ?", (backup_id,))
    conn.execute("DELETE FROM backup_categories WHERE backup_id = ?", (backup_id,))
    conn.execute("DELETE FROM backups WHERE id = ?", (backup_id,))
    conn.commit()
    conn.close()

def backup_stats(backup_id):
    conn = get_conn()
    b = conn.execute("SELECT * FROM backups WHERE id = ?", (backup_id,)).fetchone()
    if not b:
        conn.close()
        return None
    cats = conn.execute("SELECT COUNT(*) FROM backup_categories WHERE backup_id = ?", (backup_id,)).fetchone()[0]
    chs = conn.execute("SELECT COUNT(*) FROM backup_channels WHERE backup_id = ?", (backup_id,)).fetchone()[0]
    rls = conn.execute("SELECT COUNT(*) FROM backup_roles WHERE backup_id = ?", (backup_id,)).fetchone()[0]
    conn.close()
    return {"categories": cats, "channels": chs, "roles": rls}
