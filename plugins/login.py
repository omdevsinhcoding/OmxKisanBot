import asyncio
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message
from pyrogram.errors import (
    ApiIdInvalid, PhoneNumberInvalid, PhoneCodeInvalid, PhoneCodeExpired, SessionPasswordNeeded, PasswordHashInvalid
)
from database.db import save_session, get_session, delete_session
from helpers.downloader import stop_user_client
from config import API_ID, API_HASH

from helpers.cleaner import auto_clean_chat, protect_message

# Active login sessions in-memory step state
LOGIN_STATES = {}



@Client.on_message(filters.command("login") & filters.private)
async def login_handler(client: Client, message: Message):
    protect_message(message.chat.id, message.id)
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    existing_session = await get_session(user_id)
    if existing_session:
        already_msg = await message.reply_text(
            "✅ **Login Successful!**\n\n"
            "> **Your account is now connected.**\n"
            "> **You can save restricted content.**\n\n"
            "Use `/check` to verify your session anytime."
        )
        protect_message(message.chat.id, already_msg.id)
        return

    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Login by Phone No.", callback_data="start_login_flow")],
        [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
    ])
    
    # Plain text for instant Pyrogram send (no blockquotes to avoid ugly `> ` literals)
    plain_text = (
        "🔐 **Telegram Account Login**\n\n"
        "⚠️ **Warning:** _Do not misuse or abuse your account._\n"
        "_If Telegram bans or restricts your account, the responsibility is entirely yours._\n\n"
        "_Tap Login by Phone No. to begin._"
    )
    
    # Send instantly to prevent any lag
    reply_msg = await message.reply_text(plain_text, reply_markup=buttons)
    protect_message(message.chat.id, reply_msg.id)

    # Upgrade text (add blockquote) and button styles (Blue/Red) in the background via Bot API
    import json
    import asyncio
    import urllib.request
    from config import BOT_TOKEN

    html_text = (
        "🔐 <b>Telegram Account Login</b>\n\n"
        "<blockquote>⚠️ <b>Warning:</b> <i>Do not misuse or abuse your account.\n"
        "If Telegram bans or restricts your account, the responsibility is entirely yours.</i></blockquote>\n\n"
        "<i>Tap Login by Phone No. to begin.</i>"
    )

    markup_dict = {
        "inline_keyboard": [
            [{"text": "📱 Login by Phone No.", "callback_data": "start_login_flow", "style": "primary"}],
            [{"text": "❌ Cancel", "callback_data": "close_data", "style": "danger"}]
        ]
    }
    
    def _upgrade_ui():
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": message.chat.id,
            "message_id": reply_msg.id,
            "text": html_text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(markup_dict)
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    asyncio.create_task(asyncio.to_thread(_upgrade_ui))

@Client.on_callback_query(filters.regex("^start_login_flow$"))
async def start_login_callback(client: Client, query):
    user_id = query.from_user.id
    import time
    login_id = time.time()
    LOGIN_STATES[user_id] = {"step": "PHONE", "id": login_id}
    
    try:
        # Remove buttons from original message
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    text = (
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send your number with country code.\n"
        "Example: <code>+19876543210</code>\n\n"
        "⏱ <i>You have 3 minutes.</i>\n"
        "<i>Send /cancellogin to stop.</i>"
    )
    
    try:
        from pyrogram import enums
        sent_msg = await query.message.reply_text(text, quote=True, parse_mode=enums.ParseMode.HTML)
        protect_message(query.message.chat.id, sent_msg.id)
    except Exception:
        pass

    # Start 3-minute timer
    async def login_timeout():
        import asyncio
        await asyncio.sleep(180)
        state = LOGIN_STATES.get(user_id)
        # Check if they are still on the PHONE step for this specific login attempt
        if state and state.get("id") == login_id and state.get("step") == "PHONE":
            del LOGIN_STATES[user_id]
            timeout_text = (
                "⏱ **Timed out.**\n\n"
                "Phone number not received in 3 minutes.\n"
                "Send `/login` to try again."
            )
            try:
                await client.send_message(query.message.chat.id, timeout_text)
            except Exception:
                pass

    import asyncio
    asyncio.create_task(login_timeout())

@Client.on_message(filters.command("cancellogin") & filters.private)
async def cancellogin_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    if user_id in LOGIN_STATES:
        del LOGIN_STATES[user_id]
        await message.reply_text("🛑 **Login process cancelled.**")
    else:
        await message.reply_text("❌ **You are not currently in a login process.**")

