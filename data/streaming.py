"""
Real-Time Data Streaming Infrastructure

Provides event-driven, WebSocket-based market data streaming:
- WebSocket connection management with automatic reconnection
- Multi-symbol subscription support
- Tick data aggregation and validation
- Trade and order book update distribution
- Rate limiting and throttling
- Data quality checks
- Mock data source for testing

Compatible with: MetaTrader 5, OANDA, Alpaca, Binance, and other broker feeds
Inspired by: professional trading platforms and market data providers
"""

import asyncio
import json
import logging
import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ConnectionState(Enum):
    """WebSocket connection lifecycle states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"


class DataType(Enum):
    """Supported streaming data types."""

    TICK = "tick"
    TRADE = "trade"
    ORDERBOOK = "orderbook"


class DataQualityFlag(Enum):
    """Data quality classification flags."""

    VALID = "valid"
    STALE = "stale"
    CROSSED = "crossed"  # bid >= ask
    SPIKE = "spike"
    MISSING_FIELD = "missing_field"


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class TickData:
    """
    Best bid/ask snapshot for a symbol (Level 1 quote).

    Attributes:
        timestamp: UTC timestamp of the tick.
        symbol: Instrument identifier (e.g. "XAUUSD").
        bid: Best bid price.
        ask: Best ask price.
        bid_size: Volume available at the best bid.
        ask_size: Volume available at the best ask.
        last_price: Price of the most recent trade, if available.
        quality: Data quality classification.
    """

    timestamp: datetime
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last_price: Optional[float] = None
    quality: DataQualityFlag = DataQualityFlag.VALID

    @property
    def spread(self) -> float:
        """Bid-ask spread in price units."""
        return round(self.ask - self.bid, 5)

    @property
    def mid_price(self) -> float:
        """Simple mid-point between bid and ask."""
        return round((self.bid + self.ask) / 2, 5)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "last_price": self.last_price,
            "spread": self.spread,
            "mid_price": self.mid_price,
            "quality": self.quality.value,
        }


@dataclass
class TradeData:
    """
    Executed trade record from the exchange tape.

    Attributes:
        timestamp: UTC execution timestamp.
        symbol: Instrument identifier.
        price: Execution price.
        size: Trade size / volume.
        side: Aggressor side – ``'buy'`` or ``'sell'``.
        trade_id: Optional exchange-assigned trade identifier.
    """

    timestamp: datetime
    symbol: str
    price: float
    size: float
    side: str  # 'buy' | 'sell'
    trade_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "trade_id": self.trade_id,
        }


@dataclass
class OrderBookData:
    """
    Level 2 order book snapshot / delta update.

    Attributes:
        timestamp: UTC timestamp of the update.
        symbol: Instrument identifier.
        bids: List of ``[price, size]`` bid levels (best first).
        asks: List of ``[price, size]`` ask levels (best first).
        is_snapshot: ``True`` for full snapshot, ``False`` for delta.
        sequence: Exchange sequence number for ordering updates.
    """

    timestamp: datetime
    symbol: str
    bids: List[List[float]]  # [[price, size], ...]
    asks: List[List[float]]  # [[price, size], ...]
    is_snapshot: bool = True
    sequence: int = 0

    @property
    def best_bid(self) -> Optional[float]:
        """Best (highest) bid price."""
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        """Best (lowest) ask price."""
        return self.asks[0][0] if self.asks else None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "bids": self.bids,
            "asks": self.asks,
            "is_snapshot": self.is_snapshot,
            "sequence": self.sequence,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
        }


@dataclass
class StreamConfig:
    """
    Configuration for the streaming service.

    Attributes:
        symbols: List of instrument symbols to subscribe to.
        data_types: Data types to stream – any of ``'tick'``, ``'trade'``,
            ``'orderbook'``.
        buffer_size: Maximum items held per symbol buffer.
        reconnect_attempts: Maximum reconnection retries before giving up.
        throttle_ms: Minimum milliseconds between consecutive publishes for
            the same symbol / data type (rate limiting).
        reconnect_delay_s: Base delay in seconds between reconnect attempts
            (doubles with each attempt up to *max_reconnect_delay_s*).
        max_reconnect_delay_s: Upper bound on the reconnect back-off delay.
        stale_threshold_s: Seconds after which a tick is flagged as stale.
        spike_threshold_pct: Percentage change that classifies a price as a
            spike (data quality check).
    """

    symbols: List[str] = field(default_factory=list)
    data_types: List[str] = field(
        default_factory=lambda: ["tick", "trade", "orderbook"]
    )
    buffer_size: int = 1000
    reconnect_attempts: int = 10
    throttle_ms: int = 100
    reconnect_delay_s: float = 1.0
    max_reconnect_delay_s: float = 60.0
    stale_threshold_s: float = 5.0
    spike_threshold_pct: float = 1.0  # 1 % move flagged as spike


@dataclass
class ConnectionStatus:
    """
    Point-in-time snapshot of the streaming connection health.

    Attributes:
        state: Current :class:`ConnectionState`.
        connected_at: UTC timestamp of the last successful connection.
        last_message_at: UTC timestamp of the most recent inbound message.
        messages_received: Cumulative inbound message count.
        reconnect_count: Number of reconnection attempts made.
        subscribed_symbols: Set of currently subscribed symbols.
        errors: Recent error messages (ring buffer, last 20).
    """

    state: ConnectionState = ConnectionState.DISCONNECTED
    connected_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    messages_received: int = 0
    reconnect_count: int = 0
    subscribed_symbols: Set[str] = field(default_factory=set)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "state": self.state.value,
            "connected_at": (
                self.connected_at.isoformat() if self.connected_at else None
            ),
            "last_message_at": (
                self.last_message_at.isoformat()
                if self.last_message_at
                else None
            ),
            "messages_received": self.messages_received,
            "reconnect_count": self.reconnect_count,
            "subscribed_symbols": list(self.subscribed_symbols),
            "recent_errors": self.errors[-20:],
        }


# ---------------------------------------------------------------------------
# Throttle helper
# ---------------------------------------------------------------------------


class _Throttle:
    """
    Token-bucket–style per-key rate limiter.

    Ensures at most one event per *throttle_ms* milliseconds for each key.
    Thread-safe.
    """

    def __init__(self, throttle_ms: int) -> None:
        self._interval = throttle_ms / 1000.0
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return ``True`` if the event for *key* should be forwarded."""
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key, 0.0)
            if now - last >= self._interval:
                self._last[key] = now
                return True
            return False

    def update_interval(self, throttle_ms: int) -> None:
        """Update the throttle interval."""
        with self._lock:
            self._interval = throttle_ms / 1000.0


