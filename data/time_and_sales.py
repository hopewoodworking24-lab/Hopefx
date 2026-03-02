"""
Time & Sales (Trade Tape) Service

Real-time trade capture and analytics:
- Trade tape with circular buffer (configurable max trades)
- Aggressor side identification (BID/ASK)
- Historical trade queries with filtering
- Trade velocity calculation (trades per minute)
- Large trade alerts
- Trade statistics and analytics
- Thread-safe implementation

Inspired by: CME Group Time & Sales, TT Platform, CQG
"""

import logging
import threading
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# ================================================================
# DATA STRUCTURES
# ================================================================


@dataclass
class ExecutedTrade:
    """Individual executed trade record from the tape."""

    timestamp: datetime
    symbol: str
    price: float
    size: float
    side: str  # 'buy' or 'sell' (aggressor side)
    trade_id: Optional[str] = None
    is_aggressive_buy: bool = False
    is_aggressive_sell: bool = False
    is_large_trade: bool = False  # Flag for size threshold

    @property
    def notional_value(self) -> float:
        """Trade notional value (price * size)."""
        return round(self.price * self.size, 4)

    @property
    def is_buy(self) -> bool:
        """True when the aggressor is a buyer."""
        return self.side.lower() == "buy"

    @property
    def is_sell(self) -> bool:
        """True when the aggressor is a seller."""
        return self.side.lower() == "sell"

    def to_dict(self) -> Dict:
        """Serialise to plain dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "trade_id": self.trade_id,
            "is_aggressive_buy": self.is_aggressive_buy,
            "is_aggressive_sell": self.is_aggressive_sell,
            "is_large_trade": self.is_large_trade,
            "notional_value": self.notional_value,
        }


@dataclass
class TradeVelocity:
    """Trade velocity metrics over a rolling time window."""

    symbol: str
    window_minutes: float
    trades_per_minute: float
    volume_per_minute: float
    avg_trade_size: float
    buy_trades_pct: float   # 0–100
    sell_trades_pct: float  # 0–100
    total_trades: int
    total_volume: float
    calculated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Serialise to plain dictionary."""
        return {
            "symbol": self.symbol,
            "window_minutes": self.window_minutes,
            "trades_per_minute": round(self.trades_per_minute, 4),
            "volume_per_minute": round(self.volume_per_minute, 4),
            "avg_trade_size": round(self.avg_trade_size, 4),
            "buy_trades_pct": round(self.buy_trades_pct, 2),
            "sell_trades_pct": round(self.sell_trades_pct, 2),
            "total_trades": self.total_trades,
            "total_volume": round(self.total_volume, 4),
            "calculated_at": self.calculated_at.isoformat(),
        }


