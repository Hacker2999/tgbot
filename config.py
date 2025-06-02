"""
Configuration for the bot. Sensitive data is loaded from environment variables for security.
For local development, you can use a .env file and python-dotenv.
"""
import os
import logging

logger = logging.getLogger(__name__)

# Use the ENVIRONMENT VARIABLE NAMES below, not the values!
API_TOKEN = "your_telegram_bot_token"
RULES = "1. Уважать друг друга.\n2. Не флудить.\n3. Соблюдать законы."
SPAM_LIMIT = 5  # Лимит одинаковых сообщений в минуту
CHANNEL_CHAT_ID = "your_channel_chat_id"
DB_NAME = "your_db_name"
DB_USER = "your_db_user"
DB_PASSWORD = "your_db_password"
DB_HOST = "your_db_host"
DB_PORT = "your_db_port"

# For local development, create a .env file and use python-dotenv to load it automatically:
# from dotenv import load_dotenv
# load_dotenv()
