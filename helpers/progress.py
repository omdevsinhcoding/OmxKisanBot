import time
import math
from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

ACTIVE_TRACKERS = {}
REFRESH_COOLDOWNS = {}

def readable_size(size_in_bytes: int) -> str:
    if not size_in_bytes:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_in_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}"

def readable_time(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

class ProgressTracker:
    def __init__(self, message: Message, action_text="Processing"):
        self.message = message
        self.action_text = action_text
        self.start_time = time.time()
        self.last_edit_time = 0
        self.current = 0
        self.total = 0
        if message and hasattr(message, "id"):
            ACTIVE_TRACKERS[message.id] = self

    def get_text_and_markup(self, current=None, total=None):
        if current is not None:
            self.current = current
        if total is not None:
            self.total = total

        now = time.time()
        percentage = (self.current / self.total) * 100 if self.total else 0
        speed = self.current / (now - self.start_time) if (now - self.start_time) > 0 else 0
        eta = (self.total - self.current) / speed if speed > 0 else 0

        filled_len = int(math.floor(percentage / 10))
        bar = "█" * filled_len + "░" * (10 - filled_len)

        text = (
            f"**{self.action_text}**\n\n"
            f"[{bar}] `{percentage:.1f}%`\n\n"
            f"🚀 **Speed:** `{readable_size(speed)}/s`\n"
            f"📦 **Done:** `{readable_size(self.current)}` / `{readable_size(self.total)}`\n"
            f"⏱️ **ETA:** `{readable_time(eta)}`"
        )
        msg_id = self.message.id if self.message and hasattr(self.message, "id") else 0
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_prog_{msg_id}")]])
        return text, buttons

    async def progress_callback(self, current, total):
        self.current = current
        self.total = total
        now = time.time()
        # Auto update every 2.5 seconds or on completion
        if (now - self.last_edit_time < 2.5) and (current < total):
            return
        
        self.last_edit_time = now
        text, buttons = self.get_text_and_markup(current, total)
        try:
            await self.message.edit_text(text, reply_markup=buttons)
        except Exception:
            pass

async def handle_refresh_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    now = time.time()
    last_click = REFRESH_COOLDOWNS.get(user_id, 0)
    cooldown = 3.0

    time_left = cooldown - (now - last_click)
    if time_left > 0:
        sec = math.ceil(time_left)
        return await query.answer(f"⚠️ Please wait {sec} seconds before refreshing again!", show_alert=True)

    REFRESH_COOLDOWNS[user_id] = now

    try:
        msg_id = int(query.data.replace("refresh_prog_", ""))
        tracker = ACTIVE_TRACKERS.get(msg_id)

        if not tracker:
            return await query.answer("ℹ️ Download complete or tracker inactive.", show_alert=False)

        text, buttons = tracker.get_text_and_markup()
        await query.message.edit_text(text, reply_markup=buttons)
        await query.answer("🔄 Progress Refreshed!")
    except Exception:
        await query.answer("🔄 Progress up to date!")

