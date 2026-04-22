import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp
from cachetools import TTLCache

FETCH_TIMEOUT_SECONDS = 6
EXCHANGE_DISPLAY_ORDER = {
    "Binance": 0,
    "Bybit": 1,
    "MEXC": 2,
    "Gate": 3,
}


class SymbolNotFoundError(LookupError):
    pass


class UpstreamUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchSummary:
    results: list[dict]
    not_found_count: int
    upstream_error_count: int
    total_fetchers: int

    @property
    def all_missing(self) -> bool:
        return not self.results and self.not_found_count == self.total_fetchers

    @property
    def all_failed(self) -> bool:
        return not self.results and self.upstream_error_count == self.total_fetchers


def sort_results(results: list[dict]) -> list[dict]:
    return sorted(
        results,
        key=lambda result: EXCHANGE_DISPLAY_ORDER.get(
            result["name"],
            len(EXCHANGE_DISPLAY_ORDER),
        ),
    )


def _countdown(next_funding_ts_ms: int, interval_hours: int) -> str:
    now = datetime.now(timezone.utc).timestamp()
    secs = max(0, next_funding_ts_ms / 1000 - now)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    times_per_day = 24 // interval_hours
    return f"{h:02d}:{m:02d}|{times_per_day}"


def _fmt_oi(usd_value: float) -> str:
    if usd_value >= 1e9:
        return f"{usd_value / 1e9:.2f}B"
    if usd_value >= 1e6:
        return f"{usd_value / 1e6:.2f}M"
    return f"{usd_value / 1e3:.2f}K"


def _is_symbol_not_found_error(exc: Exception) -> bool:
    return isinstance(exc, aiohttp.ClientResponseError) and exc.status in {400, 404}


def _raise_fetch_error(exchange: str, symbol: str, exc: Exception) -> None:
    if _is_symbol_not_found_error(exc):
        raise SymbolNotFoundError(f"{symbol} not found on {exchange}") from exc
    raise UpstreamUnavailableError(
        f"Failed to fetch {symbol} from {exchange}: {exc}"
    ) from exc


async def _get(session: aiohttp.ClientSession, url: str):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.json(content_type=None)


async def _post(session: aiohttp.ClientSession, url: str, json_data: dict):
    async with session.post(url, json=json_data) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_binance(session: aiohttp.ClientSession, symbol: str):
    for prefix, divisor in [("", 1), ("1000", 1000)]:
        try:
            exchange_symbol = f"{prefix}{symbol}USDT"
            data, oi_data = await asyncio.gather(
                _get(
                    session,
                    f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={exchange_symbol}",
                ),
                _get(
                    session,
                    f"https://fapi.binance.com/fapi/v1/openInterest?symbol={exchange_symbol}",
                ),
            )
            raw_price = float(data["markPrice"])
            return {
                "name": "Binance",
                "price": raw_price / divisor,
                "funding": float(data["lastFundingRate"]) * 100,
                "oi": _fmt_oi(float(oi_data["openInterest"]) * raw_price),
                "countdown": _countdown(int(data["nextFundingTime"]), 8),
            }
        except Exception as exc:
            if _is_symbol_not_found_error(exc):
                continue
            _raise_fetch_error("Binance", symbol, exc)

    raise SymbolNotFoundError(f"{symbol} not found on Binance")


async def fetch_bybit(session: aiohttp.ClientSession, symbol: str):
    for prefix, divisor in [("", 1), ("1000", 1000)]:
        try:
            exchange_symbol = f"{prefix}{symbol}USDT"
            data = await _get(
                session,
                "https://api.bybit.com/v5/market/tickers"
                f"?category=linear&symbol={exchange_symbol}",
            )
            instruments = data["result"]["list"]
            if not instruments:
                continue

            item = instruments[0]
            return {
                "name": "Bybit",
                "price": float(item["markPrice"]) / divisor,
                "funding": float(item["fundingRate"]) * 100,
                "oi": _fmt_oi(float(item["openInterestValue"])),
                "countdown": _countdown(int(item["nextFundingTime"]), 8),
            }
        except Exception as exc:
            if _is_symbol_not_found_error(exc):
                continue
            _raise_fetch_error("Bybit", symbol, exc)

    raise SymbolNotFoundError(f"{symbol} not found on Bybit")


