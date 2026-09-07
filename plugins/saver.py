from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, CallbackQuery
from helpers.downloader import parse_tg_link, get_user_client, process_and_send_message
from helpers.cleaner import auto_clean_chat
from helpers.progress import handle_refresh_callback
from config import API_ID, API_HASH

@Client.on_callback_query(filters.regex(r"^refresh_prog_"))
async def refresh_progress_listener(client: Client, query: CallbackQuery):
    await handle_refresh_callback(client, query)

@Client.on_message(filters.incoming & filters.text & filters.private & ~filters.command(["start", "stop", "help", "login", "logout", "settings", "batch", "dl", "adl", "cancel", "stats", "broadcast", "id", "commands", "referral", "myplan", "premium"]))
async def single_post_saver(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    link = message.text.strip()

    chat_id, start_id, end_id, is_private = parse_tg_link(link)
    if not chat_id or not start_id:
        raise ContinuePropagation  # Not a valid Telegram link

    status = await message.reply_text("🔎 **Fetching Message...**")

    user_client = None
    try:
        if is_private:
            user_client = await get_user_client(user_id, API_ID, API_HASH)
            if not user_client:
                return await status.edit_text(
                    "🔐 **Private Channel Link Detected!**\n\n"
                    "Please login to your account using `/login` to download content from private channels."
                )

        fetch_client = user_client if is_private else client

        if start_id == end_id:
            # Single Post
            source_msg = None
            try:
                source_msg = await fetch_client.get_messages(chat_id, start_id)
            except Exception:
                if not is_private and not user_client:
                    user_client = await get_user_client(user_id, API_ID, API_HASH)
                    if user_client:
                        source_msg = await user_client.get_messages(chat_id, start_id)

            if not source_msg or source_msg.empty:
                return await status.edit_text("❌ **Could not fetch message!** Make sure link is correct and bot/user has access.")

            await process_and_send_message(client, user_id, source_msg, message.chat.id, status, user_client)
            await status.edit_text("✅ **Task Complete!**")
        else:
            import time
            start_time = time.time()
            success_count = 0
            failed_count = 0
            skipped_count = 0

            total_posts = (end_id - start_id) + 1
            await status.edit_text(f"🚀 **Starting Range Extraction ({total_posts} posts)...**")
            for current_id in range(start_id, end_id + 1):
                try:
                    source_msg = await fetch_client.get_messages(chat_id, current_id)
                    if source_msg and not source_msg.empty:
                        sub_status = await message.reply_text(f"🔄 **Processing Post {current_id}...**")
                        await process_and_send_message(client, user_id, source_msg, message.chat.id, sub_status, user_client)
                        await sub_status.delete()
                        success_count += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    print(f"Skipping post {current_id}: {e}")
                    failed_count += 1

            elapsed = int(time.time() - start_time)
            base_link = f"https://t.me/c/{str(chat_id)[4:]}" if str(chat_id).startswith("-100") else f"https://t.me/{chat_id}"
            
            text = (
                "✅ **Batch Finished**\n\n"
                f"**Original Link:** {link}\n"
                f"**Range:** {start_id} ➔ {end_id}\n"
                f"**Success:** {success_count}\n"
                f"**Skipped:** {skipped_count} (deleted/service msgs)\n"
                f"**Failed:** {failed_count}\n"
                f"**Processed Link:** {base_link}/{start_id}-{end_id}\n"
                f"**Last Processed:** {base_link}/{end_id}\n"
                f"**Time:** {elapsed}s"
            )
            await status.edit_text(text, disable_web_page_preview=True)

    except Exception as e:
        await status.edit_text(f"❌ **Error:** `{e}`")
    finally:
        if user_client:
            await user_client.stop()

