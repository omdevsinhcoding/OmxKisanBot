import os
import re
import asyncio
from pyrogram import Client, raw
from pyrogram.types import Message
from helpers.progress import ProgressTracker
from database.db import get_session, get_thumbnail, get_caption, get_replacements, get_user_settings


async def force_resolve_peer(client: Client, chat_id):
    """
    Force-resolve a chat_id into Pyrogram's internal peer cache.
    This bypasses the PEER_ID_INVALID error by using Pyrogram's raw API
    to ask Telegram's server directly for the channel info.
    
    When the bot/user IS a member of the channel/group, Telegram returns 
    the real data even with access_hash=0, and Pyrogram caches it automatically.
    """
    # Method 1: Try normal resolve first (works if peer is already cached)
    try:
        await client.resolve_peer(chat_id)
        return True
    except Exception:
        pass

    # Method 2: Try get_dialogs to populate cache (works for user accounts)
    try:
        async for dialog in client.get_dialogs(limit=200):
            if dialog.chat and dialog.chat.id == chat_id:
                return True
    except Exception:
        pass

    # Method 3: Try normal resolve again (get_dialogs may have cached it)
    try:
        await client.resolve_peer(chat_id)
        return True
    except Exception:
        pass

    # Method 4: Raw API - channels.GetChannels with access_hash=0
    # Works when bot/user is a member; Telegram ignores invalid access_hash for members
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
            print(f"Raw GetChannels also failed for {chat_id}: {e}")

    return False

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
        
        # Proactively populate the in-memory peer cache to prevent PEER_ID_INVALID
        try:
            async for _ in user_client.get_dialogs(limit=100):
                pass
        except Exception as e:
            print(f"Error populating dialogs for {user_id}: {e}")
            
        return user_client
    except Exception as e:
        print(f"Error starting user client for {user_id}: {e}")
        return None

async def process_and_send_message(bot: Client, user_id: int, source_msg: Message, target_chat_id: int, status_msg: Message, user_client: Client = None):
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

    # --- RESOLVE PEERS BEFORE SENDING ---
    # This is the critical step: we must force both bot and user_client to
    # recognize the destination chat BEFORE we try to send anything.
    # Without this, Pyrogram throws PEER_ID_INVALID because its internal
    # cache doesn't know about the chat yet.
    
    # Get or create the user_client for fallback
    local_user_client = user_client
    created_local = False
    if not local_user_client:
        from config import API_ID, API_HASH
        local_user_client = await get_user_client(user_id, API_ID, API_HASH)
        created_local = True

    for dest_chat, topic_id in targets:
        # Determine which client can actually reach the destination
        send_client = None
        
        # Try bot first
        bot_resolved = await force_resolve_peer(bot, dest_chat)
        if bot_resolved:
            send_client = bot
            print(f"✅ Bot resolved peer {dest_chat} successfully")
        
        # Try user_client if bot failed
        if not send_client and local_user_client:
            user_resolved = await force_resolve_peer(local_user_client, dest_chat)
            if user_resolved:
                send_client = local_user_client
                print(f"✅ User Client resolved peer {dest_chat} successfully")
        
        if not send_client:
            print(f"❌ Neither bot nor user client could resolve peer {dest_chat}")
            continue

        # Now send using whichever client resolved the peer
        kwargs_base = {}
        if topic_id:
            kwargs_base["reply_to_message_id"] = topic_id

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

            kwargs = {"caption": final_caption, "progress": upload_tracker.progress_callback, **kwargs_base}
            if user_thumb:
                kwargs["thumb"] = user_thumb

            try:
                if source_msg.photo:
                    await send_client.send_photo(dest_chat, photo=file_path, **kwargs)
                elif source_msg.video:
                    await send_client.send_video(dest_chat, video=file_path, **kwargs)
                elif source_msg.audio:
                    await send_client.send_audio(dest_chat, audio=file_path, **kwargs)
                elif source_msg.document:
                    await send_client.send_document(dest_chat, document=file_path, **kwargs)
                else:
                    copy_kwargs = {"caption": final_caption, **kwargs_base}
                    await send_client.copy_message(dest_chat, source_msg.chat.id, source_msg.id, **copy_kwargs)
            except Exception as e:
                print(f"❌ Failed uploading media to {dest_chat}: {e}")

            if os.path.exists(file_path):
                os.remove(file_path)
        else:
            # Text message
            try:
                await send_client.send_message(dest_chat, text=final_caption or source_msg.text, **kwargs_base)
            except Exception as e:
                print(f"❌ Failed sending text to {dest_chat}: {e}")

    # Cleanup: stop user_client only if we created it locally
    if created_local and local_user_client:
        try:
            await local_user_client.stop()
        except Exception:
            pass


