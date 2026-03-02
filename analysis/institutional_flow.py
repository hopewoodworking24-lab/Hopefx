"""
Institutional Flow Detector

Identifies and tracks institutional / smart-money activity:
- Large order detection (configurable size thresholds)
- Iceberg order identification (repeated same-level prints)
- Volume spike detection (configurable σ threshold)
- Smart-money flow score
- FastAPI endpoints

Integrates with:
    data.depth_of_market   – order-book context
    analysis.order_flow    – base trade stream
    data.time_and_sales    – tape feed
"""

import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────
DEFAULT_INSTITUTIONAL_THRESHOLD = 1_000.0   # minimum size to consider institutional
DEFAULT_SPIKE_SIGMA = 3.0                   # standard deviations for volume spike
DEFAULT_ICEBERG_WINDOW = 60                 # seconds to look for iceberg repetition
DEFAULT_ICEBERG_MIN_PRINTS = 3             # minimum repeated prints at same level
DEFAULT_SMART_MONEY_WINDOW = 300           # seconds for smart-money flow window
DEFAULT_HISTORY_SIZE = 500                 # max volume samples per symbol


# ────────────────────────────────────────────────────────────────────
# Data-classes
# ────────────────────────────────────────────────────────────────────
@dataclass
class InstitutionalTrade:
    """A trade classified as institutional."""
    timestamp: datetime
    symbol: str
    price: float
    size: float
    side: str                  # 'buy' | 'sell'
    trade_type: str            # 'large_order' | 'iceberg' | 'block'
    confidence: float          # 0–1
    trade_id: Optional[str] = None

    @property
    def notional(self) -> float:
        return self.price * self.size

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        d['notional'] = self.notional
        return d


@dataclass
class IcebergSignal:
    """Detected iceberg order."""
    symbol: str
    price: float
    side: str
    print_count: int           # how many times the level was hit
    total_volume: float
    first_seen: datetime
    last_seen: datetime
    confidence: float

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['first_seen'] = self.first_seen.isoformat()
        d['last_seen'] = self.last_seen.isoformat()
        return d


@dataclass
class VolumeSpike:
    """Detected volume spike event."""
    symbol: str
    timestamp: datetime
    volume: float
    average_volume: float
    std_volume: float
    sigma: float               # how many σ above average
    side: str                  # dominant side ('buy' | 'sell' | 'mixed')
    price: float

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class SmartMoneyFlow:
    """Smart money flow summary for a symbol."""
    symbol: str
    timestamp: datetime
    window_seconds: int
    institutional_buy_volume: float
    institutional_sell_volume: float
    institutional_delta: float
    flow_score: float          # -100 to +100 (positive = buying pressure)
    signal: str                # 'accumulation' | 'distribution' | 'neutral'
    iceberg_count: int
    spike_count: int

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