async def fetch_bitget(session: aiohttp.ClientSession, symbol: str):
    base_url = "https://api.bitget.com/api/v2/mix/market"
    for prefix, divisor in [("", 1), ("1000", 1000)]:
        try:
            exchange_symbol = f"{prefix}{symbol}USDT"
            ticker, oi_data = await asyncio.gather(
                _get(
                    session,
                    f"{base_url}/ticker?symbol={exchange_symbol}&productType=USDT-FUTURES",
                ),
                _get(
                    session,
                    f"{base_url}/open-interest?symbol={exchange_symbol}&productType=USDT-FUTURES",
                ),
            )
            item = ticker["data"][0]
            raw_price = float(item["markPrice"])
            open_interest_data = oi_data.get("data") or {}
            open_interest_list = open_interest_data.get("openInterestList") or []
            open_interest_value = (
                float(open_interest_list[0]["size"]) if open_interest_list else 0
            )
            next_time = item.get("nextSettlementTime") or item.get("fundingTime")
            if next_time:
                countdown = _countdown(int(next_time), 8)
            else:
                now = datetime.now(timezone.utc)
                minutes_into_interval = (now.hour % 8) * 60 + now.minute
                minutes_left = 480 - minutes_into_interval
                countdown = f"{minutes_left // 60:02d}:{minutes_left % 60:02d}|3"

            return {
                "name": "Bitget",
                "price": raw_price / divisor,
                "funding": float(item["fundingRate"]) * 100,
                "oi": _fmt_oi(open_interest_value * raw_price),
                "countdown": countdown,
            }
        except Exception as exc:
            if _is_symbol_not_found_error(exc):
                continue
            _raise_fetch_error("Bitget", symbol, exc)

    raise SymbolNotFoundError(f"{symbol} not found on Bitget")


async def fetch_okx(session: aiohttp.ClientSession, symbol: str):
    instrument_id = f"{symbol}-USDT-SWAP"
    try:
        funding, mark_price, oi_data = await asyncio.gather(
            _get(
                session,
                f"https://www.okx.com/api/v5/public/funding-rate?instId={instrument_id}",
            ),
            _get(
                session,
                "https://www.okx.com/api/v5/public/mark-price"
                f"?instId={instrument_id}&instType=SWAP",
            ),
            _get(
                session,
                "https://www.okx.com/api/v5/public/open-interest"
                f"?instType=SWAP&instId={instrument_id}",
            ),
        )
        item = funding["data"][0]
        price = float(mark_price["data"][0]["markPx"])
        return {
            "name": "OKX",
            "price": price,
            "funding": float(item["fundingRate"]) * 100,
            "oi": _fmt_oi(float(oi_data["data"][0]["oiCcy"]) * price),
            "countdown": _countdown(int(item["nextFundingTime"]), 8),
        }
    except (IndexError, KeyError) as exc:
        raise SymbolNotFoundError(f"{symbol} not found on OKX") from exc
    except Exception as exc:
        _raise_fetch_error("OKX", symbol, exc)


async def fetch_hyperliquid(session: aiohttp.ClientSession, symbol: str):
    if "hl" not in _hl_cache:
        _hl_cache["hl"] = await _post(
            session,
            "https://api.hyperliquid.xyz/info",
            {"type": "metaAndAssetCtxs"},
        )

    data = _hl_cache["hl"]
    universe = data[0]["universe"]
    ctxs = data[1]
    index = next((i for i, asset in enumerate(universe) if asset["name"] == symbol), None)
    if index is None:
        raise SymbolNotFoundError(f"{symbol} not found on Hyperliquid")

    ctx = ctxs[index]
    now = datetime.now(timezone.utc)
    price = float(ctx["markPx"])
    return {
        "name": "HL",
        "price": price,
        "funding": float(ctx["funding"]) * 100,
        "oi": _fmt_oi(float(ctx["openInterest"]) * price),
        "countdown": f"00:{59 - now.minute:02d}|24",
    }


