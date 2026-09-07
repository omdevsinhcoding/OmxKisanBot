import os
import json
import datetime
import threading
import psycopg2
from psycopg2 import pool
from config import DATABASE_URL

# --- PostgreSQL DB Setup ---
pg_pool = None
db_lock = threading.Lock()

if DATABASE_URL:
    try:
        pg_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)
    except Exception as e:
        print(f"Error connecting to PostgreSQL: {e}")

def db_execute(query: str, params: tuple = (), fetchone: bool = False, fetchall: bool = False, commit: bool = False):
    if not pg_pool:
        print("PostgreSQL pool not initialized.")
        return None
    try:
        with db_lock:
            conn = pg_pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    if commit:
                        conn.commit()
                    if fetchone:
                        return cursor.fetchone()
                    if fetchall:
                        return cursor.fetchall()
            finally:
                pg_pool.putconn(conn)
    except Exception as e:
        print(f"PostgreSQL db_execute error ({query}): {e}")
        return None

def init_db():
    if not pg_pool:
        return
    db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_seen TEXT
        )
    """, commit=True)
    db_execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id BIGINT PRIMARY KEY,
            session TEXT,
            updated_at TEXT
        )
    """, commit=True)
    db_execute("""
        CREATE TABLE IF NOT EXISTS settings (
            user_id BIGINT PRIMARY KEY,
            data TEXT
        )
    """, commit=True)

init_db()

DEFAULT_SETTINGS = {
    "upload_mode": "Telegram",
    "public_channel": "Re-Upload",
    "large_files": "Splitting",
    "upload_format": "Default",
    "send_pm": "On",
    "set_upload": "Not Set",
    "thumbnail": "Not Set",
    "caption": "Not Set",
    "rename": "Not Set",
}

# --- User Management ---
async def register_user(user_id: int, username: str = None, first_name: str = None):
    db_execute(
        "INSERT INTO users (user_id, username, first_name, last_seen) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, last_seen = EXCLUDED.last_seen",
        (user_id, username, first_name, datetime.datetime.utcnow().isoformat()),
        commit=True
    )

async def get_all_user_ids():
    user_ids = set()
    rows = db_execute("SELECT user_id FROM users", fetchall=True)
    if rows:
        for r in rows:
            user_ids.add(r[0])
    return list(user_ids)

# --- Pyrogram Session String ---
async def save_session(user_id: int, session_string: str):
    db_execute(
        "INSERT INTO sessions (user_id, session, updated_at) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET session = EXCLUDED.session, updated_at = EXCLUDED.updated_at",
        (user_id, session_string, datetime.datetime.utcnow().isoformat()),
        commit=True
    )
    print(f"✅ Session saved in local database for user {user_id}")

async def get_session(user_id: int):
    row = db_execute("SELECT session FROM sessions WHERE user_id = %s", (user_id,), fetchone=True)
    if row and row[0]:
        return row[0]
    return None

async def delete_session(user_id: int):
    db_execute("DELETE FROM sessions WHERE user_id = %s", (user_id,), commit=True)

# --- Full User Settings ---
async def get_user_settings(user_id: int) -> dict:
    settings = DEFAULT_SETTINGS.copy()
    row = db_execute("SELECT data FROM settings WHERE user_id = %s", (user_id,), fetchone=True)
    if row and row[0]:
        try:
            settings.update(json.loads(row[0]))
        except Exception:
            pass
    return settings

async def update_user_setting(user_id: int, key: str, value):
    current = await get_user_settings(user_id)
    current[key] = value
    db_execute(
        "INSERT INTO settings (user_id, data) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data",
        (user_id, json.dumps(current)),
        commit=True
    )

# --- Legacy Setting Helpers ---
async def save_thumbnail(user_id: int, file_id: str):
    await update_user_setting(user_id, "thumbnail", "Set")
    await update_user_setting(user_id, "thumbnail_id", file_id)

async def get_thumbnail(user_id: int):
    settings = await get_user_settings(user_id)
    return settings.get("thumbnail_id")

async def delete_thumbnail(user_id: int):
    await update_user_setting(user_id, "thumbnail", "Not Set")
    current = await get_user_settings(user_id)
    if "thumbnail_id" in current:
        del current["thumbnail_id"]
        db_execute(
            "INSERT INTO settings (user_id, data) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data",
            (user_id, json.dumps(current)),
            commit=True
        )

async def save_caption(user_id: int, caption: str):
    await update_user_setting(user_id, "caption", "Set")
    await update_user_setting(user_id, "custom_caption", caption)

async def get_caption(user_id: int):
    settings = await get_user_settings(user_id)
    return settings.get("custom_caption")

async def save_replacements(user_id: int, replace_map: dict):
    await update_user_setting(user_id, "replacements", replace_map)

async def get_replacements(user_id: int):
    settings = await get_user_settings(user_id)
    return settings.get("replacements", {})

# --- Stats ---
async def get_stats():
    total_users = 0
    active_logins = 0
    row_u = db_execute("SELECT COUNT(*) FROM users", fetchone=True)
    if row_u:
        total_users = row_u[0]
    row_s = db_execute("SELECT COUNT(*) FROM sessions", fetchone=True)
    if row_s:
        active_logins = row_s[0]

    return {
        "total_users": total_users,
        "active_logins": active_logins
    }


