from pyrogram import Client, filters
from pyrogram.types import Message
from helpers.downloader import parse_tg_link, get_user_client, process_and_send_message
from config import API_ID, API_HASH

from helpers.cleaner import auto_clean_chat

BATCH_CANCEL_FLAGS = {}

@Client.on_message(filters.command("batch") & filters.private & ~filters.reply)
async def batch_info_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    await message.reply_text(
        "📌 **Batch Download Format:**\n\n"
        "Send start link and end link separated by space:\n"
        "Example: `/batch https://t.me/c/123/10 https://t.me/c/123/50`\n\n"
        "Use `/cancel` anytime to stop the batch process!"
    )

@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_handler(client: Client, message: Message):
    await auto_clean_chat(client, message)
    user_id = message.from_user.id
    BATCH_CANCEL_FLAGS[user_id] = True
    await message.reply_text("🛑 **Batch process cancellation requested!**")

@Client.on_message(filters.command("batch") & filters.private)
async def batch_range_command(client: Client, message: Message):
    await auto_clean_chat(client, message)
    args = message.text.split()
    if len(args) < 3:
        return

    user_id = message.from_user.id
    start_link = args[1]
    end_link = args[2]

    chat_id1, start_id, _, is_priv1 = parse_tg_link(start_link)
    chat_id2, _, end_id, is_priv2 = parse_tg_link(end_link)

    if not chat_id1 or not start_id or not end_id or start_id > end_id:
        return await message.reply_text("❌ **Invalid links or range!** Make sure start ID is less than end ID.")

    total_posts = (end_id - start_id) + 1
    max_batch = 500
    if total_posts > max_batch:
        return await message.reply_text(f"⚠️ **Batch Limit Exceeded!** Maximum allowed per batch is `{max_batch}` posts.")

    status = await message.reply_text(f"🚀 **Starting Batch Extraction ({total_posts} posts)...**\nUse `/cancel` to stop anytime.")
    BATCH_CANCEL_FLAGS[user_id] = False

    user_client = None
    import time
    start_time = time.time()
    success_count = 0
    failed_count = 0
    skipped_count = 0

    try:
        if is_priv1:
            user_client = await get_user_client(user_id, API_ID, API_HASH)
            if not user_client:
                return await status.edit_text("🔐 **Private Channel!** Please login using `/login` first.")

        for current_id in range(start_id, end_id + 1):
            if BATCH_CANCEL_FLAGS.get(user_id, False):
                await message.reply_text("🛑 **Batch Process Cancelled!**")
                break

            fetch_client = user_client if is_priv1 else client
            try:
                msg = await fetch_client.get_messages(chat_id1, current_id)
                if msg and not msg.empty:
                    sub_status = await message.reply_text(f"🔄 **Processing Post {current_id}...**")
                    await process_and_send_message(client, user_id, msg, message.chat.id, sub_status)
                    await sub_status.delete()
                    success_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                print(f"Skipping post {current_id}: {e}")
                failed_count += 1

        elapsed = int(time.time() - start_time)
        base_link = f"https://t.me/c/{str(chat_id1)[4:]}" if str(chat_id1).startswith("-100") else f"https://t.me/{chat_id1}"
        processed_link = f"{base_link}/{start_id}-{end_id}"
        
        text = (
            "✅ **Batch Finished**\n\n"
            f"**Original Link:** {processed_link}\n"
            f"**Range:** {start_id} ➔ {end_id}\n"
            f"**Success:** {success_count}\n"
            f"**Skipped:** {skipped_count} (deleted/service msgs)\n"
            f"**Failed:** {failed_count}\n"
            f"**Processed Link:** {processed_link}\n"
            f"**Last Processed:** {base_link}/{end_id}\n"
            f"**Time:** {elapsed}s"
        )
        await status.edit_text(text, disable_web_page_preview=True)

    except Exception as e:
        await status.edit_text(f"❌ **Batch Error:** `{e}`")
    finally:
        if user_client:
            await user_client.stop()
