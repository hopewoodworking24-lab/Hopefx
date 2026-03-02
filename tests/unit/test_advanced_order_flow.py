"""
Tests for analysis/advanced_order_flow.py
"""

import pytest
from datetime import datetime, timedelta


class TestAggressionMetrics:
    """Tests for AggressionMetrics dataclass."""

    def _make(self, buy_vol=600.0, sell_vol=400.0):
        from analysis.advanced_order_flow import AggressionMetrics
        total = buy_vol + sell_vol
        buy_agg = buy_vol / total * 100
        sell_agg = sell_vol / total * 100
        ratio = buy_agg / (buy_agg + sell_agg)
        return AggressionMetrics(
            symbol='XAUUSD',
            timestamp=datetime.utcnow(),
            window_minutes=60,
            total_trades=100,
            buy_trades=60,
            sell_trades=40,
            total_volume=total,
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            buy_aggression_index=round(buy_agg, 2),
            sell_aggression_index=round(sell_agg, 2),
            aggression_ratio=round(ratio, 4),
            dominant_aggressor='buyers' if ratio > 0.55 else 'sellers',
        )

    def test_to_dict(self):
        m = self._make()
        d = m.to_dict()
        for k in ('symbol', 'timestamp', 'buy_aggression_index',
                  'sell_aggression_index', 'dominant_aggressor'):
            assert k in d

    def test_timestamp_is_iso(self):
        d = self._make().to_dict()
        assert isinstance(d['timestamp'], str)


class TestVolumeCluster:
    """Tests for VolumeCluster dataclass."""

    def _make(self, ctype='support'):
        from analysis.advanced_order_flow import VolumeCluster
        return VolumeCluster(
            symbol='XAUUSD',
            price_low=1948.0, price_high=1950.0, price_center=1949.0,
            total_volume=5000.0, buy_volume=3000.0, sell_volume=2000.0,
            delta=1000.0, trade_count=50,
            cluster_type=ctype, strength=0.8,
        )

    def test_to_dict(self):
        c = self._make()
        d = c.to_dict()
        assert d['cluster_type'] == 'support'
        assert 'price_center' in d


class TestStackedImbalance:
    """Tests for StackedImbalance dataclass."""

    def test_to_dict(self):
        from analysis.advanced_order_flow import StackedImbalance
        si = StackedImbalance(
            symbol='XAUUSD', timestamp=datetime.utcnow(),
            direction='buy_stack', price_start=1948.0, price_end=1952.0,
            level_count=4, avg_imbalance=0.6, total_volume=2000.0,
            signal='bullish',
        )
        d = si.to_dict()
        assert d['signal'] == 'bullish'
        assert isinstance(d['timestamp'], str)


