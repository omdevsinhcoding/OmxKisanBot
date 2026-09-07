import os
import re
from pyrogram import Client
from pyrogram.types import Message
from helpers.progress import ProgressTracker
from database.db import get_session, get_user_settings

def parse_tg_link(link: str):
    link = link.strip()
    pattern_private_range = r"t\.me/c/(\d+)/(\d+)-(\d+)"
    pattern_private_single = r"t\.me/c/(\d+)/(\d+)"
    pattern_public_range = r"t\.me/([a-zA-Z0-9_]+)/(\d+)-(\d+)"
    pattern_public_single = r"t\.me/([a-zA-Z0-9_]+)/(\d+)"

    match = re.search(pattern_private_range, link)
    if match:
        return int(f"-100{match.group(1)}"), int(match.group(2)), int(match.group(3)), True

    match = re.search(pattern_private_single, link)
    if match:
        return int(f"-100{match.group(1)}"), int(match.group(2)), int(match.group(2)), True

    match = re.search(pattern_public_range, link)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3)), False

    match = re.search(pattern_public_single, link)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(2)), False

    return None, None, None, False


async def get_user_client(user_id: int, api_id: int, api_hash: str):
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


async def resolve_peer(client: Client, chat_id):
    """
    Call get_chat() to force Pyrogram to resolve & cache the peer.
    This is the ONLY reliable fix for PEER_ID_INVALID on in_memory sessions.
    """
    try:
        await client.get_chat(chat_id)
    except Exception as e:
        print(f"resolve_peer failed for {chat_id}: {e}")
        raise  # Re-raise so the caller knows resolution failed


async def send_to_target(client: Client, source_msg: Message, dest_chat, topic_id,
                          final_caption, file_path=None, upload_tracker=None, user_thumb=None):
    """
    Resolves the peer first, then sends the content.
    Raises on failure so caller can switch to fallback client.
    """
    # Always resolve peer before sending — this caches it in Pyrogram's session
    await resolve_peer(client, dest_chat)

    send_kwargs = {}
    if topic_id:
        send_kwargs["reply_to_message_id"] = topic_id

    if file_path:
        media_kwargs = {"caption": final_caption}
        media_kwargs.update(send_kwargs)
        if upload_tracker:
            media_kwargs["progress"] = upload_tracker.progress_callback
        if user_thumb:
            media_kwargs["thumb"] = user_thumb

        if source_msg.photo:
            await client.send_photo(dest_chat, photo=file_path, **media_kwargs)
        elif source_msg.video:
            await client.send_video(dest_chat, video=file_path, **media_kwargs)
        elif source_msg.audio:
            await client.send_audio(dest_chat, audio=file_path, **media_kwargs)
        elif source_msg.document:
            await client.send_document(dest_chat, document=file_path, **media_kwargs)
        else:
            copy_kwargs = {"caption": final_caption}
            copy_kwargs.update(send_kwargs)
            await client.copy_message(dest_chat, source_msg.chat.id, source_msg.id, **copy_kwargs)
    else:
        # Text message
        text = final_caption or source_msg.text or ""
        await client.send_message(dest_chat, text=text, **send_kwargs)


async def process_and_send_message(bot: Client, user_id: int, source_msg: Message,
                                    target_chat_id: int, status_msg: Message, user_client: Client = None):
    settings = await get_user_settings(user_id)
    custom_caption_template = settings.get("custom_caption")
    replacements = settings.get("replacements", {})
    upload_data = settings.get("set_upload_data")

    # Determine destination chat and topic
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
    topic_id = thread_id

    # Build caption
    original_caption = source_msg.caption or source_msg.text or ""
    for old_word, new_word in replacements.items():
        original_caption = original_caption.replace(old_word, new_word)
    final_caption = (
        custom_caption_template.replace("{caption}", original_caption)
        if custom_caption_template else original_caption
    )

    upload_tracker = ProgressTracker(status_msg, action_text="📤 Uploading Media")
    user_thumb = settings.get("thumbnail_id")
    if user_thumb and not os.path.exists(user_thumb):
        user_thumb = None

    # Download if media
    file_path = None
    if source_msg.media:
        tracker = ProgressTracker(status_msg, action_text="📥 Downloading Media")
        os.makedirs("downloads", exist_ok=True)
        file_path = await source_msg.download(
            file_name="downloads/",
            progress=tracker.progress_callback
        )

    try:
        # Step 1: Try with bot
        try:
            await send_to_target(bot, source_msg, dest_chat, topic_id,
                                  final_caption, file_path, upload_tracker, user_thumb)
            return
        except Exception as e:
            print(f"Bot failed for {dest_chat}: {e} — switching to user client...")

        # Step 2: Fallback to user client
        fallback_client = user_client
        owns_fallback = False
        if not fallback_client:
            from config import API_ID, API_HASH
            fallback_client = await get_user_client(user_id, API_ID, API_HASH)
            owns_fallback = True

        if fallback_client:
            try:
                await send_to_target(fallback_client, source_msg, dest_chat, topic_id,
                                      final_caption, file_path, upload_tracker, user_thumb)
            except Exception as fe:
                print(f"User client also failed for {dest_chat}: {fe}")
            finally:
                if owns_fallback:
                    try:
                        await fallback_client.stop()
                    except Exception:
                        pass
        else:
            print(f"No user client available for user {user_id} — cannot upload to {dest_chat}")
    finally:
        # Always clean up downloaded file
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
