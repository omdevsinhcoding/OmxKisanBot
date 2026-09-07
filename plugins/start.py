from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.db import register_user
from config import JOIN_LINK, ADMIN_CONTACT
from helpers.cleaner import auto_clean_chat, protect_message

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    protect_message(message.chat.id, message.id)
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    await register_user(user_id, message.from_user.username, first_name)

    text = (
        f"👋 **Welcome {first_name}!**\n\n"
        f"I am the Advanced Save Restricted Content Bot.\n\n"
        f"🚀 **What I Can Do:**\n"
        f"• Save Restricted Post (Text, Media, Files)\n"
        f"• Support Private & Public Channels\n"
        f"• Batch/Bulk Mode Supported\n\n"
        f"⚠️ **Note:** You must `/login` to your account to use the downloading features."
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🆘 How To Use", callback_data="open_help"),
            InlineKeyboardButton("ℹ️ About Bot", callback_data="open_about")
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")
        ],
        [
            InlineKeyboardButton("📢 Official Channel ↗", url=JOIN_LINK),
            InlineKeyboardButton("👨‍💻 Developer ↗", url=ADMIN_CONTACT)
        ]
    ])

    reply_msg = await message.reply_text(text, reply_markup=buttons)
    protect_message(message.chat.id, reply_msg.id)

@Client.on_message(filters.command("stop") & filters.private)
async def stop_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    try:
        from plugins.batch import BATCH_CANCEL_FLAGS
        BATCH_CANCEL_FLAGS[user_id] = True
    except Exception:
        pass

    text = (
        "🛑 **Bot Stopped!**\n\n"
        "All active download & batch processes for your account have been stopped.\n\n"
        "Send `/start` anytime to reactivate the bot!"
    )
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start Bot", callback_data="back_to_start")]])
    await message.reply_text(text, reply_markup=buttons)

@Client.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    text = (
        "📖 **How To Use - Complete Guide**\n\n"
        "🔑 **1. Account Login:**\n"
        "• Use `/login` to connect your Telegram account via OTP for private restricted channels.\n"
        "• Use `/check` to verify your active session.\n"
        "• Use `/logout` to remove saved session.\n\n"
        "🔗 **2. Save Restricted Posts:**\n"
        "• **Single Link:** Send any Telegram post link directly.\n"
        "• **Range Link:** Send range link directly (e.g. `https://t.me/c/123/10-20`).\n\n"
        "📦 **3. Batch Saver:**\n"
        "• Send: `/batch <start_link> <end_link>`\n"
        "• Stop batch anytime with `/cancel` or `/stop`.\n\n"
        "📤 **4. Custom Upload Chat:**\n"
        "• Set target Channel/Group in `/settings` ➜ **Set Upload** to auto-forward extracted content.\n\n"
        "📥 **5. Social Media Downloader:**\n"
        "• `/dl <link>` - Download YouTube / Instagram / TikTok videos\n"
        "• `/adl <link>` - Download Audio MP3\n\n"
        "⚙️ **6. Settings:**\n"
        "• `/settings` - Custom Thumbnail, Caption template, and Word replacements."
    )
    await message.reply_text(text)

@Client.on_message(filters.command("id"))
async def id_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id if message.from_user else "N/A"
    chat_id = message.chat.id
    text = f"👤 **User ID:** `{user_id}`\n💬 **Chat ID:** `{chat_id}`"
    thread_id = getattr(message, "message_thread_id", None)
    if thread_id:
        text += f"\n📂 **Topic ID:** `{thread_id}`"
        text += f"\n📋 **Copy for Upload:** `{chat_id}/{thread_id}`"
        
    await message.reply_text(text)

@Client.on_message(filters.command("commands") & filters.private)
async def commands_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    text = (
        "📋 **All Bot Commands List**\n\n"
        "/start - Start the bot\n"
        "/stop - Stop active bot processes\n"
        "/help - How to use guide\n"
        "/login - Login Telegram account via OTP\n"
        "/logout - Logout saved session\n"
        "/check - Check active session status\n"
        "/batch - Batch / bulk range extraction\n"
        "/cancel - Cancel ongoing batch process\n"
        "/dl - Video downloader (YouTube/Insta/TikTok)\n"
        "/adl - Audio MP3 downloader\n"
        "/settings - Bot settings (Caption, Rename, Upload, Thumbnail)\n"
        "/id - View user ID, chat ID\n"
        "/commands - View all commands\n"
        "/referral - Referral program\n"
        "/myplan - Check your plan\n"
        "/premium - Buy premium\n\n"
        "📌 **How To Save Content**\n\n"
        "• **Single Post:** Send any Telegram post link\n"
        "• **Batch / Bulk:** Send range link like `https://t.me/c/123/10-20` or `/batch`\n"
        "• **Upload Chat:** Set via `/settings` → Set Upload\n"
        "• **Custom Caption:** `/settings` → Set Caption\n"
        "• **Rename Rules:** `/settings` → Set Rename (delete/replace words)\n\n"
        "🤖 **Bot Content Extraction** (💎 **Unlimited Access**)"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("referral") & filters.private)
