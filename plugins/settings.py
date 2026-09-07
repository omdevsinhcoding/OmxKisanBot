from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified
from database.db import (
    get_user_settings, update_user_setting,
    save_thumbnail, delete_thumbnail, save_caption, save_replacements
)
from helpers.cleaner import auto_clean_chat

SET_UPLOAD_STATES = {}

@Client.on_message(filters.command("settings") & filters.private)
async def settings_command(client: Client, message: Message):
    try:
        await auto_clean_chat(client, message)
        await render_settings_panel(message.from_user.id, message)
    except Exception as e:
        print(f"Error in settings_command: {e}")
        await message.reply_text(f"❌ **Settings Error:** `{e}`")

async def render_settings_panel(user_id: int, message_or_query):
    s = await get_user_settings(user_id)

    upload_mode = s.get("upload_mode", "Telegram")
    public_ch = s.get("public_channel", "Re-Upload")
    large_files = s.get("large_files", "Splitting")
    upload_format = s.get("upload_format", "Default")
    send_pm = s.get("send_pm", "On")
    set_upload = s.get("set_upload", "Not Set")
    thumbnail = s.get("thumbnail", "Not Set")
    caption = s.get("caption", "Not Set")
    rename = s.get("rename", "Not Set")

    text = (
        "⚙️ **Settings**\n\n"
        f"**Upload Mode:** {upload_mode} ✅\n"
        f"**Public Channel:** {public_ch} ✅\n"
        f"**Large Files (>2GB):** {large_files} ✅\n"
        f"**Upload Format:** {upload_format} ✅\n"
        f"**Send to PM:** {send_pm} ✅\n"
        f"**Set Upload:** {set_upload}\n"
        f"**Thumbnail:** {thumbnail}\n"
        f"**Caption:** {caption}\n"
        f"**Rename:** {rename}"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Upload Mode | {upload_mode} ✅", callback_data="toggle_upload_mode")],
        [InlineKeyboardButton(f"Public Channel Mode", callback_data="toggle_public_channel")],
        [InlineKeyboardButton(f"Large Files (>2GB)", callback_data="toggle_large_files")],
        [InlineKeyboardButton("Upload Format", callback_data="toggle_upload_format"), InlineKeyboardButton("Send to PM", callback_data="toggle_send_pm")],
        [InlineKeyboardButton("Set Upload", callback_data="prompt_set_upload"), InlineKeyboardButton("Set Thumbnail", callback_data="set_thumb")],
        [InlineKeyboardButton("Caption", callback_data="set_caption"), InlineKeyboardButton("Rename", callback_data="set_replace")],
        [InlineKeyboardButton("Commands", callback_data="open_help")],
        [InlineKeyboardButton("❌ Close", callback_data="close_settings"), InlineKeyboardButton("Back", callback_data="back_to_start")]
    ])

    try:
        if isinstance(message_or_query, CallbackQuery):
            await message_or_query.message.edit_text(text, reply_markup=buttons)
        else:
            await message_or_query.reply_text(text, reply_markup=buttons)
    except MessageNotModified:
        pass

