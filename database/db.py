import os
import json
import datetime
import asyncpg
from config import DATABASE_URL

# --- PostgreSQL DB Setup ---
pg_pool = None

async def init_db():
    global pg_pool
    if not DATABASE_URL:
        print("DATABASE_URL is not set!")
        return

    try:
        pg_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=20,
            command_timeout=60
        )
        print("✅ PostgreSQL connection pool initialized.")

        async with pg_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_seen TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    user_id BIGINT PRIMARY KEY,
                    session TEXT,
                    updated_at TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    user_id BIGINT PRIMARY KEY,
                    data TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_session (
                    id INTEGER PRIMARY KEY,
                    session TEXT,
                    updated_at TEXT
                )
            """)
    except Exception as e:
        print(f"Error initializing PostgreSQL database: {e}")

async def close_db():
    global pg_pool
    if pg_pool:
        await pg_pool.close()
        print("✅ PostgreSQL connection pool closed.")

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

# --- Bot Session Management ---
async def save_bot_session(session_string: str):
    if not pg_pool:
        return
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_session (id, session, updated_at) VALUES (1, $1, $2) ON CONFLICT (id) DO UPDATE SET session = EXCLUDED.session, updated_at = EXCLUDED.updated_at",
            session_string, datetime.datetime.utcnow().isoformat()
        )
    print("✅ Bot session saved in database.")

async def get_bot_session():
    if not pg_pool:
        return None
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT session FROM bot_session WHERE id = 1")
        if row and row['session']:
            return row['session']
    return None

# --- User Management ---
async def register_user(user_id: int, username: str = None, first_name: str = None):
    if not pg_pool:
        return
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, username, first_name, last_seen) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, last_seen = EXCLUDED.last_seen",
            user_id, username, first_name, datetime.datetime.utcnow().isoformat()
        )

async def get_all_user_ids():
    if not pg_pool:
        return []
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row['user_id'] for row in rows]

# --- Pyrogram Session String ---
async def save_session(user_id: int, session_string: str):
    if not pg_pool:
        return
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (user_id, session, updated_at) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET session = EXCLUDED.session, updated_at = EXCLUDED.updated_at",
            user_id, session_string, datetime.datetime.utcnow().isoformat()
        )
    print(f"✅ Session saved in database for user {user_id}")

async def get_session(user_id: int):
    if not pg_pool:
        return None
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT session FROM sessions WHERE user_id = $1", user_id)
        if row and row['session']:
            return row['session']
    return None

async def delete_session(user_id: int):
    if not pg_pool:
        return
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)

# --- Full User Settings ---
async def get_user_settings(user_id: int) -> dict:
    settings = DEFAULT_SETTINGS.copy()
    if not pg_pool:
        return settings
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT data FROM settings WHERE user_id = $1", user_id)
        if row and row['data']:
            try:
                settings.update(json.loads(row['data']))
            except Exception:
                pass
    return settings

async def update_user_setting(user_id: int, key: str, value):
    current = await get_user_settings(user_id)
    current[key] = value
    if not pg_pool:
        return
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO settings (user_id, data) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data",
            user_id, json.dumps(current)
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
        if pg_pool:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO settings (user_id, data) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data",
                    user_id, json.dumps(current)
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
    if not pg_pool:
        return {"total_users": 0, "active_logins": 0}
        
    async with pg_pool.acquire() as conn:
        row_u = await conn.fetchrow("SELECT COUNT(*) FROM users")
        if row_u:
            total_users = row_u[0]
        row_s = await conn.fetchrow("SELECT COUNT(*) FROM sessions")
        if row_s:
            active_logins = row_s[0]

    return {
        "total_users": total_users,
        "active_logins": active_logins
    }
