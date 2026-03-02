"""
Comprehensive Tests for Time & Sales (Trade Tape) Service Module

Tests for:
- ExecutedTrade dataclass
- TradeVelocity dataclass
- AggressorStats dataclass
- TradeHistogramBucket dataclass
- TimeAndSalesService (trade capture, queries, analytics)
- Thread safety basics
"""

import threading
import pytest
from datetime import datetime, timedelta, timezone


class TestExecutedTrade:
    """Tests for ExecutedTrade dataclass."""

    def test_trade_creation(self):
        """Test creating an ExecutedTrade."""
        from data.time_and_sales import ExecutedTrade

        trade = ExecutedTrade(
            timestamp=datetime.now(timezone.utc),
            symbol="XAUUSD",
            price=2345.10,
            size=10.0,
            side="buy",
        )

        assert trade.symbol == "XAUUSD"
        assert trade.price == 2345.10
        assert trade.size == 10.0
        assert trade.side == "buy"

    def test_trade_is_buy(self):
        """Test buy/sell flag properties."""
        from data.time_and_sales import ExecutedTrade

        buy = ExecutedTrade(datetime.now(timezone.utc), "XAUUSD", 2345.0, 1.0, "buy")
        sell = ExecutedTrade(datetime.now(timezone.utc), "XAUUSD", 2345.0, 1.0, "sell")

        assert buy.is_buy is True
        assert buy.is_sell is False
        assert sell.is_sell is True
        assert sell.is_buy is False

    def test_trade_notional_value(self):
        """Test notional value calculation."""
        from data.time_and_sales import ExecutedTrade

        trade = ExecutedTrade(
            datetime.now(timezone.utc), "XAUUSD", 2000.0, 5.0, "buy"
        )
        assert trade.notional_value == pytest.approx(10000.0)

    def test_trade_to_dict(self):
        """Test serialisation to dictionary."""
        from data.time_and_sales import ExecutedTrade

        trade = ExecutedTrade(
            datetime.now(timezone.utc), "XAUUSD", 2345.0, 10.0, "buy",
            trade_id="T001"
        )
        result = trade.to_dict()

        assert result["symbol"] == "XAUUSD"
        assert result["price"] == 2345.0
        assert result["size"] == 10.0
        assert result["side"] == "buy"
        assert result["trade_id"] == "T001"
        assert "notional_value" in result
        assert "timestamp" in result


class TestTradeHistogramBucket:
    """Tests for TradeHistogramBucket dataclass."""

    def test_buy_sell_pct(self):
        """Test buy/sell percentage computations."""
        from data.time_and_sales import TradeHistogramBucket

        bucket = TradeHistogramBucket(
            price_low=1950.0,
            price_high=1951.0,
            price_mid=1950.5,
            trade_count=10,
            total_volume=1000.0,
            buy_volume=700.0,
            sell_volume=300.0,
        )

        assert bucket.buy_pct == pytest.approx(70.0)
        assert bucket.sell_pct == pytest.approx(30.0)

    def test_zero_volume_pct(self):
        """Test percentage returns zero when total volume is zero."""
        from data.time_and_sales import TradeHistogramBucket

        bucket = TradeHistogramBucket(
            price_low=1950.0, price_high=1951.0, price_mid=1950.5,
            trade_count=0, total_volume=0.0, buy_volume=0.0, sell_volume=0.0,
        )

        assert bucket.buy_pct == 0.0
        assert bucket.sell_pct == 0.0

    def test_to_dict(self):
        """Test histogram bucket serialisation."""
        from data.time_and_sales import TradeHistogramBucket

        bucket = TradeHistogramBucket(
            price_low=1950.0, price_high=1951.0, price_mid=1950.5,
            trade_count=5, total_volume=500.0, buy_volume=300.0, sell_volume=200.0,
        )
        d = bucket.to_dict()

        assert d["price_mid"] == 1950.5
        assert d["trade_count"] == 5
        assert "buy_pct" in d
        assert "sell_pct" in d


