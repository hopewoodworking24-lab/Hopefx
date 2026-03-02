"""
Institutional Order Flow Detection Module

Advanced detection and classification of institutional trading activity:
- Large order identification
- Iceberg order detection (repeated fills at the same price)
- Volume spike analysis (standard-deviation-based)
- Absorption level tracking (high volume, low price movement)
- Smart money flow classification and net direction
- Institutional vs retail trade classification
- Momentum divergence detection

Inspired by: Bookmap, ATAS, Quantower order flow analytics
"""

import logging
import math
import statistics
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ================================================================
# INTERNAL DATA STRUCTURES
# ================================================================


@dataclass
class _RawTrade:
    """Internal raw trade record."""

    timestamp: datetime
    price: float
    size: float
    side: str  # 'buy' or 'sell'
    trade_id: Optional[str] = None

    @property
    def is_buy(self) -> bool:
        """Return True if the trade is a buy."""
        return self.side.lower() == "buy"

    @property
    def is_sell(self) -> bool:
        """Return True if the trade is a sell."""
        return self.side.lower() == "sell"


# ================================================================
# PUBLIC DATA STRUCTURES
# ================================================================


@dataclass
class InstitutionalTrade:
    """
    Classified institutional trade record.

    Attributes:
        timestamp: UTC time of the trade.
        symbol: Trading symbol (e.g., 'XAUUSD').
        price: Execution price.
        size: Trade size in lots.
        side: 'buy' or 'sell'.
        classification: 'institutional', 'retail', or 'unknown'.
        confidence: Classification confidence in [0.0, 1.0].
        indicators: Human-readable reasons for the classification.
    """

    timestamp: datetime
    symbol: str
    price: float
    size: float
    side: str
    classification: str
    confidence: float
    indicators: List[str]

    def to_dict(self) -> Dict:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "classification": self.classification,
            "confidence": round(self.confidence, 4),
            "indicators": self.indicators,
        }


@dataclass
class FlowSignal:
    """
    Detected institutional flow signal.

    Attributes:
        symbol: Trading symbol.
        timestamp: Signal detection time (UTC).
        signal_type: One of 'absorption', 'iceberg', 'volume_spike',
            'smart_money', or 'momentum_divergence'.
        strength: 'strong', 'moderate', or 'weak'.
        direction: Market direction implied — 'bullish', 'bearish', or 'neutral'.
        price_level: Price at which the signal occurred.
        volume: Volume associated with the signal.
        details: Additional contextual data for the signal.
    """

    symbol: str
    timestamp: datetime
    signal_type: str
    strength: str
    direction: str
    price_level: float
    volume: float
    details: Dict

    def to_dict(self) -> Dict:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal_type": self.signal_type,
            "strength": self.strength,
            "direction": self.direction,
            "price_level": self.price_level,
            "volume": self.volume,
            "details": self.details,
        }


# ================================================================
# MAIN DETECTOR
# ================================================================


