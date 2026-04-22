import unittest
from unittest.mock import patch

import exchanges
from exchanges import (
    FetchSummary,
    SymbolNotFoundError,
    UpstreamUnavailableError,
    sort_results,
)


class FetchSummaryTestCase(unittest.TestCase):
    def test_all_missing_property(self) -> None:
        summary = FetchSummary(
            results=[],
            not_found_count=9,
            upstream_error_count=0,
            total_fetchers=9,
        )
        self.assertTrue(summary.all_missing)
        self.assertFalse(summary.all_failed)

    def test_all_failed_property(self) -> None:
        summary = FetchSummary(
            results=[],
            not_found_count=0,
            upstream_error_count=9,
            total_fetchers=9,
        )
        self.assertTrue(summary.all_failed)
        self.assertFalse(summary.all_missing)

    def test_sort_results_uses_custom_exchange_priority(self) -> None:
        results = [
            {"name": "OKX"},
            {"name": "Gate"},
            {"name": "MEXC"},
            {"name": "Bybit"},
            {"name": "Binance"},
            {"name": "BingX"},
        ]

        ordered = sort_results(results)

        self.assertEqual(
            [result["name"] for result in ordered],
            ["Binance", "Bybit", "MEXC", "Gate", "OKX", "BingX"],
        )


class FetchAllTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        exchanges._cache.clear()
        exchanges.set_session(object())  # type: ignore[arg-type]

    async def test_fetch_all_tracks_not_found_and_upstream_errors(self) -> None:
        async def ok_fetcher(session, symbol):
            return {
                "name": "Demo",
                "price": 1.23,
                "funding": 0.01,
                "oi": "1.00M",
                "countdown": "01:00|3",
            }

        async def missing_fetcher(session, symbol):
            raise SymbolNotFoundError(f"{symbol} missing")

        async def broken_fetcher(session, symbol):
            raise UpstreamUnavailableError("network issue")

        with patch.object(
            exchanges,
            "FETCHERS",
            [ok_fetcher, missing_fetcher, broken_fetcher],
        ):
            summary = await exchanges.fetch_all("BTC")

        self.assertEqual(len(summary.results), 1)
        self.assertEqual(summary.not_found_count, 1)
        self.assertEqual(summary.upstream_error_count, 1)
        self.assertEqual(summary.total_fetchers, 3)


if __name__ == "__main__":
    unittest.main()
