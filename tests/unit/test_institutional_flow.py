"""
Comprehensive Tests for Institutional Flow Detection Module

Tests for:
- InstitutionalTrade dataclass
- FlowSignal dataclass
- InstitutionalFlowDetector (large order detection, iceberg, volume spikes,
  absorption, trade classification, analyze_flow, smart money direction)
"""

import pytest
from datetime import datetime, timedelta, timezone


class TestInstitutionalTrade:
    """Tests for InstitutionalTrade dataclass."""

    def test_trade_creation(self):
        """Test creating an InstitutionalTrade."""
        from analysis.institutional_flow import InstitutionalTrade

        trade = InstitutionalTrade(
            timestamp=datetime.now(timezone.utc),
            symbol="XAUUSD",
            price=1950.0,
            size=1500.0,
            side="buy",
            classification="institutional",
            confidence=0.90,
            indicators=["very_large_order"],
        )

        assert trade.symbol == "XAUUSD"
        assert trade.classification == "institutional"
        assert trade.confidence == 0.90

    def test_trade_to_dict(self):
        """Test serialisation to dictionary."""
        from analysis.institutional_flow import InstitutionalTrade

        trade = InstitutionalTrade(
            timestamp=datetime.now(timezone.utc),
            symbol="XAUUSD",
            price=1950.0,
            size=2000.0,
            side="sell",
            classification="institutional",
            confidence=0.85,
            indicators=["large_order"],
        )
        d = trade.to_dict()

        assert d["symbol"] == "XAUUSD"
        assert d["classification"] == "institutional"
        assert "indicators" in d
        assert "timestamp" in d


class TestFlowSignal:
    """Tests for FlowSignal dataclass."""

    def test_signal_creation(self):
        """Test creating a FlowSignal."""
        from analysis.institutional_flow import FlowSignal

        sig = FlowSignal(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            signal_type="iceberg",
            strength="strong",
            direction="bullish",
            price_level=1950.0,
            volume=3000.0,
            details={"fill_count": 5},
        )

        assert sig.signal_type == "iceberg"
        assert sig.direction == "bullish"

    def test_signal_to_dict(self):
        """Test FlowSignal serialisation."""
        from analysis.institutional_flow import FlowSignal

        sig = FlowSignal(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            signal_type="volume_spike",
            strength="moderate",
            direction="bearish",
            price_level=1950.0,
            volume=5000.0,
            details={"z_score": 3.5},
        )
        d = sig.to_dict()

        assert d["signal_type"] == "volume_spike"
        assert d["direction"] == "bearish"
        assert "details" in d


class TestInstitutionalFlowDetectorInit:
    """Tests for detector initialisation."""

    def test_default_init(self):
        """Test default initialisation."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector()
        assert det is not None

    def test_custom_config(self):
        """Test custom configuration is applied."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(
            config={"min_institutional_size": 500.0, "iceberg_window_seconds": 60}
        )
        assert det._min_institutional_size == 500.0
        assert det._iceberg_window_seconds == 60


class TestInstitutionalFlowDetectorTradeIngestion:
    """Tests for add_trade and input validation."""

    def test_add_trade_succeeds(self):
        """Test adding a valid trade."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector()
        det.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        assert len(det._trades["XAUUSD"]) == 1

    def test_add_trade_negative_size_raises(self):
        """Test that non-positive size raises ValueError."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector()
        with pytest.raises(ValueError):
            det.add_trade("XAUUSD", 1950.0, -5.0, "buy")

    def test_add_multiple_trades(self):
        """Test accumulating several trades."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 100.0})
        for i in range(5):
            det.add_trade("XAUUSD", 1950.0 + i, 200.0, "buy")

        assert len(det._trades["XAUUSD"]) == 5


class TestDetectLargeOrders:
    """Tests for large order detection."""

    def test_detects_large_buy(self):
        """Test detection of a large buy order."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 1000.0})
        det.add_trade("XAUUSD", 1950.0, 1500.0, "buy")
        det.add_trade("XAUUSD", 1950.0, 50.0, "sell")

        large = det.detect_large_orders("XAUUSD")
        assert len(large) == 1
        assert large[0].size == 1500.0
        assert large[0].classification == "institutional"

    def test_does_not_detect_small_trade(self):
        """Test that small trades are not flagged."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 1000.0})
        det.add_trade("XAUUSD", 1950.0, 200.0, "buy")

        assert det.detect_large_orders("XAUUSD") == []

    def test_min_size_override(self):
        """Test per-call min_size override."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 1000.0})
        det.add_trade("XAUUSD", 1950.0, 300.0, "buy")

        # With lower threshold, should be detected
        large = det.detect_large_orders("XAUUSD", min_size=200.0)
        assert len(large) == 1


