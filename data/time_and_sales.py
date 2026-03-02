"""
Time & Sales Service

Real-time trade tape with professional-grade features:
- 10,000-trade circular buffer
- Bid/Ask aggressor identification
- Trade velocity tracking
- Large trade detection and alerting
- Trade statistics and analytics
- FastAPI endpoints

Compatible with all brokers and the existing DOM/order-flow modules.
"""

import logging
import threading
from collections import deque
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# Constants / defaults
# ────────────────────────────────────────────────────────────────────
DEFAULT_BUFFER_SIZE = 10_000
DEFAULT_LARGE_TRADE_MULTIPLIER = 5.0   # x average size
DEFAULT_VELOCITY_WINDOW = 60           # seconds


# ────────────────────────────────────────────────────────────────────
# Enums
# ────────────────────────────────────────────────────────────────────
class Aggressor(str, Enum):
    """Who hit the book."""
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


# ────────────────────────────────────────────────────────────────────
# Data-classes
# ────────────────────────────────────────────────────────────────────
@dataclass
class TimeAndSalesRecord:
    """Single entry in the time-and-sales tape."""
    timestamp: datetime
    symbol: str
    price: float
    size: float
    aggressor: Aggressor
    trade_id: Optional[str] = None
    is_large: bool = False
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None

    @property
    def is_buy(self) -> bool:
        return self.aggressor == Aggressor.BUY

    @property
    def is_sell(self) -> bool:
        return self.aggressor == Aggressor.SELL

    @property
    def notional(self) -> float:
        return self.price * self.size

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        d['aggressor'] = self.aggressor.value
        d['is_buy'] = self.is_buy
        d['is_sell'] = self.is_sell
        d['notional'] = self.notional
        return d


@dataclass
class TradeVelocity:
    """Trade velocity metrics for a symbol."""
    symbol: str
    window_seconds: int
    trade_count: int
    total_volume: float
    buy_volume: float
    sell_volume: float
    trades_per_second: float
    volume_per_second: float
    delta_per_second: float
    dominant_side: str        # 'buy', 'sell', 'neutral'
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class TapeStatistics:
    """Aggregated time-and-sales statistics for a symbol."""
    symbol: str
    period_start: datetime
    period_end: datetime
    total_trades: int
    total_volume: float
    buy_volume: float
    sell_volume: float
    delta: float
    vwap: float
    large_trade_count: int
    large_trade_volume: float
    avg_trade_size: float
    max_trade_size: float
    min_price: float
    max_price: float
    price_range: float

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['period_start'] = self.period_start.isoformat()
        d['period_end'] = self.period_end.isoformat()
        return d


