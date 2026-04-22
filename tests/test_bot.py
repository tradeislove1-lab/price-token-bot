import unittest

from bot import format_table, normalize_ticker
from exchanges import FetchSummary


class BotHelpersTestCase(unittest.TestCase):
    def test_normalize_ticker_uppercases_valid_symbol(self) -> None:
        self.assertEqual(normalize_ticker(" doge "), "DOGE")
        self.assertEqual(normalize_ticker("1inch"), "1INCH")

    def test_normalize_ticker_rejects_invalid_values(self) -> None:
        self.assertIsNone(normalize_ticker(None))
        self.assertIsNone(normalize_ticker(""))
        self.assertIsNone(normalize_ticker("hello-world"))
        self.assertIsNone(normalize_ticker("ABCDEFGHIJK"))

    def test_format_table_includes_exchange_stats(self) -> None:
        summary = FetchSummary(
            results=[
                {
                    "name": "Binance",
                    "price": 123.456,
                    "funding": 0.01,
                    "oi": "2.50M",
                    "countdown": "01:23|3",
                }
            ],
            not_found_count=0,
            upstream_error_count=2,
            total_fetchers=9,
        )

        rendered = format_table("BTC", summary)

        self.assertIn("<b>BTCUSDT</b>", rendered)
        self.assertIn("Binance", rendered)
        self.assertIn("Ответило бирж: <b>1/9</b>", rendered)
        self.assertIn("Временно недоступно бирж: <b>2</b>", rendered)

    def test_format_table_preserves_sorted_exchange_order(self) -> None:
        summary = FetchSummary(
            results=[
                {
                    "name": "Binance",
                    "price": 10.0,
                    "funding": 0.01,
                    "oi": "1.00M",
                    "countdown": "01:00|3",
                },
                {
                    "name": "Bybit",
                    "price": 10.0,
                    "funding": 0.01,
                    "oi": "1.00M",
                    "countdown": "01:00|3",
                },
                {
                    "name": "MEXC",
                    "price": 10.0,
                    "funding": 0.01,
                    "oi": "1.00M",
                    "countdown": "01:00|3",
                },
                {
                    "name": "Gate",
                    "price": 10.0,
                    "funding": 0.01,
                    "oi": "1.00M",
                    "countdown": "01:00|3",
                },
                {
                    "name": "OKX",
                    "price": 10.0,
                    "funding": 0.01,
                    "oi": "1.00M",
                    "countdown": "01:00|3",
                },
            ],
            not_found_count=0,
            upstream_error_count=0,
            total_fetchers=9,
        )

        rendered = format_table("BTC", summary)

        self.assertLess(rendered.index("Binance"), rendered.index("Bybit"))
        self.assertLess(rendered.index("Bybit"), rendered.index("MEXC"))
        self.assertLess(rendered.index("MEXC"), rendered.index("Gate"))
        self.assertLess(rendered.index("Gate"), rendered.index("OKX"))


if __name__ == "__main__":
    unittest.main()
