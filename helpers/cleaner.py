from pyrogram import Client
from pyrogram.types import Message

# Set of protected message IDs per chat: {chat_id: set_of_message_ids}
PROTECTED_MESSAGES = {}

def protect_message(chat_id: int, message_id: int):
    """
    Marks a message as protected from auto-deletion (e.g. /start and /login messages).
    """
    if not message_id:
        return
    if chat_id not in PROTECTED_MESSAGES:
        PROTECTED_MESSAGES[chat_id] = set()
    PROTECTED_MESSAGES[chat_id].add(message_id)

async def auto_clean_chat(client: Client, message: Message, depth: int = 30):
    """
    Deletes previous chat messages up to depth to keep the Telegram chat clean,
    EXCEPT for protected messages like /start and /login.
    """
    # Disabled by user request: Do not delete old chats
    return
