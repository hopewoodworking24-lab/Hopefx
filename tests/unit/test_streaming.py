"""
Tests for data/streaming.py
"""

import threading
import time
import pytest
from datetime import datetime


class TestStreamEventType:
    """Tests for StreamEventType enum."""

    def test_values(self):
        from data.streaming import StreamEventType
        assert StreamEventType.TRADE.value == "trade"
        assert StreamEventType.QUOTE.value == "quote"
        assert StreamEventType.HEARTBEAT.value == "heartbeat"


class TestConnectionState:
    """Tests for ConnectionState enum."""

    def test_values(self):
        from data.streaming import ConnectionState
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.DISCONNECTED.value == "disconnected"


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def _make(self, **kwargs):
        from data.streaming import StreamEvent, StreamEventType
        defaults = dict(
            event_type=StreamEventType.TRADE,
            symbol='XAUUSD',
            data={'price': 1950.0, 'size': 10.0},
        )
        defaults.update(kwargs)
        return StreamEvent(**defaults)

    def test_to_dict_keys(self):
        e = self._make()
        d = e.to_dict()
        for k in ('event_type', 'symbol', 'data', 'timestamp', 'source'):
            assert k in d

    def test_timestamp_is_iso(self):
        d = self._make().to_dict()
        assert isinstance(d['timestamp'], str)

    def test_event_type_value_in_dict(self):
        e = self._make()
        d = e.to_dict()
        assert d['event_type'] == 'trade'


class TestEventBus:
    """Tests for EventBus."""

    def _bus(self):
        from data.streaming import EventBus
        return EventBus()

    def _event(self, symbol='XAUUSD', etype=None):
        from data.streaming import StreamEvent, StreamEventType
        return StreamEvent(
            event_type=etype or StreamEventType.TRADE,
            symbol=symbol,
            data={'price': 1950.0},
        )

    # ── basic publish / subscribe ────────────────────────────────

    def test_global_callback_receives_all_events(self):
        bus = self._bus()
        received = []
        bus.subscribe(received.append)
        bus.publish(self._event('XAUUSD'))
        bus.publish(self._event('EURUSD'))
        assert len(received) == 2

    def test_symbol_callback_receives_only_matching(self):
        from data.streaming import StreamEventType
        bus = self._bus()
        received = []
        bus.subscribe(received.append, symbol='XAUUSD')
        bus.publish(self._event('XAUUSD'))
        bus.publish(self._event('EURUSD'))
        assert len(received) == 1

    def test_event_type_callback_receives_only_matching(self):
        from data.streaming import StreamEventType
        bus = self._bus()
        received = []
        bus.subscribe(received.append, event_type=StreamEventType.TRADE)
        bus.publish(self._event(etype=StreamEventType.TRADE))
        bus.publish(self._event(etype=StreamEventType.QUOTE))
        assert len(received) == 1

    def test_unsubscribe(self):
        bus = self._bus()
        received = []
        bus.subscribe(received.append)
        bus.unsubscribe(received.append)
        bus.publish(self._event())
        assert len(received) == 0

    def test_callback_exception_does_not_crash_bus(self):
        bus = self._bus()

        def bad_cb(event):
            raise RuntimeError("oops")

        bus.subscribe(bad_cb)
        # Should not raise
        bus.publish(self._event())

    def test_stats_published_count(self):
        bus = self._bus()
        bus.subscribe(lambda e: None)
        bus.publish(self._event())
        bus.publish(self._event())
        stats = bus.get_stats()
        assert stats.get('published', 0) >= 2


class TestStreamConnection:
    """Tests for StreamConnection."""

    def _conn(self, name='test', url='wss://example.com/stream', **cfg):
        from data.streaming import StreamConnection, EventBus
        bus = EventBus()
        return StreamConnection(name=name, url=url, event_bus=bus,
                                connect_factory=None, config=cfg)

    def test_initial_state_disconnected(self):
        from data.streaming import ConnectionState
        conn = self._conn()
        assert conn.state == ConnectionState.DISCONNECTED

    def test_subscribe_adds_symbol(self):
        conn = self._conn()
        conn.subscribe('XAUUSD')
        status = conn.get_status()
        assert 'XAUUSD' in status.subscriptions

    def test_unsubscribe_removes_symbol(self):
        conn = self._conn()
        conn.subscribe('XAUUSD')
        conn.unsubscribe('XAUUSD')
        status = conn.get_status()
        assert 'XAUUSD' not in status.subscriptions

    def test_start_transitions_to_connected(self):
        from data.streaming import ConnectionState
        conn = self._conn()
        conn.start()
        time.sleep(0.1)
        assert conn.state == ConnectionState.CONNECTED
        conn.stop()

    def test_stop_transitions_to_closed(self):
        from data.streaming import ConnectionState
        conn = self._conn()
        conn.start()
        time.sleep(0.1)
        conn.stop()
        assert conn.state == ConnectionState.CLOSED

    def test_get_status_structure(self):
        conn = self._conn()
        status = conn.get_status()
        assert status.name == 'test'
        assert status.url == 'wss://example.com/stream'

    def test_connection_event_published(self):
        from data.streaming import StreamConnection, EventBus, StreamEventType
        bus = EventBus()
        received = []
        bus.subscribe(received.append, event_type=StreamEventType.CONNECTION)
        conn = StreamConnection(name='evt-test', url='wss://x',
                                event_bus=bus, connect_factory=None)
        conn.start()
        time.sleep(0.2)
        assert len(received) >= 1
        conn.stop()


