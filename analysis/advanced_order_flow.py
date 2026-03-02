"""
Advanced Order Flow Analyzer

Enhances analysis/order_flow.py with professional-grade metrics:
- Aggression metrics (buy/sell aggression index)
- Delta divergence detection (price vs. cumulative delta)
- Volume cluster detection (support/resistance from volume density)
- Stacked order-book imbalances
- Exhaustion signals
- FastAPI endpoints

Integrates with:
    analysis.order_flow       – base trade stream
    data.depth_of_market      – order-book context
    data.time_and_sales       – real-time tape
"""

import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────
DEFAULT_LOOKBACK = 60           # minutes for standard analysis window
DEFAULT_CLUSTER_BUCKETS = 30    # price buckets for cluster analysis
DEFAULT_DIVERGENCE_BARS = 5     # bars to check for delta divergence
DEFAULT_IMBALANCE_THRESHOLD = 0.4  # order book imbalance threshold
DEFAULT_EXHAUSTION_RATIO = 0.85    # buy/sell ratio to flag exhaustion


# ────────────────────────────────────────────────────────────────────
# Data-classes
# ────────────────────────────────────────────────────────────────────
@dataclass
class AggressionMetrics:
    """Buy/sell aggression index for a symbol."""
    symbol: str
    timestamp: datetime
    window_minutes: int

    # Raw counts
    total_trades: int
    buy_trades: int
    sell_trades: int
    total_volume: float
    buy_volume: float
    sell_volume: float

    # Aggression indices (0–100)
    buy_aggression_index: float   # how aggressively buyers are lifting asks
    sell_aggression_index: float  # how aggressively sellers are hitting bids

    # Derived
    aggression_ratio: float       # buy_agg / (buy_agg + sell_agg)
    dominant_aggressor: str       # 'buyers' | 'sellers' | 'neutral'

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class DeltaDivergenceSignal:
    """Detected divergence between price direction and delta direction."""
    symbol: str
    timestamp: datetime
    divergence_type: str          # 'bullish' | 'bearish'
    price_direction: str          # 'up' | 'down'
    delta_direction: str          # 'up' | 'down'
    price_change: float
    delta_change: float
    confidence: float             # 0–1
    description: str

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class VolumeCluster:
    """High-density volume cluster (support or resistance zone)."""
    symbol: str
    price_low: float
    price_high: float
    price_center: float
    total_volume: float
    buy_volume: float
    sell_volume: float
    delta: float
    trade_count: int
    cluster_type: str             # 'support' | 'resistance' | 'value_area'
    strength: float               # 0–1

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StackedImbalance:
    """Three or more consecutive imbalanced price levels."""
    symbol: str
    timestamp: datetime
    direction: str                # 'buy_stack' | 'sell_stack'
    price_start: float
    price_end: float
    level_count: int
    avg_imbalance: float
    total_volume: float
    signal: str                   # 'bullish' | 'bearish'

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class AdvancedOrderFlowAnalysis:
    """Full advanced analysis result."""
    symbol: str
    timestamp: datetime
    window_minutes: int

    # Aggression
    aggression: AggressionMetrics

    # Delta divergence (may be None)
    delta_divergence: Optional[DeltaDivergenceSignal]

    # Clusters
    volume_clusters: List[VolumeCluster]
    support_clusters: List[VolumeCluster]
    resistance_clusters: List[VolumeCluster]

    # Stacked imbalances
    stacked_imbalances: List[StackedImbalance]

    # Exhaustion flag
    is_buy_exhaustion: bool
    is_sell_exhaustion: bool

    # Overall signal
    signal: str         # 'bullish' | 'bearish' | 'neutral'
    signal_strength: float  # 0–1

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'window_minutes': self.window_minutes,
            'aggression': self.aggression.to_dict(),
            'delta_divergence': (
                self.delta_divergence.to_dict()
                if self.delta_divergence else None
            ),
            'volume_clusters': [c.to_dict() for c in self.volume_clusters],
            'support_clusters': [c.to_dict() for c in self.support_clusters],
            'resistance_clusters': [c.to_dict() for c in self.resistance_clusters],
            'stacked_imbalances': [s.to_dict() for s in self.stacked_imbalances],
            'is_buy_exhaustion': self.is_buy_exhaustion,
            'is_sell_exhaustion': self.is_sell_exhaustion,
            'signal': self.signal,
            'signal_strength': self.signal_strength,
        }


