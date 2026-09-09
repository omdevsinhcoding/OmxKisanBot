from pyrogram import Client, filters, ContinuePropagation, enums
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
                pass
            # Fallback: if bot failed, try user client
            if (not source_msg or source_msg.empty) and not is_private:
                uc = await get_user_client(user_id, API_ID, API_HASH)
                if uc:
                    user_client = uc
                    try:
                        source_msg = await uc.get_messages(chat_id, start_id)
                    except Exception:
                        pass

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
            base_link = f"https://t.me/c/{str(chat_id)[4:]}" if str(chat_id).startswith("-100") else f"https://t.me/{chat_id}"

            # ── Batch Initialized message (pin it) ──
            init_text = (
                f"📦 **Batch Initialized**\n\n"
                f"**Range:** {start_id} → {end_id}\n"
                f"**Link:** {link}\n\n"
                f"🔄 **Processing started...**\n"
                f"🛑 Use /cancel to stop"
            )
            await status.edit_text(init_text)
            try:
                await status.pin(both_sides=True)
            except Exception:
                pass

            for current_id in range(start_id, end_id + 1):
                sub_status = None
                try:
                    source_msg = await fetch_client.get_messages(chat_id, current_id)
                    if not source_msg or source_msg.empty or source_msg.service:
                        skipped_count += 1
                        continue
                    sub_status = await message.reply_text(f"🔄 **Processing Post {current_id}...**")
                    await process_and_send_message(client, user_id, source_msg, message.chat.id, sub_status, user_client)
                    success_count += 1
                except Exception:
                    failed_count += 1
                finally:
                    if sub_status:
                        try:
                            await sub_status.delete()
                        except Exception:
                            pass

            elapsed = int(time.time() - start_time)
            
            text = (
                "✅ <b>𝐁𝐚𝐭𝐜𝐡 𝐅𝐢𝐧𝐢𝐬𝐡𝐞𝐝</b>\n\n"
                "<blockquote>"
                f"<b>Original Link:</b> <code>{link}</code>\n"
                f"<b>Range:</b> {start_id} ➔ {end_id}"
                "</blockquote>\n\n"
                "📊 <b>𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬</b>\n\n"
                "<blockquote>"
                f"<b>Success:</b> {success_count}\n"
                f"<b>Skipped:</b> {skipped_count} <i>(deleted/service msgs)</i>\n"
                f"<b>Failed:</b> {failed_count}"
                "</blockquote>\n\n"
                "🔗 <b>𝐏𝐫𝐨𝐜𝐞𝐬𝐬𝐞𝐝 𝐋𝐢𝐧𝐤𝐬</b>\n\n"
                "<blockquote>"
                f"<b>Processed Link:</b> <code>{base_link}/{start_id}-{end_id}</code>\n"
                f"<b>Last Processed:</b> <code>{base_link}/{end_id}</code>"
                "</blockquote>\n\n"
                f"⏱ <b>𝐓𝐢𝐦𝐞 𝐓𝐚𝐤𝐞𝐧:</b> {elapsed}s"
            )
            try:
                # Try sending with direct HTML format to support blockquotes
                import asyncio, urllib.request, json
                from config import BOT_TOKEN
                payload = {
                    "chat_id": status.chat.id,
                    "message_id": status.id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                def _do_api():
                    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                await asyncio.to_thread(_do_api)
            except Exception as e:
                print(f"Bot API edit failed: {e}")
                # Fallback to Pyrogram
                await status.edit_text(text, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)

    except Exception as e:
        await status.edit_text(f"❌ **Error:** `{e}`")
    # NOTE: No user_client.stop() here — client is cached and reused