# ---------------------------------------------------------------------------
# Streaming Service
# ---------------------------------------------------------------------------


class StreamingService:
    """
    Event-driven real-time market data streaming service.

    Manages WebSocket connections, symbol subscriptions, data validation,
    rate limiting, and fan-out to registered callbacks.

    Example::

        config = StreamConfig(symbols=["XAUUSD"], throttle_ms=50)
        svc = StreamingService(config)

        @svc.on_tick
        def handle_tick(tick: TickData) -> None:
            print(tick.to_dict())

        svc.start_streaming()
        # … later …
        svc.stop_streaming()
    """

    def __init__(self, config: Optional[StreamConfig] = None) -> None:
        """
        Initialise the streaming service.

        Args:
            config: Stream configuration.  Defaults to :class:`StreamConfig`
                with all default values when ``None``.
        """
        self._config = config or StreamConfig()
        self._lock = threading.Lock()

        # Subscription state
        self._subscriptions: Dict[str, Set[str]] = {}  # symbol -> data_types

        # Per-symbol tick/trade/orderbook ring buffers
        self._tick_buffers: Dict[str, deque] = {}
        self._trade_buffers: Dict[str, deque] = {}
        self._orderbook_buffers: Dict[str, deque] = {}

        # Callback registries
        self._tick_callbacks: List[Callable[[TickData], None]] = []
        self._trade_callbacks: List[Callable[[TradeData], None]] = []
        self._orderbook_callbacks: List[Callable[[OrderBookData], None]] = []

        # Connection health
        self._status = ConnectionStatus()

        # Rate limiter
        self._throttle = _Throttle(self._config.throttle_ms)

        # Last known prices for spike detection
        self._last_prices: Dict[str, float] = {}

        # Async event loop for WebSocket management (created on start)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

        # Seed subscriptions from config
        for symbol in self._config.symbols:
            self._init_symbol(symbol, set(self._config.data_types))

        logger.info(
            "StreamingService initialised with %d symbol(s), throttle=%dms",
            len(self._config.symbols),
            self._config.throttle_ms,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_symbol(self, symbol: str, data_types: Set[str]) -> None:
        """Initialise buffers and subscription state for *symbol*."""
        buf_size = self._config.buffer_size
        if symbol not in self._subscriptions:
            self._subscriptions[symbol] = set()
            self._tick_buffers[symbol] = deque(maxlen=buf_size)
            self._trade_buffers[symbol] = deque(maxlen=buf_size)
            self._orderbook_buffers[symbol] = deque(maxlen=buf_size)
        self._subscriptions[symbol].update(data_types)

    def _validate_tick(self, tick: TickData) -> TickData:
        """
        Run data quality checks against *tick* and return it with an
        updated :attr:`~TickData.quality` flag.

        Checks performed:

        * Crossed market (bid ≥ ask).
        * Stale timestamp (older than ``stale_threshold_s``).
        * Price spike vs. last known price (change > ``spike_threshold_pct``).
        * Non-positive bid / ask.

        Args:
            tick: Incoming tick to validate.

        Returns:
            The same *tick* object with :attr:`~TickData.quality` set.
        """
        # Non-positive prices
        if tick.bid <= 0 or tick.ask <= 0:
            tick.quality = DataQualityFlag.MISSING_FIELD
            logger.warning(
                "Non-positive price for %s: bid=%.5f ask=%.5f",
                tick.symbol,
                tick.bid,
                tick.ask,
            )
            return tick

        # Crossed market
        if tick.bid >= tick.ask:
            tick.quality = DataQualityFlag.CROSSED
            logger.warning(
                "Crossed market for %s: bid=%.5f >= ask=%.5f",
                tick.symbol,
                tick.bid,
                tick.ask,
            )
            return tick

        # Stale timestamp
        age = (datetime.now(timezone.utc) - tick.timestamp).total_seconds()
        if age > self._config.stale_threshold_s:
            tick.quality = DataQualityFlag.STALE
            logger.debug(
                "Stale tick for %s: age=%.2fs", tick.symbol, age
            )
            return tick

        # Spike detection
        last = self._last_prices.get(tick.symbol)
        if last is not None and last > 0:
            change_pct = abs(tick.mid_price - last) / last * 100
            if change_pct > self._config.spike_threshold_pct:
                tick.quality = DataQualityFlag.SPIKE
                logger.warning(
                    "Price spike for %s: %.5f -> %.5f (%.2f%%)",
                    tick.symbol,
                    last,
                    tick.mid_price,
                    change_pct,
                )
                return tick

        self._last_prices[tick.symbol] = tick.mid_price
        tick.quality = DataQualityFlag.VALID
        return tick

    def _fire_callbacks(
        self,
        callbacks: List[Callable],
        data: Any,
        label: str,
    ) -> None:
        """
        Invoke each registered callback with *data*.

        Exceptions raised by individual callbacks are caught and logged so
        that a misbehaving subscriber cannot disrupt the whole fanout.

        Args:
            callbacks: List of callables to invoke.
            data: Argument passed to each callable.
            label: Human-readable label used in error logs.
        """
        for cb in callbacks:
            try:
                cb(data)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Error in %s callback %s: %s",
                    label,
                    getattr(cb, "__name__", repr(cb)),
                    exc,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Public subscription API
    # ------------------------------------------------------------------

    def subscribe(
        self,
        symbol: str,
        data_types: Optional[List[str]] = None,
    ) -> None:
        """
        Subscribe to market data for *symbol*.

        Args:
            symbol: Instrument identifier (e.g. ``"XAUUSD"``).
            data_types: Data types to subscribe to.  Defaults to all
                configured data types when ``None``.

        Raises:
            ValueError: If an unrecognised data type is supplied.
        """
        types = set(data_types or self._config.data_types)
        valid = {dt.value for dt in DataType}
        unknown = types - valid
        if unknown:
            raise ValueError(
                f"Unknown data type(s): {unknown}. Valid: {valid}"
            )

        with self._lock:
            self._init_symbol(symbol, types)

        logger.info("Subscribed to %s for data types: %s", symbol, types)

    def unsubscribe(self, symbol: str) -> None:
        """
        Unsubscribe from all data streams for *symbol*.

        Clears in-memory buffers for the symbol.

        Args:
            symbol: Instrument identifier to unsubscribe.
        """
        with self._lock:
            self._subscriptions.pop(symbol, None)
            self._tick_buffers.pop(symbol, None)
            self._trade_buffers.pop(symbol, None)
            self._orderbook_buffers.pop(symbol, None)
            self._last_prices.pop(symbol, None)
            self._status.subscribed_symbols.discard(symbol)

        logger.info("Unsubscribed from %s", symbol)

    def get_subscribed_symbols(self) -> Dict[str, Set[str]]:
        """
        Return the current subscription map.

        Returns:
            A copy of the mapping ``{symbol: set_of_data_types}``.
        """
        with self._lock:
            return {sym: set(types) for sym, types in self._subscriptions.items()}

    # ------------------------------------------------------------------
    # Callback registration decorators / methods
    # ------------------------------------------------------------------

    def on_tick(
        self, callback: Callable[[TickData], None]
    ) -> Callable[[TickData], None]:
        """
        Register a callback for incoming :class:`TickData` events.

        Can be used as a plain method call or as a decorator::

            @svc.on_tick
            def handle(tick: TickData) -> None:
                ...

        Args:
            callback: Callable that accepts a single :class:`TickData`
                argument.

        Returns:
            The original *callback* unchanged (decorator-compatible).
        """
        self._tick_callbacks.append(callback)
        logger.debug("Registered tick callback: %s", getattr(callback, "__name__", repr(callback)))
        return callback

    def on_trade(
        self, callback: Callable[[TradeData], None]
    ) -> Callable[[TradeData], None]:
        """
        Register a callback for incoming :class:`TradeData` events.

        Args:
            callback: Callable that accepts a single :class:`TradeData`
                argument.

        Returns:
            The original *callback* unchanged (decorator-compatible).
        """
        self._trade_callbacks.append(callback)
        logger.debug("Registered trade callback: %s", getattr(callback, "__name__", repr(callback)))
        return callback

    def on_orderbook(
        self, callback: Callable[[OrderBookData], None]
    ) -> Callable[[OrderBookData], None]:
        """
        Register a callback for incoming :class:`OrderBookData` events.

        Args:
            callback: Callable that accepts a single :class:`OrderBookData`
                argument.

        Returns:
            The original *callback* unchanged (decorator-compatible).
        """
        self._orderbook_callbacks.append(callback)
        logger.debug(
            "Registered orderbook callback: %s",
            getattr(callback, "__name__", repr(callback)),
        )
        return callback

    def remove_tick_callback(self, callback: Callable[[TickData], None]) -> None:
        """
        Remove a previously registered tick callback.

        Args:
            callback: The callable to remove.  No-op if not registered.
        """
        try:
            self._tick_callbacks.remove(callback)
        except ValueError:
            pass

    def remove_trade_callback(self, callback: Callable[[TradeData], None]) -> None:
        """
        Remove a previously registered trade callback.

        Args:
            callback: The callable to remove.  No-op if not registered.
        """
        try:
            self._trade_callbacks.remove(callback)
        except ValueError:
            pass

    def remove_orderbook_callback(
        self, callback: Callable[[OrderBookData], None]
    ) -> None:
        """
        Remove a previously registered order book callback.

        Args:
            callback: The callable to remove.  No-op if not registered.
        """
        try:
            self._orderbook_callbacks.remove(callback)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Publish API (called by data sources)
    # ------------------------------------------------------------------

    def publish_tick(self, tick_data: TickData) -> None:
        """
        Accept a tick from a data source and fan it out to subscribers.

        Performs data quality validation and rate limiting before
        distributing the event.

        Args:
            tick_data: The :class:`TickData` to publish.
        """
        if tick_data.symbol not in self._subscriptions:
            return
        if DataType.TICK.value not in self._subscriptions[tick_data.symbol]:
            return

        throttle_key = f"tick:{tick_data.symbol}"
        if not self._throttle.allow(throttle_key):
            return

        validated = self._validate_tick(tick_data)

        with self._lock:
            self._tick_buffers[tick_data.symbol].append(validated)
            self._status.last_message_at = datetime.now(timezone.utc)
            self._status.messages_received += 1
            self._status.subscribed_symbols.add(tick_data.symbol)

        self._fire_callbacks(self._tick_callbacks, validated, "tick")

    def publish_trade(self, trade_data: TradeData) -> None:
        """
        Accept a trade from a data source and fan it out to subscribers.

        Args:
            trade_data: The :class:`TradeData` to publish.
        """
        if trade_data.symbol not in self._subscriptions:
            return
        if DataType.TRADE.value not in self._subscriptions[trade_data.symbol]:
            return

        throttle_key = f"trade:{trade_data.symbol}"
        if not self._throttle.allow(throttle_key):
            return

        with self._lock:
            self._trade_buffers[trade_data.symbol].append(trade_data)
            self._status.last_message_at = datetime.now(timezone.utc)
            self._status.messages_received += 1

        self._fire_callbacks(self._trade_callbacks, trade_data, "trade")

    def publish_orderbook(self, orderbook_data: OrderBookData) -> None:
        """
        Accept an order book update and fan it out to subscribers.

        Args:
            orderbook_data: The :class:`OrderBookData` to publish.
        """
        if orderbook_data.symbol not in self._subscriptions:
            return
        if (
            DataType.ORDERBOOK.value
            not in self._subscriptions[orderbook_data.symbol]
        ):
            return

        throttle_key = f"orderbook:{orderbook_data.symbol}"
        if not self._throttle.allow(throttle_key):
            return

        with self._lock:
            self._orderbook_buffers[orderbook_data.symbol].append(
                orderbook_data
            )
            self._status.last_message_at = datetime.now(timezone.utc)
            self._status.messages_received += 1

        self._fire_callbacks(
            self._orderbook_callbacks, orderbook_data, "orderbook"
        )

    # ------------------------------------------------------------------
    # Streaming lifecycle
    # ------------------------------------------------------------------

    def start_streaming(self) -> None:
        """
        Start the streaming service.

        Launches a dedicated background thread hosting an asyncio event loop
        responsible for the WebSocket connection.  Returns immediately; the
        connection is established asynchronously.

        Raises:
            RuntimeError: If the service is already running.
        """
        with self._lock:
            if self._status.state not in (
                ConnectionState.DISCONNECTED,
                ConnectionState.STOPPED,
            ):
                raise RuntimeError(
                    "StreamingService is already running "
                    f"(state={self._status.state.value})"
                )
            self._status.state = ConnectionState.CONNECTING

        self._loop = asyncio.new_event_loop()
        self._stop_event = asyncio.Event()
        self._loop_thread = threading.Thread(
            target=self._run_event_loop,
            name="streaming-event-loop",
            daemon=True,
        )
        self._loop_thread.start()
        logger.info("StreamingService started")

    def stop_streaming(self) -> None:
        """
        Gracefully stop the streaming service.

        Signals the event loop to shut down and waits for the background
        thread to terminate (up to 5 seconds).
        """
        if self._loop is None or self._stop_event is None:
            return

        # Signal the async loop to stop
        self._loop.call_soon_threadsafe(self._stop_event.set)

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)

        with self._lock:
            self._status.state = ConnectionState.STOPPED

        logger.info("StreamingService stopped")

    def get_connection_status(self) -> Dict[str, Any]:
        """
        Return a serialisable snapshot of the connection health.

        Returns:
            Dictionary describing the current :class:`ConnectionStatus`.
        """
        with self._lock:
            return self._status.to_dict()

    # ------------------------------------------------------------------
    # Buffer access helpers
    # ------------------------------------------------------------------

    def get_tick_buffer(self, symbol: str) -> List[TickData]:
        """
        Return a snapshot of the tick buffer for *symbol*.

        Args:
            symbol: Instrument identifier.

        Returns:
            List of buffered :class:`TickData` objects (oldest first).
        """
        with self._lock:
            return list(self._tick_buffers.get(symbol, deque()))

    def get_trade_buffer(self, symbol: str) -> List[TradeData]:
        """
        Return a snapshot of the trade buffer for *symbol*.

        Args:
            symbol: Instrument identifier.

        Returns:
            List of buffered :class:`TradeData` objects (oldest first).
        """
        with self._lock:
            return list(self._trade_buffers.get(symbol, deque()))

    def get_orderbook_buffer(self, symbol: str) -> List[OrderBookData]:
        """
        Return a snapshot of the order book buffer for *symbol*.

        Args:
            symbol: Instrument identifier.

        Returns:
            List of buffered :class:`OrderBookData` objects (oldest first).
        """
        with self._lock:
            return list(self._orderbook_buffers.get(symbol, deque()))

    # ------------------------------------------------------------------
    # Async WebSocket internals
    # ------------------------------------------------------------------

    def _run_event_loop(self) -> None:
        """Entry point for the background event-loop thread."""
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._manage_connection())
        finally:
            self._loop.close()

    async def _manage_connection(self) -> None:
        """
        Connection manager coroutine.

        Attempts to connect and, on failure, applies exponential back-off
        up to ``reconnect_attempts`` times before giving up.
        """
        attempts = 0
        delay = self._config.reconnect_delay_s

        while not self._stop_event.is_set():
            try:
                await self._connect()
                # _connect returns when the connection drops
                attempts = 0
                delay = self._config.reconnect_delay_s
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                attempts += 1
                err_msg = f"Connection error (attempt {attempts}): {exc}"
                logger.error(err_msg)
                with self._lock:
                    self._status.errors.append(err_msg)
                    self._status.reconnect_count += 1

                if attempts >= self._config.reconnect_attempts:
                    logger.error(
                        "Max reconnection attempts (%d) reached. Giving up.",
                        self._config.reconnect_attempts,
                    )
                    break

                with self._lock:
                    self._status.state = ConnectionState.RECONNECTING

                logger.info(
                    "Reconnecting in %.1fs (attempt %d/%d)…",
                    delay,
                    attempts,
                    self._config.reconnect_attempts,
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay
                    )
                except asyncio.TimeoutError:
                    pass

                delay = min(
                    delay * 2,
                    self._config.max_reconnect_delay_s,
                )

        with self._lock:
            self._status.state = ConnectionState.DISCONNECTED

    async def _connect(self) -> None:
        """
        Simulate a WebSocket connection lifecycle.

        In production this method would open a ``websockets`` connection,
        send subscription messages, and loop over received frames.  Here it
        marks the service as connected and waits for the stop signal, acting
        as a clean integration point for a real broker adapter.
        """
        with self._lock:
            self._status.state = ConnectionState.CONNECTED
            self._status.connected_at = datetime.now(timezone.utc)

        logger.info("WebSocket connection established (ready for data)")

        # Block until stop is requested (real adapters would loop here)
        await self._stop_event.wait()

        with self._lock:
            self._status.state = ConnectionState.DISCONNECTED

        logger.info("WebSocket connection closed")