class TestTimeAndSalesServiceInit:
    """Tests for TimeAndSalesService initialisation."""

    def test_default_init(self):
        """Test default initialisation."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        assert svc is not None

    def test_custom_config(self):
        """Test initialisation with custom config."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService(
            config={"max_trades": 500, "large_trade_threshold": 50.0}
        )
        assert svc._max_trades == 500
        assert svc._default_large_threshold == 50.0

    def test_set_large_trade_threshold(self):
        """Test per-symbol threshold override."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        svc.set_large_trade_threshold("XAUUSD", 200.0)

        assert svc._symbol_large_threshold["XAUUSD"] == 200.0


class TestTimeAndSalesServiceTrades:
    """Tests for trade capture and storage."""

    def test_add_trade_returns_executed_trade(self):
        """Test add_trade returns an ExecutedTrade."""
        from data.time_and_sales import TimeAndSalesService, ExecutedTrade

        svc = TimeAndSalesService()
        trade = svc.add_trade("XAUUSD", 2345.0, 10.0, "buy")

        assert isinstance(trade, ExecutedTrade)
        assert trade.symbol == "XAUUSD"
        assert trade.price == 2345.0

    def test_add_trade_invalid_side_raises(self):
        """Test that an invalid side raises ValueError."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        with pytest.raises(ValueError):
            svc.add_trade("XAUUSD", 2345.0, 10.0, "invalid")

    def test_add_trade_flags_large(self):
        """Test that oversized trades are flagged correctly."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService(config={"large_trade_threshold": 50.0})
        large = svc.add_trade("XAUUSD", 2345.0, 100.0, "buy")
        small = svc.add_trade("XAUUSD", 2345.0, 10.0, "sell")

        assert large.is_large_trade is True
        assert small.is_large_trade is False

    def test_add_trade_large_callback_fired(self):
        """Test that large-trade callbacks are invoked."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService(config={"large_trade_threshold": 50.0})
        received = []
        svc.register_large_trade_callback(received.append)

        svc.add_trade("XAUUSD", 2345.0, 100.0, "buy")

        assert len(received) == 1
        assert received[0].is_large_trade is True

    def test_add_trades_bulk(self):
        """Test bulk trade ingestion."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        raw = [
            {"symbol": "XAUUSD", "price": 2345.0, "size": 5.0, "side": "buy"},
            {"symbol": "XAUUSD", "price": 2346.0, "size": 3.0, "side": "sell"},
        ]
        stored = svc.add_trades(raw)

        assert len(stored) == 2

    def test_add_trades_skips_malformed(self):
        """Test that malformed entries are skipped gracefully."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        raw = [
            {"symbol": "XAUUSD", "price": 2345.0, "size": 5.0, "side": "buy"},
            {"bad": "data"},
        ]
        stored = svc.add_trades(raw)

        assert len(stored) == 1


