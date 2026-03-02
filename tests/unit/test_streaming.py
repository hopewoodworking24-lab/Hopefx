"""
Comprehensive Tests for Real-Time Streaming Service Module

Tests for:
- TickData, TradeData, OrderBookData dataclasses
- ConnectionStatus dataclass
- StreamingService (subscribe/unsubscribe, publish, callbacks,
  connection status, buffer access)
- MockDataSource (basic functionality, price access)

No real network connections are made – all data is injected directly.
"""

import time
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# TickData tests
# ---------------------------------------------------------------------------


class TestTickData:
    """Tests for TickData dataclass."""

    def test_creation(self):
        """Test creating a TickData."""
        from data.streaming import TickData

        tick = TickData(
            timestamp=datetime.now(timezone.utc),
            symbol="XAUUSD",
            bid=2330.0,
            ask=2330.5,
            bid_size=1.0,
            ask_size=1.0,
        )

        assert tick.symbol == "XAUUSD"
        assert tick.bid == 2330.0
        assert tick.ask == 2330.5

    def test_spread(self):
        """Test spread calculation."""
        from data.streaming import TickData

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0
        )
        assert tick.spread == pytest.approx(0.5)

    def test_mid_price(self):
        """Test mid-price calculation."""
        from data.streaming import TickData

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2331.0, 1.0, 1.0
        )
        assert tick.mid_price == pytest.approx(2330.5)

    def test_to_dict(self):
        """Test serialisation."""
        from data.streaming import TickData

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0,
            last_price=2330.2
        )
        d = tick.to_dict()

        assert d["symbol"] == "XAUUSD"
        assert "spread" in d
        assert "mid_price" in d
        assert d["last_price"] == 2330.2


class TestTradeData:
    """Tests for TradeData dataclass."""

    def test_creation_and_dict(self):
        """Test TradeData creation and serialisation."""
        from data.streaming import TradeData

        trade = TradeData(
            timestamp=datetime.now(timezone.utc),
            symbol="XAUUSD",
            price=2330.25,
            size=0.5,
            side="buy",
            trade_id="T123",
        )

        assert trade.side == "buy"
        d = trade.to_dict()
        assert d["price"] == 2330.25
        assert d["trade_id"] == "T123"


class TestOrderBookData:
    """Tests for OrderBookData dataclass."""

    def test_best_bid_ask(self):
        """Test best_bid and best_ask properties."""
        from data.streaming import OrderBookData

        ob = OrderBookData(
            timestamp=datetime.now(timezone.utc),
            symbol="XAUUSD",
            bids=[[2330.0, 1.0], [2329.9, 2.0]],
            asks=[[2330.5, 1.0], [2330.6, 2.0]],
        )

        assert ob.best_bid == 2330.0
        assert ob.best_ask == 2330.5

    def test_empty_book_returns_none(self):
        """Test None when order book sides are empty."""
        from data.streaming import OrderBookData

        ob = OrderBookData(
            datetime.now(timezone.utc), "XAUUSD", [], []
        )
        assert ob.best_bid is None
        assert ob.best_ask is None

    def test_to_dict(self):
        """Test serialisation."""
        from data.streaming import OrderBookData

        ob = OrderBookData(
            datetime.now(timezone.utc), "XAUUSD",
            bids=[[2330.0, 1.0]], asks=[[2330.5, 1.0]],
            is_snapshot=True, sequence=42,
        )
        d = ob.to_dict()

        assert d["symbol"] == "XAUUSD"
        assert d["sequence"] == 42
        assert d["best_bid"] == 2330.0


class TestConnectionStatus:
    """Tests for ConnectionStatus dataclass."""

    def test_default_state(self):
        """Test ConnectionStatus defaults to DISCONNECTED."""
        from data.streaming import ConnectionStatus, ConnectionState

        status = ConnectionStatus()
        assert status.state == ConnectionState.DISCONNECTED
        assert status.messages_received == 0

    def test_to_dict(self):
        """Test serialisation."""
        from data.streaming import ConnectionStatus, ConnectionState

        status = ConnectionStatus(state=ConnectionState.CONNECTED, messages_received=5)
        d = status.to_dict()

        assert d["state"] == "connected"
        assert d["messages_received"] == 5


# ---------------------------------------------------------------------------
# StreamingService tests
# ---------------------------------------------------------------------------


class TestStreamingServiceInit:
    """Tests for StreamingService initialisation."""

    def test_default_init(self):
        """Test default initialisation."""
        from data.streaming import StreamingService

        svc = StreamingService()
        assert svc is not None

    def test_init_with_config(self):
        """Test initialisation with StreamConfig."""
        from data.streaming import StreamingService, StreamConfig

        config = StreamConfig(symbols=["XAUUSD"], throttle_ms=50)
        svc = StreamingService(config)

        subs = svc.get_subscribed_symbols()
        assert "XAUUSD" in subs

    def test_initial_status_disconnected(self):
        """Test initial connection state is DISCONNECTED."""
        from data.streaming import StreamingService, ConnectionState

        svc = StreamingService()
        status = svc.get_connection_status()
        assert status["state"] == ConnectionState.DISCONNECTED.value