# ---------------------------------------------------------------------------
# Mock Data Source
# ---------------------------------------------------------------------------


class MockDataSource:
    """
    Simulated market data source for testing the streaming pipeline.

    Generates realistic price movements using a geometric Brownian motion
    model and pushes :class:`TickData`, :class:`TradeData`, and
    :class:`OrderBookData` into a :class:`StreamingService`.

    Example::

        svc = StreamingService(StreamConfig(symbols=["XAUUSD"]))
        src = MockDataSource(svc, symbols=["XAUUSD"])
        svc.start_streaming()
        src.start()
        time.sleep(10)
        src.stop()
        svc.stop_streaming()
    """

    # Realistic seed prices for common instruments
    _SEED_PRICES: Dict[str, float] = {
        "XAUUSD": 2330.00,
        "EURUSD": 1.0850,
        "GBPUSD": 1.2700,
        "USDJPY": 154.50,
        "BTCUSD": 65000.0,
        "ETHUSD": 3500.0,
    }
    _DEFAULT_SEED = 100.0

    def __init__(
        self,
        service: StreamingService,
        symbols: Optional[List[str]] = None,
        tick_interval_ms: int = 250,
        volatility: float = 0.0002,
        spread_pct: float = 0.0003,
    ) -> None:
        """
        Initialise the mock data source.

        Args:
            service: :class:`StreamingService` instance to publish into.
            symbols: Symbols to simulate.  Defaults to all symbols
                configured in *service*.
            tick_interval_ms: Milliseconds between generated ticks.
            volatility: Per-tick price volatility (standard deviation of
                the log-return, expressed as a fraction).
            spread_pct: Bid-ask spread as a fraction of mid price.
        """
        self._service = service
        self._symbols = symbols or list(
            service.get_subscribed_symbols().keys()
        )
        self._tick_interval = tick_interval_ms / 1000.0
        self._volatility = volatility
        self._spread_pct = spread_pct

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._mid_prices: Dict[str, float] = {
            sym: self._SEED_PRICES.get(sym, self._DEFAULT_SEED)
            for sym in self._symbols
        }
        self._sequence: int = 0
        self._trade_counter: int = 0

        logger.info(
            "MockDataSource initialised for symbols=%s interval=%.3fs",
            self._symbols,
            self._tick_interval,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start generating and publishing simulated market data."""
        if self._running:
            logger.warning("MockDataSource is already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._generate_loop,
            name="mock-data-source",
            daemon=True,
        )
        self._thread.start()
        logger.info("MockDataSource started")

    def stop(self) -> None:
        """Stop the simulated data generation."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("MockDataSource stopped")

    # ------------------------------------------------------------------
    # Generation loop
    # ------------------------------------------------------------------

    def _generate_loop(self) -> None:
        """Main generation loop – runs in the mock-data-source thread."""
        while self._running:
            start = time.monotonic()
            for symbol in self._symbols:
                try:
                    self._emit_tick(symbol)
                    # Emit trade with ~40 % probability per tick
                    if random.random() < 0.4:
                        self._emit_trade(symbol)
                    # Emit order book update with ~20 % probability per tick
                    if random.random() < 0.2:
                        self._emit_orderbook(symbol)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "MockDataSource error for %s: %s", symbol, exc
                    )
            elapsed = time.monotonic() - start
            sleep_time = max(0.0, self._tick_interval - elapsed)
            time.sleep(sleep_time)

    def _next_mid(self, symbol: str) -> float:
        """
        Advance the mid price for *symbol* by one GBM step.

        Args:
            symbol: Instrument identifier.

        Returns:
            Updated mid price.
        """
        z = random.gauss(0, 1)
        drift = -0.5 * self._volatility ** 2  # Itô correction
        log_return = drift * self._tick_interval + self._volatility * math.sqrt(
            self._tick_interval
        ) * z
        self._mid_prices[symbol] *= math.exp(log_return)
        return self._mid_prices[symbol]

    def _emit_tick(self, symbol: str) -> None:
        """Generate and publish one :class:`TickData` for *symbol*."""
        mid = self._next_mid(symbol)
        half_spread = mid * self._spread_pct / 2
        bid = round(mid - half_spread, 5)
        ask = round(mid + half_spread, 5)
        bid_size = round(random.uniform(0.1, 5.0), 2)
        ask_size = round(random.uniform(0.1, 5.0), 2)

        tick = TickData(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            last_price=round(mid, 5),
        )
        self._service.publish_tick(tick)

    def _emit_trade(self, symbol: str) -> None:
        """Generate and publish one :class:`TradeData` for *symbol*."""
        mid = self._mid_prices[symbol]
        side = "buy" if random.random() > 0.5 else "sell"
        # Trades execute near mid price ± half spread
        half_spread = mid * self._spread_pct / 2
        price = mid + (half_spread if side == "buy" else -half_spread)
        self._trade_counter += 1

        trade = TradeData(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            price=round(price, 5),
            size=round(random.uniform(0.01, 2.0), 4),
            side=side,
            trade_id=f"mock-{self._trade_counter:06d}",
        )
        self._service.publish_trade(trade)

    def _emit_orderbook(self, symbol: str) -> None:
        """Generate and publish one :class:`OrderBookData` for *symbol*."""
        mid = self._mid_prices[symbol]
        half_spread = mid * self._spread_pct / 2

        levels = 5
        bids = [
            [
                round(mid - half_spread - i * mid * 0.0001, 5),
                round(random.uniform(0.5, 10.0), 2),
            ]
            for i in range(levels)
        ]
        asks = [
            [
                round(mid + half_spread + i * mid * 0.0001, 5),
                round(random.uniform(0.5, 10.0), 2),
            ]
            for i in range(levels)
        ]
        self._sequence += 1

        ob = OrderBookData(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            bids=bids,
            asks=asks,
            is_snapshot=False,
            sequence=self._sequence,
        )
        self._service.publish_orderbook(ob)

    # ------------------------------------------------------------------
    # Price access
    # ------------------------------------------------------------------

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Return the current simulated mid price for *symbol*.

        Args:
            symbol: Instrument identifier.

        Returns:
            Current mid price, or ``None`` if *symbol* is unknown.
        """
        return self._mid_prices.get(symbol)


# ---------------------------------------------------------------------------
# FastAPI endpoint structures
# ---------------------------------------------------------------------------

# The code below defines the FastAPI router and endpoint functions.
# Mount it in your application with:
#
#   from data.streaming import router as streaming_router
#   app.include_router(streaming_router)
#
# A shared StreamingService instance is expected to be provided via
# dependency injection or by replacing ``_get_service`` with your own
# factory.

try:
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
    from fastapi.responses import JSONResponse

    router = APIRouter(tags=["streaming"])

    # ------------------------------------------------------------------
    # Dependency – override this in your application
    # ------------------------------------------------------------------

    _default_service: Optional[StreamingService] = None

    def _get_service() -> StreamingService:
        """
        FastAPI dependency that returns the application-level
        :class:`StreamingService` instance.

        Replace or override this function in your application to inject
        your own service instance.

        Returns:
            The global :class:`StreamingService` singleton.

        Raises:
            RuntimeError: If no service has been configured.
        """
        if _default_service is None:
            raise RuntimeError(
                "No StreamingService configured. "
                "Set streaming._default_service before starting the app."
            )
        return _default_service

    # ------------------------------------------------------------------
    # WebSocket stream endpoint
    # ------------------------------------------------------------------

    @router.websocket("/ws/stream/{symbol}")
    async def ws_stream(
        websocket: WebSocket,
        symbol: str,
        service: StreamingService = Depends(_get_service),
    ) -> None:
        """
        WebSocket stream for a single symbol.

        ``WS /ws/stream/{symbol}``

        After connecting, the client receives JSON-serialised market data
        events (tick, trade, orderbook) as they arrive for the requested
        symbol.  The connection remains open until either the client
        disconnects or the server is shut down.

        Path parameters:
            symbol: Instrument to stream (e.g. ``XAUUSD``).
        """
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        loop = asyncio.get_event_loop()

        def _enqueue(data: Any) -> None:
            """Thread-safe enqueue from streaming callbacks."""
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except asyncio.QueueFull:
                logger.warning(
                    "WebSocket queue full for %s – dropping message", symbol
                )

        # Register per-connection callbacks scoped to this symbol
        def _on_tick(tick: TickData) -> None:
            if tick.symbol == symbol:
                _enqueue({"type": "tick", "data": tick.to_dict()})

        def _on_trade(trade: TradeData) -> None:
            if trade.symbol == symbol:
                _enqueue({"type": "trade", "data": trade.to_dict()})

        def _on_ob(ob: OrderBookData) -> None:
            if ob.symbol == symbol:
                _enqueue({"type": "orderbook", "data": ob.to_dict()})

        service.on_tick(_on_tick)
        service.on_trade(_on_trade)
        service.on_orderbook(_on_ob)

        logger.info("WebSocket client connected for %s", symbol)
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_text(json.dumps(msg, default=str))
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("WebSocket error for %s: %s", symbol, exc)
        finally:
            # Remove per-connection callbacks via the public API
            service.remove_tick_callback(_on_tick)
            service.remove_trade_callback(_on_trade)
            service.remove_orderbook_callback(_on_ob)
            logger.info("WebSocket client disconnected for %s", symbol)

    # ------------------------------------------------------------------
    # REST status endpoint
    # ------------------------------------------------------------------

    @router.get("/api/stream/status")
    async def stream_status(
        service: StreamingService = Depends(_get_service),
    ) -> JSONResponse:
        """
        Connection and subscription health check.

        ``GET /api/stream/status``

        Returns:
            JSON body with connection state, message counts, subscribed
            symbols, and recent errors.
        """
        return JSONResponse(content=service.get_connection_status())

except ImportError:
    # FastAPI is optional; streaming service works without it.
    logger.debug(
        "FastAPI not installed – WebSocket endpoints are not available"
    )
    router = None  # type: ignore[assignment]
