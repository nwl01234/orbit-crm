import asyncio
import logging

from aiogram import Bot, Dispatcher

from ..config import settings
from .handlers import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_bot() -> None:
    if not settings.telegram_enabled:
        logger.warning("TELEGRAM_BOT_TOKEN is empty. Bot is disabled.")
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Telegram bot is starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot())
