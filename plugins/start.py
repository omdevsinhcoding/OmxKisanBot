from pyrogram import Client, filters, raw
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified
from database.db import register_user
from config import JOIN_LINK, ADMIN_CONTACT
from helpers.cleaner import auto_clean_chat, protect_message


# ─── Blockquote Helper ───────────────────────────────────────────────
# Pyrogram's HTML parser does NOT support <blockquote> on older versions.
# We bypass it entirely by constructing raw MessageEntityBlockquote
# entities and editing the message via Pyrogram's raw API layer.

def _utf16_len(s: str) -> int:
    """Telegram uses UTF-16 code units for entity offsets."""
    return len(s.encode('utf-16-le')) // 2


def _build_start_content(first_name: str):
    """Build /start message text + raw entities with blockquotes."""
    bq1 = f"👋 Welcome {first_name}!"
    mid = "\nI am the Advanced Save Restricted Content Bot.\n\n"
    bq2 = (
        "🚀 What I Can Do:\n"
        "‣ Save Restricted Post (Text, Media, Files)\n"
        "‣ Support Private & Public Channels\n"
        "‣ Batch/Bulk Mode Supported"
    )
    sep = "\n"
    bq3 = "⚠️ Note: You must /login to your account to use the downloading features."

    full_text = bq1 + mid + bq2 + sep + bq3
    entities = []

    # ── Blockquote 1: Welcome ──
    o1 = 0
    entities.append(raw.types.MessageEntityBlockquote(offset=o1, length=_utf16_len(bq1)))
    entities.append(raw.types.MessageEntityBold(
        offset=_utf16_len("👋 "),
        length=_utf16_len(f"Welcome {first_name}!")
    ))

    # ── Blockquote 2: What I Can Do ──
    o2 = _utf16_len(bq1 + mid)
    entities.append(raw.types.MessageEntityBlockquote(offset=o2, length=_utf16_len(bq2)))
    entities.append(raw.types.MessageEntityBold(
        offset=o2 + _utf16_len("🚀 "),
        length=_utf16_len("What I Can Do:")
    ))

    # ── Blockquote 3: Note ──
    o3 = _utf16_len(bq1 + mid + bq2 + sep)
    entities.append(raw.types.MessageEntityBlockquote(offset=o3, length=_utf16_len(bq3)))
    entities.append(raw.types.MessageEntityBold(
        offset=o3 + _utf16_len("⚠️ "),
        length=_utf16_len("Note:")
    ))
    italic_text = "You must /login to your account to use the downloading features."
    italic_offset = o3 + _utf16_len("⚠️ Note: ")
    entities.append(raw.types.MessageEntityItalic(
        offset=italic_offset,
        length=_utf16_len(italic_text)
    ))
    code_offset = italic_offset + _utf16_len("You must ")
    entities.append(raw.types.MessageEntityCode(
        offset=code_offset,
        length=_utf16_len("/login")
    ))

    return full_text, entities


def _start_buttons():
    """Inline keyboard for /start (high-level Pyrogram types)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🆘 How To Use", callback_data="open_help"),
            InlineKeyboardButton("ℹ️ About Bot", callback_data="open_about")
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")],
        [
            InlineKeyboardButton("📢 Official Channel ↗", url=JOIN_LINK),
            InlineKeyboardButton("👨‍💻 Developer ↗", url=ADMIN_CONTACT)
        ]
    ])


def _start_raw_markup():
    """Inline keyboard for /start (raw types for EditMessage)."""
    return raw.types.ReplyInlineMarkup(
        rows=[
            raw.types.KeyboardButtonRow(buttons=[
                raw.types.KeyboardButtonCallback(text="🆘 How To Use", data=b"open_help"),
                raw.types.KeyboardButtonCallback(text="ℹ️ About Bot", data=b"open_about"),
            ]),
            raw.types.KeyboardButtonRow(buttons=[
                raw.types.KeyboardButtonCallback(text="⚙️ Settings", data=b"open_settings"),
            ]),
            raw.types.KeyboardButtonRow(buttons=[
                raw.types.KeyboardButtonUrl(text="📢 Official Channel ↗", url=JOIN_LINK),
                raw.types.KeyboardButtonUrl(text="👨‍💻 Developer ↗", url=ADMIN_CONTACT),
            ]),
        ]
    )


# ─── Command Handlers ────────────────────────────────────────────────

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    protect_message(message.chat.id, message.id)
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    await register_user(user_id, message.from_user.username, first_name)

    text, entities = _build_start_content(first_name)

    # Step 1: Send the message normally (gets us reply + message ID)
    reply_msg = await message.reply_text(text, reply_markup=_start_buttons())
    protect_message(message.chat.id, reply_msg.id)

    # Step 2: Immediately edit via raw API to inject blockquote entities
    try:
        peer = await client.resolve_peer(message.chat.id)
        await client.invoke(
            raw.functions.messages.EditMessage(
                peer=peer,
                id=reply_msg.id,
                message=text,
                entities=entities,
                reply_markup=_start_raw_markup()
            )
        )
    except Exception as e:
        print(f"Blockquote formatting edit failed: {e}")


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
    
    # Aggressive fallback: in a forum, every top-level message is technically a reply to the topic creation message
    if not thread_id:
        thread_id = getattr(message, "reply_to_message_id", None)

    if thread_id:
        text += f"\n📂 **Topic ID:** `{thread_id}`"
        text += f"\n📋 **Copy for Upload:** `{chat_id}/{thread_id}`"
    else:
        text += f"\n⚠️ **Topic ID Debug:** `Not detected (reply_to={getattr(message, 'reply_to_message_id', 'None')})`"

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


# ─── Callback Handlers ───────────────────────────────────────────────

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
    text, entities = _build_start_content(first_name)

    try:
        peer = await client.resolve_peer(query.message.chat.id)
        await client.invoke(
            raw.functions.messages.EditMessage(
                peer=peer,
                id=query.message.id,
                message=text,
                entities=entities,
                reply_markup=_start_raw_markup()
            )
        )
    except Exception:
        pass
