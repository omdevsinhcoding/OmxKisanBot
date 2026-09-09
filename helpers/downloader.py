import os
import re
import json
import asyncio
import urllib.request
from pyrogram import Client, raw
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


async def force_resolve_peer(client: Client, chat_id):
    """
    Force-resolve a chat_id into Pyrogram's internal peer cache.
    """
    try:
        await client.resolve_peer(chat_id)
        return True
    except Exception:
        pass

    try:
        async for dialog in client.get_dialogs(limit=200):
            if dialog.chat and dialog.chat.id == chat_id:
                return True
    except Exception:
        pass

    try:
        await client.resolve_peer(chat_id)
        return True
    except Exception:
        pass

    str_id = str(chat_id)
    if str_id.startswith("-100"):
        channel_id = int(str_id[4:])
        try:
            await client.invoke(
                raw.functions.channels.GetChannels(
                    id=[raw.types.InputChannel(
                        channel_id=channel_id,
                        access_hash=0
                    )]
                )
            )
            return True
        except Exception as e:
            print(f"Raw GetChannels failed for {chat_id}: {e}")

    return False

def parse_tg_link(link: str):
    """
    Parses Telegram message link.
    Handles: single, range, and topic/forum links.
    Uses (?:\d+/)? to optionally skip topic ID in forum links.
    """
    link = link.strip()

    # ── Private range: t.me/c/CHANNEL/[TOPIC/]START-END ──
    match_priv_range = re.search(r"t\.me/c/(\d+)/(?:\d+/)?(\d+)-(\d+)", link)
    if match_priv_range:
        chat_id = int(f"-100{match_priv_range.group(1)}")
        start_id = int(match_priv_range.group(2))
        end_id = int(match_priv_range.group(3))
        return chat_id, start_id, end_id, True

    # ── Private single: t.me/c/CHANNEL/[TOPIC/]MSG ──
    match_priv_single = re.search(r"t\.me/c/(\d+)/(?:\d+/)?(\d+)", link)
    if match_priv_single:
        chat_id = int(f"-100{match_priv_single.group(1)}")
        msg_id = int(match_priv_single.group(2))
        return chat_id, msg_id, msg_id, True

    # ── Public range: t.me/USERNAME/[TOPIC/]START-END ──
    match_pub_range = re.search(r"t\.me/([a-zA-Z0-9_]+)/(?:\d+/)?(\d+)-(\d+)", link)
    if match_pub_range:
        chat_id = match_pub_range.group(1)
        start_id = int(match_pub_range.group(2))
        end_id = int(match_pub_range.group(3))
        return chat_id, start_id, end_id, False

    # ── Public single: t.me/USERNAME/[TOPIC/]MSG ──
    match_pub_single = re.search(r"t\.me/([a-zA-Z0-9_]+)/(?:\d+/)?(\d+)", link)
    if match_pub_single:
        chat_id = match_pub_single.group(1)
        msg_id = int(match_pub_single.group(2))
        return chat_id, msg_id, msg_id, False

    return None, None, None, False


async def get_user_client(user_id: int, api_id: int, api_hash: str):
    """
    Get or create a cached user client. Client stays alive across requests.
    No more create/destroy per message — fixes SQLite closed DB crash.
    """
    # Per-user lock to prevent double-start
    if user_id not in _client_locks:
        _client_locks[user_id] = asyncio.Lock()

    async with _client_locks[user_id]:
        # Return cached client if alive
        if user_id in _user_clients:
            uc = _user_clients[user_id]
            if uc.is_connected:
                return uc
            else:
                # Dead client — remove and recreate
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
                # no_updates removed — it was blocking peer resolution for channels
                # SQLite crash is already fixed by client caching (no more stop/start per request)
            )
            await user_client.start()

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
    """
    Explicitly stop and remove a cached user client.
    Only call on /logout or session invalidation.
    """
    if user_id in _user_clients:
        try:
            await _user_clients[user_id].stop()
        except Exception:
            pass
        del _user_clients[user_id]


