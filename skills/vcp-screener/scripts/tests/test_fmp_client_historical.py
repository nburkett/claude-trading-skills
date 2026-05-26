"""Issue #64: stable/historical-price-eod/full normalization for vcp-screener."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fmp_client import FMPClient


def _make_client():
    client = FMPClient(api_key="test_key")
    client.max_retries = 0
    return client


def _mock_response(status_code, json_payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload
    resp.text = ""
    return resp


def _mock_text_response(status_code, text):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.side_effect = ValueError("not json")
    return resp


class TestEODFlatListSuccess:
    @patch("fmp_client.requests.Session")
    def test_get_historical_prices_normalizes_flat_list(self, mock_session_class):
        """Flat list response -> dict contract preserved."""
        mock_session = MagicMock()
        mock_session.get.return_value = _mock_response(
            200,
            [
                {
                    "symbol": "SPY",
                    "date": "2026-04-29",
                    "open": 500.0,
                    "high": 502.0,
                    "low": 499.0,
                    "close": 501.0,
                    "volume": 1_000_000,
                },
                {
                    "symbol": "SPY",
                    "date": "2026-04-28",
                    "open": 498.0,
                    "high": 501.0,
                    "low": 497.0,
                    "close": 500.0,
                    "volume": 1_100_000,
                },
            ],
        )
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session

        result = client.get_historical_prices("SPY", days=2)
        assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
        assert result["symbol"] == "SPY"
        assert len(result["historical"]) == 2
        assert result["historical"][0]["close"] == 501.0

        first_call = mock_session.get.call_args_list[0]
        url = first_call[0][0]
        params = first_call[1]["params"]
        assert "historical-price-eod/full" in url
        assert "from" in params and "to" in params
        assert "timeseries" not in params


class TestSP500Constituents:
    @patch("fmp_client.requests.Session")
    def test_get_sp500_constituents_uses_stable_endpoint(self, mock_session_class):
        """Stable S&P 500 constituent response -> list contract preserved."""
        mock_session = MagicMock()
        mock_session.get.return_value = _mock_response(
            200,
            [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "sector": "Technology",
                    "subSector": "Consumer Electronics",
                }
            ],
        )
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session

        result = client.get_sp500_constituents()

        assert result == [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "sector": "Technology",
                "subSector": "Consumer Electronics",
            }
        ]
        first_call = mock_session.get.call_args_list[0]
        url = first_call[0][0]
        assert url == "https://financialmodelingprep.com/stable/sp500-constituent"

    @patch("fmp_client.requests.Session")
    def test_get_sp500_constituents_falls_back_when_endpoint_restricted(
        self, mock_session_class
    ):
        """Restricted FMP constituent entitlement -> static universe fallback."""
        mock_session = MagicMock()
        mock_session.get.return_value = _mock_text_response(
            402,
            "Restricted Endpoint: This endpoint is not available under your current subscription",
        )
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session

        result = client.get_sp500_constituents()

        assert isinstance(result, list)
        assert len(result) == 100
        assert any(item["symbol"] == "AAPL" for item in result)
        assert any(item["symbol"] == "MSFT" for item in result)
        assert all("symbol" in item for item in result)


class TestStableQuoteRouting:
    @patch("fmp_client.requests.Session")
    def test_batch_quotes_use_stable_batch_quote_endpoint(self, mock_session_class):
        """Multiple symbols use FMP's stable batch-quote endpoint."""
        mock_session = MagicMock()
        mock_session.get.return_value = _mock_response(
            200,
            [
                {"symbol": "AAPL", "price": 300.0},
                {"symbol": "MSFT", "price": 500.0},
            ],
        )
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session

        result = client.get_quote("AAPL,MSFT")

        assert [row["symbol"] for row in result] == ["AAPL", "MSFT"]
        first_call = mock_session.get.call_args_list[0]
        url = first_call[0][0]
        params = first_call[1]["params"]
        assert url == "https://financialmodelingprep.com/stable/batch-quote"
        assert params["symbols"] == "AAPL,MSFT"
        assert "symbol" not in params

    @patch("fmp_client.requests.Session")
    def test_batch_quotes_fall_back_to_single_symbol_quotes_when_restricted(
        self, mock_session_class
    ):
        """Restricted batch quote entitlement -> single-symbol stable quotes."""
        mock_session = MagicMock()
        mock_session.get.side_effect = [
            _mock_text_response(402, "Restricted Endpoint"),
            _mock_response(403, {"Error Message": "Legacy Endpoint"}),
            _mock_response(200, [{"symbol": "AAPL", "price": 300.0}]),
            _mock_response(200, [{"symbol": "MSFT", "price": 500.0}]),
        ]
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session

        result = client.get_batch_quotes(["AAPL", "MSFT"])

        assert result == {
            "AAPL": {"symbol": "AAPL", "price": 300.0},
            "MSFT": {"symbol": "MSFT", "price": 500.0},
        }
        called_urls = [call[0][0] for call in mock_session.get.call_args_list]
        assert called_urls[0] == "https://financialmodelingprep.com/stable/batch-quote"
        assert called_urls[2] == "https://financialmodelingprep.com/stable/quote"
        assert called_urls[3] == "https://financialmodelingprep.com/stable/quote"

    @patch("fmp_client.requests.Session")
    def test_restricted_batch_quote_does_not_disable_single_quote_fallback(
        self, mock_session_class
    ):
        """Repeated batch quote restrictions do not circuit-break stable/quote."""
        symbols = [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "META",
            "GOOGL",
            "GOOG",
            "AVGO",
            "TSLA",
            "JPM",
            "LLY",
            "V",
            "MA",
            "XOM",
            "COST",
        ]
        responses = []
        for symbol in symbols:
            if len(responses) % 7 == 0:
                responses.extend(
                    [
                        _mock_text_response(402, "Restricted Endpoint"),
                        _mock_response(403, {"Error Message": "Legacy Endpoint"}),
                    ]
                )
            responses.append(_mock_response(200, [{"symbol": symbol, "price": 100.0}]))

        mock_session = MagicMock()
        mock_session.get.side_effect = responses
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session

        result = client.get_batch_quotes(symbols)

        assert set(result) == set(symbols)
        single_quote_calls = [
            call
            for call in mock_session.get.call_args_list
            if call[0][0] == "https://financialmodelingprep.com/stable/quote"
        ]
        assert len(single_quote_calls) == 15

    @patch("fmp_client.requests.Session")
    def test_restricted_single_symbols_do_not_disable_later_single_quotes(
        self, mock_session_class
    ):
        """Symbol-specific quote restrictions do not disable stable/quote."""
        mock_session = MagicMock()
        mock_session.get.side_effect = [
            _mock_text_response(402, "Premium Query Parameter"),
            _mock_response(403, {"Error Message": "Legacy Endpoint"}),
            _mock_text_response(402, "Premium Query Parameter"),
            _mock_response(403, {"Error Message": "Legacy Endpoint"}),
            _mock_text_response(402, "Premium Query Parameter"),
            _mock_response(403, {"Error Message": "Legacy Endpoint"}),
            _mock_response(200, [{"symbol": "AAPL", "price": 300.0}]),
        ]
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session

        assert client.get_quote("GOOG") is None
        assert client.get_quote("AVGO") is None
        assert client.get_quote("LLY") is None
        result = client.get_quote("AAPL")

        assert result == [{"symbol": "AAPL", "price": 300.0}]
        called_urls = [call[0][0] for call in mock_session.get.call_args_list]
        assert called_urls.count("https://financialmodelingprep.com/stable/quote") == 4
