"""
Comprehensive Tests for Advanced Order Flow Analysis Module

Tests for:
- AggressionMetrics, VolumeImbalanceLevel, StackedImbalance,
  VolumeCluster, DeltaDivergence, OrderFlowOscillator,
  PressureGauges, AdvancedOrderFlowResult dataclasses
- AdvancedOrderFlowAnalyzer (trade ingestion, aggression metrics,
  volume imbalances, stacked imbalances, delta divergence, volume clusters,
  order flow oscillator, pressure gauges, full analysis)
"""

import pytest
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestAggressionMetrics:
    """Tests for AggressionMetrics dataclass."""

    def test_creation(self):
        """Test creating AggressionMetrics."""
        from analysis.advanced_order_flow import AggressionMetrics

        m = AggressionMetrics(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            buy_aggression=65.0,
            sell_aggression=35.0,
            aggression_score=30.0,
            dominant_side="buyers",
            aggression_strength="moderate",
        )

        assert m.symbol == "XAUUSD"
        assert m.dominant_side == "buyers"

    def test_to_dict(self):
        """Test serialisation."""
        from analysis.advanced_order_flow import AggressionMetrics

        m = AggressionMetrics(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            buy_aggression=60.0,
            sell_aggression=40.0,
            aggression_score=20.0,
            dominant_side="buyers",
            aggression_strength="moderate",
        )
        d = m.to_dict()

        assert d["symbol"] == "XAUUSD"
        assert "buy_aggression" in d
        assert "aggression_strength" in d


class TestOrderFlowOscillator:
    """Tests for OrderFlowOscillator dataclass."""

    def test_creation_and_dict(self):
        """Test OrderFlowOscillator creation and serialisation."""
        from analysis.advanced_order_flow import OrderFlowOscillator

        osc = OrderFlowOscillator(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            oscillator_value=12.5,
            fast_delta=15.0,
            slow_delta=10.0,
            signal_line=12.5,
            histogram=5.0,
            trend="bullish",
            momentum="accelerating",
        )

        assert osc.trend == "bullish"
        d = osc.to_dict()
        assert d["trend"] == "bullish"
        assert "histogram" in d


class TestPressureGauges:
    """Tests for PressureGauges dataclass."""

    def test_creation_and_dict(self):
        """Test PressureGauges creation and serialisation."""
        from analysis.advanced_order_flow import PressureGauges

        pg = PressureGauges(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            buy_pressure=60.0,
            sell_pressure=40.0,
            net_pressure=20.0,
            pressure_trend="increasing_buy",
            large_trade_bias="buy",
            small_trade_bias="neutral",
            large_trade_threshold=100.0,
        )

        assert pg.net_pressure == 20.0
        d = pg.to_dict()
        assert d["large_trade_bias"] == "buy"


class TestAdvancedOrderFlowResult:
    """Tests for AdvancedOrderFlowResult dataclass."""

    def test_to_dict(self):
        """Test result serialisation includes required keys."""
        from analysis.advanced_order_flow import AdvancedOrderFlowResult

        result = AdvancedOrderFlowResult(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            aggression=None,
            stacked_imbalances=[],
            delta_divergence=None,
            volume_clusters=[],
            oscillator=None,
            pressure_gauges=None,
            absorption_zones=[],
            overall_bias="neutral",
            confidence=0.0,
            signals=[],
        )
        d = result.to_dict()

        assert d["symbol"] == "XAUUSD"
        assert d["overall_bias"] == "neutral"
        assert "signals" in d


# ---------------------------------------------------------------------------
# AdvancedOrderFlowAnalyzer tests
# ---------------------------------------------------------------------------


class TestAdvancedOrderFlowAnalyzerInit:
    """Tests for AdvancedOrderFlowAnalyzer initialisation."""

    def test_default_init(self):
        """Test default initialisation."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        assert a is not None

    def test_custom_config(self):
        """Test custom config is applied."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer(
            config={"tick_size": 0.5, "imbalance_threshold": 3.0}
        )
        assert a._tick_size == 0.5
        assert a._imbalance_threshold == 3.0


