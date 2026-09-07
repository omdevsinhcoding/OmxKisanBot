# Custom Telegram Bot Configuration
import os
from dotenv import load_dotenv

# Search for .env in current directory and parent directory
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

raw_owner = os.getenv("OWNER_ID", "")
OWNER_ID = [int(x) for x in raw_owner.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]

LOG_GROUP = int(os.getenv("LOG_GROUP", "0"))
FORCE_SUB = int(os.getenv("FORCE_SUB", "0"))

JOIN_LINK = os.getenv("JOIN_LINK", "https://t.me/telegram")
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "https://t.me/telegram")