async def fetch_message_with_retry(client: Client, chat_id, msg_id, retries=3, timeout=30):
    """
    Fetch a message from private channel with retry.
    Matches original repo logic: try -100 format, then - format, then refresh dialogs.
    """
    # Populate dialogs first (like original)
    try:
        async for _ in client.get_dialogs(limit=50):
            pass
    except Exception:
        pass

    # Build chat_id variants to try (like original get_msg)
    str_id = str(chat_id)
    ids_to_try = []

    if str_id.startswith('-100'):
        ids_to_try.append(int(str_id))           # -100xxx format
        base = str_id[4:]                          # remove -100
        ids_to_try.append(int(f"-{base}"))         # -xxx format
    elif str_id.startswith('-'):
        ids_to_try.append(int(str_id))             # -xxx format
        base = str_id[1:]                           # remove -
        ids_to_try.append(int(f"-100{base}"))       # -100xxx format
    else:
        ids_to_try.append(chat_id)                  # as-is
        if str_id.isdigit():
            ids_to_try.append(int(f"-100{str_id}"))
            ids_to_try.append(int(f"-{str_id}"))

    # Try each format
    for cid in ids_to_try:
        try:
            result = await asyncio.wait_for(
                client.get_messages(cid, msg_id),
                timeout=timeout
            )
            if result and not getattr(result, "empty", False):
                return result
        except Exception as e:
            print(f"Fetch attempt with {cid} failed: {e}")

    # Final fallback — refresh dialogs with higher limit and retry original
    try:
        async for _ in client.get_dialogs(limit=200):
            pass
        result = await asyncio.wait_for(
            client.get_messages(chat_id, msg_id),
            timeout=timeout
        )
        if result and not getattr(result, "empty", False):
            return result
    except Exception as e:
        print(f"Final fallback fetch failed: {e}")

    return None