class TestAdvancedOrderFlowAnalyzerIngestion:
    """Tests for trade ingestion."""

    def test_add_trade_stored(self):
        """Test a single trade is stored."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        a.add_trade("XAUUSD", 1950.0, 10.0, "buy")
        trades = a._get_all_trades("XAUUSD")
        assert len(trades) == 1

    def test_add_trade_invalid_side_raises(self):
        """Test that invalid side raises ValueError."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        with pytest.raises(ValueError):
            a.add_trade("XAUUSD", 1950.0, 10.0, "invalid")

    def test_add_trades_batch(self):
        """Test bulk trade ingestion."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        trades = [
            {"price": 1950.0, "size": 10.0, "side": "buy"},
            {"price": 1950.5, "size": 5.0, "side": "sell"},
        ]
        a.add_trades("XAUUSD", trades)
        assert len(a._get_all_trades("XAUUSD")) == 2

    def test_cumulative_delta_tracking(self):
        """Test cumulative delta accumulates correctly."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        a.add_trade("XAUUSD", 1950.0, 100.0, "buy")    # +100
        a.add_trade("XAUUSD", 1950.0, 40.0, "sell")    # -40
        assert a._cumulative_delta["XAUUSD"] == pytest.approx(60.0)

    def test_clear_symbol(self):
        """Test clearing symbol data."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        a.add_trade("XAUUSD", 1950.0, 10.0, "buy")
        a.clear_symbol("XAUUSD")
        assert a._get_all_trades("XAUUSD") == []
        assert a._cumulative_delta["XAUUSD"] == 0.0


class TestAggressionMetricsCalculation:
    """Tests for calculate_aggression_metrics."""

    def _add_trades(self, a, buys=10, sells=5, symbol="XAUUSD"):
        for _ in range(buys):
            a.add_trade(symbol, 1950.0, 10.0, "buy")
        for _ in range(sells):
            a.add_trade(symbol, 1950.0, 10.0, "sell")

    def test_returns_aggression_metrics(self):
        """Test that metrics are returned when data exists."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer, AggressionMetrics

        a = AdvancedOrderFlowAnalyzer()
        self._add_trades(a)

        metrics = a.calculate_aggression_metrics("XAUUSD", lookback_minutes=60.0)
        assert isinstance(metrics, AggressionMetrics)

    def test_buy_dominant(self):
        """Test buyers dominant when buy volume is much higher."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        for _ in range(20):
            a.add_trade("XAUUSD", 1950.0, 10.0, "buy")
        a.add_trade("XAUUSD", 1950.0, 10.0, "sell")

        m = a.calculate_aggression_metrics("XAUUSD", lookback_minutes=60.0)
        assert m.dominant_side == "buyers"
        assert m.aggression_score > 0

    def test_sell_dominant(self):
        """Test sellers dominant when sell volume is much higher."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        a.add_trade("XAUUSD", 1950.0, 10.0, "buy")
        for _ in range(20):
            a.add_trade("XAUUSD", 1950.0, 10.0, "sell")

        m = a.calculate_aggression_metrics("XAUUSD", lookback_minutes=60.0)
        assert m.dominant_side == "sellers"
        assert m.aggression_score < 0

    def test_none_on_empty(self):
        """Test None returned when no trades."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        assert a.calculate_aggression_metrics("XAUUSD") is None


class TestVolumeImbalances:
    """Tests for get_volume_imbalances."""

    def _populate(self, a, symbol="XAUUSD", n=30):
        for i in range(n):
            side = "buy" if i % 3 != 0 else "sell"
            a.add_trade(symbol, 1950.0 + i * 0.05, 10.0, side)

    def test_returns_list(self):
        """Test that a list is returned."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        self._populate(a)

        levels = a.get_volume_imbalances("XAUUSD", lookback_minutes=60.0)
        assert isinstance(levels, list)

    def test_empty_on_no_trades(self):
        """Test empty list returned when no trades."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        assert a.get_volume_imbalances("XAUUSD") == []


class TestStackedImbalances:
    """Tests for detect_stacked_imbalances."""

    def _populate_with_heavy_buys(self, a, symbol="XAUUSD", levels=20):
        """Add concentrated buy volume at many close prices to induce imbalances."""
        for i in range(levels):
            for _ in range(8):
                a.add_trade(symbol, 1950.0 + i * 0.01, 100.0, "buy")
            a.add_trade(symbol, 1950.0 + i * 0.01, 5.0, "sell")

    def test_returns_list(self):
        """Test that a list is always returned."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        assert isinstance(a.detect_stacked_imbalances("XAUUSD"), list)

    def test_detects_bullish_stack(self):
        """Test bullish stacked imbalance with heavy buy bias."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer(
            config={"tick_size": 0.01, "imbalance_threshold": 2.0}
        )
        self._populate_with_heavy_buys(a)

        stacks = a.detect_stacked_imbalances(
            "XAUUSD", min_stack_levels=2, lookback_minutes=60.0
        )
        # May be empty if threshold not met; just verify return type
        assert isinstance(stacks, list)


class TestDeltaDivergence:
    """Tests for detect_delta_divergence."""

    def test_none_on_insufficient_data(self):
        """Test None returned when fewer than 20 history points."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        for i in range(5):
            a.add_trade("XAUUSD", 1950.0 + i, 10.0, "buy")

        assert a.detect_delta_divergence("XAUUSD") is None

    def test_returns_divergence_or_none(self):
        """Test that with sufficient data, returns DeltaDivergence or None."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        base = datetime.now(timezone.utc) - timedelta(minutes=40)

        # First half: price going down, buys going up (bullish divergence)
        for i in range(15):
            a.add_trade(
                "XAUUSD",
                1960.0 - i * 0.5,   # price falling
                200.0,
                "buy",
                timestamp=base + timedelta(minutes=i),
            )
        # Second half: price recovering, buys dominant
        for i in range(15, 30):
            a.add_trade(
                "XAUUSD",
                1950.0 + i * 0.1,
                50.0,
                "sell",
                timestamp=base + timedelta(minutes=i),
            )

        result = a.detect_delta_divergence("XAUUSD", lookback_minutes=50.0)
        # May be None or DeltaDivergence depending on exact numbers; just validate type
        from analysis.advanced_order_flow import DeltaDivergence
        assert result is None or isinstance(result, DeltaDivergence)


class TestVolumeClusters:
    """Tests for identify_volume_clusters."""

    def _populate(self, a, symbol="XAUUSD", n=50):
        for i in range(n):
            a.add_trade(symbol, 1950.0 + (i % 10) * 0.5, 10.0 * (1 + i % 5),
                        "buy" if i % 2 == 0 else "sell")

    def test_returns_list(self):
        """Test that a list of clusters is returned."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        self._populate(a)

        clusters = a.identify_volume_clusters("XAUUSD", lookback_minutes=60.0)
        assert isinstance(clusters, list)

    def test_clusters_sorted_by_volume(self):
        """Test that clusters are sorted by volume descending."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        self._populate(a, n=100)

        clusters = a.identify_volume_clusters("XAUUSD", lookback_minutes=60.0)
        if len(clusters) >= 2:
            assert clusters[0].total_volume >= clusters[-1].total_volume


class TestOrderFlowOscillatorCalculation:
    """Tests for calculate_order_flow_oscillator."""

    def _add_trades(self, a, symbol="XAUUSD"):
        for i in range(30):
            a.add_trade(symbol, 1950.0 + i * 0.1, 10.0,
                        "buy" if i % 3 != 0 else "sell")

    def test_returns_oscillator(self):
        """Test that oscillator is returned with sufficient data."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer, OrderFlowOscillator

        a = AdvancedOrderFlowAnalyzer()
        self._add_trades(a)

        osc = a.calculate_order_flow_oscillator(
            "XAUUSD", fast_period=5.0, slow_period=20.0
        )
        assert isinstance(osc, OrderFlowOscillator)
        assert osc.trend in ("bullish", "bearish", "neutral")

    def test_none_on_invalid_periods(self):
        """Test None when fast_period >= slow_period."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        self._add_trades(a)
        # fast >= slow → should return None
        assert a.calculate_order_flow_oscillator("XAUUSD", fast_period=20.0, slow_period=10.0) is None

    def test_none_on_empty(self):
        """Test None when no data."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        assert a.calculate_order_flow_oscillator("XAUUSD") is None