class InstitutionalFlowDetector:
    """
    Institutional order flow detection and classification system.

    Identifies large institutional trades, iceberg orders, volume spikes,
    absorption levels, and smart money flow patterns in streaming trade data.

    Features:
        - Large order detection with configurable size thresholds.
        - Iceberg order identification via repeated fills at the same price.
        - Volume spike detection using a rolling mean + standard-deviation model.
        - Absorption level tracking (high volume + low price movement).
        - Smart money flow classification and net directional bias.
        - Institutional vs retail trade classification with confidence score.
        - Momentum divergence detection between price and order flow delta.

    Usage:
        detector = InstitutionalFlowDetector()

        # Feed trade data
        detector.add_trade('XAUUSD', price=1950.0, size=500.0, side='buy')
        detector.add_trade('XAUUSD', price=1950.0, size=1200.0, side='sell')

        # Run full analysis
        result = detector.analyze_flow('XAUUSD')

        # Query specific outputs
        direction = detector.get_smart_money_direction('XAUUSD')
        signals  = detector.get_flow_signals('XAUUSD')
        orders   = detector.get_large_orders('XAUUSD')
    """

    # Classification multipliers relative to min_institutional_size
    _STRONG_INSTITUTIONAL_MULTIPLIER: float = 5.0
    _MODERATE_INSTITUTIONAL_MULTIPLIER: float = 2.0

    # Iceberg: minimum number of same-price fills to flag an iceberg
    _ICEBERG_MIN_FILLS: int = 3

    # Price rounding for iceberg grouping (decimal places)
    _PRICE_TICK_DECIMALS: int = 2

    # Absorption: min volume ratio (vs window average) to flag absorption
    _ABSORPTION_MIN_VOLUME_MULTIPLIER: float = 2.0

    def __init__(self, config: Optional[Dict] = None) -> None:
        """
        Initialize the institutional flow detector.

        Args:
            config: Optional configuration overrides. Supported keys:

                min_institutional_size (float):
                    Minimum lot size considered institutional. Default: 1000.
                volume_spike_threshold (float):
                    Standard deviations above the rolling mean required to
                    classify a period as a volume spike. Default: 3.0.
                iceberg_window_seconds (int):
                    Time window in seconds for iceberg detection. Default: 30.
                absorption_window_minutes (int):
                    Width of each absorption analysis window. Default: 5.
                absorption_price_tolerance (float):
                    Maximum price range (as a fraction of price) within a
                    window that is still considered absorbed. Default: 0.001.
                lookback_periods (int):
                    Number of historical volume periods used as a baseline for
                    spike detection. Default: 20.
                volume_period_minutes (int):
                    Duration of each volume bucket in minutes. Default: 1.
                max_trades (int):
                    Maximum trades retained per symbol. Default: 100 000.
                max_signals (int):
                    Maximum flow signals retained per symbol. Default: 500.
        """
        self.config = config or {}
        self._lock = threading.Lock()

        # ── configuration ────────────────────────────────────────────────
        self._min_institutional_size: float = float(
            self.config.get("min_institutional_size", 1_000.0)
        )
        self._volume_spike_threshold: float = float(
            self.config.get("volume_spike_threshold", 3.0)
        )
        self._iceberg_window_seconds: int = int(
            self.config.get("iceberg_window_seconds", 30)
        )
        self._absorption_window_minutes: int = int(
            self.config.get("absorption_window_minutes", 5)
        )
        self._absorption_price_tolerance: float = float(
            self.config.get("absorption_price_tolerance", 0.001)
        )
        self._lookback_periods: int = int(self.config.get("lookback_periods", 20))
        self._volume_period_minutes: int = int(
            self.config.get("volume_period_minutes", 1)
        )
        self._max_trades: int = int(self.config.get("max_trades", 100_000))
        self._max_signals: int = int(self.config.get("max_signals", 500))

        # ── state ────────────────────────────────────────────────────────
        self._trades: Dict[str, List[_RawTrade]] = defaultdict(list)
        self._flow_signals: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._max_signals)
        )
        self._cumulative_institutional_buy: Dict[str, float] = defaultdict(float)
        self._cumulative_institutional_sell: Dict[str, float] = defaultdict(float)

        logger.info(
            "InstitutionalFlowDetector initialised — "
            "min_size=%.0f, spike_threshold=%.1fσ, iceberg_window=%ds",
            self._min_institutional_size,
            self._volume_spike_threshold,
            self._iceberg_window_seconds,
        )

    # ================================================================
    # TRADE INGESTION
    # ================================================================

    def add_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        timestamp: Optional[datetime] = None,
        trade_id: Optional[str] = None,
    ) -> None:
        """
        Add a trade to the detection buffer.

        Args:
            symbol: Trading symbol (e.g., 'XAUUSD').
            price: Execution price.
            size: Trade size in lots (must be > 0).
            side: 'buy' or 'sell'.
            timestamp: UTC trade time. Defaults to ``datetime.now(timezone.utc)``.
            trade_id: Optional unique identifier.

        Raises:
            ValueError: If *size* is not positive.
        """
        if size <= 0:
            raise ValueError(f"Trade size must be positive, got {size!r}")

        trade = _RawTrade(
            timestamp=timestamp or datetime.now(timezone.utc),
            price=price,
            size=size,
            side=side.lower(),
            trade_id=trade_id,
        )

        with self._lock:
            bucket = self._trades[symbol]
            bucket.append(trade)
            if len(bucket) > self._max_trades:
                bucket.pop(0)

        logger.debug(
            "Trade added — symbol=%s price=%.5f size=%.2f side=%s",
            symbol,
            price,
            size,
            side,
        )

    # ── private read helper (call while holding self._lock) ──────────────

    def _get_trades_locked(
        self,
        symbol: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[_RawTrade]:
        """Return a snapshot of trades for *symbol* (must be called under lock)."""
        trades = list(self._trades.get(symbol, []))
        if start_time:
            trades = [t for t in trades if t.timestamp >= start_time]
        if end_time:
            trades = [t for t in trades if t.timestamp <= end_time]
        return trades

    # ================================================================
    # DETECTION METHODS
    # ================================================================

    def detect_large_orders(
        self,
        symbol: str,
        min_size: Optional[float] = None,
    ) -> List[InstitutionalTrade]:
        """
        Identify institutional-size trades in the trade buffer.

        Args:
            symbol: Trading symbol.
            min_size: Override the configured ``min_institutional_size``
                threshold for this call.

        Returns:
            List of :class:`InstitutionalTrade` objects whose size meets
            the threshold.
        """
        threshold = (
            min_size if min_size is not None else self._min_institutional_size
        )

        with self._lock:
            trades = self._get_trades_locked(symbol)

        result: List[InstitutionalTrade] = []
        for trade in trades:
            if trade.size < threshold:
                continue

            indicators: List[str] = [
                f"size_{trade.size:.0f}_above_threshold_{threshold:.0f}"
            ]
            if trade.size >= threshold * self._STRONG_INSTITUTIONAL_MULTIPLIER:
                indicators.append("very_large_order")
            elif trade.size >= threshold * self._MODERATE_INSTITUTIONAL_MULTIPLIER:
                indicators.append("large_order")

            result.append(
                InstitutionalTrade(
                    timestamp=trade.timestamp,
                    symbol=symbol,
                    price=trade.price,
                    size=trade.size,
                    side=trade.side,
                    classification="institutional",
                    confidence=self._size_confidence(trade.size, threshold),
                    indicators=indicators,
                )
            )

        logger.debug(
            "Large order detection — symbol=%s threshold=%.0f found=%d",
            symbol,
            threshold,
            len(result),
        )
        return result

    def detect_iceberg_orders(
        self,
        symbol: str,
        window_seconds: Optional[int] = None,
    ) -> List[FlowSignal]:
        """
        Detect iceberg orders via repeated fills at the same price level.

        An iceberg order exposes itself through a succession of identically-
        priced small fills as each visible slice is consumed and replenished.
        A cluster of ``_ICEBERG_MIN_FILLS`` or more fills at the same rounded
        price within *window_seconds* is flagged.

        Args:
            symbol: Trading symbol.
            window_seconds: Detection window in seconds.
                Defaults to ``iceberg_window_seconds`` config value.

        Returns:
            List of :class:`FlowSignal` objects with ``signal_type='iceberg'``.
        """
        window = (
            window_seconds
            if window_seconds is not None
            else self._iceberg_window_seconds
        )
        window_td = timedelta(seconds=window)

        with self._lock:
            trades = self._get_trades_locked(symbol)

        if len(trades) < self._ICEBERG_MIN_FILLS:
            return []

        signals: List[FlowSignal] = []
        i = 0
        while i < len(trades):
            anchor = trades[i]
            anchor_price = round(anchor.price, self._PRICE_TICK_DECIMALS)
            window_end = anchor.timestamp + window_td

            fills = [
                t
                for t in trades[i:]
                if t.timestamp <= window_end
                and round(t.price, self._PRICE_TICK_DECIMALS) == anchor_price
            ]

            if len(fills) >= self._ICEBERG_MIN_FILLS:
                total_vol = sum(f.size for f in fills)
                buy_vol = sum(f.size for f in fills if f.is_buy)
                sell_vol = total_vol - buy_vol
                direction = "bullish" if buy_vol >= sell_vol else "bearish"

                signal = FlowSignal(
                    symbol=symbol,
                    timestamp=anchor.timestamp,
                    signal_type="iceberg",
                    strength=self._strength_from_fills(len(fills)),
                    direction=direction,
                    price_level=anchor_price,
                    volume=total_vol,
                    details={
                        "fill_count": len(fills),
                        "buy_volume": round(buy_vol, 2),
                        "sell_volume": round(sell_vol, 2),
                        "window_seconds": window,
                        "price_level": anchor_price,
                    },
                )
                signals.append(signal)
                self._store_signal(symbol, signal)
                i += len(fills)
            else:
                i += 1

        logger.debug(
            "Iceberg detection — symbol=%s window=%ds signals=%d",
            symbol,
            window,
            len(signals),
        )
        return signals

    def detect_volume_spikes(
        self,
        symbol: str,
        lookback_periods: Optional[int] = None,
    ) -> List[FlowSignal]:
        """
        Detect periods of unusually high volume relative to recent history.

        Trades are bucketed into fixed-duration periods. For each period, a
        rolling baseline of the preceding N periods is computed. A period whose
        volume exceeds ``mean + volume_spike_threshold * std`` is flagged.

        Args:
            symbol: Trading symbol.
            lookback_periods: Number of historical periods for baseline.
                Defaults to ``lookback_periods`` config value.

        Returns:
            List of :class:`FlowSignal` objects with
            ``signal_type='volume_spike'``.
        """
        periods = (
            lookback_periods
            if lookback_periods is not None
            else self._lookback_periods
        )

        with self._lock:
            trades = self._get_trades_locked(symbol)

        if not trades:
            return []

        bucketed = self._bucket_by_period(trades, self._volume_period_minutes)
        if len(bucketed) < 2:
            return []

        signals: List[FlowSignal] = []
        period_keys = sorted(bucketed.keys())

        for idx, key in enumerate(period_keys):
            if idx < 2:
                continue  # need at least two baseline periods

            baseline_keys = period_keys[max(0, idx - periods) : idx]
            baseline_vols = [
                sum(t.size for t in bucketed[k]) for k in baseline_keys
            ]
            if not baseline_vols:
                continue

            mean_vol = statistics.mean(baseline_vols)
            std_vol = statistics.pstdev(baseline_vols)
            if std_vol == 0:
                continue

            period_trades = bucketed[key]
            current_vol = sum(t.size for t in period_trades)
            z_score = (current_vol - mean_vol) / std_vol

            if z_score < self._volume_spike_threshold:
                continue

            buy_vol = sum(t.size for t in period_trades if t.is_buy)
            sell_vol = current_vol - buy_vol
            avg_price = sum(t.price for t in period_trades) / len(period_trades)
            direction = "bullish" if buy_vol > sell_vol else "bearish"

            signal = FlowSignal(
                symbol=symbol,
                timestamp=period_trades[0].timestamp,
                signal_type="volume_spike",
                strength=self._strength_from_z(z_score),
                direction=direction,
                price_level=round(avg_price, 5),
                volume=current_vol,
                details={
                    "z_score": round(z_score, 2),
                    "mean_volume": round(mean_vol, 2),
                    "std_volume": round(std_vol, 2),
                    "current_volume": round(current_vol, 2),
                    "buy_volume": round(buy_vol, 2),
                    "sell_volume": round(sell_vol, 2),
                    "threshold_sigma": self._volume_spike_threshold,
                },
            )
            signals.append(signal)
            self._store_signal(symbol, signal)

        logger.debug(
            "Volume spike detection — symbol=%s periods=%d spikes=%d",
            symbol,
            periods,
            len(signals),
        )
        return signals

    def detect_absorption(
        self,
        symbol: str,
        lookback_minutes: int = 30,
    ) -> List[FlowSignal]:
        """
        Detect absorption levels — high volume with minimal price movement.

        Absorption occurs when institutional players absorb aggressive market
        orders without allowing price to move. This often precedes a reversal
        or strong continuation once the absorption is exhausted.

        A window is flagged when:
        - Its total volume exceeds ``_ABSORPTION_MIN_VOLUME_MULTIPLIER × avg``.
        - Its price range / avg_price ≤ ``absorption_price_tolerance``.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Analysis lookback in minutes.

        Returns:
            List of :class:`FlowSignal` objects with
            ``signal_type='absorption'``.
        """
        start_time = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)

        with self._lock:
            trades = self._get_trades_locked(symbol, start_time=start_time)

        if len(trades) < 5:
            return []

        window_td = timedelta(minutes=self._absorption_window_minutes)
        avg_vol = self._average_window_volume(trades, window_td)

        signals: List[FlowSignal] = []
        i = 0
        while i < len(trades):
            anchor = trades[i]
            window_end = anchor.timestamp + window_td
            window_trades = [t for t in trades[i:] if t.timestamp <= window_end]

            if len(window_trades) < 3:
                i += 1
                continue

            prices = [t.price for t in window_trades]
            total_vol = sum(t.size for t in window_trades)
            price_range = max(prices) - min(prices)
            avg_price = sum(prices) / len(prices)
            price_range_pct = price_range / avg_price if avg_price > 0 else 1.0

            is_high_volume = (
                avg_vol > 0
                and total_vol >= avg_vol * self._ABSORPTION_MIN_VOLUME_MULTIPLIER
            )
            is_low_move = price_range_pct <= self._absorption_price_tolerance

            if is_high_volume and is_low_move:
                buy_vol = sum(t.size for t in window_trades if t.is_buy)
                sell_vol = total_vol - buy_vol

                # Buyers absorb selling pressure → bullish; sellers absorb
                # buying pressure → bearish.
                if sell_vol > buy_vol:
                    direction = "bullish"
                    abs_side = "buy_absorption"
                else:
                    direction = "bearish"
                    abs_side = "sell_absorption"

                signal = FlowSignal(
                    symbol=symbol,
                    timestamp=anchor.timestamp,
                    signal_type="absorption",
                    strength=self._strength_from_volume_ratio(total_vol, avg_vol),
                    direction=direction,
                    price_level=round(avg_price, 5),
                    volume=total_vol,
                    details={
                        "absorption_side": abs_side,
                        "price_range": round(price_range, 5),
                        "price_range_pct": round(price_range_pct * 100, 4),
                        "buy_volume": round(buy_vol, 2),
                        "sell_volume": round(sell_vol, 2),
                        "avg_volume_baseline": round(avg_vol, 2),
                        "volume_multiplier": (
                            round(total_vol / avg_vol, 2) if avg_vol > 0 else 0
                        ),
                    },
                )
                signals.append(signal)
                self._store_signal(symbol, signal)
                i += len(window_trades)
            else:
                i += 1

        logger.debug(
            "Absorption detection — symbol=%s lookback=%dm signals=%d",
            symbol,
            lookback_minutes,
            len(signals),
        )
        return signals

    def classify_trade(
        self,
        price: float,
        size: float,
        side: str,
        symbol: str,
    ) -> InstitutionalTrade:
        """
        Classify a single trade as institutional, retail, or unknown.

        Uses size-based heuristics and proximity to recently detected
        absorption levels as supporting evidence.

        Args:
            price: Execution price.
            size: Trade size in lots.
            side: 'buy' or 'sell'.
            symbol: Trading symbol (used for context lookup).

        Returns:
            :class:`InstitutionalTrade` with classification and confidence.
        """
        threshold = self._min_institutional_size
        indicators: List[str] = []

        if size >= threshold * self._STRONG_INSTITUTIONAL_MULTIPLIER:
            indicators += [
                "very_large_order",
                f"size_exceeds_{self._STRONG_INSTITUTIONAL_MULTIPLIER:.0f}x_threshold",
            ]
            classification = "institutional"
            confidence = 0.95
        elif size >= threshold * self._MODERATE_INSTITUTIONAL_MULTIPLIER:
            indicators += [
                "large_order",
                f"size_exceeds_{self._MODERATE_INSTITUTIONAL_MULTIPLIER:.0f}x_threshold",
            ]
            classification = "institutional"
            confidence = 0.80
        elif size >= threshold:
            indicators.append("above_institutional_threshold")
            classification = "institutional"
            confidence = self._size_confidence(size, threshold)
        elif size >= threshold * 0.5:
            indicators.append("near_institutional_threshold")
            classification = "unknown"
            confidence = 0.40
        else:
            classification = "retail"
            confidence = 0.85

        # Context: boost confidence if price is near a known absorption level.
        with self._lock:
            recent_signals = list(self._flow_signals.get(symbol, []))

        for sig in recent_signals[-50:]:
            if sig.signal_type == "absorption":
                abs_level = sig.price_level
                if abs_level > 0 and abs(abs_level - price) / abs_level < 0.002:
                    indicators.append("near_absorption_level")
                    if classification != "institutional":
                        confidence = min(confidence + 0.15, 1.0)
                    break

        return InstitutionalTrade(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            price=price,
            size=size,
            side=side.lower(),
            classification=classification,
            confidence=round(confidence, 4),
            indicators=indicators,
        )

    # ================================================================
    # FLOW ANALYSIS
    # ================================================================

    def analyze_flow(self, symbol: str) -> Dict[str, Any]:
        """
        Run a complete institutional flow analysis for a symbol.

        Executes all detectors sequentially and compiles a unified report.

        Args:
            symbol: Trading symbol.

        Returns:
            Dictionary containing:

            - ``symbol`` (str)
            - ``timestamp`` (str): ISO 8601 UTC timestamp.
            - ``large_orders`` (list[dict]): Detected institutional trades.
            - ``iceberg_signals`` (list[dict]): Iceberg order signals.
            - ``volume_spikes`` (list[dict]): Volume spike signals.
            - ``absorption_signals`` (list[dict]): Absorption signals.
            - ``smart_money_direction`` (str): 'bullish', 'bearish', or 'neutral'.
            - ``momentum_divergence`` (dict): Divergence analysis.
            - ``summary`` (dict): High-level aggregated metrics.
        """
        try:
            large_orders = self.detect_large_orders(symbol)
            iceberg_signals = self.detect_iceberg_orders(symbol)
            volume_spikes = self.detect_volume_spikes(symbol)
            absorption_signals = self.detect_absorption(symbol)
            smart_money_dir = self.get_smart_money_direction(symbol)
            divergence = self._detect_momentum_divergence(symbol)

            # Update cumulative institutional volumes
            with self._lock:
                for trade in large_orders:
                    if trade.side == "buy":
                        self._cumulative_institutional_buy[symbol] += trade.size
                    else:
                        self._cumulative_institutional_sell[symbol] += trade.size

            if smart_money_dir != "neutral":
                self._emit_smart_money_signal(symbol, smart_money_dir, large_orders)

            summary: Dict[str, Any] = {
                "total_large_orders": len(large_orders),
                "total_institutional_volume": sum(o.size for o in large_orders),
                "institutional_buy_volume": sum(
                    o.size for o in large_orders if o.side == "buy"
                ),
                "institutional_sell_volume": sum(
                    o.size for o in large_orders if o.side == "sell"
                ),
                "total_flow_signals": (
                    len(iceberg_signals)
                    + len(volume_spikes)
                    + len(absorption_signals)
                ),
                "smart_money_direction": smart_money_dir,
                "has_momentum_divergence": divergence.get(
                    "divergence_detected", False
                ),
            }

            return {
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "large_orders": [o.to_dict() for o in large_orders],
                "iceberg_signals": [s.to_dict() for s in iceberg_signals],
                "volume_spikes": [s.to_dict() for s in volume_spikes],
                "absorption_signals": [s.to_dict() for s in absorption_signals],
                "smart_money_direction": smart_money_dir,
                "momentum_divergence": divergence,
                "summary": summary,
            }

        except Exception:
            logger.exception("Error during flow analysis for %s", symbol)
            return {
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "Analysis failed — check server logs for details.",
            }

    def get_smart_money_direction(self, symbol: str) -> str:
        """
        Determine the net directional bias of institutional / smart money.

        Compares the aggregate buy and sell volume of all trades that meet
        the institutional size threshold.

        Args:
            symbol: Trading symbol.

        Returns:
            'bullish' if net institutional flow is positive,
            'bearish' if negative, or 'neutral' when balanced or absent.
        """
        large_orders = self.detect_large_orders(symbol)
        if not large_orders:
            return "neutral"

        inst_buy = sum(o.size for o in large_orders if o.side == "buy")
        inst_sell = sum(o.size for o in large_orders if o.side == "sell")
        total = inst_buy + inst_sell

        if total == 0:
            return "neutral"

        net_ratio = (inst_buy - inst_sell) / total  # range: [-1, 1]

        if net_ratio > 0.2:
            return "bullish"
        if net_ratio < -0.2:
            return "bearish"
        return "neutral"

    def get_large_orders(
        self,
        symbol: str,
        min_size: Optional[float] = None,
    ) -> List[Dict]:
        """
        Return serialized institutional-size trades for a symbol.

        Args:
            symbol: Trading symbol.
            min_size: Optional per-call size threshold override.

        Returns:
            List of dictionaries (see :meth:`InstitutionalTrade.to_dict`).
        """
        return [
            t.to_dict()
            for t in self.detect_large_orders(symbol, min_size=min_size)
        ]

    def get_flow_signals(self, symbol: str) -> List[Dict]:
        """
        Return all stored flow signals for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            List of dictionaries (see :meth:`FlowSignal.to_dict`),
            ordered oldest to newest.
        """
        with self._lock:
            signals = list(self._flow_signals.get(symbol, []))
        return [s.to_dict() for s in signals]

    # ================================================================
    # INTERNAL HELPERS
    # ================================================================

    def _store_signal(self, symbol: str, signal: FlowSignal) -> None:
        """Append *signal* to the per-symbol ring buffer."""
        with self._lock:
            self._flow_signals[symbol].append(signal)

    # ── confidence / strength helpers ────────────────────────────────────

    def _size_confidence(self, size: float, threshold: float) -> float:
        """
        Map trade size to a classification confidence score.

        Uses a saturating exponential that maps [threshold, ∞) to
        approximately [0.60, 0.95].

        Args:
            size: Observed trade size.
            threshold: Institutional threshold.

        Returns:
            Confidence value in [0.60, 0.95].
        """
        ratio = size / threshold
        confidence = 0.60 + 0.35 * (1.0 - math.exp(-(ratio - 1.0) / 3.0))
        return round(min(confidence, 0.95), 4)

    def _strength_from_fills(self, fill_count: int) -> str:
        """Map iceberg fill count to a signal strength label."""
        if fill_count >= 10:
            return "strong"
        if fill_count >= 5:
            return "moderate"
        return "weak"

    def _strength_from_z(self, z_score: float) -> str:
        """Map volume z-score to a signal strength label."""
        if z_score >= self._volume_spike_threshold * 2.0:
            return "strong"
        if z_score >= self._volume_spike_threshold * 1.5:
            return "moderate"
        return "weak"

    def _strength_from_volume_ratio(self, volume: float, avg: float) -> str:
        """Map the volume / average ratio to a signal strength label."""
        if avg == 0:
            return "weak"
        ratio = volume / avg
        if ratio >= 5.0:
            return "strong"
        if ratio >= 3.0:
            return "moderate"
        return "weak"

    # ── data utilities ────────────────────────────────────────────────────

    def _bucket_by_period(
        self,
        trades: List[_RawTrade],
        period_minutes: int,
    ) -> Dict[datetime, List[_RawTrade]]:
        """
        Group trades into fixed-duration time buckets.

        Args:
            trades: List of raw trades.
            period_minutes: Bucket width in minutes.

        Returns:
            Dict mapping each bucket's start time to its trades.
        """
        buckets: Dict[datetime, List[_RawTrade]] = defaultdict(list)
        for trade in trades:
            floored_minute = (
                trade.timestamp.minute // period_minutes
            ) * period_minutes
            key = trade.timestamp.replace(
                minute=floored_minute, second=0, microsecond=0
            )
            buckets[key].append(trade)
        return dict(buckets)

    def _average_window_volume(
        self,
        trades: List[_RawTrade],
        window: timedelta,
    ) -> float:
        """
        Compute the mean volume across non-overlapping windows of *trades*.

        Args:
            trades: Ordered list of trades.
            window: Window duration.

        Returns:
            Mean per-window volume, or 0.0 if no complete windows exist.
        """
        if not trades:
            return 0.0

        volumes: List[float] = []
        start = trades[0].timestamp
        end = start + window
        current_vol = 0.0

        for trade in trades:
            if trade.timestamp < end:
                current_vol += trade.size
            else:
                volumes.append(current_vol)
                start = end
                end = start + window
                current_vol = trade.size

        if current_vol > 0:
            volumes.append(current_vol)

        return statistics.mean(volumes) if volumes else 0.0

    # ── divergence & smart money helpers ─────────────────────────────────

    def _detect_momentum_divergence(self, symbol: str) -> Dict[str, Any]:
        """
        Detect divergence between price momentum and order-flow delta.

        Compares the first and second halves of the trade buffer. Divergence
        is declared when price direction and delta direction conflict:

        - *Bullish divergence*: price is falling, but cumulative delta is
          rising (buyers are absorbing more than sellers despite falling price).
        - *Bearish divergence*: price is rising, but cumulative delta is
          falling (sellers dominate despite rising price).

        Args:
            symbol: Trading symbol.

        Returns:
            Dictionary with keys: ``divergence_detected``, ``type``,
            ``price_trend``, ``delta_trend``, ``price_change_pct``,
            ``first_half_delta``, ``second_half_delta``, ``confidence``.
        """
        with self._lock:
            trades = self._get_trades_locked(symbol)

        if len(trades) < 10:
            return {"divergence_detected": False, "details": "insufficient_data"}

        mid = len(trades) // 2
        first_half = trades[:mid]
        second_half = trades[mid:]

        first_avg_price = sum(t.price for t in first_half) / len(first_half)
        second_avg_price = sum(t.price for t in second_half) / len(second_half)

        price_trend = "up" if second_avg_price > first_avg_price else "down"
        price_change_pct = (
            (second_avg_price - first_avg_price) / first_avg_price * 100.0
            if first_avg_price > 0
            else 0.0
        )

        def _delta(tlist: List[_RawTrade]) -> float:
            return sum(t.size if t.is_buy else -t.size for t in tlist)

        first_delta = _delta(first_half)
        second_delta = _delta(second_half)
        delta_trend = "up" if second_delta > first_delta else "down"

        divergence_detected = price_trend != delta_trend
        divergence_type = "neutral"
        confidence = 0.0

        if divergence_detected:
            divergence_type = (
                "bullish" if (price_trend == "down" and delta_trend == "up") else "bearish"
            )
            price_strength = abs(price_change_pct)
            delta_diff = abs(second_delta - first_delta)
            # Confidence increases with the magnitude of both diverging trends.
            confidence = round(
                min(
                    0.90,
                    0.50
                    + price_strength * 0.05
                    + (delta_diff / (delta_diff + 1.0)) * 0.20,
                ),
                4,
            )

        return {
            "divergence_detected": divergence_detected,
            "type": divergence_type,
            "price_trend": price_trend,
            "delta_trend": delta_trend,
            "price_change_pct": round(price_change_pct, 4),
            "first_half_delta": round(first_delta, 2),
            "second_half_delta": round(second_delta, 2),
            "confidence": confidence,
        }

    def _emit_smart_money_signal(
        self,
        symbol: str,
        direction: str,
        large_orders: List[InstitutionalTrade],
    ) -> None:
        """
        Store a ``smart_money`` :class:`FlowSignal` derived from large orders.

        Args:
            symbol: Trading symbol.
            direction: 'bullish' or 'bearish'.
            large_orders: Contributing institutional trades.
        """
        if not large_orders:
            return

        total_vol = sum(o.size for o in large_orders)
        avg_price = sum(o.price for o in large_orders) / len(large_orders)

        if len(large_orders) >= 10:
            strength = "strong"
        elif len(large_orders) >= 5:
            strength = "moderate"
        else:
            strength = "weak"

        signal = FlowSignal(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            signal_type="smart_money",
            strength=strength,
            direction=direction,
            price_level=round(avg_price, 5),
            volume=total_vol,
            details={
                "order_count": len(large_orders),
                "institutional_buy_volume": round(
                    sum(o.size for o in large_orders if o.side == "buy"), 2
                ),
                "institutional_sell_volume": round(
                    sum(o.size for o in large_orders if o.side == "sell"), 2
                ),
            },
        )
        self._store_signal(symbol, signal)

    # ================================================================
    # STATISTICS
    # ================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Return detector-level statistics across all tracked symbols.

        Returns:
            Dictionary with keys: ``symbols_tracked``, ``trades_by_symbol``,
            ``signals_by_symbol``, ``cumulative_institutional_buy``,
            ``cumulative_institutional_sell``.
        """
        with self._lock:
            return {
                "symbols_tracked": list(self._trades.keys()),
                "trades_by_symbol": {
                    s: len(t) for s, t in self._trades.items()
                },
                "signals_by_symbol": {
                    s: len(q) for s, q in self._flow_signals.items()
                },
                "cumulative_institutional_buy": dict(
                    self._cumulative_institutional_buy
                ),
                "cumulative_institutional_sell": dict(
                    self._cumulative_institutional_sell
                ),
            }


# ================================================================
# FASTAPI INTEGRATION
# ================================================================


def create_institutional_flow_router(detector: InstitutionalFlowDetector):
    """
    Build a FastAPI router exposing institutional flow analysis endpoints.

    Routes:
        GET /api/institutional/{symbol}
            Full flow analysis for a symbol.
        GET /api/institutional/{symbol}/large-orders
            Institutional-size trades with optional ``min_size`` query param.
        GET /api/institutional/{symbol}/signals
            All stored flow signals for a symbol.
        GET /api/institutional/stats
            Detector-level statistics.

    Args:
        detector: :class:`InstitutionalFlowDetector` instance.

    Returns:
        ``fastapi.APIRouter`` instance.
    """
    from fastapi import APIRouter, HTTPException, Query

    router = APIRouter(
        prefix="/api/institutional",
        tags=["Institutional Flow"],
    )

    @router.get("/{symbol}")
    async def get_flow_analysis(symbol: str):
        """Run a complete institutional flow analysis for *symbol*."""
        result = detector.analyze_flow(symbol.upper())
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        if not result.get("large_orders") and not result.get("iceberg_signals"):
            raise HTTPException(
                status_code=404,
                detail=f"No institutional flow data found for {symbol!r}.",
            )
        return result

    @router.get("/{symbol}/large-orders")
    async def get_large_orders(
        symbol: str,
        min_size: Optional[float] = Query(
            default=None,
            description="Minimum order size override (lots)",
        ),
    ):
        """Return institutional-size orders for *symbol*."""
        orders = detector.get_large_orders(symbol.upper(), min_size=min_size)
        return {
            "symbol": symbol.upper(),
            "count": len(orders),
            "orders": orders,
        }

    @router.get("/{symbol}/signals")
    async def get_flow_signals(symbol: str):
        """Return all stored flow signals for *symbol*."""
        signals = detector.get_flow_signals(symbol.upper())
        return {
            "symbol": symbol.upper(),
            "count": len(signals),
            "signals": signals,
        }

    @router.get("/stats")
    async def get_stats():
        """Return detector-level statistics."""
        return detector.get_stats()

    return router


# ── global singleton ──────────────────────────────────────────────────────────

_institutional_flow_detector: Optional[InstitutionalFlowDetector] = None


def get_institutional_flow_detector() -> InstitutionalFlowDetector:
    """
    Return the global :class:`InstitutionalFlowDetector` singleton.

    Creates a default instance on first call.

    Returns:
        Global :class:`InstitutionalFlowDetector` instance.
    """
    global _institutional_flow_detector
    if _institutional_flow_detector is None:
        _institutional_flow_detector = InstitutionalFlowDetector()
    return _institutional_flow_detector
