"""
Configuration for the bot. Sensitive data is loaded from environment variables for security.
For local development, you can use a .env file and python-dotenv.
"""
import os
import logging

logger = logging.getLogger(__name__)

def get_env(key: str, default: str = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value:
        logger.error(f"Required environment variable '{key}' is missing!")
    return value

API_TOKEN = get_env("API_TOKEN", required=True)
RULES = os.getenv("RULES", "1. Уважать друг друга.\n2. Не флудить.\n3. Соблюдать законы.")
SPAM_LIMIT = int(os.getenv("SPAM_LIMIT", "5"))  # Лимит одинаковых сообщений в минуту

DB_NAME = get_env("DB_NAME", required=True)
DB_USER = get_env("DB_USER", required=True)
DB_PASSWORD = get_env("DB_PASSWORD", required=True)
DB_HOST = get_env("DB_HOST", required=True)
DB_PORT = get_env("DB_PORT", required=True)

# For local development, create a .env file and use python-dotenv to load it automatically:
# from dotenv import load_dotenv
# load_dotenv()
