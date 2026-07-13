# src/notifications/telegram_bot.py
"""
Telegram notification sender with interactive buttons.

WHY TELEGRAM:
- Free, instant push notifications to your phone
- Supports interactive buttons (confirm/skip)
- Works globally, no SMS fees
- Bot setup takes 5 minutes
- Rich formatting (bold, code blocks, emojis)

SETUP INSTRUCTIONS:
1. Open Telegram → search @BotFather → send /newbot
2. Follow prompts to create your bot
3. Copy the token → put in .env as TELEGRAM_BOT_TOKEN
4. Send any message to your new bot
5. Visit: https://api.telegram.org/bot<TOKEN>/getUpdates
6. Find chat.id in the JSON → put in .env as TELEGRAM_CHAT_ID
"""

import os
import asyncio
from dotenv import load_dotenv

load_dotenv()


def _get_credentials() -> tuple[str, str] | None:
    """Load Telegram credentials from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or token == "placeholder":
        return None
    if not chat_id or chat_id == "placeholder":
        return None

    return token, chat_id


async def _send_message(token: str, chat_id: str, text: str) -> bool:
    """Send a message via Telegram Bot API."""
    try:
        from telegram import Bot

        bot = Bot(token=token)

        # Telegram has 4096 char limit per message
        if len(text) > 4000:
            text = text[:4000] + "\n... (truncated)"

        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=None,  # Plain text to avoid formatting errors
        )
        return True

    except Exception as e:
        print(f"   Telegram error: {e}")
        return False


def notify(text: str) -> bool:
    """
    Send notification to Telegram. Returns True if sent.
    Silently skips if Telegram is not configured.
    
    WHY SYNC WRAPPER:
    Telegram library is async. Our LangGraph nodes are sync.
    This wrapper bridges the gap cleanly.
    """
    creds = _get_credentials()
    if creds is None:
        print("   Telegram not configured. Skipping notification.")
        print("   (Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env)")
        return False

    token, chat_id = creds
    print("   Sending to Telegram...")

    # Run async function from sync context
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in an async context, create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run, _send_message(token, chat_id, text)
                ).result()
            return result
        else:
            return loop.run_until_complete(_send_message(token, chat_id, text))
    except RuntimeError:
        # No event loop exists yet
        return asyncio.run(_send_message(token, chat_id, text))