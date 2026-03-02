"""
Tests for analysis/institutional_flow.py
"""

import pytest
from datetime import datetime, timedelta


class TestInstitutionalTrade:
    """Tests for InstitutionalTrade dataclass."""

    def _make(self, **kwargs):
        from analysis.institutional_flow import InstitutionalTrade
        defaults = dict(
            timestamp=datetime.utcnow(),
            symbol='XAUUSD',
            price=1950.0,
            size=2000.0,
            side='buy',
            trade_type='large_order',
            confidence=0.9,
        )
        defaults.update(kwargs)
        return InstitutionalTrade(**defaults)

    def test_notional(self):
        t = self._make(price=2000.0, size=500.0)
        assert t.notional == 1_000_000.0

    def test_to_dict_keys(self):
        t = self._make()
        d = t.to_dict()
        for k in ('timestamp', 'symbol', 'price', 'size', 'side',
                  'trade_type', 'confidence', 'notional'):
            assert k in d


class TestVolumeSpike:
    """Tests for VolumeSpike dataclass."""

    def test_to_dict(self):
        from analysis.institutional_flow import VolumeSpike
        spike = VolumeSpike(
            symbol='XAUUSD', timestamp=datetime.utcnow(),
            volume=999.0, average_volume=100.0, std_volume=50.0,
            sigma=3.5, side='buy', price=1950.0,
        )
        d = spike.to_dict()
        assert d['sigma'] == 3.5
        assert isinstance(d['timestamp'], str)


class TestIcebergSignal:
    """Tests for IcebergSignal dataclass."""

    def test_to_dict(self):
        from analysis.institutional_flow import IcebergSignal
        sig = IcebergSignal(
            symbol='XAUUSD', price=1950.0, side='buy',
            print_count=5, total_volume=500.0,
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            confidence=0.8,
        )
        d = sig.to_dict()
        assert d['print_count'] == 5