async def fetch_htx(session: aiohttp.ClientSession, symbol: str):
    contract = f"{symbol}-USDT"
    try:
        funding, mark_price, oi_data = await asyncio.gather(
            _get(
                session,
                "https://api.hbdm.com/linear-swap-api/v1/swap_funding_rate"
                f"?contract_code={contract}",
            ),
            _get(
                session,
                "https://api.hbdm.com/linear-swap-ex/market/detail/merged"
                f"?contract_code={contract}",
            ),
            _get(
                session,
                "https://api.hbdm.com/linear-swap-api/v1/swap_open_interest"
                f"?contract_code={contract}",
            ),
        )
        price = float(mark_price["tick"]["close"])
        next_funding_time = funding["data"].get("next_funding_time")
        if next_funding_time:
            countdown = _countdown(int(next_funding_time), 8)
        else:
            now = datetime.now(timezone.utc)
            minutes_left = 480 - (now.hour % 8) * 60 - now.minute
            countdown = f"{minutes_left // 60:02d}:{minutes_left % 60:02d}|3"

        return {
            "name": "HTX",
            "price": price,
            "funding": float(funding["data"]["funding_rate"]) * 100,
            "oi": _fmt_oi(float(oi_data["data"][0]["value"])),
            "countdown": countdown,
        }
    except (IndexError, KeyError) as exc:
        raise SymbolNotFoundError(f"{symbol} not found on HTX") from exc
    except Exception as exc:
        _raise_fetch_error("HTX", symbol, exc)


async def fetch_gate(session: aiohttp.ClientSession, symbol: str):
    try:
        ticker = await _get(
            session,
            "https://api.gateio.ws/api/v4/futures/usdt/tickers"
            f"?contract={symbol}_USDT",
        )
        if not ticker:
            raise SymbolNotFoundError(f"{symbol} not found on Gate")

        item = ticker[0]
        price = float(item["mark_price"])
        contract_size = float(item.get("quanto_multiplier", 1))
        total_size = float(item.get("total_size") or 0)
        oi = _fmt_oi(total_size * contract_size * price) if total_size > 0 else "N/A"
        now = datetime.now(timezone.utc)
        minutes_into_interval = (now.hour % 8) * 60 + now.minute
        minutes_left = 480 - minutes_into_interval
        return {
            "name": "Gate",
            "price": price,
            "funding": float(item["funding_rate"]) * 100,
            "oi": oi,
            "countdown": f"{minutes_left // 60:02d}:{minutes_left % 60:02d}|3",
        }
    except SymbolNotFoundError:
        raise
    except (IndexError, KeyError) as exc:
        raise SymbolNotFoundError(f"{symbol} not found on Gate") from exc
    except Exception as exc:
        _raise_fetch_error("Gate", symbol, exc)


async def fetch_kucoin(session: aiohttp.ClientSession, symbol: str):
    for prefix, divisor in [("", 1), ("1000", 1000)]:
        try:
            if symbol == "BTC" and divisor == 1:
                kucoin_symbol = "XBTUSDTM"
            else:
                kucoin_symbol = f"{prefix}{symbol}USDTM"
            contract, funding = await asyncio.gather(
                _get(
                    session,
                    f"https://api-futures.kucoin.com/api/v1/contracts/{kucoin_symbol}",
                ),
                _get(
                    session,
                    f"https://api-futures.kucoin.com/api/v1/funding-rate/{kucoin_symbol}/current",
                ),
            )
            item = contract["data"]
            if item is None:
                continue

            raw_price = float(item["markPrice"])
            multiplier = float(item.get("multiplier", 1))
            now = datetime.now(timezone.utc)
            minutes_into_interval = (now.hour % 8) * 60 + now.minute
            minutes_left = 480 - minutes_into_interval
            return {
                "name": "KuCoin",
                "price": raw_price / divisor,
                "funding": float(funding["data"]["value"]) * 100,
                "oi": _fmt_oi(float(item["openInterest"]) * multiplier * raw_price),
                "countdown": f"{minutes_left // 60:02d}:{minutes_left % 60:02d}|3",
            }
        except Exception as exc:
            if _is_symbol_not_found_error(exc):
                continue
            _raise_fetch_error("KuCoin", symbol, exc)

    raise SymbolNotFoundError(f"{symbol} not found on KuCoin")