class TestTimeAndSalesServiceQueries:
    """Tests for trade filtering and query methods."""

    def _populate(self, svc, symbol="XAUUSD", n=10):
        for i in range(n):
            svc.add_trade(symbol, 2340.0 + i * 0.5, float(i + 1), "buy" if i % 2 == 0 else "sell")

    def test_get_recent_trades(self):
        """Test get_recent_trades returns correct count."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        self._populate(svc, n=20)

        trades = svc.get_recent_trades("XAUUSD", n=5)
        assert len(trades) == 5

    def test_get_recent_trades_empty(self):
        """Test get_recent_trades on unknown symbol returns empty list."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        assert svc.get_recent_trades("UNKNOWN") == []

    def test_get_trades_by_time(self):
        """Test time-range filtering."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        now = datetime.now(timezone.utc)

        # Old trade (5 minutes ago)
        svc.add_trade("XAUUSD", 2340.0, 1.0, "buy",
                      timestamp=now - timedelta(minutes=5))
        # Recent trade (now)
        svc.add_trade("XAUUSD", 2341.0, 1.0, "sell", timestamp=now)

        result = svc.get_trades_by_time(
            "XAUUSD",
            start_time=now - timedelta(minutes=2),
            end_time=now + timedelta(minutes=1),
        )
        assert len(result) == 1
        assert result[0].price == 2341.0

    def test_get_large_trades_filters_by_size(self):
        """Test get_large_trades returns only qualifying trades."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService(config={"large_trade_threshold": 50.0})
        svc.add_trade("XAUUSD", 2340.0, 10.0, "buy")
        svc.add_trade("XAUUSD", 2341.0, 200.0, "sell")

        large = svc.get_large_trades("XAUUSD")
        assert len(large) == 1
        assert large[0].size == 200.0

    def test_get_large_trades_with_min_size_override(self):
        """Test min_size parameter override in get_large_trades."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        svc.add_trade("XAUUSD", 2340.0, 30.0, "buy")
        svc.add_trade("XAUUSD", 2341.0, 80.0, "sell")

        large = svc.get_large_trades("XAUUSD", min_size=50.0)
        assert len(large) == 1
        assert large[0].size == 80.0


class TestTimeAndSalesServiceAnalytics:
    """Tests for velocity, aggressor stats, and histogram."""

    def _add_mixed(self, svc, symbol="XAUUSD", buys=10, sells=5):
        for i in range(buys):
            svc.add_trade(symbol, 2340.0 + i * 0.1, 10.0, "buy")
        for i in range(sells):
            svc.add_trade(symbol, 2340.0 + i * 0.1, 10.0, "sell")

    def test_get_trade_velocity_returns_velocity(self):
        """Test that velocity is returned when trades exist."""
        from data.time_and_sales import TimeAndSalesService, TradeVelocity

        svc = TimeAndSalesService()
        self._add_mixed(svc)

        velocity = svc.get_trade_velocity("XAUUSD", window_minutes=60.0)
        assert isinstance(velocity, TradeVelocity)
        assert velocity.total_trades == 15

    def test_get_trade_velocity_none_on_empty(self):
        """Test None returned when no trades exist."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        assert svc.get_trade_velocity("XAUUSD") is None

    def test_get_trade_velocity_buy_pct(self):
        """Test buy percentage in velocity."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        for _ in range(3):
            svc.add_trade("XAUUSD", 2340.0, 10.0, "buy")
        svc.add_trade("XAUUSD", 2340.0, 10.0, "sell")

        v = svc.get_trade_velocity("XAUUSD", window_minutes=60.0)
        assert v.buy_trades_pct == pytest.approx(75.0)
        assert v.sell_trades_pct == pytest.approx(25.0)

    def test_get_aggressor_stats_returns_stats(self):
        """Test that aggressor stats are returned."""
        from data.time_and_sales import TimeAndSalesService, AggressorStats

        svc = TimeAndSalesService()
        self._add_mixed(svc, buys=10, sells=5)

        stats = svc.get_aggressor_stats("XAUUSD")
        assert isinstance(stats, AggressorStats)
        assert stats.buy_trades == 10
        assert stats.sell_trades == 5

    def test_get_aggressor_stats_dominant_side(self):
        """Test dominant side detection with heavy buy imbalance."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        for _ in range(20):
            svc.add_trade("XAUUSD", 2340.0, 100.0, "buy")
        svc.add_trade("XAUUSD", 2340.0, 100.0, "sell")

        stats = svc.get_aggressor_stats("XAUUSD")
        assert stats.dominant_side == "buyers"
        assert stats.net_delta > 0

    def test_get_aggressor_stats_none_on_empty(self):
        """Test None returned when no trades exist."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        assert svc.get_aggressor_stats("XAUUSD") is None

    def test_get_trade_histogram(self):
        """Test histogram generation returns buckets."""
        from data.time_and_sales import TimeAndSalesService, TradeHistogramBucket

        svc = TimeAndSalesService()
        for i in range(30):
            svc.add_trade("XAUUSD", 2340.0 + i * 0.5, 10.0, "buy" if i % 2 == 0 else "sell")

        buckets = svc.get_trade_histogram("XAUUSD", price_levels=10)
        assert isinstance(buckets, list)
        assert len(buckets) > 0
        assert all(isinstance(b, TradeHistogramBucket) for b in buckets)

    def test_get_trade_histogram_empty_symbol(self):
        """Test histogram returns empty list for unknown symbol."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        assert svc.get_trade_histogram("UNKNOWN") == []

    def test_get_trade_stats(self):
        """Test per-symbol stats dictionary."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        self._add_mixed(svc)

        stats = svc.get_trade_stats("XAUUSD")
        assert "trade_count" in stats
        assert "buy_volume" in stats
        assert "sell_volume" in stats
        assert stats["trade_count"] == 15

    def test_get_service_stats(self):
        """Test global service statistics."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        self._add_mixed(svc)

        stats = svc.get_service_stats()
        assert "total_trades_buffered" in stats
        assert "symbols_tracked" in stats

    def test_clear_symbol(self):
        """Test clearing all trades for a symbol."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        self._add_mixed(svc)

        svc.clear_symbol("XAUUSD")
        assert svc.get_recent_trades("XAUUSD") == []


class TestTimeAndSalesThreadSafety:
    """Basic thread-safety tests for TimeAndSalesService."""

    def test_concurrent_add_trades(self):
        """Test concurrent writes do not corrupt state."""
        from data.time_and_sales import TimeAndSalesService

        svc = TimeAndSalesService()
        errors = []

        def worker(side):
            try:
                for i in range(50):
                    svc.add_trade("XAUUSD", 2340.0 + i * 0.01, 1.0, side)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=("buy",)),
            threading.Thread(target=worker, args=("sell",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        trades = svc.get_recent_trades("XAUUSD", n=1000)
        assert len(trades) == 100


class TestGlobalTimeAndSalesService:
    """Test the module-level singleton helper."""

    def test_get_service_returns_singleton(self):
        """Test that repeated calls return the same instance."""
        from data.time_and_sales import get_time_and_sales_service

        svc1 = get_time_and_sales_service()
        svc2 = get_time_and_sales_service()
        assert svc1 is svc2
