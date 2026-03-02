"""
Tests for data/time_and_sales.py
"""

import time
import pytest
from datetime import datetime, timedelta


class TestAggressor:
    """Tests for Aggressor enum."""

    def test_values(self):
        from data.time_and_sales import Aggressor
        assert Aggressor.BUY.value == "buy"
        assert Aggressor.SELL.value == "sell"
        assert Aggressor.UNKNOWN.value == "unknown"


class TestTimeAndSalesRecord:
    """Tests for TimeAndSalesRecord dataclass."""

    def _make(self, **kwargs):
        from data.time_and_sales import TimeAndSalesRecord, Aggressor
        defaults = dict(
            timestamp=datetime.utcnow(),
            symbol='XAUUSD',
            price=1950.0,
            size=10.0,
            aggressor=Aggressor.BUY,
        )
        defaults.update(kwargs)
        return TimeAndSalesRecord(**defaults)

    def test_is_buy_true(self):
        from data.time_and_sales import Aggressor
        r = self._make(aggressor=Aggressor.BUY)
        assert r.is_buy is True
        assert r.is_sell is False

    def test_is_sell_true(self):
        from data.time_and_sales import Aggressor
        r = self._make(aggressor=Aggressor.SELL)
        assert r.is_sell is True
        assert r.is_buy is False

    def test_notional(self):
        r = self._make(price=2000.0, size=5.0)
        assert r.notional == 10_000.0

    def test_to_dict_contains_required_keys(self):
        r = self._make()
        d = r.to_dict()
        for key in ('timestamp', 'symbol', 'price', 'size', 'aggressor',
                    'is_buy', 'is_sell', 'notional'):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_timestamp_is_iso_string(self):
        r = self._make()
        d = r.to_dict()
        assert isinstance(d['timestamp'], str)


