# Price Token Bot

Telegram bot for quickly checking perpetual futures market data for a token across several exchanges.
It returns price, funding rate, open interest, and time left until the next funding event in a compact Telegram message.

## Features

- Supports tickers like `BTC`, `ETH`, `DOGE`, `PEPE`, and `1INCH`
- Aggregates data from Binance, Bybit, Bitget, OKX, HTX, Gate, KuCoin, MEXC, and BingX
- Separates "token not found" from temporary upstream API failures
- Handles non-text Telegram messages without crashing
- Keeps a short in-memory cache to reduce duplicate exchange requests

## Example

Input:

```text
BTC
```

Output:

```text
BTCUSDT
Exc.   |Price   |Funding |OI      |Cntd.
-------------------------------------------
Binance|93650   |+0.010% |18.20B  |03:44|3
Bybit  |93648   |+0.008% |15.10B  |03:44|3
OKX    |93660   |+0.011% |8.25B   |03:44|3

Answered exchanges: 3/9
Temporarily unavailable: 0
```

## Why This Project

- Useful as a lightweight market snapshot bot without exchange API keys
- Good base for a richer crypto analytics bot
- Small enough to understand quickly, but real enough to show practical async integration work

## Quick Start

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure the bot token

```bash
cp .env.example .env
```

Then put your Telegram bot token into `.env`.

### 3. Run the bot

```bash
python3 bot.py
```

## Testing

```bash
python3 -m unittest discover -s tests -v
```

## Project Layout

- `bot.py` - Telegram handlers and bot entrypoint
- `config.py` - environment loading
- `exchanges.py` - exchange integrations and aggregation logic
- `tests/` - lightweight regression tests

## Ideas To Extend

- Sort exchanges by highest price, lowest price, or funding rate
- Add `/help` and `/exchanges` commands
- Show spread between best and worst price
- Add Docker support and a sample systemd service
- Export structured logs for easier monitoring

## Notes

- This bot uses public exchange APIs, so temporary failures and rate limits can happen.
- The repository intentionally does not include a real bot token, local logs, or a virtual environment.

## License

MIT
