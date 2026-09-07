from pyrogram import Client, filters
from pyrogram.types import Message
from database.db import get_stats, get_all_user_ids
from config import OWNER_ID

def is_owner_filter(_, __, message: Message):
    return message.from_user and message.from_user.id in OWNER_ID

is_owner = filters.create(is_owner_filter)

@Client.on_message(filters.command("stats") & is_owner & filters.private)
async def stats_handler(client: Client, message: Message):
    stats = await get_stats()
    text = (
        "📊 **Bot System Statistics**\n\n"
        f"👥 **Total Users:** `{stats['total_users']}`\n"
        f"🔑 **Active Login Sessions:** `{stats['active_logins']}`"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("broadcast") & is_owner & filters.private & filters.reply)
async def broadcast_handler(client: Client, message: Message):
    reply_msg = message.reply_to_message
    if not reply_msg:
        return await message.reply_text("❌ **Reply to a message to broadcast it to all users!**")

    user_ids = await get_all_user_ids()
    status = await message.reply_text(f"📢 **Starting Broadcast to {len(user_ids)} users...**")

    success, failed = 0, 0
    for uid in user_ids:
        try:
            await reply_msg.copy(uid)
            success += 1
        except Exception:
            failed += 1

    await status.edit_text(f"✅ **Broadcast Completed!**\n\n🎯 **Success:** `{success}`\n⚠️ **Failed:** `{failed}`")
