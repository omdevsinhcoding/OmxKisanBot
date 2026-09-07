import os
import re
import asyncio
from pyrogram import Client
from pyrogram.types import Message
from helpers.progress import ProgressTracker
from database.db import get_session, get_thumbnail, get_caption, get_replacements, get_user_settings

def parse_tg_link(link: str):
    """
    Parses Telegram message link.
    Supports:
    - https://t.me/c/1234567890/123 -> private chat single (-1001234567890, 123, 123, True)
    - https://t.me/c/1234567890/123-125 -> private chat range (-1001234567890, 123, 125, True)
    - https://t.me/channel_username/123 -> public chat single ("channel_username", 123, 123, False)
    - https://t.me/channel_username/123-125 -> public chat range ("channel_username", 123, 125, False)
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
    tracker = ProgressTracker(status_msg, action_text="📥 Downloading Media")
    
    settings = await get_user_settings(user_id)
    custom_caption_template = settings.get("custom_caption")
    replacements = settings.get("replacements", {})
    send_pm = settings.get("send_pm", "On")
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
            kwargs = {"caption": final_caption, "progress": upload_tracker.progress_callback}
            if user_thumb:
                kwargs["thumb"] = user_thumb
            if topic_id:
                kwargs["reply_to_message_id"] = topic_id

            try:
                if source_msg.photo:
                    await bot.send_photo(dest_chat, photo=file_path, **kwargs)
                elif source_msg.video:
                    await bot.send_video(dest_chat, video=file_path, **kwargs)
                elif source_msg.audio:
                    await bot.send_audio(dest_chat, audio=file_path, **kwargs)
                elif source_msg.document:
                    await bot.send_document(dest_chat, document=file_path, **kwargs)
                else:
                    copy_kwargs = {"caption": final_caption}
                    if topic_id:
                        copy_kwargs["reply_to_message_id"] = topic_id
                    await bot.copy_message(dest_chat, source_msg.chat.id, source_msg.id, **copy_kwargs)
            except Exception as e:
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
                            copy_kwargs = {"caption": final_caption}
                            if topic_id:
                                copy_kwargs["reply_to_message_id"] = topic_id
                            await bot.copy_message(new_dest, source_msg.chat.id, source_msg.id, **copy_kwargs)
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
                kwargs = {}
                if topic_id:
                    kwargs["reply_to_message_id"] = topic_id
                await bot.send_message(dest_chat, text=final_caption or source_msg.text, **kwargs)
            except Exception as e:
                if "PEER_ID_INVALID" in str(e) and str(dest_chat).startswith("-") and not str(dest_chat).startswith("-100"):
                    new_dest = int(f"-100{str(dest_chat)[1:]}")
                    try:
                        await bot.send_message(new_dest, text=final_caption or source_msg.text, **kwargs)
                    except Exception as e2:
                        print(f"Failed sending text to fallback ID {new_dest}: {e2}")
                else:
                    print(f"Failed sending text to {dest_chat}: {e}")