class TestStreamingService:
    """Tests for StreamingService."""

    def _service(self):
        from data.streaming import StreamingService
        return StreamingService()

    # ── connection management ────────────────────────────────────

    def test_add_connection_returns_conn(self):
        from data.streaming import StreamConnection
        svc = self._service()
        conn = svc.add_connection('c1', 'wss://example.com')
        assert isinstance(conn, StreamConnection)

    def test_get_connection_status(self):
        svc = self._service()
        svc.add_connection('c1', 'wss://example.com')
        status = svc.get_connection_status('c1')
        assert status is not None
        assert status.name == 'c1'

    def test_get_connection_status_none_for_unknown(self):
        svc = self._service()
        assert svc.get_connection_status('no_such_conn') is None

    def test_start_stop_connection(self):
        from data.streaming import ConnectionState
        svc = self._service()
        svc.add_connection('c1', 'wss://example.com')
        svc.start_connection('c1')
        time.sleep(0.1)
        status = svc.get_connection_status('c1')
        assert status.state == ConnectionState.CONNECTED
        svc.stop_connection('c1')

    def test_start_unknown_connection_raises(self):
        svc = self._service()
        with pytest.raises(KeyError):
            svc.start_connection('ghost')

    def test_get_all_connection_statuses(self):
        svc = self._service()
        svc.add_connection('c1', 'wss://a.com')
        svc.add_connection('c2', 'wss://b.com')
        statuses = svc.get_all_connection_statuses()
        assert len(statuses) == 2

    # ── symbol subscriptions ─────────────────────────────────────

    def test_subscribe_symbol(self):
        svc = self._service()
        svc.subscribe_symbol('XAUUSD')
        subs = svc.get_subscriptions()
        assert any(s.symbol == 'XAUUSD' for s in subs)

    def test_unsubscribe_symbol(self):
        svc = self._service()
        svc.subscribe_symbol('XAUUSD')
        svc.unsubscribe_symbol('XAUUSD')
        subs = svc.get_subscriptions()
        assert not any(s.symbol == 'XAUUSD' for s in subs)

    # ── publish / subscribe ──────────────────────────────────────

    def test_publish_trade_fires_callback(self):
        from data.streaming import StreamEventType
        svc = self._service()
        received = []
        svc.subscribe(symbol='XAUUSD', callback=received.append,
                      event_type=StreamEventType.TRADE)
        svc.publish_trade('XAUUSD', price=1950.0, size=10.0, side='buy')
        assert len(received) == 1

    def test_publish_quote_fires_callback(self):
        from data.streaming import StreamEventType
        svc = self._service()
        received = []
        svc.subscribe(symbol='XAUUSD', callback=received.append,
                      event_type=StreamEventType.QUOTE)
        svc.publish_quote('XAUUSD', bid=1949.9, ask=1950.1)
        assert len(received) == 1

    def test_publish_increments_event_count(self):
        from data.streaming import StreamEventType
        svc = self._service()
        svc.subscribe_symbol('XAUUSD')
        svc.subscribe(symbol='XAUUSD', callback=lambda e: None)
        svc.publish_trade('XAUUSD', price=1950.0, size=10.0, side='buy')
        subs = svc.get_subscriptions()
        xau = next((s for s in subs if s.symbol == 'XAUUSD'), None)
        assert xau is not None
        assert xau.event_count >= 1

    def test_unsubscribe_callback(self):
        svc = self._service()
        received = []
        svc.subscribe(symbol='XAUUSD', callback=received.append)
        svc.unsubscribe(received.append, symbol='XAUUSD')
        svc.publish_trade('XAUUSD', price=1950.0, size=1.0, side='buy')
        assert len(received) == 0

    # ── get_stats ────────────────────────────────────────────────

    def test_get_stats_structure(self):
        svc = self._service()
        stats = svc.get_stats()
        assert 'connections' in stats
        assert 'subscriptions_count' in stats
        assert 'bus_stats' in stats

    # ── start_all / stop_all ─────────────────────────────────────

    def test_start_all_stop_all(self):
        from data.streaming import ConnectionState
        svc = self._service()
        svc.add_connection('c1', 'wss://a.com')
        svc.add_connection('c2', 'wss://b.com')
        svc.start_all()
        time.sleep(0.15)
        statuses = svc.get_all_connection_statuses()
        for s in statuses:
            assert s.state == ConnectionState.CONNECTED
        svc.stop_all()

    # ── subscription info ────────────────────────────────────────

    def test_subscription_info_to_dict(self):
        svc = self._service()
        svc.subscribe_symbol('XAUUSD')
        subs = svc.get_subscriptions()
        d = subs[0].to_dict()
        assert 'symbol' in d
        assert 'event_types' in d

    # ── singleton ────────────────────────────────────────────────

    def test_global_singleton(self):
        from data.streaming import get_streaming_service
        s1 = get_streaming_service()
        s2 = get_streaming_service()
        assert s1 is s2