# ────────────────────────────────────────────────────────────────────
# Detector
# ────────────────────────────────────────────────────────────────────
class InstitutionalFlowDetector:
    """
    Detects institutional and smart-money activity in the trade stream.

    Usage::

        detector = InstitutionalFlowDetector()

        # Feed trades (same interface as OrderFlowAnalyzer)
        detector.add_trade('XAUUSD', price=1950.0, size=500.0, side='buy')

        # Get detected institutional trades
        inst_trades = detector.get_institutional_trades('XAUUSD')

        # Smart money flow
        flow = detector.get_smart_money_flow('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the detector.

        Args:
            config: Optional overrides:
                - institutional_threshold (float)
                - spike_sigma (float)
                - iceberg_window (int) seconds
                - iceberg_min_prints (int)
                - smart_money_window (int) seconds
                - history_size (int)
        """
        cfg = config or {}
        self._inst_threshold: float = cfg.get('institutional_threshold',
                                               DEFAULT_INSTITUTIONAL_THRESHOLD)
        self._spike_sigma: float = cfg.get('spike_sigma', DEFAULT_SPIKE_SIGMA)
        self._iceberg_window: int = cfg.get('iceberg_window', DEFAULT_ICEBERG_WINDOW)
        self._iceberg_min_prints: int = cfg.get('iceberg_min_prints',
                                                 DEFAULT_ICEBERG_MIN_PRINTS)
        self._smart_money_window: int = cfg.get('smart_money_window',
                                                 DEFAULT_SMART_MONEY_WINDOW)
        self._history_size: int = cfg.get('history_size', DEFAULT_HISTORY_SIZE)

        # Raw trade records per symbol  (timestamp, price, size, side)
        self._trades: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._history_size)
        )

        # Volume samples for spike detection
        self._volume_samples: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._history_size)
        )

        # Detected events
        self._institutional_trades: Dict[str, List[InstitutionalTrade]] = defaultdict(list)
        self._icebergs: Dict[str, List[IcebergSignal]] = defaultdict(list)
        self._spikes: Dict[str, List[VolumeSpike]] = defaultdict(list)

        self._lock = threading.RLock()
        logger.info("InstitutionalFlowDetector initialized (threshold=%.1f σ=%.1f)",
                    self._inst_threshold, self._spike_sigma)

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
        trade_id: Optional[str] = None,
    ):
        """
        Process a single trade.

        Args:
            symbol:    Instrument ticker.
            price:     Trade price.
            size:      Trade size.
            side:      'buy' or 'sell'.
            timestamp: Trade time (UTC). Defaults to now.
            trade_id:  Optional identifier.
        """
        ts = timestamp or datetime.utcnow()
        record = (ts, price, size, side.lower(), trade_id)

        with self._lock:
            self._trades[symbol].append(record)
            self._volume_samples[symbol].append((ts, size))

            # Run detectors
            self._detect_large_order(symbol, ts, price, size, side, trade_id)
            self._detect_volume_spike(symbol, ts, price, size, side)

        # Iceberg detection is periodic (uses full history)
        self._detect_icebergs(symbol)

    def add_trades(self, symbol: str, trades: List[Dict]):
        """Batch-insert trades."""
        for t in trades:
            self.add_trade(
                symbol=symbol,
                price=t['price'],
                size=t['size'],
                side=t['side'],
                timestamp=t.get('timestamp'),
                trade_id=t.get('trade_id'),
            )

    # ────────────────────────────────────────────────────────────────
    # Public read API
    # ────────────────────────────────────────────────────────────────

    def get_institutional_trades(
        self,
        symbol: str,
        limit: int = 50,
    ) -> List[InstitutionalTrade]:
        """Return recently detected institutional trades."""
        with self._lock:
            return list(self._institutional_trades[symbol])[-limit:]

    def get_icebergs(self, symbol: str) -> List[IcebergSignal]:
        """Return detected iceberg signals."""
        with self._lock:
            return list(self._icebergs[symbol])

    def get_volume_spikes(
        self,
        symbol: str,
        limit: int = 20,
    ) -> List[VolumeSpike]:
        """Return detected volume spikes."""
        with self._lock:
            return list(self._spikes[symbol])[-limit:]

    def get_smart_money_flow(
        self,
        symbol: str,
        window_seconds: Optional[int] = None,
    ) -> Optional[SmartMoneyFlow]:
        """
        Compute smart-money flow score.

        Returns *None* when no institutional trades are present.
        """
        window = window_seconds or self._smart_money_window
        cutoff = datetime.utcnow() - timedelta(seconds=window)

        with self._lock:
            inst_trades = [
                t for t in self._institutional_trades[symbol]
                if t.timestamp >= cutoff
            ]
            icebergs = [
                ic for ic in self._icebergs[symbol]
                if ic.last_seen >= cutoff
            ]
            spikes = [
                sp for sp in self._spikes[symbol]
                if sp.timestamp >= cutoff
            ]

        if not inst_trades and not icebergs:
            return None

        buy_vol = sum(
            t.size for t in inst_trades if t.side == 'buy'
        ) + sum(ic.total_volume for ic in icebergs if ic.side == 'buy')
        sell_vol = sum(
            t.size for t in inst_trades if t.side == 'sell'
        ) + sum(ic.total_volume for ic in icebergs if ic.side == 'sell')
        total = buy_vol + sell_vol

        flow_score = ((buy_vol - sell_vol) / total * 100) if total > 0 else 0.0

        if flow_score > 20:
            signal = 'accumulation'
        elif flow_score < -20:
            signal = 'distribution'
        else:
            signal = 'neutral'

        return SmartMoneyFlow(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            window_seconds=window,
            institutional_buy_volume=buy_vol,
            institutional_sell_volume=sell_vol,
            institutional_delta=buy_vol - sell_vol,
            flow_score=round(flow_score, 2),
            signal=signal,
            iceberg_count=len(icebergs),
            spike_count=len(spikes),
        )

    # ────────────────────────────────────────────────────────────────
    # Detection logic
    # ────────────────────────────────────────────────────────────────

    def _detect_large_order(
        self,
        symbol: str,
        ts: datetime,
        price: float,
        size: float,
        side: str,
        trade_id: Optional[str],
    ):
        """Flag trades that exceed the institutional threshold."""
        if size < self._inst_threshold:
            return

        # Confidence scales with how far above the threshold
        ratio = size / self._inst_threshold
        confidence = min(1.0, 0.5 + (ratio - 1.0) * 0.1)

        trade_type = 'block' if size >= self._inst_threshold * 10 else 'large_order'
        record = InstitutionalTrade(
            timestamp=ts,
            symbol=symbol,
            price=price,
            size=size,
            side=side.lower(),
            trade_type=trade_type,
            confidence=round(confidence, 3),
            trade_id=trade_id,
        )
        self._institutional_trades[symbol].append(record)

    def _detect_volume_spike(
        self,
        symbol: str,
        ts: datetime,
        price: float,
        size: float,
        side: str,
    ):
        """Detect when current volume is ≥ spike_sigma σ above the running mean."""
        samples = self._volume_samples[symbol]
        if len(samples) < 10:
            return

        volumes = [s for _, s in samples]
        n = len(volumes)
        mean = sum(volumes) / n
        variance = sum((v - mean) ** 2 for v in volumes) / n
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std == 0:
            return

        sigma = (size - mean) / std
        if sigma >= self._spike_sigma:
            spike = VolumeSpike(
                symbol=symbol,
                timestamp=ts,
                volume=size,
                average_volume=round(mean, 4),
                std_volume=round(std, 4),
                sigma=round(sigma, 3),
                side=side.lower(),
                price=price,
            )
            self._spikes[symbol].append(spike)
            logger.debug("Volume spike: %s %.2fσ @ %.5f", symbol, sigma, price)

    def _detect_icebergs(self, symbol: str):
        """
        Identify iceberg orders by looking for repeated fills at the
        same price level within the iceberg detection window.
        """
        cutoff = datetime.utcnow() - timedelta(seconds=self._iceberg_window)

        with self._lock:
            recent = [
                r for r in self._trades[symbol]
                if r[0] >= cutoff
            ]

        if len(recent) < self._iceberg_min_prints:
            return

        # Group by rounded price and side
        groups: Dict[Tuple, List] = defaultdict(list)
        for ts, price, size, side, tid in recent:
            key = (round(price, 2), side)
            groups[key].append((ts, size))

        new_icebergs = []
        for (price, side), prints in groups.items():
            if len(prints) < self._iceberg_min_prints:
                continue

            total_vol = sum(s for _, s in prints)
            first_seen = min(t for t, _ in prints)
            last_seen = max(t for t, _ in prints)

            # Confidence scales with number of prints
            confidence = min(1.0, len(prints) / (self._iceberg_min_prints * 3))

            new_icebergs.append(
                IcebergSignal(
                    symbol=symbol,
                    price=price,
                    side=side,
                    print_count=len(prints),
                    total_volume=total_vol,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    confidence=round(confidence, 3),
                )
            )

        with self._lock:
            # Replace – we recompute from the current window each time
            self._icebergs[symbol] = new_icebergs

    # ────────────────────────────────────────────────────────────────
    # Utility
    # ────────────────────────────────────────────────────────────────

    def get_symbols(self) -> List[str]:
        """Return symbols with trade data."""
        with self._lock:
            return list(self._trades.keys())

    def clear_symbol(self, symbol: str):
        """Clear all data for *symbol*."""
        with self._lock:
            for store in (
                self._trades,
                self._volume_samples,
                self._institutional_trades,
                self._icebergs,
                self._spikes,
            ):
                store.pop(symbol, None)

    def get_stats(self) -> Dict:
        """Return service-level diagnostics."""
        with self._lock:
            return {
                'symbols_tracked': len(self._trades),
                'symbols': list(self._trades.keys()),
                'institutional_threshold': self._inst_threshold,
                'spike_sigma': self._spike_sigma,
                'detected_by_symbol': {
                    s: {
                        'institutional_trades': len(self._institutional_trades[s]),
                        'icebergs': len(self._icebergs[s]),
                        'spikes': len(self._spikes[s]),
                    }
                    for s in self._trades
                },
            }


