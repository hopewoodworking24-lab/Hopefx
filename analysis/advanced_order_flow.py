"""
Advanced Order Flow Analysis Module

Enhanced order flow analysis tools providing institutional-grade insights:
- Real-time aggression metrics (bid vs ask aggressor)
- Volume imbalance by price level
- Stacked imbalances (consecutive price levels)
- Delta divergence detection (price vs cumulative delta)
- Volume clusters (support/resistance from volume)
- Order flow oscillator
- Buy/sell pressure gauges
- Market absorption detection

Inspired by: Bookmap, Sierra Chart, Jigsaw Trading, ATAS
"""

import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ================================================================
# DATA STRUCTURES
# ================================================================


@dataclass
class AggressionMetrics:
    """Real-time aggression metrics showing bid vs ask aggressor activity."""

    symbol: str
    timestamp: datetime
    buy_aggression: float  # 0-100, percentage of aggressive buys
    sell_aggression: float  # 0-100, percentage of aggressive sells
    aggression_score: float  # -100 (bearish) to +100 (bullish)
    dominant_side: str  # 'buyers', 'sellers', 'neutral'
    aggression_strength: str  # 'extreme', 'strong', 'moderate', 'weak'

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "buy_aggression": self.buy_aggression,
            "sell_aggression": self.sell_aggression,
            "aggression_score": self.aggression_score,
            "dominant_side": self.dominant_side,
            "aggression_strength": self.aggression_strength,
        }


@dataclass
class VolumeImbalanceLevel:
    """Volume imbalance at a single price level."""

    price: float
    buy_volume: float
    sell_volume: float
    imbalance_ratio: float  # buy/sell ratio, >1 bullish, <1 bearish
    imbalance_pct: float  # Percentage imbalance (-100 to +100)
    is_bid_imbalance: bool  # True when buys dominate
    is_ask_imbalance: bool  # True when sells dominate

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "price": self.price,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "imbalance_ratio": self.imbalance_ratio,
            "imbalance_pct": self.imbalance_pct,
            "is_bid_imbalance": self.is_bid_imbalance,
            "is_ask_imbalance": self.is_ask_imbalance,
        }


@dataclass
class StackedImbalance:
    """Consecutive price levels with the same directional imbalance."""

    start_price: float
    end_price: float
    num_levels: int
    direction: str  # 'bullish' or 'bearish'
    avg_imbalance: float
    total_buy_volume: float
    total_sell_volume: float
    levels: List[VolumeImbalanceLevel] = field(default_factory=list)
    strength: str = "moderate"  # 'extreme', 'strong', 'moderate', 'weak'

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "start_price": self.start_price,
            "end_price": self.end_price,
            "num_levels": self.num_levels,
            "direction": self.direction,
            "avg_imbalance": self.avg_imbalance,
            "total_buy_volume": self.total_buy_volume,
            "total_sell_volume": self.total_sell_volume,
            "strength": self.strength,
            "levels": [lv.to_dict() for lv in self.levels],
        }


@dataclass
class VolumeCluster:
    """High-volume price cluster acting as support or resistance."""

    price_level: float
    total_volume: float
    buy_volume: float
    sell_volume: float
    trade_count: int
    cluster_type: str  # 'support', 'resistance', 'neutral'
    strength: float  # Relative to other clusters (0-100)

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "price_level": self.price_level,
            "total_volume": self.total_volume,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "trade_count": self.trade_count,
            "cluster_type": self.cluster_type,
            "strength": self.strength,
        }


@dataclass
class DeltaDivergence:
    """Divergence between price direction and cumulative delta direction."""

    symbol: str
    timestamp: datetime
    divergence_type: str  # 'bullish', 'bearish', 'hidden_bullish', 'hidden_bearish'
    price_direction: str  # 'up', 'down', 'flat'
    delta_direction: str  # 'up', 'down', 'flat'
    price_change_pct: float
    delta_change_pct: float
    strength: float  # 0-100
    confidence: float  # 0-100

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "divergence_type": self.divergence_type,
            "price_direction": self.price_direction,
            "delta_direction": self.delta_direction,
            "price_change_pct": self.price_change_pct,
            "delta_change_pct": self.delta_change_pct,
            "strength": self.strength,
            "confidence": self.confidence,
        }


@dataclass
class OrderFlowOscillator:
    """Momentum oscillator based on order flow delta."""

    symbol: str
    timestamp: datetime
    oscillator_value: float  # -100 to +100
    fast_delta: float
    slow_delta: float
    signal_line: float
    histogram: float
    trend: str  # 'bullish', 'bearish', 'neutral'
    momentum: str  # 'accelerating', 'decelerating', 'steady'

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "oscillator_value": self.oscillator_value,
            "fast_delta": self.fast_delta,
            "slow_delta": self.slow_delta,
            "signal_line": self.signal_line,
            "histogram": self.histogram,
            "trend": self.trend,
            "momentum": self.momentum,
        }


@dataclass
class PressureGauges:
    """Real-time buy/sell pressure gauges."""

    symbol: str
    timestamp: datetime
    buy_pressure: float  # 0-100
    sell_pressure: float  # 0-100
    net_pressure: float  # -100 (max sell) to +100 (max buy)
    pressure_trend: str  # 'increasing_buy', 'increasing_sell', 'stable'
    large_trade_bias: str  # 'buy', 'sell', 'neutral' based on large trades
    small_trade_bias: str  # 'buy', 'sell', 'neutral' based on small trades
    large_trade_threshold: float

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "buy_pressure": self.buy_pressure,
            "sell_pressure": self.sell_pressure,
            "net_pressure": self.net_pressure,
            "pressure_trend": self.pressure_trend,
            "large_trade_bias": self.large_trade_bias,
            "small_trade_bias": self.small_trade_bias,
            "large_trade_threshold": self.large_trade_threshold,
        }


@dataclass
class AbsorptionZone:
    """Market absorption detection — large volume with minimal price movement."""

    symbol: str
    timestamp: datetime
    price_level: float
    absorbed_volume: float
    absorbing_side: str  # 'buyers_absorbing_sells', 'sellers_absorbing_buys'
    price_range: float  # How little price moved despite volume
    absorption_strength: str  # 'extreme', 'strong', 'moderate'
    buy_volume: float
    sell_volume: float
    volume_velocity: float  # Volume per second during absorption
    implication: str  # 'potential_reversal', 'continuation', 'unclear'

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "price_level": self.price_level,
            "absorbed_volume": self.absorbed_volume,
            "absorbing_side": self.absorbing_side,
            "price_range": self.price_range,
            "absorption_strength": self.absorption_strength,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "volume_velocity": self.volume_velocity,
            "implication": self.implication,
        }