async def render_upload_chat_menu(client: Client, user_id: int, query: CallbackQuery):
    s = await get_user_settings(user_id)
    upload_data = s.get("set_upload_data")

    if upload_data and isinstance(upload_data, dict):
        # Already set - Show Screenshot 2 UI
        name = upload_data.get("name", "Custom Chat")
        c_type = upload_data.get("type", "Group / Channel")
        chat_id = upload_data.get("chat_id", "Not Set")
        topic = upload_data.get("topic", "None")
        link = upload_data.get("link", "#")

        text = (
            "**Upload Chat**\n\n"
            "✅ _Upload chat set successfully!_\n\n"
            f"**Name:** {name}\n"
            f"**Type:** {c_type}\n"
            f"**Chat ID:** `{chat_id}`\n"
            f"**Topic:** {topic}\n"
            f"**Link:** [Open Chat]({link})"
        )
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Change", callback_data="enter_upload_chat_id"), InlineKeyboardButton("🗑️ Remove", callback_data="remove_upload_chat")],
            [InlineKeyboardButton("Back", callback_data="open_settings")]
        ])
    else:
        # Not set - Show Initial Instructions
        bot_info = await client.get_me()
        bot_username = bot_info.username
        text = (
            "**Upload Chat**\n\n"
            "_Turn on this feature and the bot will upload all saved content to your channel or group._\n\n"
            "**How to set up:**\n"
            "1. Add the bot to your channel or group using the buttons below.\n"
            "2. Send `/id` in that channel or group.\n"
            "3. Copy the chat ID (starts with -100).\n"
            "4. Come back here and click Set Upload Chat.\n\n"
            "_For group topics: send as `-100xxx/topic_id`_"
        )
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add to Channel ↗", url=f"https://t.me/{bot_username}?startchannel=true")],
            [InlineKeyboardButton("Add to Group ↗", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton("Set Upload Chat", callback_data="enter_upload_chat_id")],
            [InlineKeyboardButton("Back", callback_data="open_settings")]
        ])

    try:
        await query.message.edit_text(text, reply_markup=buttons, disable_web_page_preview=True)
    except MessageNotModified:
        pass

@Client.on_callback_query(filters.regex("^(open_settings|toggle_upload_mode|toggle_public_channel|toggle_large_files|toggle_upload_format|toggle_send_pm|prompt_set_upload|enter_upload_chat_id|remove_upload_chat|set_thumb|set_caption|set_replace|close_settings|back_to_settings)$"))
async def settings_callbacks(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    try:
        if data in ["open_settings", "back_to_settings"]:
            if user_id in SET_UPLOAD_STATES:
                del SET_UPLOAD_STATES[user_id]
            await render_settings_panel(user_id, query)
        elif data == "close_settings":
            await query.message.delete()
        elif data == "toggle_upload_mode":
            s = await get_user_settings(user_id)
            curr = s.get("upload_mode", "Telegram")
            new_val = "Drive" if curr == "Telegram" else "Telegram"
            await update_user_setting(user_id, "upload_mode", new_val)
            await query.answer(f"Upload Mode set to {new_val}")
            await render_settings_panel(user_id, query)
        elif data == "toggle_public_channel":
            s = await get_user_settings(user_id)
            curr = s.get("public_channel", "Re-Upload")
            new_val = "Forward" if curr == "Re-Upload" else "Re-Upload"
            await update_user_setting(user_id, "public_channel", new_val)
            await query.answer(f"Public Channel set to {new_val}")
            await render_settings_panel(user_id, query)
        elif data == "toggle_large_files":
            s = await get_user_settings(user_id)
            curr = s.get("large_files", "Splitting")
            new_val = "Skip" if curr == "Splitting" else "Splitting"
            await update_user_setting(user_id, "large_files", new_val)
            await query.answer(f"Large Files handling set to {new_val}")
            await render_settings_panel(user_id, query)
        elif data == "toggle_upload_format":
            s = await get_user_settings(user_id)
            curr = s.get("upload_format", "Default")
            formats = ["Default", "Video", "Document"]
            new_val = formats[(formats.index(curr) + 1) % len(formats)]
            await update_user_setting(user_id, "upload_format", new_val)
            await query.answer(f"Upload Format set to {new_val}")
            await render_settings_panel(user_id, query)
        elif data == "toggle_send_pm":
            s = await get_user_settings(user_id)
            curr = s.get("send_pm", "On")
            new_val = "Off" if curr == "On" else "On"
            await update_user_setting(user_id, "send_pm", new_val)
            await query.answer(f"Send to PM set to {new_val}")
            await render_settings_panel(user_id, query)
        elif data == "prompt_set_upload":
            await render_upload_chat_menu(client, user_id, query)
        elif data == "enter_upload_chat_id":
            SET_UPLOAD_STATES[user_id] = True
            # Show Screenshot 1 Waiting UI
            text = (
                "**Upload Chat**\n\n"
                "_Send your Chat ID within 60 seconds._\n\n"
                "**Format:** `-100123456789`\n"
                "**With topic:** `-100123456789/456`\n\n"
                "⏳ _Waiting..._"
            )
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="prompt_set_upload")]])
            await query.message.edit_text(text, reply_markup=buttons)
        elif data == "remove_upload_chat":
            await update_user_setting(user_id, "set_upload", "Not Set")
            await update_user_setting(user_id, "set_upload_data", None)
            await query.answer("Upload Chat removed!")
            await render_upload_chat_menu(client, user_id, query)
        elif data == "set_thumb":
            await query.answer()
            await query.message.reply_text("🖼️ **Send the photo you want to set as custom video thumbnail:**")
        elif data == "set_caption":
            await query.answer()
            await query.message.reply_text(
                "📝 **Send your Custom Caption Template:**\n\n"
                "Use `{caption}` placeholder for original caption.\n"
                "Example: `My Channel \n\n {caption}`"
            )
        elif data == "set_replace":
            await query.answer()
            await query.message.reply_text(
                "🔄 **Send Word Replacement Pair or Rename rule:**\n\n"
                "Format: `old_word|new_word`\n"
                "Example: `oldchannel|mychannel`"
            )
    except MessageNotModified:
        pass
    except Exception as e:
        print(f"Error in settings_callbacks: {e}")