# ────────────────────────────────────────────────────────────────────
# FastAPI integration
# ────────────────────────────────────────────────────────────────────

def create_institutional_flow_router(detector: InstitutionalFlowDetector):
    """
    Build a FastAPI router exposing institutional-flow endpoints.

    Args:
        detector: :class:`InstitutionalFlowDetector` instance.

    Returns:
        ``fastapi.APIRouter``
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/institutional", tags=["Institutional Flow"])

    @router.get("/{symbol}/trades")
    async def get_institutional_trades(symbol: str, limit: int = 50):
        """Return recent institutional trades."""
        trades = detector.get_institutional_trades(symbol, limit=limit)
        if not trades:
            raise HTTPException(status_code=404,
                                detail=f"No institutional trades for {symbol}")
        return [t.to_dict() for t in trades]

    @router.get("/{symbol}/icebergs")
    async def get_icebergs(symbol: str):
        """Return detected iceberg orders."""
        return [ic.to_dict() for ic in detector.get_icebergs(symbol)]

    @router.get("/{symbol}/spikes")
    async def get_volume_spikes(symbol: str, limit: int = 20):
        """Return volume spike events."""
        return [sp.to_dict() for sp in detector.get_volume_spikes(symbol, limit)]

    @router.get("/{symbol}/flow")
    async def get_smart_money_flow(symbol: str, window: int = 300):
        """Return smart-money flow analysis."""
        flow = detector.get_smart_money_flow(symbol, window_seconds=window)
        if flow is None:
            raise HTTPException(status_code=404,
                                detail=f"No institutional activity for {symbol}")
        return flow.to_dict()

    @router.get("/")
    async def list_symbols():
        """Return all tracked symbols."""
        return {"symbols": detector.get_symbols()}

    @router.get("/stats/service")
    async def service_stats():
        """Return service diagnostics."""
        return detector.get_stats()

    return router


# ────────────────────────────────────────────────────────────────────
# Global singleton
# ────────────────────────────────────────────────────────────────────
_detector: Optional[InstitutionalFlowDetector] = None


def get_institutional_flow_detector() -> InstitutionalFlowDetector:
    """Return the process-wide :class:`InstitutionalFlowDetector` instance."""
    global _detector
    if _detector is None:
        _detector = InstitutionalFlowDetector()
    return _detector