class TestInstitutionalFlowDetector:
    """Tests for InstitutionalFlowDetector."""

    def _detector(self, **cfg):
        from analysis.institutional_flow import InstitutionalFlowDetector
        return InstitutionalFlowDetector(config=cfg)

    # ── large order detection ────────────────────────────────────

    def test_large_order_detected(self):
        det = self._detector(institutional_threshold=500.0)
        det.add_trade('XAUUSD', price=1950.0, size=1000.0, side='buy')
        trades = det.get_institutional_trades('XAUUSD')
        assert len(trades) == 1
        assert trades[0].trade_type in ('large_order', 'block')

    def test_small_order_not_detected(self):
        det = self._detector(institutional_threshold=500.0)
        det.add_trade('XAUUSD', price=1950.0, size=1.0, side='buy')
        assert len(det.get_institutional_trades('XAUUSD')) == 0

    def test_block_trade_classified(self):
        det = self._detector(institutional_threshold=100.0)
        # block = >= threshold * 10
        det.add_trade('XAUUSD', price=1950.0, size=5000.0, side='buy')
        trades = det.get_institutional_trades('XAUUSD')
        assert trades[0].trade_type == 'block'

    def test_confidence_between_0_and_1(self):
        det = self._detector(institutional_threshold=100.0)
        det.add_trade('XAUUSD', price=1950.0, size=500.0, side='buy')
        trade = det.get_institutional_trades('XAUUSD')[0]
        assert 0.0 <= trade.confidence <= 1.0

    def test_multiple_symbols(self):
        det = self._detector(institutional_threshold=50.0)
        det.add_trade('XAUUSD', price=1950.0, size=1000.0, side='buy')
        det.add_trade('EURUSD', price=1.08, size=500.0, side='sell')
        assert len(det.get_institutional_trades('XAUUSD')) >= 1
        assert len(det.get_institutional_trades('EURUSD')) >= 1

    # ── volume spike detection ───────────────────────────────────

    def test_spike_detected(self):
        det = self._detector(spike_sigma=2.0)
        # Establish baseline
        for _ in range(20):
            det.add_trade('XAUUSD', price=1950.0, size=1.0, side='buy')
        # Spike
        det.add_trade('XAUUSD', price=1950.0, size=1000.0, side='buy')
        spikes = det.get_volume_spikes('XAUUSD')
        assert len(spikes) >= 1
        assert spikes[-1].sigma >= 2.0

    def test_no_spike_without_enough_samples(self):
        det = self._detector(spike_sigma=3.0)
        # Only 5 samples – below minimum of 10
        for _ in range(5):
            det.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')
        assert len(det.get_volume_spikes('XAUUSD')) == 0

    # ── iceberg detection ────────────────────────────────────────

    def test_iceberg_detected(self):
        det = self._detector(
            iceberg_min_prints=3,
            iceberg_window=300,
        )
        # 5 prints at the same price level
        for _ in range(5):
            det.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')
        icebergs = det.get_icebergs('XAUUSD')
        assert len(icebergs) >= 1

    def test_iceberg_confidence_between_0_and_1(self):
        det = self._detector(iceberg_min_prints=3, iceberg_window=300)
        for _ in range(6):
            det.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')
        for ic in det.get_icebergs('XAUUSD'):
            assert 0.0 <= ic.confidence <= 1.0

    # ── smart money flow ─────────────────────────────────────────

    def test_smart_money_flow_none_when_no_activity(self):
        det = self._detector()
        assert det.get_smart_money_flow('XAUUSD') is None

    def test_smart_money_flow_accumulation(self):
        from analysis.institutional_flow import SmartMoneyFlow
        det = self._detector(institutional_threshold=100.0)
        for _ in range(10):
            det.add_trade('XAUUSD', price=1950.0, size=500.0, side='buy')
        flow = det.get_smart_money_flow('XAUUSD')
        assert isinstance(flow, SmartMoneyFlow)
        assert flow.flow_score > 0
        assert flow.signal == 'accumulation'

    def test_smart_money_flow_distribution(self):
        det = self._detector(institutional_threshold=100.0)
        for _ in range(10):
            det.add_trade('XAUUSD', price=1950.0, size=500.0, side='sell')
        flow = det.get_smart_money_flow('XAUUSD')
        assert flow.flow_score < 0
        assert flow.signal == 'distribution'

    def test_smart_money_flow_to_dict(self):
        det = self._detector(institutional_threshold=100.0)
        det.add_trade('XAUUSD', price=1950.0, size=500.0, side='buy')
        flow = det.get_smart_money_flow('XAUUSD')
        d = flow.to_dict()
        assert 'flow_score' in d
        assert 'signal' in d

    # ── batch add_trades ─────────────────────────────────────────

    def test_add_trades_batch(self):
        det = self._detector(institutional_threshold=50.0)
        trades = [
            {'price': 1950.0, 'size': 100.0, 'side': 'buy'},
            {'price': 1951.0, 'size': 200.0, 'side': 'sell'},
        ]
        det.add_trades('XAUUSD', trades)
        assert len(det.get_institutional_trades('XAUUSD')) == 2

    # ── utility ──────────────────────────────────────────────────

    def test_get_symbols(self):
        det = self._detector()
        det.add_trade('XAUUSD', 1950.0, 1.0, 'buy')
        assert 'XAUUSD' in det.get_symbols()

    def test_clear_symbol(self):
        det = self._detector(institutional_threshold=10.0)
        det.add_trade('XAUUSD', 1950.0, 100.0, 'buy')
        det.clear_symbol('XAUUSD')
        assert det.get_institutional_trades('XAUUSD') == []

    def test_get_stats(self):
        det = self._detector()
        det.add_trade('XAUUSD', 1950.0, 1.0, 'buy')
        stats = det.get_stats()
        assert 'symbols_tracked' in stats

    # ── singleton ────────────────────────────────────────────────

    def test_global_singleton(self):
        from analysis.institutional_flow import get_institutional_flow_detector
        d1 = get_institutional_flow_detector()
        d2 = get_institutional_flow_detector()
        assert d1 is d2