async def fetch_mexc(session: aiohttp.ClientSession, symbol: str):
    for prefix, divisor in [("", 1), ("1000", 1000)]:
        try:
            mexc_symbol = f"{prefix}{symbol}_USDT"
            ticker, funding, detail = await asyncio.gather(
                _get(
                    session,
                    f"https://contract.mexc.com/api/v1/contract/ticker?symbol={mexc_symbol}",
                ),
                _get(
                    session,
                    f"https://contract.mexc.com/api/v1/contract/funding_rate/{mexc_symbol}",
                ),
                _get(
                    session,
                    f"https://contract.mexc.com/api/v1/contract/detail?symbol={mexc_symbol}",
                ),
            )
            data = ticker["data"]
            if not data:
                continue
            if isinstance(data, list):
                data = data[0]

            raw_price = float(data.get("fairPrice") or data.get("lastPrice"))
            contract_size = float(detail["data"]["contractSize"])
            hold_volume = float(data.get("holdVol") or 0)
            oi = (
                _fmt_oi(hold_volume * contract_size * raw_price)
                if hold_volume > 0
                else "N/A"
            )
            return {
                "name": "MEXC",
                "price": raw_price / divisor,
                "funding": float(funding["data"]["fundingRate"]) * 100,
                "oi": oi,
                "countdown": _countdown(int(funding["data"]["nextSettleTime"]), 8),
            }
        except Exception as exc:
            if _is_symbol_not_found_error(exc):
                continue
            _raise_fetch_error("MEXC", symbol, exc)

    raise SymbolNotFoundError(f"{symbol} not found on MEXC")


async def fetch_bingx(session: aiohttp.ClientSession, symbol: str):
    for prefix, divisor in [("", 1), ("1000", 1000)]:
        try:
            exchange_symbol = f"{prefix}{symbol}-USDT"
            data, oi_data = await asyncio.gather(
                _get(
                    session,
                    "https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex"
                    f"?symbol={exchange_symbol}",
                ),
                _get(
                    session,
                    "https://open-api.bingx.com/openApi/swap/v2/quote/openInterest"
                    f"?symbol={exchange_symbol}",
                ),
            )
            item = data.get("data")
            if not item or "markPrice" not in item:
                continue

            return {
                "name": "BingX",
                "price": float(item["markPrice"]) / divisor,
                "funding": float(item["lastFundingRate"]) * 100,
                "oi": _fmt_oi(float(oi_data["data"]["openInterest"])),
                "countdown": _countdown(int(item["nextFundingTime"]), 8),
            }
        except Exception as exc:
            if _is_symbol_not_found_error(exc):
                continue
            _raise_fetch_error("BingX", symbol, exc)

    raise SymbolNotFoundError(f"{symbol} not found on BingX")


FETCHERS = [
    fetch_binance,
    fetch_bybit,
    fetch_bitget,
    fetch_okx,
    # fetch_hyperliquid,  # disabled by default: large payload noticeably slows replies
    fetch_htx,
    fetch_gate,
    fetch_kucoin,
    fetch_mexc,
    fetch_bingx,
]

_cache: TTLCache = TTLCache(maxsize=1000, ttl=30)
_hl_cache: TTLCache = TTLCache(maxsize=1, ttl=10)
_session: aiohttp.ClientSession | None = None


def set_session(session: aiohttp.ClientSession) -> None:
    global _session
    _session = session


async def fetch_all(symbol: str) -> FetchSummary:
    if _session is None:
        raise RuntimeError("HTTP session is not configured")

    if symbol in _cache:
        return _cache[symbol]

    tasks = [
        asyncio.wait_for(fetcher(_session, symbol), timeout=FETCH_TIMEOUT_SECONDS)
        for fetcher in FETCHERS
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[dict] = []
    not_found_count = 0
    upstream_error_count = 0
    for fetcher, response in zip(FETCHERS, responses):
        if isinstance(response, SymbolNotFoundError):
            not_found_count += 1
            continue
        if isinstance(response, Exception):
            upstream_error_count += 1
            logging.warning("Fetcher %s failed for %s: %s", fetcher.__name__, symbol, response)
            continue
        results.append(response)

    summary = FetchSummary(
        results=sort_results(results),
        not_found_count=not_found_count,
        upstream_error_count=upstream_error_count,
        total_fetchers=len(FETCHERS),
    )
    _cache[symbol] = summary
    return summary
