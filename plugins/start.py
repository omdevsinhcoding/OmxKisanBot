from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified
from database.db import register_user
from config import JOIN_LINK, ADMIN_CONTACT, BOT_TOKEN
from helpers.cleaner import auto_clean_chat, protect_message
import json
import asyncio
import urllib.request
import html as html_mod


# ─── Telegram Bot API Direct Call ─────────────────────────────────────
# Pyrogram's HTML parser doesn't support <blockquote>.
# We call Telegram Bot API over HTTP using stdlib urllib.

def _build_start_html(first_name: str) -> str:
    """Build /start HTML text with <blockquote> tags."""
    safe_name = html_mod.escape(first_name)
    return (
        f"<blockquote>👋 <b>Welcome {safe_name}!</b></blockquote>\n\n"
        f"<b>I am the Advanced Save Restricted Content Bot.</b>\n\n"
        f"<blockquote>🚀 <b>What I Can Do:</b>\n"
        f"‣ Save Restricted Post (Text, Media, Files)\n"
        f"‣ Support Private &amp; Public Channels\n"
        f"‣ Batch/Bulk Mode Supported</blockquote>\n\n"
        f"<blockquote>⚠️ <b>Note:</b> <i>You must <code>/login</code> to your account to use the downloading features.</i></blockquote>"
    )


def _build_start_plain(first_name: str) -> str:
    """Fallback plain text (no blockquotes) if Bot API call fails."""
    return (
        f"👋 **Welcome {first_name}!**\n\n"
        f"I am the Advanced Save Restricted Content Bot.\n\n"
        f"🚀 **What I Can Do:**\n"
        f"‣ Save Restricted Post (Text, Media, Files)\n"
        f"‣ Support Private & Public Channels\n"
        f"‣ Batch/Bulk Mode Supported\n\n"
        f"⚠️ **Note:** _You must `/login` to your account to use the downloading features._"
    )


def _build_help_html() -> str:
    """Build /help HTML text with <blockquote> tags."""
    return (
        "🛠 <b>𝐇𝐨𝐰 𝐓𝐨 𝐔𝐬𝐞 𝐌𝐞</b>\n\n"
        "👤 <b>𝐔𝐬𝐞𝐫 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬</b>\n\n"
        "<blockquote>/start - Start the bot\n"
        "/help - How to use guide\n"
        "/id - View user ID, chat ID\n"
        "/commands - View all commands\n"
        "/login - Login your Telegram account\n"
        "/logout - Logout current session\n"
        "/cancel - Cancel ongoing process\n"
        "/settings - Bot settings (Caption, Rename, Upload, Thumbnail)\n"
        "/referral - Referral program\n"
        "/myplan - Check your plan\n"
        "/premium - Buy premium</blockquote>\n\n"
        "📌 <b>𝐇𝐨𝐰 𝐓𝐨 𝐒𝐚𝐯𝐞 𝐂𝐨𝐧𝐭𝐞𝐧𝐭</b>\n\n"
        "<blockquote><b>Single Post:</b> Send any Telegram post link\n"
        "<b>Batch/Bulk:</b> Send link with range like\n"
        "<code>https://t.me/channel/1-100</code>\n"
        "<b>Upload Chat:</b> Set via /settings → Set Upload\n"
        "<b>Custom Caption:</b> /settings → Set Caption\n"
        "<b>Rename Rules:</b> /settings → Set Rename (delete/replace words)</blockquote>\n\n"
        "🤖 <b>𝐁𝐨𝐭 𝐂𝐨𝐧𝐭𝐞𝐧𝐭 𝐄𝐱𝐭𝐫𝐚𝐜𝐭𝐢𝐨𝐧</b> (💎 Premium)\n\n"
        "<blockquote>Extract restricted content from other bots!\n"
        "Just send the bot's deep link like:\n"
        "<code>https://t.me/SomeBot?start=PARAM</code>\n\n"
        "Bot will extract all messages &amp; media the target bot sends.\n"
        "<b>Limit:</b> 5000 msgs/link | 2 min cooldown</blockquote>"
    )