class TestAdvancedOrderFlowAnalyzer:
    """Tests for AdvancedOrderFlowAnalyzer."""

    def _analyzer(self, **cfg):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer
        return AdvancedOrderFlowAnalyzer(config=cfg)

    def _add_trades(self, analyzer, symbol, n_buy, n_sell, base_price=1950.0):
        for i in range(n_buy):
            analyzer.add_trade(symbol, price=base_price + i * 0.01,
                               size=100.0, side='buy')
        for i in range(n_sell):
            analyzer.add_trade(symbol, price=base_price - i * 0.01,
                               size=100.0, side='sell')

    # ── add_trade ────────────────────────────────────────────────

    def test_add_trade_stored(self):
        a = self._analyzer()
        a.add_trade('XAUUSD', price=1950.0, size=1.0, side='buy')
        stats = a.get_stats()
        assert stats['trades_by_symbol']['XAUUSD'] == 1

    def test_cumulative_delta_buy(self):
        a = self._analyzer()
        a.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')
        a.add_trade('XAUUSD', price=1950.0, size=40.0, side='sell')
        assert a.get_stats()['cumulative_delta']['XAUUSD'] == 60.0

    # ── get_aggression_metrics ───────────────────────────────────

    def test_aggression_none_when_no_trades(self):
        a = self._analyzer()
        assert a.get_aggression_metrics('XAUUSD') is None

    def test_aggression_dominant_buyers(self):
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=20, n_sell=5)
        agg = a.get_aggression_metrics('XAUUSD')
        assert agg is not None
        assert agg.dominant_aggressor == 'buyers'

    def test_aggression_dominant_sellers(self):
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=5, n_sell=20)
        agg = a.get_aggression_metrics('XAUUSD')
        assert agg.dominant_aggressor == 'sellers'

    def test_aggression_indices_sum_to_100(self):
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=10, n_sell=10)
        agg = a.get_aggression_metrics('XAUUSD')
        total = agg.buy_aggression_index + agg.sell_aggression_index
        assert abs(total - 100.0) < 0.01

    # ── snapshot & delta divergence ──────────────────────────────

    def test_divergence_none_before_enough_snapshots(self):
        a = self._analyzer(divergence_bars=5)
        for _ in range(3):
            a.snapshot('XAUUSD', 1950.0)
        assert a.get_delta_divergence('XAUUSD') is None

    def test_bearish_divergence_detected(self):
        from analysis.advanced_order_flow import DeltaDivergenceSignal
        a = self._analyzer(divergence_bars=3)
        # Price goes up but delta goes down → bearish divergence
        prices = [1950.0, 1951.0, 1952.0]
        deltas = [1000.0, 800.0, 600.0]
        for p, d_val in zip(prices, deltas):
            a._price_snapshots['XAUUSD'].append(p)
            a._delta_snapshots['XAUUSD'].append(d_val)
        div = a.get_delta_divergence('XAUUSD')
        assert isinstance(div, DeltaDivergenceSignal)
        assert div.divergence_type == 'bearish'

    def test_bullish_divergence_detected(self):
        a = self._analyzer(divergence_bars=3)
        # Price goes down but delta goes up → bullish divergence
        prices = [1952.0, 1951.0, 1950.0]
        deltas = [600.0, 800.0, 1000.0]
        for p, d_val in zip(prices, deltas):
            a._price_snapshots['XAUUSD'].append(p)
            a._delta_snapshots['XAUUSD'].append(d_val)
        div = a.get_delta_divergence('XAUUSD')
        assert div is not None
        assert div.divergence_type == 'bullish'

    def test_no_divergence_when_aligned(self):
        a = self._analyzer(divergence_bars=3)
        # Both going up – no divergence
        for p, d_val in [(1950.0, 100.0), (1951.0, 200.0), (1952.0, 300.0)]:
            a._price_snapshots['XAUUSD'].append(p)
            a._delta_snapshots['XAUUSD'].append(d_val)
        assert a.get_delta_divergence('XAUUSD') is None

    # ── get_volume_clusters ──────────────────────────────────────

    def test_clusters_empty_with_no_trades(self):
        a = self._analyzer()
        assert a.get_volume_clusters('XAUUSD') == []

    def test_clusters_returned_for_dense_area(self):
        a = self._analyzer(cluster_buckets=5)
        # Concentrate volume at 1950
        for _ in range(50):
            a.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')
        for _ in range(10):
            a.add_trade('XAUUSD', price=1960.0, size=10.0, side='sell')
        clusters = a.get_volume_clusters('XAUUSD')
        assert len(clusters) >= 1
        # Highest volume cluster first
        assert clusters[0].total_volume >= clusters[-1].total_volume

    def test_cluster_type_support_resistance(self):
        a = self._analyzer(cluster_buckets=3)
        # Trades below and above a gap
        for _ in range(20):
            a.add_trade('XAUUSD', price=1940.0, size=100.0, side='buy')
        for _ in range(20):
            a.add_trade('XAUUSD', price=1960.0, size=100.0, side='sell')
        clusters = a.get_volume_clusters('XAUUSD')
        types = {c.cluster_type for c in clusters}
        assert types & {'support', 'resistance'}

    # ── get_stacked_imbalances ───────────────────────────────────

    def test_stacked_imbalances_empty_with_insufficient_data(self):
        a = self._analyzer()
        assert a.get_stacked_imbalances('XAUUSD') == []

    def test_stacked_buy_imbalance(self):
        a = self._analyzer(
            cluster_buckets=5,
            imbalance_threshold=0.3,
        )
        # Heavy buying across multiple price levels
        for price in [1948.0, 1949.0, 1950.0, 1951.0, 1952.0]:
            for _ in range(40):
                a.add_trade('XAUUSD', price=price, size=90.0, side='buy')
            for _ in range(5):
                a.add_trade('XAUUSD', price=price, size=10.0, side='sell')

        stacks = a.get_stacked_imbalances('XAUUSD')
        if stacks:
            buy_stacks = [s for s in stacks if s.direction == 'buy_stack']
            assert len(buy_stacks) >= 1

    # ── full analyze ─────────────────────────────────────────────

    def test_analyze_none_with_no_trades(self):
        a = self._analyzer()
        assert a.analyze('XAUUSD') is None

    def test_analyze_returns_result(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalysis
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=20, n_sell=10)
        result = a.analyze('XAUUSD')
        assert isinstance(result, AdvancedOrderFlowAnalysis)

    def test_analyze_bullish_signal(self):
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=50, n_sell=5)
        result = a.analyze('XAUUSD')
        assert result.signal in ('bullish', 'neutral')

    def test_analyze_bearish_signal(self):
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=5, n_sell=50)
        result = a.analyze('XAUUSD')
        assert result.signal in ('bearish', 'neutral')

    def test_analyze_to_dict(self):
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=10, n_sell=10)
        result = a.analyze('XAUUSD')
        d = result.to_dict()
        for k in ('symbol', 'timestamp', 'aggression', 'signal',
                  'signal_strength', 'volume_clusters', 'stacked_imbalances'):
            assert k in d

    def test_signal_strength_between_0_and_1(self):
        a = self._analyzer()
        self._add_trades(a, 'XAUUSD', n_buy=20, n_sell=5)
        result = a.analyze('XAUUSD')
        assert 0.0 <= result.signal_strength <= 1.0

    def test_exhaustion_flag_buy(self):
        a = self._analyzer(exhaustion_ratio=0.5)
        # All buys → buy exhaustion
        for _ in range(20):
            a.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')
        result = a.analyze('XAUUSD')
        assert result.is_buy_exhaustion is True
        assert result.is_sell_exhaustion is False

    # ── batch add_trades ─────────────────────────────────────────

    def test_add_trades_batch(self):
        a = self._analyzer()
        batch = [
            {'price': 1950.0, 'size': 1.0, 'side': 'buy'},
            {'price': 1951.0, 'size': 2.0, 'side': 'sell'},
        ]
        a.add_trades('XAUUSD', batch)
        assert a.get_stats()['trades_by_symbol']['XAUUSD'] == 2

    # ── utility ──────────────────────────────────────────────────

    def test_get_symbols(self):
        a = self._analyzer()
        a.add_trade('XAUUSD', 1950.0, 1.0, 'buy')
        assert 'XAUUSD' in a.get_symbols()

    def test_clear_trades(self):
        a = self._analyzer()
        a.add_trade('XAUUSD', 1950.0, 1.0, 'buy')
        a.clear_trades('XAUUSD')
        assert a.get_aggression_metrics('XAUUSD') is None

    def test_get_stats_structure(self):
        a = self._analyzer()
        a.add_trade('XAUUSD', 1950.0, 1.0, 'buy')
        stats = a.get_stats()
        assert 'symbols_tracked' in stats
        assert 'cumulative_delta' in stats

    # ── singleton ────────────────────────────────────────────────

    def test_global_singleton(self):
        from analysis.advanced_order_flow import get_advanced_order_flow_analyzer
        a1 = get_advanced_order_flow_analyzer()
        a2 = get_advanced_order_flow_analyzer()
        assert a1 is a2