class TestStreamingServiceSubscriptions:
    """Tests for subscribe/unsubscribe."""

    def test_subscribe_adds_symbol(self):
        """Test that subscribing adds symbol to subscriptions."""
        from data.streaming import StreamingService

        svc = StreamingService()
        svc.subscribe("EURUSD")

        subs = svc.get_subscribed_symbols()
        assert "EURUSD" in subs

    def test_subscribe_specific_data_types(self):
        """Test subscribing to specific data types."""
        from data.streaming import StreamingService

        svc = StreamingService()
        svc.subscribe("XAUUSD", data_types=["tick"])

        subs = svc.get_subscribed_symbols()
        assert "tick" in subs["XAUUSD"]
        assert "trade" not in subs["XAUUSD"]

    def test_subscribe_invalid_type_raises(self):
        """Test that an invalid data type raises ValueError."""
        from data.streaming import StreamingService

        svc = StreamingService()
        with pytest.raises(ValueError):
            svc.subscribe("XAUUSD", data_types=["invalid_type"])

    def test_unsubscribe_removes_symbol(self):
        """Test that unsubscribing removes symbol completely."""
        from data.streaming import StreamingService

        svc = StreamingService()
        svc.subscribe("XAUUSD")
        svc.unsubscribe("XAUUSD")

        subs = svc.get_subscribed_symbols()
        assert "XAUUSD" not in subs

    def test_unsubscribe_clears_buffers(self):
        """Test that buffers are cleared on unsubscribe."""
        from data.streaming import StreamingService, TickData

        svc = StreamingService()
        svc.subscribe("XAUUSD", data_types=["tick"])

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0
        )
        svc.publish_tick(tick)

        svc.unsubscribe("XAUUSD")
        # After unsubscribe, get_tick_buffer should return empty (symbol removed)
        assert svc.get_tick_buffer("XAUUSD") == []


class TestStreamingServiceCallbacks:
    """Tests for callback registration and invocation."""

    def _make_subscribed_service(self, symbol="XAUUSD"):
        from data.streaming import StreamingService, StreamConfig
        config = StreamConfig(symbols=[symbol], throttle_ms=0)
        return StreamingService(config)

    def test_on_tick_callback_called(self):
        """Test that registered tick callbacks are invoked on publish."""
        from data.streaming import TickData

        svc = self._make_subscribed_service()
        received = []
        svc.on_tick(received.append)

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0
        )
        svc.publish_tick(tick)

        assert len(received) == 1
        assert received[0].symbol == "XAUUSD"

    def test_on_trade_callback_called(self):
        """Test that trade callbacks are invoked on publish."""
        from data.streaming import TradeData

        svc = self._make_subscribed_service()
        received = []
        svc.on_trade(received.append)

        trade = TradeData(
            datetime.now(timezone.utc), "XAUUSD", 2330.25, 0.5, "buy"
        )
        svc.publish_trade(trade)

        assert len(received) == 1
        assert received[0].price == 2330.25

    def test_on_orderbook_callback_called(self):
        """Test that order book callbacks are invoked on publish."""
        from data.streaming import OrderBookData

        svc = self._make_subscribed_service()
        received = []
        svc.on_orderbook(received.append)

        ob = OrderBookData(
            datetime.now(timezone.utc), "XAUUSD",
            bids=[[2330.0, 1.0]], asks=[[2330.5, 1.0]]
        )
        svc.publish_orderbook(ob)

        assert len(received) == 1

    def test_on_tick_decorator_style(self):
        """Test on_tick used as a decorator returns the original callback."""
        from data.streaming import StreamingService

        svc = StreamingService()
        callback = MagicMock()

        returned = svc.on_tick(callback)
        assert returned is callback

    def test_remove_tick_callback(self):
        """Test that removed callbacks are no longer invoked."""
        from data.streaming import TickData

        svc = self._make_subscribed_service()
        received = []
        svc.on_tick(received.append)

        svc.remove_tick_callback(received.append)

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0
        )
        svc.publish_tick(tick)

        assert len(received) == 0

    def test_remove_nonexistent_callback_no_error(self):
        """Test removing a callback that is not registered is a no-op."""
        from data.streaming import StreamingService

        svc = StreamingService()
        cb = MagicMock()
        svc.remove_tick_callback(cb)  # should not raise