@dataclass
class AggressorStats:
    """Buy vs sell aggressor statistics over a lookback window."""

    symbol: str
    lookback_minutes: float
    buy_trades: int
    sell_trades: int
    buy_volume: float
    sell_volume: float
    buy_trades_pct: float
    sell_trades_pct: float
    buy_volume_pct: float
    sell_volume_pct: float
    net_delta: float          # buy_volume - sell_volume
    dominant_side: str        # 'buyers', 'sellers', 'neutral'
    calculated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Serialise to plain dictionary."""
        return {
            "symbol": self.symbol,
            "lookback_minutes": self.lookback_minutes,
            "buy_trades": self.buy_trades,
            "sell_trades": self.sell_trades,
            "buy_volume": round(self.buy_volume, 4),
            "sell_volume": round(self.sell_volume, 4),
            "buy_trades_pct": round(self.buy_trades_pct, 2),
            "sell_trades_pct": round(self.sell_trades_pct, 2),
            "buy_volume_pct": round(self.buy_volume_pct, 2),
            "sell_volume_pct": round(self.sell_volume_pct, 2),
            "net_delta": round(self.net_delta, 4),
            "dominant_side": self.dominant_side,
            "calculated_at": self.calculated_at.isoformat(),
        }


@dataclass
class TradeHistogramBucket:
    """Single price-level bucket in a trade distribution histogram."""

    price_low: float
    price_high: float
    price_mid: float
    trade_count: int
    total_volume: float
    buy_volume: float
    sell_volume: float

    @property
    def buy_pct(self) -> float:
        """Percentage of volume that was buy-aggressed."""
        if self.total_volume == 0:
            return 0.0
        return round(self.buy_volume / self.total_volume * 100, 2)

    @property
    def sell_pct(self) -> float:
        """Percentage of volume that was sell-aggressed."""
        if self.total_volume == 0:
            return 0.0
        return round(self.sell_volume / self.total_volume * 100, 2)

    def to_dict(self) -> Dict:
        """Serialise to plain dictionary."""
        return {
            "price_low": self.price_low,
            "price_high": self.price_high,
            "price_mid": self.price_mid,
            "trade_count": self.trade_count,
            "total_volume": round(self.total_volume, 4),
            "buy_volume": round(self.buy_volume, 4),
            "sell_volume": round(self.sell_volume, 4),
            "buy_pct": self.buy_pct,
            "sell_pct": self.sell_pct,
        }


# ================================================================
# SERVICE
# ================================================================


class TimeAndSalesService:
    """
    Real-time Time & Sales (trade tape) service.

    Features:
    - Thread-safe circular buffer per symbol
    - Aggressor side identification
    - Large trade flagging and alerting
    - Trade velocity calculation
    - Buy/sell aggressor statistics
    - Price-level trade histogram
    - Configurable alert callbacks

    Usage::

        service = TimeAndSalesService()

        # Register a large-trade alert handler
        service.register_large_trade_callback(lambda t: print(t))

        # Feed live trades
        service.add_trade(
            symbol="XAUUSD",
            price=2345.10,
            size=10.0,
            side="buy",
        )

        # Query recent tape
        trades = service.get_recent_trades("XAUUSD", n=50)

        # Velocity metrics
        velocity = service.get_trade_velocity("XAUUSD", window_minutes=5)
    """

    _DOMINANCE_THRESHOLD = 0.15  # >15 % net imbalance triggers dominant_side label

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise the Time & Sales service.

        Args:
            config: Optional configuration dictionary. Supported keys:

                - ``max_trades`` (int): Circular buffer depth per symbol.
                  Default ``10_000``.
                - ``large_trade_threshold`` (float): Minimum size that
                  qualifies as a large trade.  Default ``100.0``.
                - ``large_trade_threshold_by_symbol`` (dict): Per-symbol
                  overrides for the large trade threshold.
        """
        self._config: Dict = config or {}

        self._max_trades: int = int(self._config.get("max_trades", 10_000))
        self._default_large_threshold: float = float(
            self._config.get("large_trade_threshold", 100.0)
        )
        self._symbol_large_threshold: Dict[str, float] = dict(
            self._config.get("large_trade_threshold_by_symbol", {})
        )

        # Per-symbol circular buffers  {symbol -> deque[ExecutedTrade]}
        self._tapes: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._max_trades)
        )

        # Callbacks fired on large trades
        self._large_trade_callbacks: List[Callable[[ExecutedTrade], None]] = []

        # Master lock – all public methods acquire it
        self._lock = threading.Lock()

        logger.info(
            "TimeAndSalesService initialised (max_trades=%d, large_threshold=%.2f)",
            self._max_trades,
            self._default_large_threshold,
        )

    # ----------------------------------------------------------------
    # CONFIGURATION HELPERS
    # ----------------------------------------------------------------

    def set_large_trade_threshold(self, symbol: str, threshold: float) -> None:
        """
        Override the large-trade size threshold for a specific symbol.

        Args:
            symbol: Trading symbol.
            threshold: Minimum size to flag as a large trade.
        """
        with self._lock:
            self._symbol_large_threshold[symbol] = threshold
            logger.debug(
                "Large trade threshold for %s set to %.2f", symbol, threshold
            )

    def register_large_trade_callback(
        self, callback: Callable[["ExecutedTrade"], None]
    ) -> None:
        """
        Register a callback that fires whenever a large trade is captured.

        Args:
            callback: Callable that receives an :class:`ExecutedTrade`.
        """
        with self._lock:
            self._large_trade_callbacks.append(callback)
            logger.debug(
                "Large trade callback registered (%d total)",
                len(self._large_trade_callbacks),
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
        trade_id: Optional[str] = None,
    ) -> ExecutedTrade:
        """
        Add a single executed trade to the tape.

        Args:
            symbol: Trading symbol (e.g. ``"XAUUSD"``).
            price: Executed price.
            size: Executed size / quantity.
            side: Aggressor side – ``"buy"`` or ``"sell"``.
            timestamp: UTC trade timestamp.  Defaults to ``datetime.utcnow()``.
            trade_id: Optional broker-assigned trade identifier.

        Returns:
            The :class:`ExecutedTrade` that was stored.

        Raises:
            ValueError: When *side* is not ``"buy"`` or ``"sell"``.
        """
        normalised_side = side.strip().lower()
        if normalised_side not in ("buy", "sell"):
            raise ValueError(
                f"side must be 'buy' or 'sell', got {side!r}"
            )

        threshold = self._symbol_large_threshold.get(
            symbol, self._default_large_threshold
        )
        is_large = size >= threshold

        trade = ExecutedTrade(
            timestamp=timestamp or datetime.utcnow(),
            symbol=symbol,
            price=price,
            size=size,
            side=normalised_side,
            trade_id=trade_id,
            is_aggressive_buy=(normalised_side == "buy"),
            is_aggressive_sell=(normalised_side == "sell"),
            is_large_trade=is_large,
        )

        with self._lock:
            self._tapes[symbol].append(trade)
            callbacks_snapshot = list(self._large_trade_callbacks) if is_large else []

        if is_large and callbacks_snapshot:
            self._fire_large_trade_callbacks(trade, callbacks_snapshot)

        logger.debug(
            "Trade added: %s %.5f x %.2f %s%s",
            symbol,
            price,
            size,
            normalised_side,
            " [LARGE]" if is_large else "",
        )

        return trade

    def add_trades(self, trades: List[Dict]) -> List[ExecutedTrade]:
        """
        Bulk-ingest a list of trade dictionaries.

        Each dictionary must contain the same keys accepted by
        :meth:`add_trade`.

        Args:
            trades: List of trade dicts.

        Returns:
            List of stored :class:`ExecutedTrade` objects.
        """
        stored: List[ExecutedTrade] = []
        for raw in trades:
            try:
                stored.append(
                    self.add_trade(
                        symbol=raw["symbol"],
                        price=float(raw["price"]),
                        size=float(raw["size"]),
                        side=raw["side"],
                        timestamp=raw.get("timestamp"),
                        trade_id=raw.get("trade_id"),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed trade record: %s – %s", raw, exc)

        logger.debug("Bulk ingested %d / %d trades", len(stored), len(trades))
        return stored

    # ----------------------------------------------------------------
    # QUERIES
    # ----------------------------------------------------------------

    def get_recent_trades(
        self, symbol: str, n: int = 100
    ) -> List[ExecutedTrade]:
        """
        Return the last *n* trades for *symbol*, most-recent last.

        Args:
            symbol: Trading symbol.
            n: Number of trades to return.  Clamped to buffer size.

        Returns:
            List of :class:`ExecutedTrade` objects (oldest first).
        """
        with self._lock:
            tape = self._tapes.get(symbol)
            if not tape:
                return []
            # deque is ordered oldest→newest; slice the tail
            trades_snapshot = list(tape)

        return trades_snapshot[-n:] if n < len(trades_snapshot) else trades_snapshot

    def get_trades_by_time(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[ExecutedTrade]:
        """
        Return trades within an inclusive UTC time range.

        Args:
            symbol: Trading symbol.
            start_time: Range start (UTC, inclusive).
            end_time: Range end (UTC, inclusive).

        Returns:
            Matching :class:`ExecutedTrade` objects, oldest first.
        """
        with self._lock:
            tape = self._tapes.get(symbol)
            if not tape:
                return []
            snapshot = list(tape)

        return [t for t in snapshot if start_time <= t.timestamp <= end_time]

    def get_large_trades(
        self,
        symbol: str,
        min_size: Optional[float] = None,
        lookback_minutes: Optional[float] = None,
    ) -> List[ExecutedTrade]:
        """
        Return trades that exceed a size threshold.

        Args:
            symbol: Trading symbol.
            min_size: Minimum trade size.  Defaults to the configured
                large-trade threshold for *symbol*.
            lookback_minutes: Optional rolling window in minutes.  When
                ``None`` the full buffer is searched.

        Returns:
            Matching :class:`ExecutedTrade` objects, oldest first.
        """
        threshold = min_size
        if threshold is None:
            threshold = self._symbol_large_threshold.get(
                symbol, self._default_large_threshold
            )

        with self._lock:
            tape = self._tapes.get(symbol)
            if not tape:
                return []
            snapshot = list(tape)

        if lookback_minutes is not None:
            cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
            snapshot = [t for t in snapshot if t.timestamp >= cutoff]

        return [t for t in snapshot if t.size >= threshold]

    # ----------------------------------------------------------------
    # ANALYTICS
    # ----------------------------------------------------------------

    def get_trade_velocity(
        self, symbol: str, window_minutes: float = 5.0
    ) -> Optional[TradeVelocity]:
        """
        Calculate trade velocity metrics over a rolling window.

        Args:
            symbol: Trading symbol.
            window_minutes: Look-back window in minutes.

        Returns:
            :class:`TradeVelocity` or ``None`` when no trades exist.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)

        with self._lock:
            tape = self._tapes.get(symbol)
            if not tape:
                return None
            snapshot = list(tape)

        window_trades = [t for t in snapshot if t.timestamp >= cutoff]
        if not window_trades:
            return None

        n = len(window_trades)
        total_vol = sum(t.size for t in window_trades)
        buy_count = sum(1 for t in window_trades if t.is_buy)
        sell_count = n - buy_count

        # Effective elapsed time: use actual span if ≥1 s, else window_minutes
        earliest = min(t.timestamp for t in window_trades)
        elapsed_minutes = max(
            (datetime.utcnow() - earliest).total_seconds() / 60.0,
            1.0 / 60.0,  # floor at one second
        )

        return TradeVelocity(
            symbol=symbol,
            window_minutes=window_minutes,
            trades_per_minute=n / elapsed_minutes,
            volume_per_minute=total_vol / elapsed_minutes,
            avg_trade_size=total_vol / n,
            buy_trades_pct=buy_count / n * 100.0,
            sell_trades_pct=sell_count / n * 100.0,
            total_trades=n,
            total_volume=total_vol,
        )

    def get_aggressor_stats(
        self, symbol: str, lookback_minutes: float = 60.0
    ) -> Optional[AggressorStats]:
        """
        Calculate buy vs sell aggressor statistics.

        Args:
            symbol: Trading symbol.
            lookback_minutes: Rolling look-back window in minutes.

        Returns:
            :class:`AggressorStats` or ``None`` when no trades exist.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)

        with self._lock:
            tape = self._tapes.get(symbol)
            if not tape:
                return None
            snapshot = list(tape)

        window = [t for t in snapshot if t.timestamp >= cutoff]
        if not window:
            return None

        buy_trades = [t for t in window if t.is_buy]
        sell_trades = [t for t in window if t.is_sell]

        buy_vol = sum(t.size for t in buy_trades)
        sell_vol = sum(t.size for t in sell_trades)
        total_vol = buy_vol + sell_vol
        total_count = len(window)

        buy_trades_pct = len(buy_trades) / total_count * 100.0 if total_count else 0.0
        sell_trades_pct = len(sell_trades) / total_count * 100.0 if total_count else 0.0
        buy_vol_pct = buy_vol / total_vol * 100.0 if total_vol else 0.0
        sell_vol_pct = sell_vol / total_vol * 100.0 if total_vol else 0.0
        net_delta = buy_vol - sell_vol

        # Classify dominant side
        imbalance = net_delta / total_vol if total_vol else 0.0
        if imbalance > self._DOMINANCE_THRESHOLD:
            dominant_side = "buyers"
        elif imbalance < -self._DOMINANCE_THRESHOLD:
            dominant_side = "sellers"
        else:
            dominant_side = "neutral"

        return AggressorStats(
            symbol=symbol,
            lookback_minutes=lookback_minutes,
            buy_trades=len(buy_trades),
            sell_trades=len(sell_trades),
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            buy_trades_pct=buy_trades_pct,
            sell_trades_pct=sell_trades_pct,
            buy_volume_pct=buy_vol_pct,
            sell_volume_pct=sell_vol_pct,
            net_delta=net_delta,
            dominant_side=dominant_side,
        )

    def get_trade_histogram(
        self,
        symbol: str,
        price_levels: int = 20,
        lookback_minutes: Optional[float] = None,
    ) -> List[TradeHistogramBucket]:
        """
        Build a trade distribution histogram across *price_levels* buckets.

        Args:
            symbol: Trading symbol.
            price_levels: Number of price buckets to divide the range into.
            lookback_minutes: Optional rolling window.  When ``None`` the
                full buffer is used.

        Returns:
            List of :class:`TradeHistogramBucket` objects sorted by price
            (ascending), or an empty list when there are no trades.
        """
        with self._lock:
            tape = self._tapes.get(symbol)
            if not tape:
                return []
            snapshot = list(tape)

        if lookback_minutes is not None:
            cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
            snapshot = [t for t in snapshot if t.timestamp >= cutoff]

        if not snapshot:
            return []

        prices = [t.price for t in snapshot]
        min_price = min(prices)
        max_price = max(prices)

        if min_price == max_price:
            # All trades at the same price – single bucket
            bucket = TradeHistogramBucket(
                price_low=min_price,
                price_high=max_price,
                price_mid=min_price,
                trade_count=len(snapshot),
                total_volume=sum(t.size for t in snapshot),
                buy_volume=sum(t.size for t in snapshot if t.is_buy),
                sell_volume=sum(t.size for t in snapshot if t.is_sell),
            )
            return [bucket]

        bucket_width = (max_price - min_price) / price_levels

        # Accumulate per bucket  {bucket_index -> aggregated data}
        buckets: Dict[int, Dict[str, Any]] = {}

        for trade in snapshot:
            # Clamp the highest price into the last bucket
            idx = min(
                int((trade.price - min_price) / bucket_width),
                price_levels - 1,
            )
            if idx not in buckets:
                low = min_price + idx * bucket_width
                buckets[idx] = {
                    "price_low": low,
                    "price_high": low + bucket_width,
                    "price_mid": low + bucket_width / 2.0,
                    "trade_count": 0,
                    "total_volume": 0.0,
                    "buy_volume": 0.0,
                    "sell_volume": 0.0,
                }
            b = buckets[idx]
            b["trade_count"] += 1
            b["total_volume"] += trade.size
            if trade.is_buy:
                b["buy_volume"] += trade.size
            else:
                b["sell_volume"] += trade.size

        return [
            TradeHistogramBucket(**buckets[i])
            for i in sorted(buckets.keys())
        ]

    def get_trade_stats(self, symbol: str) -> Dict:
        """
        Return summary statistics for the full trade buffer.

        Args:
            symbol: Trading symbol.

        Returns:
            Dictionary with count, volume, price range, and basic
            buy/sell breakdown.
        """
        with self._lock:
            tape = self._tapes.get(symbol)
            if not tape:
                return {"symbol": symbol, "trade_count": 0}
            snapshot = list(tape)

        if not snapshot:
            return {"symbol": symbol, "trade_count": 0}

        prices = [t.price for t in snapshot]
        sizes = [t.size for t in snapshot]
        buy_vol = sum(t.size for t in snapshot if t.is_buy)
        sell_vol = sum(t.size for t in snapshot if t.is_sell)
        total_vol = buy_vol + sell_vol
        large = [t for t in snapshot if t.is_large_trade]

        return {
            "symbol": symbol,
            "trade_count": len(snapshot),
            "total_volume": round(total_vol, 4),
            "buy_volume": round(buy_vol, 4),
            "sell_volume": round(sell_vol, 4),
            "net_delta": round(buy_vol - sell_vol, 4),
            "large_trade_count": len(large),
            "large_trade_volume": round(sum(t.size for t in large), 4),
            "avg_trade_size": round(total_vol / len(snapshot), 4),
            "min_trade_size": round(min(sizes), 4),
            "max_trade_size": round(max(sizes), 4),
            "min_price": round(min(prices), 5),
            "max_price": round(max(prices), 5),
            "first_trade_at": snapshot[0].timestamp.isoformat(),
            "last_trade_at": snapshot[-1].timestamp.isoformat(),
            "buffer_utilisation_pct": round(
                len(snapshot) / self._max_trades * 100.0, 2
            ),
        }

    def get_service_stats(self) -> Dict:
        """
        Return operational statistics for all tracked symbols.

        Returns:
            Dictionary mapping each symbol to its buffer depth plus
            a global summary.
        """
        with self._lock:
            by_symbol = {s: len(d) for s, d in self._tapes.items()}

        return {
            "symbols_tracked": list(by_symbol.keys()),
            "total_trades_buffered": sum(by_symbol.values()),
            "trades_by_symbol": by_symbol,
            "max_trades_per_symbol": self._max_trades,
            "large_trade_threshold_default": self._default_large_threshold,
            "large_trade_threshold_by_symbol": dict(self._symbol_large_threshold),
            "registered_callbacks": len(self._large_trade_callbacks),
        }

    def clear_symbol(self, symbol: str) -> None:
        """
        Discard all buffered trades for *symbol*.

        Args:
            symbol: Trading symbol to clear.
        """
        with self._lock:
            if symbol in self._tapes:
                self._tapes[symbol].clear()
        logger.info("Trade tape cleared for %s", symbol)

    # ----------------------------------------------------------------
    # PRIVATE HELPERS
    # ----------------------------------------------------------------

    def _fire_large_trade_callbacks(
        self,
        trade: ExecutedTrade,
        callbacks: List[Callable[[ExecutedTrade], None]],
    ) -> None:
        """Fire all registered large-trade callbacks (outside the lock)."""
        for cb in callbacks:
            try:
                cb(trade)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Large trade callback raised an exception: %s", exc, exc_info=True
                )


# ================================================================
# FASTAPI INTEGRATION
# ================================================================


def create_time_sales_router(service: TimeAndSalesService):
    """
    Create a FastAPI router with Time & Sales endpoints.

    Args:
        service: :class:`TimeAndSalesService` instance to bind.

    Returns:
        A ``fastapi.APIRouter`` configured with the endpoints below.

    Endpoints:
        - ``GET /api/time-sales/{symbol}`` – Recent trades
        - ``GET /api/time-sales/{symbol}/velocity`` – Trade velocity metrics
        - ``GET /api/time-sales/{symbol}/large-trades`` – Large trades filter
        - ``GET /api/time-sales/{symbol}/aggressor`` – Buy/sell aggressor stats
        - ``GET /api/time-sales/{symbol}/histogram`` – Price-level histogram
        - ``GET /api/time-sales/{symbol}/stats`` – Symbol trade statistics
        - ``GET /api/time-sales/service/stats`` – Service-level statistics
    """
    from fastapi import APIRouter, HTTPException, Query

    router = APIRouter(prefix="/api/time-sales", tags=["Time & Sales"])

    @router.get("/{symbol}")
    async def get_recent_trades(
        symbol: str,
        n: int = Query(default=100, ge=1, le=10_000, description="Number of trades"),
    ):
        """Get the most recent *n* trades for a symbol."""
        trades = service.get_recent_trades(symbol, n=n)
        if not trades:
            raise HTTPException(status_code=404, detail=f"No trades found for {symbol}")
        return [t.to_dict() for t in trades]

    @router.get("/{symbol}/velocity")
    async def get_trade_velocity(
        symbol: str,
        window_minutes: float = Query(
            default=5.0, ge=0.1, le=1440.0, description="Look-back window in minutes"
        ),
    ):
        """Get trade velocity metrics for a rolling window."""
        velocity = service.get_trade_velocity(symbol, window_minutes=window_minutes)
        if velocity is None:
            raise HTTPException(
                status_code=404,
                detail=f"No trades in the last {window_minutes} minutes for {symbol}",
            )
        return velocity.to_dict()

    @router.get("/{symbol}/large-trades")
    async def get_large_trades(
        symbol: str,
        min_size: Optional[float] = Query(
            default=None, ge=0.0, description="Minimum trade size filter"
        ),
        lookback_minutes: Optional[float] = Query(
            default=None, ge=0.1, description="Optional rolling window in minutes"
        ),
    ):
        """Return trades that exceed the large-trade size threshold."""
        trades = service.get_large_trades(
            symbol, min_size=min_size, lookback_minutes=lookback_minutes
        )
        if not trades:
            raise HTTPException(
                status_code=404, detail=f"No large trades found for {symbol}"
            )
        return [t.to_dict() for t in trades]

    @router.get("/{symbol}/aggressor")
    async def get_aggressor_stats(
        symbol: str,
        lookback_minutes: float = Query(
            default=60.0, ge=1.0, le=1440.0, description="Look-back window in minutes"
        ),
    ):
        """Get buy vs sell aggressor statistics."""
        stats = service.get_aggressor_stats(symbol, lookback_minutes=lookback_minutes)
        if stats is None:
            raise HTTPException(
                status_code=404,
                detail=f"No aggressor data for {symbol} in the last {lookback_minutes} minutes",
            )
        return stats.to_dict()

    @router.get("/{symbol}/histogram")
    async def get_trade_histogram(
        symbol: str,
        price_levels: int = Query(
            default=20, ge=2, le=500, description="Number of price buckets"
        ),
        lookback_minutes: Optional[float] = Query(
            default=None, ge=0.1, description="Optional rolling window in minutes"
        ),
    ):
        """Get trade distribution histogram across price levels."""
        histogram = service.get_trade_histogram(
            symbol,
            price_levels=price_levels,
            lookback_minutes=lookback_minutes,
        )
        if not histogram:
            raise HTTPException(
                status_code=404, detail=f"No histogram data for {symbol}"
            )
        return [b.to_dict() for b in histogram]

    @router.get("/{symbol}/stats")
    async def get_trade_stats(symbol: str):
        """Get summary statistics for the full trade buffer."""
        stats = service.get_trade_stats(symbol)
        if stats.get("trade_count", 0) == 0:
            raise HTTPException(status_code=404, detail=f"No trades found for {symbol}")
        return stats

    @router.get("/service/stats")
    async def get_service_stats():
        """Get service-level operational statistics."""
        return service.get_service_stats()

    return router


# ================================================================
# MODULE-LEVEL SINGLETON
# ================================================================

_time_and_sales_service: Optional[TimeAndSalesService] = None


def get_time_and_sales_service(config: Optional[Dict] = None) -> TimeAndSalesService:
    """
    Return the module-level singleton :class:`TimeAndSalesService`.

    Args:
        config: Optional configuration passed to the constructor on first
            call.  Ignored on subsequent calls.

    Returns:
        The shared :class:`TimeAndSalesService` instance.
    """
    global _time_and_sales_service
    if _time_and_sales_service is None:
        _time_and_sales_service = TimeAndSalesService(config=config)
    return _time_and_sales_service