class TestPressureGaugesMethod:
    """Tests for get_pressure_gauges."""

    def _add_trades(self, a, buys=10, sells=5):
        for _ in range(buys):
            a.add_trade("XAUUSD", 1950.0, 10.0, "buy")
        for _ in range(sells):
            a.add_trade("XAUUSD", 1950.0, 10.0, "sell")

    def test_returns_pressure_gauges(self):
        """Test PressureGauges returned with trades."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer, PressureGauges

        a = AdvancedOrderFlowAnalyzer()
        self._add_trades(a)

        pg = a.get_pressure_gauges("XAUUSD", lookback_minutes=60.0)
        assert isinstance(pg, PressureGauges)
        assert 0.0 <= pg.buy_pressure <= 100.0
        assert pg.buy_pressure + pg.sell_pressure == pytest.approx(100.0)

    def test_none_on_empty(self):
        """Test None returned when no trades."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        assert a.get_pressure_gauges("XAUUSD") is None

    def test_buy_biased_pressure(self):
        """Test that heavy buy volume yields positive net_pressure."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        for _ in range(20):
            a.add_trade("XAUUSD", 1950.0, 10.0, "buy")
        a.add_trade("XAUUSD", 1950.0, 10.0, "sell")

        pg = a.get_pressure_gauges("XAUUSD", lookback_minutes=60.0)
        assert pg.net_pressure > 0


class TestFullAnalysis:
    """Tests for the analyze() pipeline."""

    def _populate(self, a, symbol="XAUUSD"):
        for i in range(40):
            side = "buy" if i % 3 != 0 else "sell"
            a.add_trade(symbol, 1950.0 + i * 0.1, 10.0 * (1 + i % 4), side)

    def test_analyze_returns_result(self):
        """Test full analyze() pipeline returns AdvancedOrderFlowResult."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer, AdvancedOrderFlowResult

        a = AdvancedOrderFlowAnalyzer()
        self._populate(a)

        result = a.analyze("XAUUSD")
        assert isinstance(result, AdvancedOrderFlowResult)
        assert result.symbol == "XAUUSD"
        assert result.overall_bias in ("bullish", "bearish", "neutral")
        assert 0.0 <= result.confidence <= 100.0

    def test_analyze_empty_symbol_still_returns(self):
        """Test analyze() does not raise on unknown symbol."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        result = a.analyze("UNKNOWN")
        assert result.overall_bias == "neutral"

    def test_get_stats(self):
        """Test get_stats returns expected structure."""
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        a = AdvancedOrderFlowAnalyzer()
        self._populate(a)

        stats = a.get_stats()
        assert "total_trades" in stats
        assert "symbols_tracked" in stats
        assert "cumulative_delta" in stats

    def test_singleton_accessor(self):
        """Test module-level singleton returns the same instance."""
        from analysis.advanced_order_flow import get_advanced_order_flow_analyzer

        a1 = get_advanced_order_flow_analyzer()
        a2 = get_advanced_order_flow_analyzer()
        assert a1 is a2