# ────────────────────────────────────────────────────────────────────
# Core service
# ────────────────────────────────────────────────────────────────────
class TimeAndSalesService:
    """
    Professional time-and-sales (trade tape) service.

    Features:
    - Thread-safe 10,000-trade circular buffer per symbol
    - Automatic aggressor classification from bid/ask context
    - Trade velocity calculation (trades/s, volume/s, delta/s)
    - Large-trade detection with configurable multiplier
    - Event callbacks for real-time processing
    - Handles 1,000+ trades per second

    Usage::

        service = TimeAndSalesService()

        # Feed trades (with optional bid/ask for aggressor inference)
        service.add_trade('XAUUSD', price=1950.0, size=10.0,
                          aggressor='buy', bid=1949.95, ask=1950.05)

        # Latest records
        records = service.get_tape('XAUUSD', limit=50)

        # Velocity
        vel = service.get_velocity('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the service.

        Args:
            config: Optional overrides:
                - buffer_size (int): circular buffer depth per symbol
                - large_trade_multiplier (float): × avg size to flag large
                - velocity_window (int): seconds for velocity window
        """
        cfg = config or {}
        self._buffer_size: int = cfg.get('buffer_size', DEFAULT_BUFFER_SIZE)
        self._large_multiplier: float = cfg.get('large_trade_multiplier',
                                                 DEFAULT_LARGE_TRADE_MULTIPLIER)
        self._velocity_window: int = cfg.get('velocity_window',
                                             DEFAULT_VELOCITY_WINDOW)

        # Per-symbol circular buffers
        self._tapes: Dict[str, deque] = {}

        # Running size sums for large-trade detection (simple rolling avg)
        self._size_sums: Dict[str, float] = {}
        self._size_counts: Dict[str, int] = {}

        # Registered callbacks  (symbol -> list[callable])
        self._callbacks: Dict[str, List[Callable]] = {}
        self._global_callbacks: List[Callable] = []

        self._lock = threading.RLock()
        logger.info("TimeAndSalesService initialized (buffer=%d)", self._buffer_size)

    # ────────────────────────────────────────────────────────────────
    # Public write API
    # ────────────────────────────────────────────────────────────────

    def add_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        aggressor: str = 'unknown',
        timestamp: Optional[datetime] = None,
        trade_id: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
    ) -> TimeAndSalesRecord:
        """
        Add a single trade to the tape.

        Args:
            symbol:    Instrument ticker
            price:     Execution price
            size:      Trade size / volume
            aggressor: 'buy', 'sell', or 'unknown'. If 'unknown' is
                       supplied but bid/ask are known the aggressor is
                       inferred automatically.
            timestamp: Trade time (UTC). Defaults to *now*.
            trade_id:  Optional unique identifier.
            bid:       Best bid at time of trade (for aggressor inference).
            ask:       Best ask at time of trade (for aggressor inference).

        Returns:
            The created :class:`TimeAndSalesRecord`.
        """
        agg = self._classify_aggressor(price, aggressor, bid, ask)
        ts = timestamp or datetime.utcnow()

        with self._lock:
            if symbol not in self._tapes:
                self._tapes[symbol] = deque(maxlen=self._buffer_size)
                self._size_sums[symbol] = 0.0
                self._size_counts[symbol] = 0

            # Rolling average for large-trade detection
            self._size_sums[symbol] += size
            self._size_counts[symbol] += 1
            avg_size = self._size_sums[symbol] / self._size_counts[symbol]
            is_large = size >= avg_size * self._large_multiplier

            record = TimeAndSalesRecord(
                timestamp=ts,
                symbol=symbol,
                price=price,
                size=size,
                aggressor=agg,
                trade_id=trade_id,
                is_large=is_large,
                bid_price=bid,
                ask_price=ask,
            )
            self._tapes[symbol].append(record)

        # Fire callbacks outside the lock
        self._dispatch(symbol, record)

        if is_large:
            logger.debug(
                "Large trade detected: %s @ %.5f x %.2f (avg=%.2f)",
                symbol, price, size, avg_size,
            )

        return record

    def add_trades(self, symbol: str, trades: List[Dict]) -> List[TimeAndSalesRecord]:
        """Batch-insert trades. Each dict must contain 'price' and 'size'."""
        return [self.add_trade(symbol, **t) for t in trades]

    # ────────────────────────────────────────────────────────────────
    # Public read API
    # ────────────────────────────────────────────────────────────────

    def get_tape(
        self,
        symbol: str,
        limit: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[TimeAndSalesRecord]:
        """Return the most recent *limit* records, with optional time slice."""
        with self._lock:
            records = list(self._tapes.get(symbol, []))

        if start_time:
            records = [r for r in records if r.timestamp >= start_time]
        if end_time:
            records = [r for r in records if r.timestamp <= end_time]

        return records[-limit:]

    def get_large_trades(
        self,
        symbol: str,
        limit: int = 50,
    ) -> List[TimeAndSalesRecord]:
        """Return the most recent large trades."""
        with self._lock:
            all_records = list(self._tapes.get(symbol, []))
        large = [r for r in all_records if r.is_large]
        return large[-limit:]

    def get_velocity(
        self,
        symbol: str,
        window_seconds: Optional[int] = None,
    ) -> Optional[TradeVelocity]:
        """
        Compute trade velocity metrics over the last *window_seconds*.

        Returns *None* if there are no trades for the symbol.
        """
        window = window_seconds or self._velocity_window
        cutoff = datetime.utcnow() - timedelta(seconds=window)

        with self._lock:
            records = [
                r for r in self._tapes.get(symbol, [])
                if r.timestamp >= cutoff
            ]

        if not records:
            return None

        buy_vol = sum(r.size for r in records if r.is_buy)
        sell_vol = sum(r.size for r in records if r.is_sell)
        total_vol = buy_vol + sell_vol
        delta = buy_vol - sell_vol

        elapsed = max(
            (records[-1].timestamp - records[0].timestamp).total_seconds(),
            1.0,
        )

        if buy_vol > sell_vol * 1.2:
            dominant = 'buy'
        elif sell_vol > buy_vol * 1.2:
            dominant = 'sell'
        else:
            dominant = 'neutral'

        return TradeVelocity(
            symbol=symbol,
            window_seconds=window,
            trade_count=len(records),
            total_volume=total_vol,
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            trades_per_second=round(len(records) / elapsed, 4),
            volume_per_second=round(total_vol / elapsed, 4),
            delta_per_second=round(delta / elapsed, 4),
            dominant_side=dominant,
        )

    def get_statistics(
        self,
        symbol: str,
        lookback_seconds: int = 3600,
    ) -> Optional[TapeStatistics]:
        """Return aggregated statistics over the lookback window."""
        cutoff = datetime.utcnow() - timedelta(seconds=lookback_seconds)
        records = self.get_tape(symbol, limit=self._buffer_size,
                                start_time=cutoff)

        if not records:
            return None

        prices = [r.price for r in records]
        sizes = [r.size for r in records]
        buy_vol = sum(r.size for r in records if r.is_buy)
        sell_vol = sum(r.size for r in records if r.is_sell)
        total_vol = buy_vol + sell_vol

        # VWAP
        vwap = (
            sum(r.price * r.size for r in records) / total_vol
            if total_vol > 0 else 0.0
        )

        large = [r for r in records if r.is_large]

        return TapeStatistics(
            symbol=symbol,
            period_start=records[0].timestamp,
            period_end=records[-1].timestamp,
            total_trades=len(records),
            total_volume=total_vol,
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            delta=buy_vol - sell_vol,
            vwap=round(vwap, 5),
            large_trade_count=len(large),
            large_trade_volume=sum(r.size for r in large),
            avg_trade_size=round(sum(sizes) / len(sizes), 4),
            max_trade_size=max(sizes),
            min_price=min(prices),
            max_price=max(prices),
            price_range=round(max(prices) - min(prices), 5),
        )

    # ────────────────────────────────────────────────────────────────
    # Callbacks / event system
    # ────────────────────────────────────────────────────────────────

    def register_callback(
        self,
        callback: Callable[[TimeAndSalesRecord], None],
        symbol: Optional[str] = None,
    ):
        """
        Register a callback invoked on every new trade.

        Args:
            callback: Callable receiving :class:`TimeAndSalesRecord`.
            symbol:   If given, only fires for that symbol; else all symbols.
        """
        with self._lock:
            if symbol:
                if symbol not in self._callbacks:
                    self._callbacks[symbol] = []
                self._callbacks[symbol].append(callback)
            else:
                self._global_callbacks.append(callback)

    def unregister_callback(
        self,
        callback: Callable,
        symbol: Optional[str] = None,
    ):
        """Unregister a previously registered callback."""
        with self._lock:
            if symbol and symbol in self._callbacks:
                self._callbacks[symbol] = [
                    c for c in self._callbacks[symbol] if c != callback
                ]
            else:
                self._global_callbacks = [
                    c for c in self._global_callbacks if c != callback
                ]

    # ────────────────────────────────────────────────────────────────
    # Utility
    # ────────────────────────────────────────────────────────────────

    def get_symbols(self) -> List[str]:
        """Return symbols that have tape data."""
        with self._lock:
            return list(self._tapes.keys())

    def clear_symbol(self, symbol: str):
        """Remove all tape data for *symbol*."""
        with self._lock:
            self._tapes.pop(symbol, None)
            self._size_sums.pop(symbol, None)
            self._size_counts.pop(symbol, None)

    def get_stats(self) -> Dict:
        """Return service-level diagnostics."""
        with self._lock:
            return {
                'symbols_tracked': len(self._tapes),
                'symbols': list(self._tapes.keys()),
                'buffer_size': self._buffer_size,
                'trades_by_symbol': {
                    s: len(buf) for s, buf in self._tapes.items()
                },
            }

    # ────────────────────────────────────────────────────────────────
    # Private helpers
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    def _classify_aggressor(
        price: float,
        aggressor: str,
        bid: Optional[float],
        ask: Optional[float],
    ) -> Aggressor:
        """Return confirmed/inferred aggressor enum."""
        agg = aggressor.lower() if aggressor else 'unknown'
        if agg in ('buy', 'bid'):
            return Aggressor.BUY
        if agg in ('sell', 'ask'):
            return Aggressor.SELL

        # Infer from bid/ask
        if bid is not None and ask is not None:
            if price >= ask:
                return Aggressor.BUY
            if price <= bid:
                return Aggressor.SELL

        return Aggressor.UNKNOWN

    def _dispatch(self, symbol: str, record: TimeAndSalesRecord):
        """Call registered callbacks (best-effort, never raises)."""
        callbacks = []
        with self._lock:
            callbacks.extend(self._callbacks.get(symbol, []))
            callbacks.extend(self._global_callbacks)

        for cb in callbacks:
            try:
                cb(record)
            except Exception:  # noqa: BLE001
                logger.exception("Callback error for %s", symbol)


# ────────────────────────────────────────────────────────────────────
# FastAPI integration
# ────────────────────────────────────────────────────────────────────

def create_time_and_sales_router(service: TimeAndSalesService):
    """
    Build a FastAPI router exposing time-and-sales endpoints.

    Args:
        service: :class:`TimeAndSalesService` instance.

    Returns:
        ``fastapi.APIRouter``
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/tape", tags=["Time & Sales"])

    @router.get("/{symbol}")
    async def get_tape(symbol: str, limit: int = 100):
        """Return the latest tape records."""
        records = service.get_tape(symbol, limit=limit)
        if not records:
            raise HTTPException(status_code=404, detail=f"No tape data for {symbol}")
        return [r.to_dict() for r in records]

    @router.get("/{symbol}/large")
    async def get_large_trades(symbol: str, limit: int = 50):
        """Return recent large trades."""
        records = service.get_large_trades(symbol, limit=limit)
        return [r.to_dict() for r in records]

    @router.get("/{symbol}/velocity")
    async def get_velocity(symbol: str, window: int = 60):
        """Return trade velocity metrics."""
        vel = service.get_velocity(symbol, window_seconds=window)
        if vel is None:
            raise HTTPException(status_code=404, detail=f"No tape data for {symbol}")
        return vel.to_dict()

    @router.get("/{symbol}/statistics")
    async def get_statistics(symbol: str, lookback: int = 3600):
        """Return tape statistics."""
        stats = service.get_statistics(symbol, lookback_seconds=lookback)
        if stats is None:
            raise HTTPException(status_code=404, detail=f"No tape data for {symbol}")
        return stats.to_dict()

    @router.get("/")
    async def list_symbols():
        """Return all symbols with tape data."""
        return {"symbols": service.get_symbols()}

    @router.get("/stats/service")
    async def service_stats():
        """Return service diagnostics."""
        return service.get_stats()

    return router


# ────────────────────────────────────────────────────────────────────
# Global singleton
# ────────────────────────────────────────────────────────────────────
_service: Optional[TimeAndSalesService] = None


def get_time_and_sales_service() -> TimeAndSalesService:
    """Return the process-wide :class:`TimeAndSalesService` instance."""
    global _service
    if _service is None:
        _service = TimeAndSalesService()
    return _service