@Client.on_message(filters.command("check") & filters.private)
async def check_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    session = await get_session(user_id)
    if session:
        check_msg = await message.reply_text(
            "✅ **Session Active!**\n\n"
            "> **Your account is connected.**\n"
            "> **You can save restricted content.**"
        )
        protect_message(message.chat.id, check_msg.id)
    else:
        await message.reply_text("❌ **No Active Session!** Please use `/login` to connect your account.")

@Client.on_message(filters.command("logout") & filters.private)
async def logout_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    await stop_user_client(user_id)  # Kill cached client first
    await delete_session(user_id)
    if user_id in LOGIN_STATES:
        del LOGIN_STATES[user_id]
    await message.reply_text("🚪 **Logged out successfully!** Your saved session string has been deleted.")

@Client.on_message(filters.incoming & filters.text & filters.private & ~filters.command(["login", "logout", "check", "start", "stop", "help", "settings", "batch", "dl", "adl", "cancel", "id", "commands", "referral", "myplan", "premium"]))
async def login_step_listener(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in LOGIN_STATES:
        raise ContinuePropagation

    state = LOGIN_STATES[user_id]
    step = state.get("step")

    if step == "PHONE":
        phone_number = message.text.strip().replace(" ", "")
        
        wait_msg = await message.reply_text("⏳ **Sending OTP...**")
        
        temp_client = Client(f"temp_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
        try:
            await temp_client.connect()
            code_hash = await temp_client.send_code(phone_number)
            LOGIN_STATES[user_id] = {
                "step": "OTP",
                "phone": phone_number,
                "code_hash": code_hash.phone_code_hash,
                "temp_client": temp_client
            }
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await message.reply_text(
                "📩 **OTP Sent!**\n\n"
                "Please enter the OTP code sent to your Telegram app.\n"
                "Format: Enter numbers separated by spaces (e.g. `1 2 3 4 5`) so Telegram doesn't auto-read it."
            )
        except Exception as e:
            await temp_client.disconnect()
            del LOGIN_STATES[user_id]
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await message.reply_text(f"❌ **Login Error:** `{e}`\nPlease start again using `/login`.")

    elif step == "OTP":
        otp_code = message.text.strip().replace(" ", "")
        temp_client = state["temp_client"]
        phone_number = state["phone"]
        code_hash = state["code_hash"]

        try:
            await temp_client.sign_in(phone_number=phone_number, phone_code_hash=code_hash, phone_code=otp_code)
            session_string = await temp_client.export_session_string()
            await save_session(user_id, session_string)
            await temp_client.disconnect()
            del LOGIN_STATES[user_id]
            
            success_text = (
                "✅ **Login Successful!**\n\n"
                "> **Your account is now connected.**\n"
                "> **You can save restricted content.**\n\n"
                "Use `/check` to verify your session anytime."
            )
            success_msg = await message.reply_text(success_text)
            protect_message(message.chat.id, success_msg.id)
        except SessionPasswordNeeded:
            LOGIN_STATES[user_id]["step"] = "2FA"
            await message.reply_text("🔐 **Two-Factor Authentication (2FA) Required!**\nPlease enter your Two-Step Verification Password:")
        except (PhoneCodeInvalid, PhoneCodeExpired) as e:
            await message.reply_text(f"❌ **Invalid/Expired OTP:** `{e}`. Please try entering again:")
        except Exception as e:
            await temp_client.disconnect()
            del LOGIN_STATES[user_id]
            await message.reply_text(f"❌ **Error:** `{e}`")

    elif step == "2FA":
        password = message.text.strip()
        temp_client = state["temp_client"]
        try:
            await temp_client.check_password(password=password)
            session_string = await temp_client.export_session_string()
            await save_session(user_id, session_string)
            await temp_client.disconnect()
            del LOGIN_STATES[user_id]
            
            success_text = (
                "✅ **Login Successful!**\n\n"
                "> **Your account is now connected.**\n"
                "> **You can save restricted content.**\n\n"
                "Use `/check` to verify your session anytime."
            )
            success_msg = await message.reply_text(success_text)
            protect_message(message.chat.id, success_msg.id)
        except PasswordHashInvalid:
            await message.reply_text("❌ **Incorrect 2FA Password!** Please enter password again:")
        except Exception as e:
            await temp_client.disconnect()
            del LOGIN_STATES[user_id]
            await message.reply_text(f"❌ **Error:** `{e}`")