# ────────────────────────────────────────────────────────────────────
# Analyzer
# ────────────────────────────────────────────────────────────────────
class AdvancedOrderFlowAnalyzer:
    """
    Enhanced order-flow analyzer with professional-grade metrics.

    Usage::

        analyzer = AdvancedOrderFlowAnalyzer()

        # Feed trades (identical interface to OrderFlowAnalyzer)
        analyzer.add_trade('XAUUSD', price=1950.0, size=100.0, side='buy')

        # Full analysis
        result = analyzer.analyze('XAUUSD')

        # Individual components
        agg  = analyzer.get_aggression_metrics('XAUUSD')
        divg = analyzer.get_delta_divergence('XAUUSD')
        clus = analyzer.get_volume_clusters('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the analyzer.

        Args:
            config: Optional overrides:
                - lookback_minutes (int)
                - cluster_buckets (int)
                - divergence_bars (int)
                - imbalance_threshold (float)
                - exhaustion_ratio (float)
                - max_trades (int)
        """
        cfg = config or {}
        self._lookback: int = cfg.get('lookback_minutes', DEFAULT_LOOKBACK)
        self._cluster_buckets: int = cfg.get('cluster_buckets', DEFAULT_CLUSTER_BUCKETS)
        self._divergence_bars: int = cfg.get('divergence_bars', DEFAULT_DIVERGENCE_BARS)
        self._imbalance_threshold: float = cfg.get('imbalance_threshold',
                                                    DEFAULT_IMBALANCE_THRESHOLD)
        self._exhaustion_ratio: float = cfg.get('exhaustion_ratio',
                                                 DEFAULT_EXHAUSTION_RATIO)
        self._max_trades: int = cfg.get('max_trades', 100_000)

        # Storage: (timestamp, price, size, side)
        self._trades: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._max_trades)
        )

        # Cumulative delta per symbol
        self._cum_delta: Dict[str, float] = defaultdict(float)

        # Price & delta snapshots for divergence (per bar)
        self._price_snapshots: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=50)
        )
        self._delta_snapshots: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=50)
        )

        self._lock = threading.RLock()
        logger.info("AdvancedOrderFlowAnalyzer initialized")

    # ────────────────────────────────────────────────────────────────
    # Public write API
    # ────────────────────────────────────────────────────────────────

    def add_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        timestamp: Optional[datetime] = None,
    ):
        """
        Add a single trade.

        Args:
            symbol:    Instrument ticker.
            price:     Trade price.
            size:      Trade size.
            side:      'buy' or 'sell'.
            timestamp: Trade time (UTC). Defaults to now.
        """
        ts = timestamp or datetime.utcnow()
        side = side.lower()

        with self._lock:
            self._trades[symbol].append((ts, price, size, side))
            delta = size if side == 'buy' else -size
            self._cum_delta[symbol] += delta

    def add_trades(self, symbol: str, trades: List[Dict]):
        """Batch-insert trades."""
        for t in trades:
            self.add_trade(
                symbol=symbol,
                price=t['price'],
                size=t['size'],
                side=t['side'],
                timestamp=t.get('timestamp'),
            )

    def snapshot(self, symbol: str, current_price: float):
        """
        Record a price/delta snapshot for divergence detection.

        Call once per bar close.

        Args:
            symbol:        Instrument ticker.
            current_price: Closing price of the bar.
        """
        with self._lock:
            self._price_snapshots[symbol].append(current_price)
            self._delta_snapshots[symbol].append(self._cum_delta[symbol])

    # ────────────────────────────────────────────────────────────────
    # Public read API – individual components
    # ────────────────────────────────────────────────────────────────

    def get_aggression_metrics(
        self,
        symbol: str,
        window_minutes: Optional[int] = None,
    ) -> Optional[AggressionMetrics]:
        """Compute buy/sell aggression metrics."""
        window = window_minutes or self._lookback
        cutoff = datetime.utcnow() - timedelta(minutes=window)

        with self._lock:
            recent = [r for r in self._trades[symbol] if r[0] >= cutoff]

        if not recent:
            return None

        buy_trades = [(p, s) for _, p, s, side in recent if side == 'buy']
        sell_trades = [(p, s) for _, p, s, side in recent if side == 'sell']

        buy_vol = sum(s for _, s in buy_trades)
        sell_vol = sum(s for _, s in sell_trades)
        total_vol = buy_vol + sell_vol

        # Aggression index: weighted by size relative to total
        buy_agg = (buy_vol / total_vol * 100) if total_vol > 0 else 50.0
        sell_agg = (sell_vol / total_vol * 100) if total_vol > 0 else 50.0

        total_agg = buy_agg + sell_agg
        agg_ratio = (buy_agg / total_agg) if total_agg > 0 else 0.5

        if agg_ratio > 0.55:
            dominant = 'buyers'
        elif agg_ratio < 0.45:
            dominant = 'sellers'
        else:
            dominant = 'neutral'

        return AggressionMetrics(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            window_minutes=window,
            total_trades=len(recent),
            buy_trades=len(buy_trades),
            sell_trades=len(sell_trades),
            total_volume=total_vol,
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            buy_aggression_index=round(buy_agg, 2),
            sell_aggression_index=round(sell_agg, 2),
            aggression_ratio=round(agg_ratio, 4),
            dominant_aggressor=dominant,
        )

    def get_delta_divergence(
        self,
        symbol: str,
    ) -> Optional[DeltaDivergenceSignal]:
        """
        Detect divergence between price direction and cumulative delta.

        Requires at least *divergence_bars* snapshots via :meth:`snapshot`.
        """
        with self._lock:
            prices = list(self._price_snapshots[symbol])
            deltas = list(self._delta_snapshots[symbol])

        n = self._divergence_bars
        if len(prices) < n or len(deltas) < n:
            return None

        price_slice = prices[-n:]
        delta_slice = deltas[-n:]

        price_change = price_slice[-1] - price_slice[0]
        delta_change = delta_slice[-1] - delta_slice[0]

        price_dir = 'up' if price_change > 0 else 'down'
        delta_dir = 'up' if delta_change > 0 else 'down'

        # Divergence = price and delta move in opposite directions
        if price_dir == delta_dir:
            return None

        if price_dir == 'up' and delta_dir == 'down':
            div_type = 'bearish'
            description = (
                "Price making higher levels while delta is falling – "
                "buyers may be losing momentum."
            )
        else:
            div_type = 'bullish'
            description = (
                "Price making lower levels while delta is rising – "
                "sellers may be exhausted."
            )

        # Confidence proportional to magnitude of divergence
        if max(abs(price_change), 1e-9) > 0 and max(abs(delta_change), 1e-9) > 0:
            confidence = min(1.0, abs(delta_change) / (abs(price_change) + 1e-9) * 0.1)
        else:
            confidence = 0.5

        return DeltaDivergenceSignal(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            divergence_type=div_type,
            price_direction=price_dir,
            delta_direction=delta_dir,
            price_change=round(price_change, 5),
            delta_change=round(delta_change, 2),
            confidence=round(min(confidence, 1.0), 3),
            description=description,
        )

    def get_volume_clusters(
        self,
        symbol: str,
        window_minutes: Optional[int] = None,
        buckets: Optional[int] = None,
    ) -> List[VolumeCluster]:
        """
        Identify high-density volume clusters.

        Args:
            symbol:         Instrument ticker.
            window_minutes: Look-back window.
            buckets:        Number of price buckets.

        Returns:
            List of :class:`VolumeCluster` sorted by total volume desc.
        """
        window = window_minutes or self._lookback
        n_buckets = buckets or self._cluster_buckets
        cutoff = datetime.utcnow() - timedelta(minutes=window)

        with self._lock:
            recent = [r for r in self._trades[symbol] if r[0] >= cutoff]

        if len(recent) < 2:
            return []

        prices = [r[1] for r in recent]
        min_p, max_p = min(prices), max(prices)

        if min_p == max_p:
            return []

        bucket_size = (max_p - min_p) / n_buckets

        # Aggregate
        agg: Dict[int, Dict] = defaultdict(lambda: {
            'buy': 0.0, 'sell': 0.0, 'count': 0
        })
        for _, price, size, side in recent:
            idx = int((price - min_p) / bucket_size)
            idx = min(idx, n_buckets - 1)
            agg[idx]['count'] += 1
            if side == 'buy':
                agg[idx]['buy'] += size
            else:
                agg[idx]['sell'] += size

        total_vol = sum(
            d['buy'] + d['sell'] for d in agg.values()
        )
        avg_vol = total_vol / n_buckets if n_buckets > 0 else 0

        # Determine current price for support/resistance classification
        current_price = prices[-1] if prices else (min_p + max_p) / 2

        clusters = []
        for idx, data in agg.items():
            bv = data['buy']
            sv = data['sell']
            tv = bv + sv
            if tv < avg_vol * 1.5:
                continue   # not a cluster

            pl = min_p + idx * bucket_size
            ph = pl + bucket_size
            pc = (pl + ph) / 2
            strength = min(1.0, tv / (avg_vol * 3))

            if pc < current_price:
                ctype = 'support'
            elif pc > current_price:
                ctype = 'resistance'
            else:
                ctype = 'value_area'

            clusters.append(VolumeCluster(
                symbol=symbol,
                price_low=round(pl, 5),
                price_high=round(ph, 5),
                price_center=round(pc, 5),
                total_volume=round(tv, 4),
                buy_volume=round(bv, 4),
                sell_volume=round(sv, 4),
                delta=round(bv - sv, 4),
                trade_count=data['count'],
                cluster_type=ctype,
                strength=round(strength, 3),
            ))

        return sorted(clusters, key=lambda c: -c.total_volume)

    def get_stacked_imbalances(
        self,
        symbol: str,
        window_minutes: Optional[int] = None,
        min_stack: int = 3,
    ) -> List[StackedImbalance]:
        """
        Detect stacked order-book imbalances.

        A "stack" is ≥ *min_stack* consecutive price levels where the
        buy/sell ratio exceeds the imbalance threshold in the same direction.

        Args:
            symbol:         Instrument ticker.
            window_minutes: Look-back window.
            min_stack:      Minimum levels to qualify as a stack.

        Returns:
            List of :class:`StackedImbalance`.
        """
        clusters = self.get_volume_clusters(
            symbol, window_minutes=window_minutes or self._lookback
        )
        if len(clusters) < min_stack:
            return []

        # Sort by price
        sorted_clusters = sorted(clusters, key=lambda c: c.price_center)

        stacks: List[StackedImbalance] = []
        run: List[VolumeCluster] = []
        run_dir: Optional[str] = None

        def flush_run():
            if len(run) >= min_stack:
                total_vol = sum(c.total_volume for c in run)
                avg_imb = sum(
                    (c.buy_volume - c.sell_volume) / max(c.total_volume, 1e-9)
                    for c in run
                ) / len(run)
                stacks.append(StackedImbalance(
                    symbol=symbol,
                    timestamp=datetime.utcnow(),
                    direction=run_dir,
                    price_start=run[0].price_low,
                    price_end=run[-1].price_high,
                    level_count=len(run),
                    avg_imbalance=round(avg_imb, 4),
                    total_volume=round(total_vol, 4),
                    signal='bullish' if run_dir == 'buy_stack' else 'bearish',
                ))

        for cluster in sorted_clusters:
            tv = cluster.total_volume
            if tv == 0:
                flush_run(); run = []; run_dir = None
                continue

            imb = (cluster.buy_volume - cluster.sell_volume) / tv
            if imb >= self._imbalance_threshold:
                direction = 'buy_stack'
            elif imb <= -self._imbalance_threshold:
                direction = 'sell_stack'
            else:
                flush_run(); run = []; run_dir = None
                continue

            if run_dir is None:
                run_dir = direction

            if direction == run_dir:
                run.append(cluster)
            else:
                flush_run()
                run = [cluster]
                run_dir = direction

        flush_run()
        return stacks

    # ────────────────────────────────────────────────────────────────
    # Full analysis
    # ────────────────────────────────────────────────────────────────

    def analyze(
        self,
        symbol: str,
        window_minutes: Optional[int] = None,
    ) -> Optional[AdvancedOrderFlowAnalysis]:
        """
        Run full advanced order-flow analysis.

        Returns *None* if there are no trades for the symbol.
        """
        window = window_minutes or self._lookback

        agg = self.get_aggression_metrics(symbol, window_minutes=window)
        if agg is None:
            return None

        divergence = self.get_delta_divergence(symbol)
        clusters = self.get_volume_clusters(symbol, window_minutes=window)
        stacks = self.get_stacked_imbalances(symbol, window_minutes=window)

        support_clusters = [c for c in clusters if c.cluster_type == 'support']
        resistance_clusters = [c for c in clusters if c.cluster_type == 'resistance']

        # Exhaustion
        exh_ratio = self._exhaustion_ratio
        is_buy_exh = agg.buy_aggression_index >= exh_ratio * 100
        is_sell_exh = agg.sell_aggression_index >= exh_ratio * 100

        # Overall signal
        signal, strength = self._compute_signal(
            agg, divergence, stacks, is_buy_exh, is_sell_exh
        )

        return AdvancedOrderFlowAnalysis(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            window_minutes=window,
            aggression=agg,
            delta_divergence=divergence,
            volume_clusters=clusters,
            support_clusters=support_clusters,
            resistance_clusters=resistance_clusters,
            stacked_imbalances=stacks,
            is_buy_exhaustion=is_buy_exh,
            is_sell_exhaustion=is_sell_exh,
            signal=signal,
            signal_strength=round(strength, 3),
        )

    # ────────────────────────────────────────────────────────────────
    # Private helpers
    # ────────────────────────────────────────────────────────────────

    def _compute_signal(
        self,
        agg: AggressionMetrics,
        divergence: Optional[DeltaDivergenceSignal],
        stacks: List[StackedImbalance],
        buy_exh: bool,
        sell_exh: bool,
    ) -> Tuple[str, float]:
        """Aggregate sub-signals into a single directional view."""
        score = 0.0

        # Aggression contribution (-1 … +1)
        score += (agg.aggression_ratio - 0.5) * 2

        # Divergence (reversal signal)
        if divergence:
            div_weight = 0.5
            if divergence.divergence_type == 'bullish':
                score += div_weight * divergence.confidence
            else:
                score -= div_weight * divergence.confidence

        # Stacked imbalances
        for stack in stacks:
            w = min(stack.level_count / 10.0, 0.3)
            if stack.direction == 'buy_stack':
                score += w
            else:
                score -= w

        # Exhaustion reversal hints
        if buy_exh:
            score -= 0.2
        if sell_exh:
            score += 0.2

        # Normalise
        strength = min(1.0, abs(score))
        if score > 0.15:
            return 'bullish', strength
        if score < -0.15:
            return 'bearish', strength
        return 'neutral', strength

    # ────────────────────────────────────────────────────────────────
    # Utility
    # ────────────────────────────────────────────────────────────────

    def get_symbols(self) -> List[str]:
        """Return symbols with trade data."""
        with self._lock:
            return list(self._trades.keys())

    def clear_trades(self, symbol: str):
        """Clear trade data for *symbol*."""
        with self._lock:
            self._trades.pop(symbol, None)
            self._cum_delta.pop(symbol, None)
            self._price_snapshots.pop(symbol, None)
            self._delta_snapshots.pop(symbol, None)

    def get_stats(self) -> Dict:
        """Return service-level diagnostics."""
        with self._lock:
            return {
                'symbols_tracked': len(self._trades),
                'symbols': list(self._trades.keys()),
                'trades_by_symbol': {
                    s: len(buf) for s, buf in self._trades.items()
                },
                'cumulative_delta': dict(self._cum_delta),
            }