@Client.on_message(filters.incoming & filters.text & filters.private & ~filters.command(["start", "stop", "help", "login", "logout", "settings", "batch", "dl", "adl", "cancel", "stats", "broadcast", "id", "commands", "referral", "myplan", "premium"]))
async def text_settings_listener(client: Client, message: Message):
    user_id = message.from_user.id
    text_val = message.text.strip()

    if SET_UPLOAD_STATES.get(user_id):
        del SET_UPLOAD_STATES[user_id]
        await auto_clean_chat(client, message)
        parts = text_val.split('/')
        raw_chat_id = parts[0].strip()
        topic_id = parts[1].strip() if len(parts) > 1 else None

        # Try fetching chat info from Telegram
        chat_title = "Custom Chat"
        chat_type = "Group / Channel"
        topic_suffix = f"/{topic_id}" if topic_id else "/1"
        chat_link = f"https://t.me/c/{raw_chat_id.replace('-100', '')}{topic_suffix}" if raw_chat_id.startswith("-100") else "https://t.me/"

        try:
            chat_id_num = int(raw_chat_id)
            c_info = await client.get_chat(chat_id_num)
            if c_info.title:
                chat_title = c_info.title
            if c_info.type:
                chat_type = str(c_info.type).replace("ChatType.", "").replace("_", " ").title()
            
            if c_info.username:
                chat_link = f"https://t.me/{c_info.username}{topic_suffix}"
            elif c_info.invite_link and not topic_id:
                chat_link = c_info.invite_link
        except Exception:
            pass

        upload_data = {
            "chat_id": raw_chat_id,
            "name": chat_title,
            "type": chat_type,
            "topic": topic_id if topic_id else "None",
            "link": chat_link
        }

        await update_user_setting(user_id, "set_upload", chat_title)
        await update_user_setting(user_id, "set_upload_data", upload_data)

        # Reply with Screenshot 2 Success UI
        text = (
            "**Upload Chat**\n\n"
            "✅ _Upload chat set successfully!_\n\n"
            f"**Name:** {chat_title}\n"
            f"**Type:** {chat_type}\n"
            f"**Chat ID:** `{raw_chat_id}`\n"
            f"**Topic:** {topic_id if topic_id else 'None'}\n"
            f"**Link:** [Open Chat]({chat_link})"
        )
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Change", callback_data="enter_upload_chat_id"), InlineKeyboardButton("🗑️ Remove", callback_data="remove_upload_chat")],
            [InlineKeyboardButton("Back", callback_data="open_settings")]
        ])
        await message.reply_text(text, reply_markup=buttons, disable_web_page_preview=True)
    else:
        raise ContinuePropagation

@Client.on_message(filters.photo & filters.private)
async def photo_settings_handler(client: Client, message: Message):
    user_id = message.from_user.id
    file_id = message.photo.file_id
    await save_thumbnail(user_id, file_id)
    await message.reply_text("✅ **Custom Thumbnail Saved & Enabled in Settings!**")