class TestTimeAndSalesService:
    """Tests for TimeAndSalesService."""

    def _service(self, **cfg):
        from data.time_and_sales import TimeAndSalesService
        return TimeAndSalesService(config=cfg)

    # ── add_trade ──────────────────────────────────────────────────

    def test_add_trade_returns_record(self):
        from data.time_and_sales import TimeAndSalesRecord
        svc = self._service()
        r = svc.add_trade('XAUUSD', price=1950.0, size=1.0, aggressor='buy')
        assert isinstance(r, TimeAndSalesRecord)

    def test_add_trade_stored(self):
        svc = self._service()
        svc.add_trade('XAUUSD', price=1950.0, size=1.0, aggressor='buy')
        tape = svc.get_tape('XAUUSD', limit=10)
        assert len(tape) == 1

    def test_add_multiple_trades(self):
        svc = self._service()
        for i in range(5):
            svc.add_trade('XAUUSD', price=1950.0 + i, size=1.0, aggressor='buy')
        assert len(svc.get_tape('XAUUSD')) == 5

    def test_buffer_circular(self):
        svc = self._service(buffer_size=5)
        for i in range(10):
            svc.add_trade('XAUUSD', price=float(i), size=1.0, aggressor='buy')
        tape = svc.get_tape('XAUUSD', limit=100)
        assert len(tape) == 5

    # ── aggressor inference ────────────────────────────────────────

    def test_aggressor_explicit_buy(self):
        from data.time_and_sales import Aggressor
        svc = self._service()
        r = svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        assert r.aggressor == Aggressor.BUY

    def test_aggressor_explicit_sell(self):
        from data.time_and_sales import Aggressor
        svc = self._service()
        r = svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='sell')
        assert r.aggressor == Aggressor.SELL

    def test_aggressor_inferred_buy_from_bid_ask(self):
        from data.time_and_sales import Aggressor
        svc = self._service()
        # price == ask → buy aggressor
        r = svc.add_trade('XAUUSD', 1950.05, 1.0, aggressor='unknown',
                          bid=1949.95, ask=1950.05)
        assert r.aggressor == Aggressor.BUY

    def test_aggressor_inferred_sell_from_bid_ask(self):
        from data.time_and_sales import Aggressor
        svc = self._service()
        r = svc.add_trade('XAUUSD', 1949.95, 1.0, aggressor='unknown',
                          bid=1949.95, ask=1950.05)
        assert r.aggressor == Aggressor.SELL

    # ── large trade detection ──────────────────────────────────────

    def test_large_trade_flagged(self):
        svc = self._service(large_trade_multiplier=3.0)
        # Establish baseline with small trades
        for _ in range(20):
            svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        # Large trade
        r = svc.add_trade('XAUUSD', 1950.0, 100.0, aggressor='buy')
        assert r.is_large is True

    def test_normal_trade_not_large(self):
        svc = self._service(large_trade_multiplier=5.0)
        for _ in range(10):
            svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        r = svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        assert r.is_large is False

    # ── get_tape filtering ─────────────────────────────────────────

    def test_get_tape_limit(self):
        svc = self._service()
        for _ in range(20):
            svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        assert len(svc.get_tape('XAUUSD', limit=5)) == 5

    def test_get_tape_empty_symbol(self):
        svc = self._service()
        assert svc.get_tape('NOSUCHSYMBOL') == []

    def test_get_tape_time_filter(self):
        svc = self._service()
        old_ts = datetime.utcnow() - timedelta(hours=2)
        svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy', timestamp=old_ts)
        svc.add_trade('XAUUSD', 1950.0, 2.0, aggressor='buy')  # now

        cutoff = datetime.utcnow() - timedelta(minutes=5)
        tape = svc.get_tape('XAUUSD', limit=100, start_time=cutoff)
        assert len(tape) == 1
        assert tape[0].size == 2.0

    # ── get_large_trades ──────────────────────────────────────────

    def test_get_large_trades_returns_only_large(self):
        svc = self._service(large_trade_multiplier=3.0)
        for _ in range(20):
            svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        svc.add_trade('XAUUSD', 1950.0, 999.0, aggressor='buy')
        large = svc.get_large_trades('XAUUSD')
        assert all(r.is_large for r in large)
        assert len(large) >= 1

    # ── get_velocity ──────────────────────────────────────────────

    def test_get_velocity_none_when_no_trades(self):
        svc = self._service()
        assert svc.get_velocity('XAUUSD') is None

    def test_get_velocity_returns_metrics(self):
        from data.time_and_sales import TradeVelocity
        svc = self._service()
        for i in range(10):
            svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        vel = svc.get_velocity('XAUUSD')
        assert isinstance(vel, TradeVelocity)
        assert vel.trade_count == 10
        assert vel.total_volume == 10.0

    def test_get_velocity_dominant_buy(self):
        svc = self._service()
        for _ in range(10):
            svc.add_trade('XAUUSD', 1950.0, 10.0, aggressor='buy')
        for _ in range(2):
            svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='sell')
        vel = svc.get_velocity('XAUUSD')
        assert vel.dominant_side == 'buy'

    def test_get_velocity_dominant_sell(self):
        svc = self._service()
        for _ in range(10):
            svc.add_trade('XAUUSD', 1950.0, 10.0, aggressor='sell')
        for _ in range(2):
            svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        vel = svc.get_velocity('XAUUSD')
        assert vel.dominant_side == 'sell'

    # ── get_statistics ────────────────────────────────────────────

    def test_get_statistics_none_when_no_trades(self):
        svc = self._service()
        assert svc.get_statistics('XAUUSD') is None

    def test_get_statistics_vwap(self):
        from data.time_and_sales import TapeStatistics
        svc = self._service()
        svc.add_trade('XAUUSD', 1950.0, 2.0, aggressor='buy')
        svc.add_trade('XAUUSD', 1952.0, 2.0, aggressor='sell')
        stats = svc.get_statistics('XAUUSD')
        assert isinstance(stats, TapeStatistics)
        # VWAP = (1950*2 + 1952*2) / 4 = 1951.0
        assert abs(stats.vwap - 1951.0) < 0.01

    def test_get_statistics_delta(self):
        svc = self._service()
        svc.add_trade('XAUUSD', 1950.0, 5.0, aggressor='buy')
        svc.add_trade('XAUUSD', 1950.0, 2.0, aggressor='sell')
        stats = svc.get_statistics('XAUUSD')
        assert stats.delta == 3.0

    # ── callbacks ────────────────────────────────────────────────

    def test_callback_fires_on_trade(self):
        svc = self._service()
        received = []
        svc.register_callback(received.append, symbol='XAUUSD')
        svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        assert len(received) == 1

    def test_global_callback_fires_for_all_symbols(self):
        svc = self._service()
        received = []
        svc.register_callback(received.append)
        svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        svc.add_trade('EURUSD', 1.08, 100.0, aggressor='sell')
        assert len(received) == 2

    def test_unregister_callback(self):
        svc = self._service()
        received = []
        svc.register_callback(received.append, symbol='XAUUSD')
        svc.unregister_callback(received.append, symbol='XAUUSD')
        svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        assert len(received) == 0

    # ── utility ──────────────────────────────────────────────────

    def test_get_symbols(self):
        svc = self._service()
        svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        svc.add_trade('EURUSD', 1.08, 100.0, aggressor='sell')
        syms = svc.get_symbols()
        assert 'XAUUSD' in syms
        assert 'EURUSD' in syms

    def test_clear_symbol(self):
        svc = self._service()
        svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        svc.clear_symbol('XAUUSD')
        assert svc.get_tape('XAUUSD') == []

    def test_get_stats(self):
        svc = self._service()
        svc.add_trade('XAUUSD', 1950.0, 1.0, aggressor='buy')
        stats = svc.get_stats()
        assert 'symbols_tracked' in stats
        assert stats['symbols_tracked'] == 1

    # ── add_trades (batch) ───────────────────────────────────────

    def test_add_trades_batch(self):
        svc = self._service()
        batch = [
            {'price': 1950.0, 'size': 1.0, 'aggressor': 'buy'},
            {'price': 1951.0, 'size': 2.0, 'aggressor': 'sell'},
        ]
        records = svc.add_trades('XAUUSD', batch)
        assert len(records) == 2
        assert len(svc.get_tape('XAUUSD')) == 2

    # ── singleton ────────────────────────────────────────────────

    def test_global_singleton(self):
        from data.time_and_sales import get_time_and_sales_service
        s1 = get_time_and_sales_service()
        s2 = get_time_and_sales_service()
        assert s1 is s2
