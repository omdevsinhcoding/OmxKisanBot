import os
import re
import json
import asyncio
import urllib.request
from pyrogram import Client
from pyrogram.types import Message
from helpers.progress import ProgressTracker
from database.db import get_session, get_thumbnail, get_caption, get_replacements, get_user_settings
from config import BOT_TOKEN


def _bot_api_upload(method: str, fields: dict, file_field: str, file_path: str) -> dict:
    """Upload a file to Telegram Bot API using multipart/form-data."""
    import mimetypes
    boundary = "----PythonBotUpload"
    body = b""
    
    for key, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    
    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: {mime_type}\r\n\r\n".encode()
    with open(file_path, "rb") as f:
        body += f.read()
    body += f"\r\n--{boundary}--\r\n".encode()

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _bot_api_call(method: str, payload: dict) -> dict:
    """Call Telegram Bot API directly via urllib."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_tg_link(link: str):
    """
    Parses Telegram message link. Exact Kisan logic.
    """
    link = link.strip()
    pattern_private_range = r"t\.me/c/(\d+)/(\d+)-(\d+)"
    pattern_private_single = r"t\.me/c/(\d+)/(\d+)"
    pattern_public_range = r"t\.me/([a-zA-Z0-9_]+)/(\d+)-(\d+)"
    pattern_public_single = r"t\.me/([a-zA-Z0-9_]+)/(\d+)"
    
    match_priv_range = re.search(pattern_private_range, link)
    if match_priv_range:
        chat_id = int(f"-100{match_priv_range.group(1)}")
        start_id = int(match_priv_range.group(2))
        end_id = int(match_priv_range.group(3))
        return chat_id, start_id, end_id, True

    match_priv_single = re.search(pattern_private_single, link)
    if match_priv_single:
        chat_id = int(f"-100{match_priv_single.group(1)}")
        msg_id = int(match_priv_single.group(2))
        return chat_id, msg_id, msg_id, True

    match_pub_range = re.search(pattern_public_range, link)
    if match_pub_range:
        chat_id = match_pub_range.group(1)
        start_id = int(match_pub_range.group(2))
        end_id = int(match_pub_range.group(3))
        return chat_id, start_id, end_id, False

    match_pub_single = re.search(pattern_public_single, link)
    if match_pub_single:
        chat_id = match_pub_single.group(1)
        msg_id = int(match_pub_single.group(2))
        return chat_id, msg_id, msg_id, False

    return None, None, None, False


async def get_user_client(user_id: int, api_id: int, api_hash: str):
    """Exact Kisan logic — fresh client each time."""
    session_str = await get_session(user_id)
    if not session_str:
        return None
    try:
        user_client = Client(
            f"user_{user_id}",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_str,
            in_memory=True
        )
        await user_client.start()
        return user_client
    except Exception as e:
        print(f"Error starting user client for {user_id}: {e}")
        return None


async def process_and_send_message(bot: Client, user_id: int, source_msg: Message, target_chat_id: int, status_msg: Message):
    """Exact Kisan logic + Bot API topic routing."""
    tracker = ProgressTracker(status_msg, action_text="📥 Downloading Media")
    
    settings = await get_user_settings(user_id)
    custom_caption_template = settings.get("custom_caption")
    replacements = settings.get("replacements", {})
    upload_data = settings.get("set_upload_data")

    # Determine destination targets [(chat_id, message_thread_id)]
    targets = []
    custom_chat_id = None
    thread_id = None

    if upload_data and isinstance(upload_data, dict):
        raw_chat = upload_data.get("chat_id")
        if raw_chat:
            try:
                custom_chat_id = int(raw_chat) if str(raw_chat).replace('-', '').isdigit() else raw_chat
                topic = upload_data.get("topic")
                if topic and str(topic).strip() not in ["None", "", "0"]:
                    thread_id = int(topic)
            except Exception as e:
                print(f"Error parsing set_upload_data: {e}")

    if custom_chat_id:
        targets.append((custom_chat_id, thread_id))
    else:
        targets.append((target_chat_id, None))

    # Calculate caption
    original_caption = source_msg.caption or source_msg.text or ""
    for old_word, new_word in replacements.items():
        original_caption = original_caption.replace(old_word, new_word)

    final_caption = custom_caption_template.replace("{caption}", original_caption) if custom_caption_template else original_caption

    # Check for media
    if source_msg.media:
        os.makedirs("downloads", exist_ok=True)
        file_path = await source_msg.download(
            file_name="downloads/",
            progress=tracker.progress_callback
        )

        upload_tracker = ProgressTracker(status_msg, action_text="📤 Uploading Media")
        user_thumb = settings.get("thumbnail_id")
        if user_thumb and not os.path.exists(user_thumb):
            user_thumb = None

        for dest_chat, topic_id in targets:
            if topic_id:
                # Upload via Bot API with message_thread_id for topic routing
                try:
                    fields = {"chat_id": str(dest_chat), "message_thread_id": str(topic_id)}
                    if final_caption:
                        fields["caption"] = final_caption

                    api_method, file_field = "sendDocument", "document"
                    if source_msg.photo:
                        api_method, file_field = "sendPhoto", "photo"
                    elif source_msg.video:
                        api_method, file_field = "sendVideo", "video"
                    elif source_msg.audio:
                        api_method, file_field = "sendAudio", "audio"
                    elif source_msg.document:
                        api_method, file_field = "sendDocument", "document"
                    elif source_msg.animation:
                        api_method, file_field = "sendAnimation", "animation"
                    elif source_msg.voice:
                        api_method, file_field = "sendVoice", "voice"
                    elif source_msg.video_note:
                        api_method, file_field = "sendVideoNote", "video_note"
                        fields.pop("caption", None)
                    elif source_msg.sticker:
                        api_method, file_field = "sendSticker", "sticker"
                        fields.pop("caption", None)

                    result = await asyncio.to_thread(_bot_api_upload, api_method, fields, file_field, file_path)
                    if not result.get("ok"):
                        print(f"Bot API upload failed: {result}")
                except Exception as e:
                    print(f"Failed uploading media via Bot API to {dest_chat}/{topic_id}: {e}")
            else:
                # Exact Kisan logic — upload via bot using Pyrogram
                kwargs = {"caption": final_caption, "progress": upload_tracker.progress_callback}
                if user_thumb:
                    kwargs["thumb"] = user_thumb

                try:
                    if source_msg.photo:
                        await bot.send_photo(dest_chat, photo=file_path, **kwargs)
                    elif source_msg.video:
                        await bot.send_video(dest_chat, video=file_path, **kwargs)
                    elif source_msg.audio:
                        await bot.send_audio(dest_chat, audio=file_path, **kwargs)
                    elif source_msg.document:
                        await bot.send_document(dest_chat, document=file_path, **kwargs)
                    elif source_msg.animation:
                        await bot.send_animation(dest_chat, animation=file_path, **kwargs)
                    elif source_msg.voice:
                        await bot.send_voice(dest_chat, voice=file_path, caption=final_caption)
                    elif source_msg.video_note:
                        await bot.send_video_note(dest_chat, video_note=file_path)
                    elif source_msg.sticker:
                        await bot.send_sticker(dest_chat, sticker=file_path)
                    else:
                        await bot.send_document(dest_chat, document=file_path, **kwargs)
                except Exception as e:
                    # Kisan's PEER_ID_INVALID fallback
                    if "PEER_ID_INVALID" in str(e) and str(dest_chat).startswith("-") and not str(dest_chat).startswith("-100"):
                        new_dest = int(f"-100{str(dest_chat)[1:]}")
                        try:
                            if source_msg.photo:
                                await bot.send_photo(new_dest, photo=file_path, **kwargs)
                            elif source_msg.video:
                                await bot.send_video(new_dest, video=file_path, **kwargs)
                            elif source_msg.audio:
                                await bot.send_audio(new_dest, audio=file_path, **kwargs)
                            elif source_msg.document:
                                await bot.send_document(new_dest, document=file_path, **kwargs)
                            else:
                                await bot.send_document(new_dest, document=file_path, **kwargs)
                        except Exception as e2:
                            print(f"Failed uploading media to fallback ID {new_dest}: {e2}")
                    else:
                        print(f"Failed uploading media to {dest_chat}: {e}")

        if os.path.exists(file_path):
            os.remove(file_path)
    else:
        # Text message
        for dest_chat, topic_id in targets:
            try:
                if topic_id:
                    await asyncio.to_thread(_bot_api_call, "sendMessage", {
                        "chat_id": dest_chat,
                        "text": final_caption or source_msg.text or "",
                        "message_thread_id": topic_id,
                    })
                else:
                    await bot.send_message(dest_chat, text=final_caption or source_msg.text or "")
            except Exception as e:
                if "PEER_ID_INVALID" in str(e) and str(dest_chat).startswith("-") and not str(dest_chat).startswith("-100"):
                    new_dest = int(f"-100{str(dest_chat)[1:]}")
                    try:
                        await bot.send_message(new_dest, text=final_caption or source_msg.text or "")
                    except Exception as e2:
                        print(f"Failed sending text to fallback ID {new_dest}: {e2}")
                else:
                    print(f"Failed sending text to {dest_chat}: {e}")
