import os
from pyrogram import Client, filters
from pyrogram.types import Message
from helpers.ytdlp_helper import download_social_media
from helpers.progress import ProgressTracker

from helpers.cleaner import auto_clean_chat

@Client.on_message(filters.command(["dl", "adl"]) & filters.private)
async def social_media_downloader(client: Client, message: Message):
    await auto_clean_chat(client, message)
    cmd = message.command[0]
    is_audio = (cmd == "adl")

    if len(message.command) < 2:
        return await message.reply_text(f"❌ **Usage:** `/{cmd} <video/audio URL>`\nExample: `/{cmd} https://www.youtube.com/watch?v=...`")

    url = message.command[1]
    status = await message.reply_text("🔎 **Fetching & Downloading Media via yt-dlp...**")

    try:
        filename, title = await download_social_media(url, is_audio=is_audio)
        if not filename or not os.path.exists(filename):
            return await status.edit_text("❌ **Failed to download media!** Check URL or format.")

        tracker = ProgressTracker(status, action_text="📤 Uploading Media to Telegram")

        caption = f"🎬 **{title}**\n\nDownloaded via Social Media Extractor"
        if is_audio:
            await client.send_audio(
                message.chat.id,
                audio=filename,
                caption=caption,
                progress=tracker.progress_callback
            )
        else:
            await client.send_video(
                message.chat.id,
                video=filename,
                caption=caption,
                progress=tracker.progress_callback
            )

        if os.path.exists(filename):
            os.remove(filename)

        await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ **Download Error:** `{e}`")
