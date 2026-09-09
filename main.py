import os
import sys
import asyncio

# Fix Windows console UTF-8 output encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from pyrogram import Client, idle
from pyrogram.types import BotCommand
from config import API_ID, API_HASH, BOT_TOKEN, LOG_GROUP, OWNER_ID
from database.db import init_db, close_db, get_bot_session, save_bot_session

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

async def set_bot_commands(app: Client):
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("stop", "Stop active bot processes"),
        BotCommand("help", "How to use guide"),
        BotCommand("login", "Login your Telegram account"),
        BotCommand("logout", "Logout current session"),
        BotCommand("check", "Check session status"),
        BotCommand("batch", "Batch / bulk range extraction"),
        BotCommand("cancel", "Cancel ongoing process"),
        BotCommand("dl", "Download video (YouTube/Insta/TikTok)"),
        BotCommand("adl", "Download audio MP3"),
        BotCommand("settings", "Bot settings (Caption, Rename, Upload, Thumbnail)"),
        BotCommand("id", "View user ID, chat ID"),
        BotCommand("commands", "View all commands"),
        BotCommand("referral", "Referral program"),
        BotCommand("myplan", "Check your plan"),
        BotCommand("premium", "Buy premium"),
    ]
    try:
        await app.delete_bot_commands()
        await app.set_bot_commands(commands)
        print("✅ Telegram Bot Commands Menu registered successfully!")
    except Exception as e:
        print(f"⚠️ Failed to set bot commands: {e}")

async def send_status_notification(app: Client, is_online: bool):
    msg = "🚀 **Bot Started & Online Successfully!**" if is_online else "🔴 **Bot Stopped / Offline!**"

    for owner in OWNER_ID:
        try:
            await app.send_message(owner, msg)
        except Exception:
            pass  # Silently ignore to prevent console confusion

async def main():
    await init_db()

    bot_session = await get_bot_session()
    
    if bot_session:
        print("✅ Found existing bot session in database. Initializing in-memory client...")
        app = Client(
            "custom_restricted_saver_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=bot_session,
            in_memory=True,
            plugins=dict(root="plugins")
        )
    else:
        print("ℹ️ No bot session found in database. Initializing with bot token...")
        app = Client(
            "custom_restricted_saver_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True,
            plugins=dict(root="plugins")
        )

    await app.start()
    
    # Save session string if we just logged in via bot token
    if not bot_session:
        new_session = await app.export_session_string()
        await save_bot_session(new_session)

    await set_bot_commands(app)
    await send_status_notification(app, is_online=True)
    
    print("==========================================")
    print("Custom Restricted Saver Bot is Online!")
    print("==========================================")
    
    await idle()
    
    try:
        await send_status_notification(app, is_online=False)
    except Exception:
        pass
    
    await app.stop()
    await close_db()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nBot Stopped Cleanly!")
