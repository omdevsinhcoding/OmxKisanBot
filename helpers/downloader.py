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

# ══════════════════════════════════════════════════════════════
# CACHED USER CLIENTS — stay alive, no more create/destroy spam
# ══════════════════════════════════════════════════════════════
_user_clients = {}  # {user_id: Client}
_client_locks = {}  # {user_id: asyncio.Lock}


def _bot_api_call(method: str, payload: dict) -> dict:
    """Call Telegram Bot API directly via urllib."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def parse_tg_link(link: str):
    """
    Parses Telegram message link.
    Handles: single, range, and topic/forum links.
    """
    link = link.strip()

    # Private range: t.me/c/CHANNEL/[TOPIC/]START-END
    match_priv_range = re.search(r"t\.me/c/(\d+)/(?:\d+/)?(\d+)-(\d+)", link)
    if match_priv_range:
        chat_id = int(f"-100{match_priv_range.group(1)}")
        start_id = int(match_priv_range.group(2))
        end_id = int(match_priv_range.group(3))
        return chat_id, start_id, end_id, True

    # Private single: t.me/c/CHANNEL/[TOPIC/]MSG
    match_priv_single = re.search(r"t\.me/c/(\d+)/(?:\d+/)?(\d+)", link)
    if match_priv_single:
        chat_id = int(f"-100{match_priv_single.group(1)}")
        msg_id = int(match_priv_single.group(2))
        return chat_id, msg_id, msg_id, True

    # Public range: t.me/USERNAME/[TOPIC/]START-END
    match_pub_range = re.search(r"t\.me/([a-zA-Z0-9_]+)/(?:\d+/)?(\d+)-(\d+)", link)
    if match_pub_range:
        chat_id = match_pub_range.group(1)
        start_id = int(match_pub_range.group(2))
        end_id = int(match_pub_range.group(3))
        return chat_id, start_id, end_id, False

    # Public single: t.me/USERNAME/[TOPIC/]MSG
    match_pub_single = re.search(r"t\.me/([a-zA-Z0-9_]+)/(?:\d+/)?(\d+)", link)
    if match_pub_single:
        chat_id = match_pub_single.group(1)
        msg_id = int(match_pub_single.group(2))
        return chat_id, msg_id, msg_id, False

    return None, None, None, False


async def get_user_client(user_id: int, api_id: int, api_hash: str):
    """
    Get or create a cached user client. Client stays alive across requests.
    """
    if user_id not in _client_locks:
        _client_locks[user_id] = asyncio.Lock()

    async with _client_locks[user_id]:
        # Return cached client if alive
        if user_id in _user_clients:
            uc = _user_clients[user_id]
            if uc.is_connected:
                return uc
            else:
                try:
                    await uc.stop()
                except Exception:
                    pass
                del _user_clients[user_id]

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

            # Populate dialogs so Pyrogram knows about joined channels
            try:
                async for _ in user_client.get_dialogs(limit=100):
                    pass
            except Exception as e:
                print(f"Error populating dialogs for {user_id}: {e}")

            _user_clients[user_id] = user_client
            return user_client
        except Exception as e:
            print(f"Error starting user client for {user_id}: {e}")
            return None


async def stop_user_client(user_id: int):
    """Explicitly stop and remove a cached user client."""
    if user_id in _user_clients:
        try:
            await _user_clients[user_id].stop()
        except Exception:
            pass
        del _user_clients[user_id]


async def process_and_send_message(bot: Client, user_id: int, source_msg: Message, target_chat_id: int, status_msg: Message, user_client: Client = None):
    """
    Download from source (via user_client) and upload to destination (via bot).
    Based on Kisan's proven working logic + topic routing support.
    """
    tracker = ProgressTracker(status_msg, action_text="📥 Downloading Media")

    settings = await get_user_settings(user_id)
    custom_caption_template = settings.get("custom_caption")
    replacements = settings.get("replacements", {})
    upload_data = settings.get("set_upload_data")

    # Determine destination
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

    dest_chat = custom_chat_id if custom_chat_id else target_chat_id

    # Caption
    original_caption = source_msg.caption or source_msg.text or ""
    for old_word, new_word in replacements.items():
        original_caption = original_caption.replace(old_word, new_word)
    final_caption = custom_caption_template.replace("{caption}", original_caption) if custom_caption_template else original_caption

    # Get user_client if not provided
    local_user_client = user_client
    if not local_user_client:
        from config import API_ID, API_HASH
        local_user_client = await get_user_client(user_id, API_ID, API_HASH)

    user_thumb = settings.get("thumbnail_id")
    if user_thumb and not os.path.exists(user_thumb):
        user_thumb = None

    # ══════════════════════════════════════════════════════════════
    # MEDIA MESSAGES: Download via source_msg, Upload via bot
    # ══════════════════════════════════════════════════════════════
    if source_msg.media:
        file_path = None
        try:
            os.makedirs("downloads", exist_ok=True)
            # Download from source message (user_client fetched it, so it has access)
            file_path = await source_msg.download(
                file_name="downloads/",
                progress=tracker.progress_callback
            )
        except Exception as e:
            print(f"Download failed: {e}")

        if file_path and os.path.exists(file_path):
            try:
                if thread_id:
                    # ── Topic routing: Upload via Bot API with message_thread_id ──
                    fields = {"chat_id": str(dest_chat), "message_thread_id": str(thread_id)}
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
                        raise Exception(f"Bot API upload failed: {result}")
                else:
                    # ── No topic: Upload via bot using Pyrogram (matches Kisan logic) ──
                    upload_tracker = ProgressTracker(status_msg, action_text="📤 Uploading Media")
                    kwargs = {"caption": final_caption, "progress": upload_tracker.progress_callback}
                    if user_thumb:
                        kwargs["thumb"] = user_thumb

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
                print(f"Upload failed: {e}")
                # Fallback: try copy_message via bot (works for public sources)
                try:
                    await bot.copy_message(dest_chat, source_msg.chat.id, source_msg.id)
                except Exception as e2:
                    print(f"Fallback copy also failed: {e2}")
                    raise Exception(f"Upload failed: {e}")
            finally:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            return

        # Download failed — try copy_message as fallback
        try:
            await bot.copy_message(dest_chat, source_msg.chat.id, source_msg.id)
            return
        except Exception:
            pass

        # Try user_client copy_message
        if local_user_client:
            try:
                await local_user_client.copy_message(dest_chat, source_msg.chat.id, source_msg.id)
                return
            except Exception:
                pass

        raise Exception(f"Media download+upload failed for dest={dest_chat}")

    # ══════════════════════════════════════════════════════════════
    # NON-MEDIA: Location, Contact, Sticker (by file_id), etc.
    # ══════════════════════════════════════════════════════════════
    if thread_id:
        sent = False
        try:
            if source_msg.location and not source_msg.venue:
                result = await asyncio.to_thread(_bot_api_call, "sendLocation", {
                    "chat_id": dest_chat, "message_thread_id": thread_id,
                    "latitude": source_msg.location.latitude, "longitude": source_msg.location.longitude,
                })
                sent = result.get("ok", False)
            elif source_msg.venue:
                payload = {
                    "chat_id": dest_chat, "message_thread_id": thread_id,
                    "latitude": source_msg.venue.location.latitude, "longitude": source_msg.venue.location.longitude,
                    "title": source_msg.venue.title, "address": source_msg.venue.address,
                }
                result = await asyncio.to_thread(_bot_api_call, "sendVenue", payload)
                sent = result.get("ok", False)
            elif source_msg.contact:
                payload = {
                    "chat_id": dest_chat, "message_thread_id": thread_id,
                    "phone_number": source_msg.contact.phone_number,
                    "first_name": source_msg.contact.first_name or "",
                }
                if source_msg.contact.last_name:
                    payload["last_name"] = source_msg.contact.last_name
                result = await asyncio.to_thread(_bot_api_call, "sendContact", payload)
                sent = result.get("ok", False)
            elif source_msg.dice:
                result = await asyncio.to_thread(_bot_api_call, "sendDice", {
                    "chat_id": dest_chat, "message_thread_id": thread_id,
                    "emoji": source_msg.dice.emoji,
                })
                sent = result.get("ok", False)
        except Exception as e:
            print(f"Bot API special type failed: {e}")

        if sent:
            return

    # ══════════════════════════════════════════════════════════════
    # TEXT MESSAGES
    # ══════════════════════════════════════════════════════════════
    if source_msg.text or final_caption:
        text_to_send = final_caption or source_msg.text or ""
        if thread_id:
            try:
                result = await asyncio.to_thread(_bot_api_call, "sendMessage", {
                    "chat_id": dest_chat, "text": text_to_send, "message_thread_id": thread_id,
                })
                if result.get("ok"):
                    return
            except Exception as e:
                print(f"Bot API sendMessage failed: {e}")

        # Pyrogram fallback (no topic)
        try:
            await bot.send_message(dest_chat, text=text_to_send)
            return
        except Exception as e:
            print(f"Pyrogram send_message failed: {e}")

        if local_user_client:
            try:
                await local_user_client.send_message(dest_chat, text=text_to_send)
                return
            except Exception as e:
                print(f"User client send_message failed: {e}")

    # ══════════════════════════════════════════════════════════════
    # LAST RESORT: copy_message (for anything we couldn't handle above)
    # ══════════════════════════════════════════════════════════════
    try:
        await bot.copy_message(dest_chat, source_msg.chat.id, source_msg.id)
        return
    except Exception:
        pass

    if local_user_client:
        try:
            await local_user_client.copy_message(dest_chat, source_msg.chat.id, source_msg.id)
            return
        except Exception:
            pass

    raise Exception(f"All strategies failed for dest={dest_chat}")