def _build_help_plain() -> str:
    """Fallback plain text (no blockquotes) for /help."""
    return (
        "🛠 **How To Use Me**\n\n"
        "👤 **User Commands**\n\n"
        "/start - Start the bot\n"
        "/help - How to use guide\n"
        "/id - View user ID, chat ID\n"
        "/commands - View all commands\n"
        "/login - Login your Telegram account\n"
        "/logout - Logout current session\n"
        "/cancel - Cancel ongoing process\n"
        "/settings - Bot settings (Caption, Rename, Upload, Thumbnail)\n"
        "/referral - Referral program\n"
        "/myplan - Check your plan\n"
        "/premium - Buy premium\n\n"
        "📌 **How To Save Content**\n\n"
        "**Single Post:** Send any Telegram post link\n"
        "**Batch/Bulk:** Send link with range like\n"
        "`https://t.me/channel/1-100`\n"
        "**Upload Chat:** Set via /settings → Set Upload\n"
        "**Custom Caption:** /settings → Set Caption\n"
        "**Rename Rules:** /settings → Set Rename (delete/replace words)\n\n"
        "🤖 **Bot Content Extraction** (💎 Premium)\n\n"
        "Extract restricted content from other bots!\n"
        "Just send the bot's deep link like:\n"
        "`https://t.me/SomeBot?start=PARAM`\n\n"
        "Bot will extract all messages & media the target bot sends.\n"
        "**Limit:** 5000 msgs/link | 2 min cooldown"
    )


def _start_markup_dict() -> dict:
    """Inline keyboard dict for Bot API."""
    return {
        "inline_keyboard": [
            [
                {"text": "🆘 How To Use", "callback_data": "open_help"},
                {"text": "ℹ️ About Bot", "callback_data": "open_about"}
            ],
            [{"text": "⚙️ Settings", "callback_data": "open_settings"}],
            [
                {"text": "📢 Official Channel ↗", "url": JOIN_LINK},
                {"text": "👨‍💻 Developer ↗", "url": ADMIN_CONTACT}
            ]
        ]
    }


def _start_buttons():
    """Inline keyboard for Pyrogram fallback."""
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