@dataclass
class AdvancedOrderFlowResult:
    """Complete advanced order flow analysis result."""

    symbol: str
    timestamp: datetime
    aggression: Optional[AggressionMetrics]
    stacked_imbalances: List[StackedImbalance]
    delta_divergence: Optional[DeltaDivergence]
    volume_clusters: List[VolumeCluster]
    oscillator: Optional[OrderFlowOscillator]
    pressure_gauges: Optional[PressureGauges]
    absorption_zones: List[AbsorptionZone]
    overall_bias: str  # 'bullish', 'bearish', 'neutral'
    confidence: float  # 0-100
    signals: List[str]

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "aggression": self.aggression.to_dict() if self.aggression else None,
            "stacked_imbalances": [si.to_dict() for si in self.stacked_imbalances],
            "delta_divergence": self.delta_divergence.to_dict() if self.delta_divergence else None,
            "volume_clusters": [vc.to_dict() for vc in self.volume_clusters],
            "oscillator": self.oscillator.to_dict() if self.oscillator else None,
            "pressure_gauges": self.pressure_gauges.to_dict() if self.pressure_gauges else None,
            "absorption_zones": [az.to_dict() for az in self.absorption_zones],
            "overall_bias": self.overall_bias,
            "confidence": self.confidence,
            "signals": self.signals,
        }


# ================================================================
# INTERNAL TRADE RECORD
# ================================================================


@dataclass
class _Trade:
    """Internal trade record."""

    timestamp: datetime
    price: float
    size: float
    side: str  # 'buy' or 'sell'

    @property
    def is_buy(self) -> bool:
        """Return True if trade is a buy."""
        return self.side == "buy"

    @property
    def is_sell(self) -> bool:
        """Return True if trade is a sell."""
        return self.side == "sell"


# ================================================================
# ADVANCED ORDER FLOW ANALYZER
# ================================================================