# ────────────────────────────────────────────────────────────────────
# FastAPI integration
# ────────────────────────────────────────────────────────────────────

def create_advanced_order_flow_router(analyzer: AdvancedOrderFlowAnalyzer):
    """
    Build a FastAPI router exposing advanced order-flow endpoints.

    Args:
        analyzer: :class:`AdvancedOrderFlowAnalyzer` instance.

    Returns:
        ``fastapi.APIRouter``
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/advanced-orderflow", tags=["Advanced Order Flow"])

    @router.get("/{symbol}/analyze")
    async def analyze(symbol: str, window_minutes: int = 60):
        """Run full advanced order-flow analysis."""
        result = analyzer.analyze(symbol, window_minutes=window_minutes)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        return result.to_dict()

    @router.get("/{symbol}/aggression")
    async def get_aggression(symbol: str, window_minutes: int = 60):
        """Return aggression metrics."""
        metrics = analyzer.get_aggression_metrics(symbol, window_minutes=window_minutes)
        if metrics is None:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        return metrics.to_dict()

    @router.get("/{symbol}/divergence")
    async def get_divergence(symbol: str):
        """Return delta divergence signal."""
        div = analyzer.get_delta_divergence(symbol)
        if div is None:
            return {"symbol": symbol, "divergence": None}
        return div.to_dict()

    @router.get("/{symbol}/clusters")
    async def get_clusters(symbol: str, window_minutes: int = 60):
        """Return volume clusters."""
        clusters = analyzer.get_volume_clusters(symbol, window_minutes=window_minutes)
        return [c.to_dict() for c in clusters]

    @router.get("/{symbol}/stacked-imbalances")
    async def get_stacked_imbalances(symbol: str, window_minutes: int = 60):
        """Return stacked imbalance zones."""
        stacks = analyzer.get_stacked_imbalances(
            symbol, window_minutes=window_minutes
        )
        return [s.to_dict() for s in stacks]

    @router.get("/stats/service")
    async def service_stats():
        """Return service diagnostics."""
        return analyzer.get_stats()

    return router


# ────────────────────────────────────────────────────────────────────
# Global singleton
# ────────────────────────────────────────────────────────────────────
_analyzer: Optional[AdvancedOrderFlowAnalyzer] = None


def get_advanced_order_flow_analyzer() -> AdvancedOrderFlowAnalyzer:
    """Return the process-wide :class:`AdvancedOrderFlowAnalyzer` instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = AdvancedOrderFlowAnalyzer()
    return _analyzer