async def process_and_send_message(bot: Client, user_id: int, source_msg: Message, target_chat_id: int, status_msg: Message, user_client: Client = None):
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

    # Get or create user_client (cached — no new client created if already exists)
    local_user_client = user_client
    created_local = False
    if not local_user_client:
        from config import API_ID, API_HASH
        local_user_client = await get_user_client(user_id, API_ID, API_HASH)
        created_local = True

    # Build list of clients
    clients_to_try = []
    if local_user_client:
        clients_to_try.append(local_user_client)
    clients_to_try.append(bot)

    sent_ok = False

    # ══════════════════════════════════════════════════════════════
    # STRATEGY 1: User client copy_message (works for ALL msg types)
    #   - user_client has access to both source and dest
    #   - If no topic, this is the fastest and best method
    #   - If topic is set, messages go to General (no topic kwarg)
    #     so we only use this when there's NO topic
    # ══════════════════════════════════════════════════════════════
    if not thread_id:
        for c in clients_to_try:
            try:
                await force_resolve_peer(c, dest_chat)
                await force_resolve_peer(c, source_msg.chat.id)
                copy_kwargs = {}
                if source_msg.media and source_msg.caption is not None:
                    copy_kwargs["caption"] = final_caption
                await c.copy_message(dest_chat, source_msg.chat.id, source_msg.id, **copy_kwargs)
                sent_ok = True
                break
            except Exception as e:
                print(f"Pyrogram copy_message failed ({type(c).__name__}): {e}")

    # ══════════════════════════════════════════════════════════════
    # STRATEGY 2: Download + Bot API upload (for topic routing)
    #   - Download file via user_client (has source access)
    #   - Upload via Bot API with message_thread_id (topic routing)
    # ══════════════════════════════════════════════════════════════
    if not sent_ok and source_msg.media:
        try:
            os.makedirs("downloads", exist_ok=True)
            file_path = await source_msg.download(
                file_name="downloads/",
                progress=tracker.progress_callback
            )
            if file_path and os.path.exists(file_path):
                if thread_id:
                    # Upload via Bot API with message_thread_id
                    fields = {"chat_id": str(dest_chat), "message_thread_id": str(thread_id)}
                    if final_caption:
                        fields["caption"] = final_caption

                    api_method = None
                    file_field = None
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
                    else:
                        api_method, file_field = "sendDocument", "document"

                    result = await asyncio.to_thread(_bot_api_upload, api_method, fields, file_field, file_path)
                    if result.get("ok"):
                        sent_ok = True
                else:
                    # No topic — upload via Pyrogram (faster for large files with progress)
                    send_client = None
                    for c in clients_to_try:
                        if await force_resolve_peer(c, dest_chat):
                            send_client = c
                            break
                    
                    if send_client:
                        up_tracker = ProgressTracker(status_msg, action_text="📤 Uploading Media")
                        kwargs = {"caption": final_caption, "progress": up_tracker.progress_callback}

                        if source_msg.photo:
                            await send_client.send_photo(dest_chat, photo=file_path, **kwargs)
                        elif source_msg.video:
                            await send_client.send_video(dest_chat, video=file_path, **kwargs)
                        elif source_msg.audio:
                            await send_client.send_audio(dest_chat, audio=file_path, **kwargs)
                        elif source_msg.document:
                            await send_client.send_document(dest_chat, document=file_path, **kwargs)
                        elif source_msg.animation:
                            await send_client.send_animation(dest_chat, animation=file_path, **kwargs)
                        elif source_msg.voice:
                            await send_client.send_voice(dest_chat, voice=file_path, caption=final_caption)
                        elif source_msg.video_note:
                            await send_client.send_video_note(dest_chat, video_note=file_path)
                        elif source_msg.sticker:
                            await send_client.send_sticker(dest_chat, sticker=file_path)
                        else:
                            await send_client.send_document(dest_chat, document=file_path, **kwargs)
                        sent_ok = True

                if os.path.exists(file_path):
                    os.remove(file_path)
        except Exception as e:
            print(f"Download+upload failed: {e}")

    # ══════════════════════════════════════════════════════════════
    # STRATEGY 2.5: Non-downloadable types via Bot API (location, contact, sticker, etc.)
    #   When topic is set, use Bot API methods with message_thread_id
    # ══════════════════════════════════════════════════════════════
    if not sent_ok and thread_id:
        try:
            # Location
            if source_msg.location and not source_msg.venue:
                result = await asyncio.to_thread(_bot_api_call, "sendLocation", {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "latitude": source_msg.location.latitude,
                    "longitude": source_msg.location.longitude,
                })
                if result.get("ok"):
                    sent_ok = True

            # Venue
            elif source_msg.venue:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "latitude": source_msg.venue.location.latitude,
                    "longitude": source_msg.venue.location.longitude,
                    "title": source_msg.venue.title,
                    "address": source_msg.venue.address,
                }
                if source_msg.venue.foursquare_id:
                    payload["foursquare_id"] = source_msg.venue.foursquare_id
                result = await asyncio.to_thread(_bot_api_call, "sendVenue", payload)
                if result.get("ok"):
                    sent_ok = True

            # Contact
            elif source_msg.contact:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "phone_number": source_msg.contact.phone_number,
                    "first_name": source_msg.contact.first_name or "",
                }
                if source_msg.contact.last_name:
                    payload["last_name"] = source_msg.contact.last_name
                result = await asyncio.to_thread(_bot_api_call, "sendContact", payload)
                if result.get("ok"):
                    sent_ok = True

            # Sticker (use file_id, no need to download)
            elif source_msg.sticker:
                result = await asyncio.to_thread(_bot_api_call, "sendSticker", {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "sticker": source_msg.sticker.file_id,
                })
                if result.get("ok"):
                    sent_ok = True

            # Dice
            elif source_msg.dice:
                result = await asyncio.to_thread(_bot_api_call, "sendDice", {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "emoji": source_msg.dice.emoji,
                })
                if result.get("ok"):
                    sent_ok = True

            # Poll
            elif source_msg.poll:
                # Polls can't be easily re-sent, try forwarding
                pass

            # Animation/GIF (use file_id)
            elif source_msg.animation:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "animation": source_msg.animation.file_id,
                }
                if final_caption:
                    payload["caption"] = final_caption
                result = await asyncio.to_thread(_bot_api_call, "sendAnimation", payload)
                if result.get("ok"):
                    sent_ok = True

            # Photo (use file_id)
            elif source_msg.photo:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "photo": source_msg.photo.file_id,
                }
                if final_caption:
                    payload["caption"] = final_caption
                result = await asyncio.to_thread(_bot_api_call, "sendPhoto", payload)
                if result.get("ok"):
                    sent_ok = True

            # Video (use file_id)
            elif source_msg.video:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "video": source_msg.video.file_id,
                }
                if final_caption:
                    payload["caption"] = final_caption
                result = await asyncio.to_thread(_bot_api_call, "sendVideo", payload)
                if result.get("ok"):
                    sent_ok = True

            # Document (use file_id)
            elif source_msg.document:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "document": source_msg.document.file_id,
                }
                if final_caption:
                    payload["caption"] = final_caption
                result = await asyncio.to_thread(_bot_api_call, "sendDocument", payload)
                if result.get("ok"):
                    sent_ok = True

            # Audio (use file_id)
            elif source_msg.audio:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "audio": source_msg.audio.file_id,
                }
                if final_caption:
                    payload["caption"] = final_caption
                result = await asyncio.to_thread(_bot_api_call, "sendAudio", payload)
                if result.get("ok"):
                    sent_ok = True

            # Voice (use file_id)
            elif source_msg.voice:
                payload = {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "voice": source_msg.voice.file_id,
                }
                if final_caption:
                    payload["caption"] = final_caption
                result = await asyncio.to_thread(_bot_api_call, "sendVoice", payload)
                if result.get("ok"):
                    sent_ok = True

            # Video Note (use file_id)
            elif source_msg.video_note:
                result = await asyncio.to_thread(_bot_api_call, "sendVideoNote", {
                    "chat_id": dest_chat,
                    "message_thread_id": thread_id,
                    "video_note": source_msg.video_note.file_id,
                })
                if result.get("ok"):
                    sent_ok = True

        except Exception as e:
            print(f"Bot API special type send failed: {e}")

    # ══════════════════════════════════════════════════════════════
    # STRATEGY 3: Text message
    # ══════════════════════════════════════════════════════════════
    if not sent_ok and (source_msg.text or final_caption):
        if thread_id:
            try:
                result = await asyncio.to_thread(_bot_api_call, "sendMessage", {
                    "chat_id": dest_chat,
                    "text": final_caption or source_msg.text or "",
                    "message_thread_id": thread_id,
                })
                if result.get("ok"):
                    sent_ok = True
            except Exception as e:
                print(f"Bot API sendMessage failed: {e}")
        
        if not sent_ok:
            for c in clients_to_try:
                try:
                    await force_resolve_peer(c, dest_chat)
                    await c.send_message(dest_chat, text=final_caption or source_msg.text or "")
                    sent_ok = True
                    break
                except Exception as e:
                    print(f"Pyrogram send_message failed ({type(c).__name__}): {e}")

    # ══════════════════════════════════════════════════════════════
    # STRATEGY 4: Last resort — copy without topic (at least content is saved)
    # ══════════════════════════════════════════════════════════════
    if not sent_ok:
        for c in clients_to_try:
            try:
                await force_resolve_peer(c, dest_chat)
                await force_resolve_peer(c, source_msg.chat.id)
                await c.copy_message(dest_chat, source_msg.chat.id, source_msg.id)
                sent_ok = True
                break
            except Exception as e:
                print(f"Last resort copy failed ({type(c).__name__}): {e}")

    if not sent_ok:
        raise Exception(f"All strategies failed for dest={dest_chat}")

    # NOTE: No cleanup here — cached clients stay alive