class AdvancedOrderFlowAnalyzer:
    """
    Advanced order flow analysis service providing institutional-grade metrics.

    Features:
    - Real-time aggression metrics (bid vs ask aggressor)
    - Volume imbalance by price level with stacked imbalance detection
    - Delta divergence detection (price vs cumulative delta)
    - Volume cluster identification (support/resistance from volume)
    - Order flow oscillator (MACD-style momentum indicator)
    - Buy/sell pressure gauges with large vs small trade separation
    - Enhanced market absorption detection

    Thread-safe using threading.Lock. Circular buffers (deque) limit memory use.

    Usage:
        analyzer = AdvancedOrderFlowAnalyzer()

        # Feed trades (e.g., from websocket)
        analyzer.add_trade('XAUUSD', 1950.50, 10.0, 'buy')
        analyzer.add_trade('XAUUSD', 1950.45, 5.0, 'sell')

        # Run full analysis
        result = analyzer.analyze('XAUUSD')

        # Individual components
        aggression = analyzer.calculate_aggression_metrics('XAUUSD')
        clusters   = analyzer.identify_volume_clusters('XAUUSD')
        divergence = analyzer.detect_delta_divergence('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the advanced order flow analyzer.

        Args:
            config: Optional configuration overrides. Supported keys:
                - max_trades (int): Max trades buffered per symbol. Default 200000.
                - tick_size (float): Minimum price increment. Default 0.01.
                - imbalance_threshold (float): Ratio above which a level is imbalanced. Default 2.0.
                - absorption_window_seconds (int): Seconds for absorption window. Default 30.
                - large_trade_percentile (float): Percentile to classify large trades. Default 90.
                - value_area_pct (float): Fraction of volume in value area. Default 0.70.
        """
        self._config: Dict[str, Any] = config or {}

        self._max_trades: int = self._config.get("max_trades", 200_000)
        self._tick_size: float = self._config.get("tick_size", 0.01)
        self._imbalance_threshold: float = self._config.get("imbalance_threshold", 2.0)
        self._absorption_window_seconds: int = self._config.get("absorption_window_seconds", 30)
        self._large_trade_percentile: float = self._config.get("large_trade_percentile", 90.0)
        self._value_area_pct: float = self._config.get("value_area_pct", 0.70)

        # Per-symbol trade buffers — deque for O(1) append/popleft
        self._trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self._max_trades))

        # Running cumulative delta per symbol
        self._cumulative_delta: Dict[str, float] = defaultdict(float)

        # Historical delta snapshots for divergence detection [(timestamp, price, cum_delta)]
        self._delta_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5_000))

        # Thread safety
        self._lock = threading.Lock()

        logger.info(
            "AdvancedOrderFlowAnalyzer initialized (max_trades=%d, tick_size=%.4f)",
            self._max_trades,
            self._tick_size,
        )

    # ----------------------------------------------------------------
    # TRADE INGESTION
    # ----------------------------------------------------------------

    def add_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Add a single trade tick for a symbol.

        Args:
            symbol: Trading symbol (e.g., 'XAUUSD').
            price: Execution price.
            size: Trade size / volume.
            side: Aggressor side — 'buy' or 'sell'.
            timestamp: Trade timestamp. Defaults to utcnow().

        Raises:
            ValueError: If side is not 'buy' or 'sell'.
        """
        side_normalized = side.lower().strip()
        if side_normalized not in ("buy", "sell"):
            raise ValueError(f"Invalid trade side '{side}'. Must be 'buy' or 'sell'.")

        ts = timestamp or datetime.now(timezone.utc)
        trade = _Trade(timestamp=ts, price=price, size=size, side=side_normalized)

        with self._lock:
            self._trades[symbol].append(trade)
            delta = size if trade.is_buy else -size
            self._cumulative_delta[symbol] += delta
            self._delta_history[symbol].append((ts, price, self._cumulative_delta[symbol]))

    def add_trades(self, symbol: str, trades: List[Dict]) -> None:
        """
        Add multiple trades at once.

        Args:
            symbol: Trading symbol.
            trades: List of trade dicts with keys: price, size, side, timestamp (optional).
        """
        for t in trades:
            self.add_trade(
                symbol=symbol,
                price=t["price"],
                size=t["size"],
                side=t["side"],
                timestamp=t.get("timestamp"),
            )

    def _get_recent_trades(self, symbol: str, lookback_minutes: float) -> List[_Trade]:
        """Return trades within the lookback window (thread-safe snapshot)."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        with self._lock:
            trades_snapshot = list(self._trades[symbol])
        return [t for t in trades_snapshot if t.timestamp >= cutoff]

    def _get_all_trades(self, symbol: str) -> List[_Trade]:
        """Return all buffered trades for a symbol (thread-safe snapshot)."""
        with self._lock:
            return list(self._trades[symbol])

    # ----------------------------------------------------------------
    # AGGRESSION METRICS
    # ----------------------------------------------------------------

    def calculate_aggression_metrics(
        self, symbol: str, lookback_minutes: float = 5.0
    ) -> Optional[AggressionMetrics]:
        """
        Calculate bid vs ask aggressor metrics over a recent window.

        Aggression is measured by counting how many trades were initiated
        by aggressive buyers (lifting the ask) versus aggressive sellers
        (hitting the bid), weighted by volume.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Look-back window in minutes. Default 5.

        Returns:
            AggressionMetrics or None if insufficient data.
        """
        trades = self._get_recent_trades(symbol, lookback_minutes)
        if not trades:
            logger.debug("calculate_aggression_metrics: no trades for %s", symbol)
            return None

        buy_vol = sum(t.size for t in trades if t.is_buy)
        sell_vol = sum(t.size for t in trades if t.is_sell)
        total_vol = buy_vol + sell_vol

        if total_vol == 0:
            return None

        buy_aggression = round((buy_vol / total_vol) * 100, 2)
        sell_aggression = round((sell_vol / total_vol) * 100, 2)

        # Score: +100 = all buys, -100 = all sells
        aggression_score = round(buy_aggression - sell_aggression, 2)

        if aggression_score > 20:
            dominant_side = "buyers"
        elif aggression_score < -20:
            dominant_side = "sellers"
        else:
            dominant_side = "neutral"

        abs_score = abs(aggression_score)
        if abs_score >= 70:
            strength = "extreme"
        elif abs_score >= 40:
            strength = "strong"
        elif abs_score >= 20:
            strength = "moderate"
        else:
            strength = "weak"

        return AggressionMetrics(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            buy_aggression=buy_aggression,
            sell_aggression=sell_aggression,
            aggression_score=aggression_score,
            dominant_side=dominant_side,
            aggression_strength=strength,
        )

    def get_aggression_metrics(
        self, symbol: str, lookback_minutes: float = 5.0
    ) -> Optional[AggressionMetrics]:
        """
        Shortcut for calculate_aggression_metrics.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Look-back window in minutes.

        Returns:
            AggressionMetrics or None.
        """
        return self.calculate_aggression_metrics(symbol, lookback_minutes)

    # ----------------------------------------------------------------
    # VOLUME IMBALANCE BY PRICE LEVEL
    # ----------------------------------------------------------------

    def _build_price_level_map(
        self, trades: List[_Trade], bucket_size: Optional[float] = None
    ) -> Dict[float, Dict]:
        """
        Aggregate trades into a price-bucketed map.

        Args:
            trades: List of trade records.
            bucket_size: Price bucket width. Defaults to tick_size.

        Returns:
            Dict mapping bucketed price -> {buy_volume, sell_volume, trade_count}.
        """
        bsize = bucket_size or self._tick_size
        level_map: Dict[float, Dict] = defaultdict(
            lambda: {"buy_volume": 0.0, "sell_volume": 0.0, "trade_count": 0}
        )
        for trade in trades:
            bucket = round(math.floor(trade.price / bsize) * bsize, 8)
            lv = level_map[bucket]
            lv["trade_count"] += 1
            if trade.is_buy:
                lv["buy_volume"] += trade.size
            else:
                lv["sell_volume"] += trade.size
        return level_map

    def _calculate_bucket_size(
        self, trades: List[_Trade], num_buckets: int = 50
    ) -> float:
        """Derive a sensible bucket size from the price range of trades."""
        if not trades:
            return self._tick_size
        prices = [t.price for t in trades]
        price_range = max(prices) - min(prices)
        if price_range <= 0:
            return self._tick_size
        bucket = price_range / num_buckets
        # Round to nearest tick multiple
        bucket = max(self._tick_size, round(bucket / self._tick_size) * self._tick_size)
        return bucket

    def get_volume_imbalances(
        self,
        symbol: str,
        lookback_minutes: float = 30.0,
        price_buckets: int = 50,
    ) -> List[VolumeImbalanceLevel]:
        """
        Calculate volume imbalance at each price level.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Analysis window in minutes.
            price_buckets: Number of price buckets to build.

        Returns:
            List of VolumeImbalanceLevel sorted ascending by price.
        """
        trades = self._get_recent_trades(symbol, lookback_minutes)
        if not trades:
            return []

        bucket_size = self._calculate_bucket_size(trades, price_buckets)
        level_map = self._build_price_level_map(trades, bucket_size)

        results: List[VolumeImbalanceLevel] = []
        for price in sorted(level_map):
            lv = level_map[price]
            bv = lv["buy_volume"]
            sv = lv["sell_volume"]
            total = bv + sv

            if total == 0:
                continue

            ratio = (bv / sv) if sv > 0 else float("inf")
            imb_pct = round(((bv - sv) / total) * 100, 2)

            is_bid_imb = ratio >= self._imbalance_threshold
            is_ask_imb = sv > 0 and (sv / bv) >= self._imbalance_threshold if bv > 0 else sv > 0

            results.append(
                VolumeImbalanceLevel(
                    price=price,
                    buy_volume=round(bv, 6),
                    sell_volume=round(sv, 6),
                    imbalance_ratio=round(min(ratio, 999.0), 4),
                    imbalance_pct=imb_pct,
                    is_bid_imbalance=is_bid_imb,
                    is_ask_imbalance=is_ask_imb,
                )
            )

        return results

    # ----------------------------------------------------------------
    # STACKED IMBALANCES
    # ----------------------------------------------------------------

    def detect_stacked_imbalances(
        self,
        symbol: str,
        min_stack_levels: int = 3,
        lookback_minutes: float = 30.0,
        price_buckets: int = 50,
    ) -> List[StackedImbalance]:
        """
        Detect stacked imbalances — consecutive price levels with the same
        directional volume dominance, indicating strong institutional interest.

        Args:
            symbol: Trading symbol.
            min_stack_levels: Minimum consecutive levels to qualify. Default 3.
            lookback_minutes: Analysis window in minutes. Default 30.
            price_buckets: Price bucket granularity. Default 50.

        Returns:
            List of StackedImbalance objects, strongest first.
        """
        levels = self.get_volume_imbalances(symbol, lookback_minutes, price_buckets)
        if len(levels) < min_stack_levels:
            return []

        stacks: List[StackedImbalance] = []
        i = 0
        while i < len(levels):
            lv = levels[i]
            if not lv.is_bid_imbalance and not lv.is_ask_imbalance:
                i += 1
                continue

            direction = "bullish" if lv.is_bid_imbalance else "bearish"
            stack_levels = [lv]
            j = i + 1

            while j < len(levels):
                next_lv = levels[j]
                next_dir = None
                if next_lv.is_bid_imbalance:
                    next_dir = "bullish"
                elif next_lv.is_ask_imbalance:
                    next_dir = "bearish"

                if next_dir == direction:
                    stack_levels.append(next_lv)
                    j += 1
                else:
                    break

            if len(stack_levels) >= min_stack_levels:
                total_buy = sum(sl.buy_volume for sl in stack_levels)
                total_sell = sum(sl.sell_volume for sl in stack_levels)
                avg_imb = round(
                    sum(sl.imbalance_pct for sl in stack_levels) / len(stack_levels), 2
                )

                num = len(stack_levels)
                if num >= 8 or abs(avg_imb) >= 70:
                    strength = "extreme"
                elif num >= 5 or abs(avg_imb) >= 50:
                    strength = "strong"
                elif num >= 3 or abs(avg_imb) >= 30:
                    strength = "moderate"
                else:
                    strength = "weak"

                stacks.append(
                    StackedImbalance(
                        start_price=stack_levels[0].price,
                        end_price=stack_levels[-1].price,
                        num_levels=num,
                        direction=direction,
                        avg_imbalance=avg_imb,
                        total_buy_volume=round(total_buy, 6),
                        total_sell_volume=round(total_sell, 6),
                        levels=stack_levels,
                        strength=strength,
                    )
                )
            i = j if j > i else i + 1

        # Sort by num_levels descending (strongest stacks first)
        stacks.sort(key=lambda x: x.num_levels, reverse=True)
        return stacks

    # ----------------------------------------------------------------
    # DELTA DIVERGENCE
    # ----------------------------------------------------------------

    def detect_delta_divergence(
        self, symbol: str, lookback_minutes: float = 30.0
    ) -> Optional[DeltaDivergence]:
        """
        Detect divergence between price direction and cumulative delta direction.

        Divergence types:
        - bullish: Price makes lower low but delta makes higher low (hidden strength).
        - bearish: Price makes higher high but delta makes lower high (hidden weakness).
        - hidden_bullish: Price makes higher high, delta makes higher high faster.
        - hidden_bearish: Price makes lower low, delta makes lower low faster.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Analysis window in minutes. Default 30.

        Returns:
            DeltaDivergence or None if insufficient history.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)

        with self._lock:
            history = [
                (ts, price, cdelta)
                for ts, price, cdelta in self._delta_history[symbol]
                if ts >= cutoff
            ]

        if len(history) < 20:
            logger.debug("detect_delta_divergence: insufficient history for %s", symbol)
            return None

        # Compare first half vs second half to detect structural divergence
        midpoint = len(history) // 2
        first_half = history[:midpoint]
        second_half = history[midpoint:]

        first_price = sum(h[1] for h in first_half) / len(first_half)
        second_price = sum(h[1] for h in second_half) / len(second_half)
        first_delta = sum(h[2] for h in first_half) / len(first_half)
        second_delta = sum(h[2] for h in second_half) / len(second_half)

        price_change = second_price - first_price
        delta_change = second_delta - first_delta

        # Normalise changes to percentages avoiding division by zero
        price_change_pct = (price_change / first_price * 100) if first_price != 0 else 0.0
        delta_ref = abs(first_delta) if first_delta != 0 else 1.0
        delta_change_pct = (delta_change / delta_ref) * 100

        price_dir = "up" if price_change_pct > 0.01 else ("down" if price_change_pct < -0.01 else "flat")
        delta_dir = "up" if delta_change_pct > 0.5 else ("down" if delta_change_pct < -0.5 else "flat")

        if price_dir == "flat" or delta_dir == "flat":
            return None

        divergence_type: Optional[str] = None
        strength = 0.0
        confidence = 0.0

        # Classic divergence: price and delta move in opposite directions
        if price_dir == "down" and delta_dir == "up":
            divergence_type = "bullish"
            strength = min(100.0, abs(price_change_pct) + abs(delta_change_pct))
            confidence = min(100.0, strength * 0.8)
        elif price_dir == "up" and delta_dir == "down":
            divergence_type = "bearish"
            strength = min(100.0, abs(price_change_pct) + abs(delta_change_pct))
            confidence = min(100.0, strength * 0.8)
        # Hidden divergence: both move same direction but delta moves proportionally more
        elif price_dir == "up" and delta_dir == "up" and delta_change_pct > price_change_pct * 2:
            divergence_type = "hidden_bullish"
            strength = min(100.0, abs(delta_change_pct - price_change_pct))
            confidence = min(100.0, strength * 0.6)
        elif price_dir == "down" and delta_dir == "down" and abs(delta_change_pct) > abs(price_change_pct) * 2:
            divergence_type = "hidden_bearish"
            strength = min(100.0, abs(delta_change_pct) - abs(price_change_pct))
            confidence = min(100.0, strength * 0.6)

        if divergence_type is None:
            return None

        return DeltaDivergence(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            divergence_type=divergence_type,
            price_direction=price_dir,
            delta_direction=delta_dir,
            price_change_pct=round(price_change_pct, 4),
            delta_change_pct=round(delta_change_pct, 4),
            strength=round(strength, 2),
            confidence=round(confidence, 2),
        )

    # ----------------------------------------------------------------
    # VOLUME CLUSTERS
    # ----------------------------------------------------------------

    def identify_volume_clusters(
        self,
        symbol: str,
        num_clusters: int = 10,
        lookback_minutes: float = 60.0,
        price_buckets: int = 100,
    ) -> List[VolumeCluster]:
        """
        Identify high-volume price clusters that act as support or resistance.

        Uses volume-weighted bucketing to find price levels where the market
        has repeatedly transacted large volumes — these act as magnets.

        Args:
            symbol: Trading symbol.
            num_clusters: Maximum number of clusters to return. Default 10.
            lookback_minutes: Analysis window in minutes. Default 60.
            price_buckets: Granularity of price buckets. Default 100.

        Returns:
            List of VolumeCluster objects, sorted by total_volume descending.
        """
        trades = self._get_recent_trades(symbol, lookback_minutes)
        if not trades:
            return []

        bucket_size = self._calculate_bucket_size(trades, price_buckets)
        level_map = self._build_price_level_map(trades, bucket_size)

        all_volumes = [
            lv["buy_volume"] + lv["sell_volume"] for lv in level_map.values()
        ]
        if not all_volumes:
            return []

        max_vol = max(all_volumes)
        total_vol_all = sum(all_volumes)
        avg_vol = total_vol_all / len(all_volumes) if all_volumes else 1.0

        # Current price proxy
        current_price = trades[-1].price

        # Only keep levels with above-average volume (these are clusters)
        high_vol_levels = [
            (price, lv)
            for price, lv in level_map.items()
            if (lv["buy_volume"] + lv["sell_volume"]) > avg_vol
        ]
        high_vol_levels.sort(key=lambda x: x[1]["buy_volume"] + x[1]["sell_volume"], reverse=True)

        clusters: List[VolumeCluster] = []
        for price, lv in high_vol_levels[:num_clusters]:
            bv = lv["buy_volume"]
            sv = lv["sell_volume"]
            total = bv + sv

            relative_strength = round((total / max_vol) * 100, 2) if max_vol > 0 else 0.0

            if price < current_price:
                cluster_type = "support"
            elif price > current_price:
                cluster_type = "resistance"
            else:
                cluster_type = "neutral"

            clusters.append(
                VolumeCluster(
                    price_level=price,
                    total_volume=round(total, 6),
                    buy_volume=round(bv, 6),
                    sell_volume=round(sv, 6),
                    trade_count=lv["trade_count"],
                    cluster_type=cluster_type,
                    strength=relative_strength,
                )
            )

        clusters.sort(key=lambda x: x.total_volume, reverse=True)
        return clusters

    # ----------------------------------------------------------------
    # ORDER FLOW OSCILLATOR
    # ----------------------------------------------------------------

    def calculate_order_flow_oscillator(
        self,
        symbol: str,
        fast_period: float = 5.0,
        slow_period: float = 20.0,
    ) -> Optional[OrderFlowOscillator]:
        """
        Calculate a MACD-style order flow oscillator based on delta momentum.

        The oscillator compares delta accumulated over a fast window versus a
        slow window to highlight shifts in buying/selling pressure.

        Args:
            symbol: Trading symbol.
            fast_period: Fast window in minutes. Default 5.
            slow_period: Slow window in minutes. Default 20.

        Returns:
            OrderFlowOscillator or None if insufficient data.
        """
        if fast_period >= slow_period:
            logger.warning(
                "fast_period (%s) must be less than slow_period (%s)", fast_period, slow_period
            )
            return None

        fast_trades = self._get_recent_trades(symbol, fast_period)
        slow_trades = self._get_recent_trades(symbol, slow_period)

        if not slow_trades:
            return None

        def _net_delta(trade_list: List[_Trade]) -> float:
            return sum(t.size if t.is_buy else -t.size for t in trade_list)

        fast_delta = _net_delta(fast_trades)
        slow_delta = _net_delta(slow_trades)

        # Normalise by total volume to get a comparable scale
        fast_total = sum(t.size for t in fast_trades) or 1.0
        slow_total = sum(t.size for t in slow_trades) or 1.0

        fast_norm = (fast_delta / fast_total) * 100
        slow_norm = (slow_delta / slow_total) * 100

        histogram = round(fast_norm - slow_norm, 4)
        # Simple signal line approximation (average of fast and slow)
        signal_line = round((fast_norm + slow_norm) / 2, 4)
        oscillator_value = round(fast_norm, 4)

        if fast_norm > slow_norm:
            trend = "bullish"
        elif fast_norm < slow_norm:
            trend = "bearish"
        else:
            trend = "neutral"

        if abs(histogram) > abs(signal_line) * 0.1:
            momentum = "accelerating"
        elif abs(histogram) < abs(signal_line) * 0.05:
            momentum = "decelerating"
        else:
            momentum = "steady"

        return OrderFlowOscillator(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            oscillator_value=oscillator_value,
            fast_delta=round(fast_norm, 4),
            slow_delta=round(slow_norm, 4),
            signal_line=signal_line,
            histogram=histogram,
            trend=trend,
            momentum=momentum,
        )

    # ----------------------------------------------------------------
    # PRESSURE GAUGES
    # ----------------------------------------------------------------

    def get_pressure_gauges(
        self, symbol: str, lookback_minutes: float = 15.0
    ) -> Optional[PressureGauges]:
        """
        Calculate real-time buy/sell pressure gauges with large/small trade separation.

        Splits trades at the 90th-percentile size threshold to detect whether
        large institutional players or small retail traders are driving pressure.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Analysis window in minutes. Default 15.

        Returns:
            PressureGauges or None if insufficient data.
        """
        trades = self._get_recent_trades(symbol, lookback_minutes)
        if not trades:
            return None

        total_buy = sum(t.size for t in trades if t.is_buy)
        total_sell = sum(t.size for t in trades if t.is_sell)
        total_vol = total_buy + total_sell

        if total_vol == 0:
            return None

        buy_pressure = round((total_buy / total_vol) * 100, 2)
        sell_pressure = round((total_sell / total_vol) * 100, 2)
        net_pressure = round(buy_pressure - sell_pressure, 2)

        # Determine large-trade threshold at configured percentile
        sizes = sorted(t.size for t in trades)
        threshold_idx = int(len(sizes) * self._large_trade_percentile / 100)
        threshold_idx = min(threshold_idx, len(sizes) - 1)
        large_threshold = sizes[threshold_idx]

        large_trades = [t for t in trades if t.size >= large_threshold]
        small_trades = [t for t in trades if t.size < large_threshold]

        def _bias(trade_list: List[_Trade]) -> str:
            buy_v = sum(t.size for t in trade_list if t.is_buy)
            sell_v = sum(t.size for t in trade_list if t.is_sell)
            if buy_v > sell_v * 1.2:
                return "buy"
            if sell_v > buy_v * 1.2:
                return "sell"
            return "neutral"

        large_bias = _bias(large_trades) if large_trades else "neutral"
        small_bias = _bias(small_trades) if small_trades else "neutral"

        # Pressure trend: compare first and second half of window
        half = len(trades) // 2
        if half > 0:
            first_net = sum(
                t.size if t.is_buy else -t.size for t in trades[:half]
            )
            second_net = sum(
                t.size if t.is_buy else -t.size for t in trades[half:]
            )
            if second_net > first_net * 1.1:
                pressure_trend = "increasing_buy"
            elif second_net < first_net * 0.9:
                pressure_trend = "increasing_sell"
            else:
                pressure_trend = "stable"
        else:
            pressure_trend = "stable"

        return PressureGauges(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            buy_pressure=buy_pressure,
            sell_pressure=sell_pressure,
            net_pressure=net_pressure,
            pressure_trend=pressure_trend,
            large_trade_bias=large_bias,
            small_trade_bias=small_bias,
            large_trade_threshold=round(large_threshold, 6),
        )

    # ----------------------------------------------------------------
    # MARKET ABSORPTION
    # ----------------------------------------------------------------

    def detect_market_absorption(
        self, symbol: str, lookback_minutes: float = 30.0
    ) -> List[AbsorptionZone]:
        """
        Detect market absorption — periods where large volume is transacted but
        price barely moves, indicating strong opposing interest absorbing flow.

        Absorption by buyers (buying all sell pressure) is bullish.
        Absorption by sellers (selling into all buy pressure) is bearish.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Analysis window in minutes. Default 30.

        Returns:
            List of AbsorptionZone objects, sorted by absorbed_volume descending.
        """
        trades = self._get_recent_trades(symbol, lookback_minutes)
        if len(trades) < 10:
            return []

        window_size = timedelta(seconds=self._absorption_window_seconds)
        zones: List[AbsorptionZone] = []

        # Slide a fixed-width time window through the trades
        i = 0
        while i < len(trades):
            window_start_ts = trades[i].timestamp
            window_end_ts = window_start_ts + window_size

            window_trades = [
                t for t in trades[i:] if t.timestamp <= window_end_ts
            ]

            if len(window_trades) < 5:
                i += 1
                continue

            prices = [t.price for t in window_trades]
            price_range = max(prices) - min(prices)
            avg_price = sum(prices) / len(prices)
            total_vol = sum(t.size for t in window_trades)
            buy_vol = sum(t.size for t in window_trades if t.is_buy)
            sell_vol = sum(t.size for t in window_trades if t.is_sell)

            # Duration in seconds
            duration_secs = max(
                (window_trades[-1].timestamp - window_trades[0].timestamp).total_seconds(),
                1.0,
            )
            vol_velocity = total_vol / duration_secs

            # Absorption criterion: high volume but tiny price range
            # A move of < 0.05% of price with meaningful volume qualifies
            price_move_pct = (price_range / avg_price) if avg_price > 0 else 0
            if price_move_pct >= 0.0005:  # 0.05% threshold
                i += len(window_trades)
                continue

            # Classify which side is absorbing
            if sell_vol > buy_vol * 1.5:
                # Lots of selling but price not falling — buyers absorbing
                absorbing_side = "buyers_absorbing_sells"
                implication = "potential_reversal"
            elif buy_vol > sell_vol * 1.5:
                # Lots of buying but price not rising — sellers absorbing
                absorbing_side = "sellers_absorbing_buys"
                implication = "potential_reversal"
            else:
                absorbing_side = "two_sided_absorption"
                implication = "unclear"

            if total_vol > 0:
                if vol_velocity > 10 and price_move_pct < 0.0002:
                    absorption_strength = "extreme"
                elif vol_velocity > 3:
                    absorption_strength = "strong"
                else:
                    absorption_strength = "moderate"

                zones.append(
                    AbsorptionZone(
                        symbol=symbol,
                        timestamp=window_trades[0].timestamp,
                        price_level=round(avg_price, 5),
                        absorbed_volume=round(total_vol, 6),
                        absorbing_side=absorbing_side,
                        price_range=round(price_range, 5),
                        absorption_strength=absorption_strength,
                        buy_volume=round(buy_vol, 6),
                        sell_volume=round(sell_vol, 6),
                        volume_velocity=round(vol_velocity, 4),
                        implication=implication,
                    )
                )

            i += len(window_trades)

        zones.sort(key=lambda z: z.absorbed_volume, reverse=True)
        return zones

    # ----------------------------------------------------------------
    # VOLUME PROFILE
    # ----------------------------------------------------------------

    def get_volume_profile(
        self,
        symbol: str,
        price_buckets: int = 50,
        lookback_minutes: float = 60.0,
    ) -> Dict:
        """
        Build a full volume profile with POC, VAH, VAL, and per-level detail.

        Args:
            symbol: Trading symbol.
            price_buckets: Number of price levels. Default 50.
            lookback_minutes: Analysis window in minutes. Default 60.

        Returns:
            Dict with keys: symbol, levels, poc, vah, val, total_volume,
            total_buy_volume, total_sell_volume, total_delta.
        """
        trades = self._get_recent_trades(symbol, lookback_minutes)
        if not trades:
            return {"symbol": symbol, "levels": [], "poc": None, "vah": None, "val": None}

        bucket_size = self._calculate_bucket_size(trades, price_buckets)
        level_map = self._build_price_level_map(trades, bucket_size)

        levels = []
        total_buy = 0.0
        total_sell = 0.0
        for price in sorted(level_map):
            lv = level_map[price]
            bv = lv["buy_volume"]
            sv = lv["sell_volume"]
            total_buy += bv
            total_sell += sv
            levels.append(
                {
                    "price": price,
                    "total_volume": round(bv + sv, 6),
                    "buy_volume": round(bv, 6),
                    "sell_volume": round(sv, 6),
                    "delta": round(bv - sv, 6),
                    "trade_count": lv["trade_count"],
                }
            )

        total_volume = total_buy + total_sell

        # POC — price of maximum volume
        poc = max(levels, key=lambda x: x["total_volume"])["price"] if levels else None

        # Value Area — expand from POC to cover value_area_pct of total volume
        vah: Optional[float] = None
        val: Optional[float] = None
        if poc is not None and levels:
            sorted_by_vol = sorted(levels, key=lambda x: -x["total_volume"])
            target = total_volume * self._value_area_pct
            accumulated = 0.0
            va_prices = []
            for lv in sorted_by_vol:
                accumulated += lv["total_volume"]
                va_prices.append(lv["price"])
                if accumulated >= target:
                    break
            if va_prices:
                vah = max(va_prices)
                val = min(va_prices)

        return {
            "symbol": symbol,
            "levels": levels,
            "poc": poc,
            "vah": vah,
            "val": val,
            "total_volume": round(total_volume, 6),
            "total_buy_volume": round(total_buy, 6),
            "total_sell_volume": round(total_sell, 6),
            "total_delta": round(total_buy - total_sell, 6),
        }

    # ----------------------------------------------------------------
    # KEY LEVELS
    # ----------------------------------------------------------------

    def get_key_levels(self, symbol: str) -> Dict:
        """
        Return key support and resistance levels derived from order flow.

        Combines volume clusters, POC, and value area levels into a single
        unified key-level map.

        Args:
            symbol: Trading symbol.

        Returns:
            Dict with keys: support (list), resistance (list), poc (dict|None),
            vah (float|None), val (float|None).
        """
        profile = self.get_volume_profile(symbol, price_buckets=50)
        clusters = self.identify_volume_clusters(symbol, num_clusters=10)

        trades_snapshot = self._get_all_trades(symbol)
        current_price = trades_snapshot[-1].price if trades_snapshot else None

        support: List[Dict] = []
        resistance: List[Dict] = []

        for cluster in clusters:
            entry = {
                "price": cluster.price_level,
                "volume": cluster.total_volume,
                "strength": cluster.strength,
                "source": "volume_cluster",
            }
            if cluster.cluster_type == "support":
                support.append(entry)
            elif cluster.cluster_type == "resistance":
                resistance.append(entry)

        poc = profile.get("poc")
        vah = profile.get("vah")
        val = profile.get("val")

        if val is not None and current_price is not None:
            if val < current_price:
                support.append({"price": val, "volume": 0, "strength": 70, "source": "val"})
            else:
                resistance.append({"price": val, "volume": 0, "strength": 70, "source": "val"})

        if vah is not None and current_price is not None:
            if vah < current_price:
                support.append({"price": vah, "volume": 0, "strength": 70, "source": "vah"})
            else:
                resistance.append({"price": vah, "volume": 0, "strength": 70, "source": "vah"})

        support.sort(key=lambda x: -x["price"])
        resistance.sort(key=lambda x: x["price"])

        return {
            "support": support,
            "resistance": resistance,
            "poc": {"price": poc, "source": "poc"} if poc is not None else None,
            "vah": vah,
            "val": val,
        }

    # ----------------------------------------------------------------
    # COMPREHENSIVE ANALYSIS
    # ----------------------------------------------------------------

    def analyze(self, symbol: str) -> AdvancedOrderFlowResult:
        """
        Run the complete advanced order flow analysis pipeline for a symbol.

        Combines aggression metrics, stacked imbalances, delta divergence,
        volume clusters, oscillator, pressure gauges, and absorption detection
        into a single result with an overall directional bias and confidence score.

        Args:
            symbol: Trading symbol.

        Returns:
            AdvancedOrderFlowResult with all component results populated.
        """
        logger.debug("Running full advanced order flow analysis for %s", symbol)

        aggression = self.calculate_aggression_metrics(symbol)
        stacked = self.detect_stacked_imbalances(symbol)
        divergence = self.detect_delta_divergence(symbol)
        clusters = self.identify_volume_clusters(symbol)
        oscillator = self.calculate_order_flow_oscillator(symbol)
        pressure = self.get_pressure_gauges(symbol)
        absorption = self.detect_market_absorption(symbol)

        # Score signals: positive = bullish, negative = bearish
        score = 0.0
        signals: List[str] = []

        if aggression:
            if aggression.dominant_side == "buyers":
                score += 1.5
                signals.append(f"Aggressive buying ({aggression.aggression_strength})")
            elif aggression.dominant_side == "sellers":
                score -= 1.5
                signals.append(f"Aggressive selling ({aggression.aggression_strength})")

        if stacked:
            for stack in stacked[:2]:
                if stack.direction == "bullish":
                    score += 1.0
                    signals.append(
                        f"Stacked bid imbalance: {stack.num_levels} levels ({stack.strength})"
                    )
                else:
                    score -= 1.0
                    signals.append(
                        f"Stacked ask imbalance: {stack.num_levels} levels ({stack.strength})"
                    )

        if divergence:
            if divergence.divergence_type in ("bullish", "hidden_bullish"):
                score += 1.5
                signals.append(f"Delta divergence: {divergence.divergence_type}")
            else:
                score -= 1.5
                signals.append(f"Delta divergence: {divergence.divergence_type}")

        if oscillator:
            if oscillator.trend == "bullish":
                score += 1.0
                signals.append(f"Order flow oscillator bullish ({oscillator.momentum})")
            elif oscillator.trend == "bearish":
                score -= 1.0
                signals.append(f"Order flow oscillator bearish ({oscillator.momentum})")

        if pressure:
            if pressure.net_pressure > 15:
                score += 0.5
                signals.append("Buy pressure dominant")
            elif pressure.net_pressure < -15:
                score -= 0.5
                signals.append("Sell pressure dominant")

            if pressure.large_trade_bias == "buy":
                score += 1.0
                signals.append("Large traders buying")
            elif pressure.large_trade_bias == "sell":
                score -= 1.0
                signals.append("Large traders selling")

        if absorption:
            for zone in absorption[:2]:
                if zone.absorbing_side == "buyers_absorbing_sells":
                    score += 1.0
                    signals.append(
                        f"Buy absorption at {zone.price_level:.2f} ({zone.absorption_strength})"
                    )
                elif zone.absorbing_side == "sellers_absorbing_buys":
                    score -= 1.0
                    signals.append(
                        f"Sell absorption at {zone.price_level:.2f} ({zone.absorption_strength})"
                    )

        # Determine overall bias
        if score > 2.0:
            overall_bias = "bullish"
        elif score < -2.0:
            overall_bias = "bearish"
        else:
            overall_bias = "neutral"

        # Confidence: how many signals aligned
        max_score = 9.0  # theoretical maximum
        confidence = round(min(100.0, (abs(score) / max_score) * 100), 2)

        return AdvancedOrderFlowResult(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            aggression=aggression,
            stacked_imbalances=stacked,
            delta_divergence=divergence,
            volume_clusters=clusters,
            oscillator=oscillator,
            pressure_gauges=pressure,
            absorption_zones=absorption,
            overall_bias=overall_bias,
            confidence=confidence,
            signals=signals,
        )

    # ----------------------------------------------------------------
    # STATISTICS & MANAGEMENT
    # ----------------------------------------------------------------

    def get_stats(self) -> Dict:
        """
        Return runtime statistics for the analyzer.

        Returns:
            Dict with trade counts, delta, and tracked symbols.
        """
        with self._lock:
            stats = {
                "symbols_tracked": list(self._trades.keys()),
                "trades_by_symbol": {s: len(t) for s, t in self._trades.items()},
                "total_trades": sum(len(t) for t in self._trades.values()),
                "cumulative_delta": dict(self._cumulative_delta),
            }
        return stats

    def clear_symbol(self, symbol: str) -> None:
        """
        Clear all trade data for a symbol.

        Args:
            symbol: Trading symbol to clear.
        """
        with self._lock:
            self._trades.pop(symbol, None)
            self._cumulative_delta.pop(symbol, None)
            self._delta_history.pop(symbol, None)
        logger.info("Cleared data for symbol %s", symbol)


# ================================================================
# FASTAPI ROUTER
# ================================================================


def create_advanced_order_flow_router(analyzer: AdvancedOrderFlowAnalyzer):
    """
    Create a FastAPI router with all advanced order flow endpoints.

    Args:
        analyzer: AdvancedOrderFlowAnalyzer instance to back the endpoints.

    Returns:
        FastAPI APIRouter with the following endpoints:
            GET /api/order-flow/{symbol}/aggression
            GET /api/order-flow/{symbol}/divergence
            GET /api/order-flow/{symbol}/clusters
            GET /api/order-flow/{symbol}/stacked-imbalances
            GET /api/order-flow/{symbol}/oscillator
            GET /api/order-flow/{symbol}/pressure
            GET /api/order-flow/{symbol}/absorption
            GET /api/order-flow/{symbol}/analyze
            GET /api/order-flow/{symbol}/volume-profile
            GET /api/order-flow/{symbol}/key-levels
            GET /api/order-flow/stats
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/order-flow", tags=["Advanced Order Flow"])

    @router.get("/{symbol}/aggression")
    async def get_aggression(symbol: str, lookback_minutes: float = 5.0):
        """Get real-time bid vs ask aggression metrics."""
        result = analyzer.calculate_aggression_metrics(symbol, lookback_minutes)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Insufficient trade data for symbol '{symbol}'",
            )
        return result.to_dict()

    @router.get("/{symbol}/divergence")
    async def get_divergence(symbol: str, lookback_minutes: float = 30.0):
        """Detect delta divergence between price and cumulative delta."""
        result = analyzer.detect_delta_divergence(symbol, lookback_minutes)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No divergence detected or insufficient data for '{symbol}'",
            )
        return result.to_dict()

    @router.get("/{symbol}/clusters")
    async def get_clusters(
        symbol: str, num_clusters: int = 10, lookback_minutes: float = 60.0
    ):
        """Get high-volume price clusters acting as support/resistance."""
        clusters = analyzer.identify_volume_clusters(symbol, num_clusters, lookback_minutes)
        return {
            "symbol": symbol,
            "clusters": [c.to_dict() for c in clusters],
            "count": len(clusters),
        }

    @router.get("/{symbol}/stacked-imbalances")
    async def get_stacked_imbalances(
        symbol: str,
        min_stack_levels: int = 3,
        lookback_minutes: float = 30.0,
    ):
        """Detect stacked imbalances across consecutive price levels."""
        stacks = analyzer.detect_stacked_imbalances(symbol, min_stack_levels, lookback_minutes)
        return {
            "symbol": symbol,
            "stacked_imbalances": [s.to_dict() for s in stacks],
            "count": len(stacks),
        }

    @router.get("/{symbol}/oscillator")
    async def get_oscillator(
        symbol: str, fast_period: float = 5.0, slow_period: float = 20.0
    ):
        """Get order flow oscillator values."""
        result = analyzer.calculate_order_flow_oscillator(symbol, fast_period, slow_period)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Insufficient data for oscillator calculation for '{symbol}'",
            )
        return result.to_dict()

    @router.get("/{symbol}/pressure")
    async def get_pressure(symbol: str, lookback_minutes: float = 15.0):
        """Get real-time buy/sell pressure gauges."""
        result = analyzer.get_pressure_gauges(symbol, lookback_minutes)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Insufficient trade data for symbol '{symbol}'",
            )
        return result.to_dict()

    @router.get("/{symbol}/absorption")
    async def get_absorption(symbol: str, lookback_minutes: float = 30.0):
        """Detect market absorption zones."""
        zones = analyzer.detect_market_absorption(symbol, lookback_minutes)
        return {
            "symbol": symbol,
            "absorption_zones": [z.to_dict() for z in zones],
            "count": len(zones),
        }

    @router.get("/{symbol}/analyze")
    async def get_full_analysis(symbol: str):
        """Run the complete advanced order flow analysis pipeline."""
        result = analyzer.analyze(symbol)
        return result.to_dict()

    @router.get("/{symbol}/volume-profile")
    async def get_volume_profile(
        symbol: str, price_buckets: int = 50, lookback_minutes: float = 60.0
    ):
        """Get volume profile with POC, VAH, VAL."""
        return analyzer.get_volume_profile(symbol, price_buckets, lookback_minutes)

    @router.get("/{symbol}/key-levels")
    async def get_key_levels(symbol: str):
        """Get key support and resistance levels from order flow."""
        return analyzer.get_key_levels(symbol)

    @router.get("/stats")
    async def get_stats():
        """Get analyzer runtime statistics."""
        return analyzer.get_stats()

    return router


# ================================================================
# GLOBAL INSTANCE
# ================================================================

_advanced_analyzer: Optional[AdvancedOrderFlowAnalyzer] = None


def get_advanced_order_flow_analyzer() -> AdvancedOrderFlowAnalyzer:
    """
    Return the global AdvancedOrderFlowAnalyzer singleton.

    Returns:
        AdvancedOrderFlowAnalyzer instance.
    """
    global _advanced_analyzer
    if _advanced_analyzer is None:
        _advanced_analyzer = AdvancedOrderFlowAnalyzer()
    return _advanced_analyzer