async def referral_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    bot_info = await client.get_me()
    bot_username = bot_info.username
    user_id = message.from_user.id
    link = f"https://t.me/{bot_username}?start={user_id}"
    text = (
        "🎁 **Referral Program**\n\n"
        f"Share your referral link with friends:\n`{link}`\n\n"
        "👥 **Total Referred Users:** `0`"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("myplan") & filters.private)
async def myplan_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    text = (
        "📊 **Your Subscription Plan**\n\n"
        "⚡ **Plan:** `Unlimited Free Access`\n"
        "⏳ **Validity:** `Lifetime`\n"
        "📦 **Daily Downloads:** `Unlimited`"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("premium") & filters.private)
async def premium_info_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    text = (
        "💎 **Premium Features Info**\n\n"
        "🎉 Good news! All premium features (Unlimited Downloads, Batch Saver, 4GB support, Social Media Downloader) are **100% FREE** for everyone on this bot!"
    )
    await message.reply_text(text)

from pyrogram.errors import MessageNotModified

@Client.on_callback_query(filters.regex("^(open_help|open_about)$"))
async def start_callbacks(client: Client, query: CallbackQuery):
    data = query.data
    try:
        if data == "open_help":
            help_text = (
                "📖 **How To Use - Quick Guide**\n\n"
                "🔑 **1. Login Account:**\n"
                "• Use `/login` to connect your Telegram account via OTP for private channels.\n\n"
                "🔗 **2. Save Single Post:**\n"
                "• Send any Telegram post link directly (e.g. `https://t.me/c/12345/10`).\n\n"
                "📦 **3. Batch & Range Saver:**\n"
                "• Send range link directly (e.g. `https://t.me/c/12345/10-20`) or use `/batch`.\n"
                "• Use `/cancel` or `/stop` to stop anytime.\n\n"
                "📤 **4. Custom Upload Chat:**\n"
                "• Go to `/settings` ➜ **Set Upload** to auto-forward all content to your Channel/Group!\n\n"
                "📥 **5. Social Media Downloader:**\n"
                "• `/dl <link>` for YouTube, Instagram, TikTok videos.\n"
                "• `/adl <link>` for Audio MP3.\n\n"
                "⚙️ **6. Custom Captions & Thumbnails:**\n"
                "• Manage via `/settings` panel."
            )
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]])
            await query.message.edit_text(help_text, reply_markup=buttons)
        elif data == "open_about":
            about_text = (
                "ℹ️ **About Save Restricted Content Bot**\n\n"
                "• **Version:** 3.0 (Custom Build)\n"
                "• **Framework:** Pyrogram v2 & Python 3.12\n"
                "• **Features:** Private/Public Post Saver, Batch Saver, Social Media Downloader, Custom Thumbnail & Captions.\n"
                "• **Limits:** 100% Free & Unlimited!"
            )
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]])
            await query.message.edit_text(about_text, reply_markup=buttons)
    except MessageNotModified:
        pass

@Client.on_callback_query(filters.regex("^back_to_start$"))
async def back_to_start(client: Client, query: CallbackQuery):
    first_name = query.from_user.first_name
    text = (
        f"👋 **Welcome {first_name}!**\n\n"
        f"I am the Advanced Save Restricted Content Bot.\n\n"
        f"🚀 **What I Can Do:**\n"
        f"• Save Restricted Post (Text, Media, Files)\n"
        f"• Support Private & Public Channels\n"
        f"• Batch/Bulk Mode Supported\n\n"
        f"⚠️ **Note:** You must `/login` to your account to use the downloading features."
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🆘 How To Use", callback_data="open_help"),
            InlineKeyboardButton("ℹ️ About Bot", callback_data="open_about")
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")
        ],
        [
            InlineKeyboardButton("📢 Official Channel ↗", url=JOIN_LINK),
            InlineKeyboardButton("👨‍💻 Developer ↗", url=ADMIN_CONTACT)
        ]
    ])

    try:
        await query.message.edit_text(text, reply_markup=buttons)
    except MessageNotModified:
        pass