def _bot_api_call(method: str, payload: dict) -> dict:
    """Call Telegram Bot API directly via urllib (stdlib, always available)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ─── Command Handlers ────────────────────────────────────────────────

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    protect_message(message.chat.id, message.id)
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    await register_user(user_id, message.from_user.username, first_name)

    # Try Telegram Bot API directly for blockquotes (non-blocking via thread)
    try:
        result = await asyncio.to_thread(_bot_api_call, "sendMessage", {
            "chat_id": message.chat.id,
            "text": _build_start_html(first_name),
            "parse_mode": "HTML",
            "reply_markup": json.dumps(_start_markup_dict()),
            "reply_to_message_id": message.id,
        })
        if result.get("ok"):
            sent_id = result["result"]["message_id"]
            protect_message(message.chat.id, sent_id)
            return
    except Exception as e:
        print(f"Bot API blockquote send failed: {e}")

    # Fallback: Pyrogram without blockquotes (bot will always respond)
    reply_msg = await message.reply_text(
        _build_start_plain(first_name), reply_markup=_start_buttons()
    )
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
    
    # Try Telegram Bot API directly for blockquotes (non-blocking via thread)
    try:
        result = await asyncio.to_thread(_bot_api_call, "sendMessage", {
            "chat_id": message.chat.id,
            "text": _build_help_html(),
            "parse_mode": "HTML",
            "reply_to_message_id": message.id,
        })
        if result.get("ok"):
            sent_id = result["result"]["message_id"]
            protect_message(message.chat.id, sent_id)
            return
    except Exception as e:
        print(f"Bot API blockquote help send failed: {e}")

    # Fallback
    reply_msg = await message.reply_text(_build_help_plain())
    protect_message(message.chat.id, reply_msg.id)

@Client.on_message(filters.command("id"))
async def id_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id if message.from_user else "N/A"
    first_name = message.from_user.first_name if message.from_user else "Unknown"
    
    text = (
        "👤 **User Info**\n\n"
        f"**Name:** {first_name}\n"
        f"**User ID:** `{user_id}`"
    )
    
    # Only show Chat/Topic info if used in a group or channel
    if message.chat.id != user_id:
        chat_id = message.chat.id
        text += f"\n\n💬 **Chat Info**\n**Chat ID:** `{chat_id}`"
        
        thread_id = getattr(message, "message_thread_id", None)
        if not thread_id:
            thread_id = getattr(message, "reply_to_message_id", None)
            
        if thread_id:
            text += f"\n📂 **Topic ID:** `{thread_id}`"
            text += f"\n📋 **Copy for Upload:** `{chat_id}/{thread_id}`"

    await message.reply_text(text)

def _build_commands_html() -> str:
    return (
        "📜 <b>Available Commands</b>\n\n"
        "<blockquote><b>User Commands:</b>\n"
        "/start - Start the bot\n"
        "/help - How to use guide\n"
        "/commands - View all commands\n"
        "/id - View user ID, chat ID\n"
        "/login - Login account\n"
        "/logout - Logout account\n"
        "/cancel - Cancel ongoing process\n"
        "/settings - Bot settings (Caption, Rename, Upload, Thumbnail)\n"
        "/referral - Referral program\n"
        "/myplan - Check plan status\n"
        "/premium - Buy premium</blockquote>"
    )

def _build_commands_plain() -> str:
    return (
        "📜 **Available Commands**\n\n"
        "**User Commands:**\n"
        "/start - Start the bot\n"
        "/help - How to use guide\n"
        "/commands - View all commands\n"
        "/id - View user ID, chat ID\n"
        "/login - Login account\n"
        "/logout - Logout account\n"
        "/cancel - Cancel ongoing process\n"
        "/settings - Bot settings (Caption, Rename, Upload, Thumbnail)\n"
        "/referral - Referral program\n"
        "/myplan - Check plan status\n"
        "/premium - Buy premium"
    )

@Client.on_message(filters.command("commands") & filters.private)
async def commands_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    
    markup_dict = {
        "inline_keyboard": [
            [{"text": "❌ Close", "callback_data": "close_data"}]
        ]
    }
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close_data")]])
    
    # Try Telegram Bot API directly for blockquotes (non-blocking via thread)
    try:
        result = await asyncio.to_thread(_bot_api_call, "sendMessage", {
            "chat_id": message.chat.id,
            "text": _build_commands_html(),
            "parse_mode": "HTML",
            "reply_markup": json.dumps(markup_dict),
            "reply_to_message_id": message.id,
        })
        if result.get("ok"):
            sent_id = result["result"]["message_id"]
            protect_message(message.chat.id, sent_id)
            return
    except Exception as e:
        print(f"Bot API blockquote commands send failed: {e}")

    # Fallback
    reply_msg = await message.reply_text(_build_commands_plain(), reply_markup=buttons)
    protect_message(message.chat.id, reply_msg.id)

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
            markup_dict = {
                "inline_keyboard": [
                    [{"text": "❌ Close", "callback_data": "close_data", "style": "danger"}, {"text": "🔙 Back", "callback_data": "back_to_start"}]
                ]
            }
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close_data"), InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]])
            
            try:
                await asyncio.to_thread(_bot_api_call, "editMessageText", {
                    "chat_id": query.message.chat.id,
                    "message_id": query.message.id,
                    "text": _build_help_html(),
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(markup_dict),
                })
                return
            except Exception:
                pass
            
            try:
                await query.message.edit_text(_build_help_plain(), reply_markup=buttons)
            except MessageNotModified:
                pass
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

    # Try Bot API for blockquotes (non-blocking via thread)
    try:
        await asyncio.to_thread(_bot_api_call, "editMessageText", {
            "chat_id": query.message.chat.id,
            "message_id": query.message.id,
            "text": _build_start_html(first_name),
            "parse_mode": "HTML",
            "reply_markup": json.dumps(_start_markup_dict()),
        })
        return
    except Exception as e:
        print(f"Bot API edit failed: {e}")

    # Fallback: Pyrogram without blockquotes
    try:
        await query.message.edit_text(
            _build_start_plain(first_name), reply_markup=_start_buttons()
        )
    except MessageNotModified:
        pass


@Client.on_callback_query(filters.regex("^close_data$"))
async def close_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
    except Exception:
        pass
