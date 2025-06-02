# Telegram Bot Project

## Features
- Anti-spam middleware
- User statistics and message counting
- Welcome and goodbye messages
- Admin and user commands
- Fetches random jokes from baneks.site
- Dynamic button/links management

## Requirements
- Python 3.8+
- PostgreSQL database

## Setup
1. **Clone the repository**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Create a `.env` file** in the project root with the following content:
   ```env
   API_TOKEN=your_telegram_bot_token
   DB_NAME=your_db_name
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   DB_HOST=your_db_host
   DB_PORT=your_db_port
   # Optional
   RULES=1. Уважать друг друга.\n2. Не флудить.\n3. Соблюдать законы.
   SPAM_LIMIT=5
   ```
4. **Run the bot:**
   ```bash
   python main.py
   ```

## Environment Variables
- `API_TOKEN`: Telegram bot token (required)
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: PostgreSQL connection (required)
- `RULES`: Chat rules (optional)
- `SPAM_LIMIT`: Spam message limit per minute (optional, default: 5)

## Notes
- Make sure your database is running and accessible.
- The file `xyz.txt` must exist for the `/size` command.
- For local development, install [python-dotenv](https://pypi.org/project/python-dotenv/) to load `.env` automatically.

## License
MIT 