class TestStreamingServicePublish:
    """Tests for publish_tick / publish_trade / publish_orderbook."""

    def _make_svc(self, symbol="XAUUSD"):
        from data.streaming import StreamingService, StreamConfig
        config = StreamConfig(symbols=[symbol], throttle_ms=0)
        return StreamingService(config)

    def test_publish_tick_ignored_for_unsubscribed_symbol(self):
        """Test that ticks for unsubscribed symbols are silently ignored."""
        from data.streaming import TickData

        svc = self._make_svc("XAUUSD")
        received = []
        svc.on_tick(received.append)

        # Publish for a symbol we never subscribed to
        tick = TickData(
            datetime.now(timezone.utc), "EURUSD", 1.08, 1.0801, 1.0, 1.0
        )
        svc.publish_tick(tick)

        assert received == []

    def test_publish_tick_stored_in_buffer(self):
        """Test that published ticks are stored in the tick buffer."""
        from data.streaming import TickData

        svc = self._make_svc()
        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0
        )
        svc.publish_tick(tick)

        buf = svc.get_tick_buffer("XAUUSD")
        assert len(buf) >= 1

    def test_publish_trade_stored_in_buffer(self):
        """Test that published trades are stored in the trade buffer."""
        from data.streaming import TradeData

        svc = self._make_svc()
        trade = TradeData(
            datetime.now(timezone.utc), "XAUUSD", 2330.25, 0.5, "buy"
        )
        svc.publish_trade(trade)

        buf = svc.get_trade_buffer("XAUUSD")
        assert len(buf) >= 1

    def test_publish_orderbook_stored_in_buffer(self):
        """Test that published order books are stored in the buffer."""
        from data.streaming import OrderBookData

        svc = self._make_svc()
        ob = OrderBookData(
            datetime.now(timezone.utc), "XAUUSD",
            bids=[[2330.0, 1.0]], asks=[[2330.5, 1.0]]
        )
        svc.publish_orderbook(ob)

        buf = svc.get_orderbook_buffer("XAUUSD")
        assert len(buf) >= 1

    def test_messages_received_increments(self):
        """Test messages_received counter increments on publish."""
        from data.streaming import TickData

        svc = self._make_svc()
        initial = svc.get_connection_status()["messages_received"]

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0
        )
        svc.publish_tick(tick)

        assert svc.get_connection_status()["messages_received"] == initial + 1


class TestStreamingServiceBufferAccess:
    """Tests for get_tick_buffer, get_trade_buffer, get_orderbook_buffer."""

    def test_empty_buffer_for_unknown_symbol(self):
        """Test empty list returned for unknown symbol buffers."""
        from data.streaming import StreamingService

        svc = StreamingService()
        assert svc.get_tick_buffer("UNKNOWN") == []
        assert svc.get_trade_buffer("UNKNOWN") == []
        assert svc.get_orderbook_buffer("UNKNOWN") == []

    def test_buffer_returns_snapshot(self):
        """Test that buffer accessor returns a list (not a deque)."""
        from data.streaming import StreamingService, StreamConfig, TickData

        config = StreamConfig(symbols=["XAUUSD"], throttle_ms=0)
        svc = StreamingService(config)

        tick = TickData(
            datetime.now(timezone.utc), "XAUUSD", 2330.0, 2330.5, 1.0, 1.0
        )
        svc.publish_tick(tick)

        result = svc.get_tick_buffer("XAUUSD")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# MockDataSource tests
# ---------------------------------------------------------------------------


class TestMockDataSource:
    """Tests for MockDataSource basic functionality."""

    def _make_service_and_source(self, symbol="XAUUSD"):
        from data.streaming import StreamingService, StreamConfig, MockDataSource

        config = StreamConfig(symbols=[symbol], throttle_ms=0)
        svc = StreamingService(config)
        src = MockDataSource(svc, symbols=[symbol], tick_interval_ms=50)
        return svc, src

    def test_get_current_price_returns_seed(self):
        """Test get_current_price returns the seed price for known symbol."""
        from data.streaming import StreamingService, StreamConfig, MockDataSource

        config = StreamConfig(symbols=["XAUUSD"], throttle_ms=0)
        svc = StreamingService(config)
        src = MockDataSource(svc, symbols=["XAUUSD"])

        price = src.get_current_price("XAUUSD")
        assert price is not None
        assert price > 0

    def test_get_current_price_none_for_unknown(self):
        """Test None returned for unknown symbol."""
        from data.streaming import StreamingService, MockDataSource

        svc = StreamingService()
        src = MockDataSource(svc, symbols=["XAUUSD"])

        assert src.get_current_price("UNKNOWN") is None

    def test_start_stop_lifecycle(self):
        """Test that start/stop lifecycle works without errors."""
        svc, src = self._make_service_and_source()
        src.start()
        assert src._running is True
        time.sleep(0.2)
        src.stop()
        assert src._running is False

    def test_start_idempotent(self):
        """Test that calling start() twice does not raise."""
        svc, src = self._make_service_and_source()
        src.start()
        src.start()  # second call should be a no-op
        src.stop()

    def test_data_published_after_start(self):
        """Test that ticks are published after source starts."""
        from data.streaming import StreamConfig, StreamingService, MockDataSource

        config = StreamConfig(symbols=["XAUUSD"], throttle_ms=0)
        svc = StreamingService(config)
        src = MockDataSource(svc, symbols=["XAUUSD"], tick_interval_ms=20)

        received = []
        svc.on_tick(received.append)

        src.start()
        time.sleep(0.3)
        src.stop()

        assert len(received) > 0
        assert received[0].symbol == "XAUUSD"