class TestDetectIcebergOrders:
    """Tests for iceberg order detection."""

    def test_detects_iceberg(self):
        """Test that repeated same-price fills trigger iceberg signal."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(
            config={"min_institutional_size": 100.0, "iceberg_window_seconds": 60}
        )
        base = datetime.now(timezone.utc)
        for i in range(5):
            det.add_trade(
                "XAUUSD", 1950.00, 50.0, "buy",
                timestamp=base + timedelta(seconds=i * 5)
            )

        signals = det.detect_iceberg_orders("XAUUSD", window_seconds=60)
        assert len(signals) >= 1
        assert signals[0].signal_type == "iceberg"

    def test_no_iceberg_on_varied_prices(self):
        """Test that varied prices do not trigger an iceberg."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector()
        base = datetime.now(timezone.utc)
        prices = [1950.0, 1951.0, 1952.0, 1953.0, 1954.0]
        for i, p in enumerate(prices):
            det.add_trade(
                "XAUUSD", p, 50.0, "buy",
                timestamp=base + timedelta(seconds=i)
            )

        signals = det.detect_iceberg_orders("XAUUSD", window_seconds=60)
        assert len(signals) == 0


class TestDetectVolumeSpikes:
    """Tests for volume spike detection."""

    def _populate_baseline(self, det, symbol, periods=5, volume_per_period=100.0):
        """Helper: build a varied volume baseline spread across distinct minutes."""
        base = datetime.now(timezone.utc) - timedelta(minutes=periods + 2)
        for p in range(periods):
            # Vary each period slightly so pstdev > 0
            period_vol = volume_per_period * (1.0 + p * 0.2)
            for _ in range(3):
                det.add_trade(
                    symbol, 1950.0, period_vol / 3, "buy",
                    timestamp=base + timedelta(minutes=p, seconds=1)
                )

    def test_detects_spike(self):
        """Test that a very high-volume period is flagged as a spike."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(
            config={
                "volume_spike_threshold": 1.5,
                "volume_period_minutes": 1,
                "lookback_periods": 5,
            }
        )
        self._populate_baseline(det, "XAUUSD", periods=5, volume_per_period=100.0)

        # Add a massive spike in a single distinct minute
        spike_base = datetime.now(timezone.utc)
        for j in range(10):
            det.add_trade(
                "XAUUSD", 1950.0, 10_000.0, "buy",
                timestamp=spike_base + timedelta(seconds=j)
            )

        spikes = det.detect_volume_spikes("XAUUSD")
        # With baseline of ~100 vol per minute and a 100,000-vol spike the
        # z-score will vastly exceed 1.5 σ — at least one spike must be found.
        assert len(spikes) >= 1
        assert spikes[0].signal_type == "volume_spike"

    def test_no_spike_on_uniform_volume(self):
        """Test no spikes when volume is uniform."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(
            config={"volume_spike_threshold": 3.0, "volume_period_minutes": 1}
        )
        # Uniform volume – no spike
        base = datetime.now(timezone.utc) - timedelta(minutes=5)
        for i in range(5):
            det.add_trade("XAUUSD", 1950.0, 100.0, "buy",
                          timestamp=base + timedelta(minutes=i))

        spikes = det.detect_volume_spikes("XAUUSD")
        assert len(spikes) == 0


