import os
import asyncio
import yt_dlp

async def download_social_media(url: str, is_audio: bool = False, download_dir: str = "downloads"):
    os.makedirs(download_dir, exist_ok=True)
    out_tmpl = os.path.join(download_dir, "%(title).50s.%(ext)s")

    ydl_opts = {
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best" if is_audio else "bestvideo+bestaudio/best",
        "merge_output_format": "mp3" if is_audio else "mp4",
    }

    loop = asyncio.get_event_loop()
    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Handle post-processed output format extensions
            if is_audio and not filename.endswith(".mp3"):
                base, _ = os.path.splitext(filename)
                if os.path.exists(base + ".mp3"):
                    filename = base + ".mp3"
            elif not is_audio and not filename.endswith(".mp4"):
                base, _ = os.path.splitext(filename)
                if os.path.exists(base + ".mp4"):
                    filename = base + ".mp4"
            title = info.get("title", "Social Media Media")
            return filename, title

    return await loop.run_in_executor(None, _download)
