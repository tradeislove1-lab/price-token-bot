import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from config import load_settings
from exchanges import FetchSummary, fetch_all, set_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

dp = Dispatcher()


def normalize_ticker(text: str | None) -> str | None:
    if text is None:
        return None

    normalized = text.strip().upper()
    if not normalized or not normalized.isalnum() or len(normalized) > 10:
        return None

    return normalized


def _fmt_price(price: float) -> str:
    if price >= 10000:
        return f"{price:.0f}"
    if price >= 100:
        return f"{price:.1f}"
    if price >= 1:
        return f"{price:.3f}"
    return f"{price:.6f}"


def format_table(symbol: str, summary: FetchSummary) -> str:
    lines = [f"<b>{symbol}USDT</b>", "<pre>"]
    lines.append(f"{'Exc.':<7}|{'Price':<8}|{'Funding':<8}|{'OI':<8}|Cntd.")
    lines.append("-" * 43)
    for result in summary.results:
        lines.append(
            f"{result['name']:<7}|"
            f"{_fmt_price(result['price']):<8}|"
            f"{result['funding']:+.3f}%".ljust(8)
            + "|"
            + f"{result['oi']:<8}|"
            + f"{result['countdown']}"
        )
    lines.append("</pre>")
    lines.append(f"Ответило бирж: <b>{len(summary.results)}/{summary.total_fetchers}</b>")
    if summary.upstream_error_count:
        lines.append(
            f"Временно недоступно бирж: <b>{summary.upstream_error_count}</b>"
        )
    return "\n".join(lines)


def start_message() -> str:
    return (
        "Привет! Отправь тикер токена, например <b>BTC</b>, <b>ETH</b> или "
        "<b>1INCH</b>.\n"
        "Я покажу цену, фандинг и open interest по нескольким биржам."
    )


def invalid_ticker_message() -> str:
    return (
        "❌ <b>Неверный формат.</b>\n"
        "Отправь тикер текстом, только буквы и цифры, до 10 символов.\n"
        "<i>Примеры: BTC, DOGE, 1INCH, PEPE</i>"
    )


def upstream_unavailable_message() -> str:
    return (
        "⚠️ Не удалось получить данные от бирж.\n"
        "Похоже, часть API сейчас недоступна. Попробуй ещё раз через минуту."
    )


def symbol_not_found_message(symbol: str) -> str:
    return f"Тикер <b>{symbol}</b> не найден на поддерживаемых биржах."


@dp.message(Command("start"))
@dp.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(start_message())


@dp.message(F.text)
async def handle_ticker(message: Message) -> None:
    symbol = normalize_ticker(message.text)
    if symbol is None:
        await message.answer(invalid_ticker_message())
        return

    status_message = await message.answer("Загружаю данные...")
    summary = await fetch_all(symbol)

    if summary.all_failed:
        await status_message.edit_text(upstream_unavailable_message())
        return

    if summary.all_missing:
        await status_message.edit_text(symbol_not_found_message(symbol))
        return

    await status_message.edit_text(format_table(symbol, summary))


@dp.message()
async def handle_non_text(message: Message) -> None:
    await message.answer(
        "Отправь тикер обычным текстом, например <b>BTC</b> или <b>ETH</b>."
    )


async def main() -> None:
    settings = load_settings()
    connector = aiohttp.TCPConnector(ttl_dns_cache=300, limit=100)
    session = aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=10),
    )
    set_session(session)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        await dp.start_polling(bot)
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