class TestClassifyTrade:
    """Tests for trade classification."""

    def test_classifies_very_large_as_institutional(self):
        """Test very large trade classified as institutional with high confidence."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 1000.0})
        result = det.classify_trade(1950.0, 6000.0, "buy", "XAUUSD")

        assert result.classification == "institutional"
        assert result.confidence >= 0.90

    def test_classifies_small_as_retail(self):
        """Test small trade classified as retail."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 1000.0})
        result = det.classify_trade(1950.0, 10.0, "sell", "XAUUSD")

        assert result.classification == "retail"
        assert result.confidence >= 0.80

    def test_classifies_borderline_as_unknown(self):
        """Test borderline size classified as unknown."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 1000.0})
        # Between 0.5x and 1x threshold → unknown
        result = det.classify_trade(1950.0, 600.0, "buy", "XAUUSD")

        assert result.classification == "unknown"


class TestAnalyzeFlow:
    """Tests for the full analyze_flow pipeline."""

    def _add_large_trades(self, det, symbol="XAUUSD"):
        for i in range(5):
            det.add_trade(symbol, 1950.0 + i, 2000.0, "buy")
        det.add_trade(symbol, 1950.0, 2000.0, "sell")

    def test_analyze_flow_returns_dict(self):
        """Test analyze_flow returns a dictionary with required keys."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 1000.0})
        self._add_large_trades(det)

        result = det.analyze_flow("XAUUSD")

        assert isinstance(result, dict)
        assert "symbol" in result
        assert "large_orders" in result
        assert "smart_money_direction" in result
        assert "summary" in result

    def test_analyze_flow_empty_symbol(self):
        """Test analyze_flow on an empty symbol doesn't raise."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector()
        result = det.analyze_flow("UNKNOWN")

        assert result["symbol"] == "UNKNOWN"


class TestSmartMoneyDirection:
    """Tests for get_smart_money_direction."""

    def test_bullish_when_buy_dominant(self):
        """Test bullish direction with heavy buy imbalance."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 100.0})
        for _ in range(8):
            det.add_trade("XAUUSD", 1950.0, 1000.0, "buy")
        det.add_trade("XAUUSD", 1950.0, 1000.0, "sell")

        assert det.get_smart_money_direction("XAUUSD") == "bullish"

    def test_bearish_when_sell_dominant(self):
        """Test bearish direction with heavy sell imbalance."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 100.0})
        det.add_trade("XAUUSD", 1950.0, 1000.0, "buy")
        for _ in range(8):
            det.add_trade("XAUUSD", 1950.0, 1000.0, "sell")

        assert det.get_smart_money_direction("XAUUSD") == "bearish"

    def test_neutral_when_no_trades(self):
        """Test neutral when no institutional trades."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector()
        assert det.get_smart_money_direction("XAUUSD") == "neutral"


class TestGetLargeOrdersAndSignals:
    """Tests for get_large_orders and get_flow_signals."""

    def test_get_large_orders_returns_dicts(self):
        """Test get_large_orders serialises correctly."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 500.0})
        det.add_trade("XAUUSD", 1950.0, 1000.0, "buy")

        orders = det.get_large_orders("XAUUSD")
        assert isinstance(orders, list)
        assert len(orders) >= 1
        assert "classification" in orders[0]

    def test_get_stats(self):
        """Test get_stats returns meaningful data."""
        from analysis.institutional_flow import InstitutionalFlowDetector

        det = InstitutionalFlowDetector(config={"min_institutional_size": 100.0})
        det.add_trade("XAUUSD", 1950.0, 200.0, "buy")

        stats = det.get_stats()
        assert "symbols_tracked" in stats
        assert "trades_by_symbol" in stats

    def test_singleton_accessor(self):
        """Test the module-level singleton accessor returns the same instance."""
        from analysis.institutional_flow import get_institutional_flow_detector

        d1 = get_institutional_flow_detector()
        d2 = get_institutional_flow_detector()
        assert d1 is d2
