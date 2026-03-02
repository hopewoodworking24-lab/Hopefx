"""
Real-Time Streaming Service

WebSocket-based infrastructure for streaming market data:
- Multi-symbol subscription management
- Event-driven architecture
- Automatic reconnection with exponential back-off
- Thread-safe publish/subscribe bus
- Integration with TimeAndSalesService, DOM, and OrderFlow modules
- FastAPI WebSocket endpoint

This module does *not* depend on any specific broker; broker adapters
push data via the public ``publish`` API.
"""

import asyncio
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────
DEFAULT_MAX_QUEUE = 10_000      # per-subscriber event queue depth
DEFAULT_RECONNECT_BASE = 1.0   # seconds – first retry delay
DEFAULT_RECONNECT_MAX = 60.0   # seconds – cap for exponential back-off
DEFAULT_RECONNECT_FACTOR = 2.0 # multiplier


# ────────────────────────────────────────────────────────────────────
# Enums & event types
# ────────────────────────────────────────────────────────────────────
class StreamEventType(str, Enum):
    """Types of events published on the stream bus."""
    TRADE = "trade"
    QUOTE = "quote"
    ORDER_BOOK = "order_book"
    TICKER = "ticker"
    HEARTBEAT = "heartbeat"
    CONNECTION = "connection"
    DISCONNECTION = "disconnection"
    ERROR = "error"
    CUSTOM = "custom"


class ConnectionState(str, Enum):
    """WebSocket connection lifecycle states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


# ────────────────────────────────────────────────────────────────────
# Data-classes
# ────────────────────────────────────────────────────────────────────
@dataclass
class StreamEvent:
    """A single event published to the event bus."""
    event_type: StreamEventType
    symbol: str
    data: Dict
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "unknown"

    def to_dict(self) -> Dict:
        return {
            'event_type': self.event_type.value,
            'symbol': self.symbol,
            'data': self.data,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
        }


@dataclass
class SubscriptionInfo:
    """Metadata about a symbol subscription."""
    symbol: str
    event_types: Set[StreamEventType]
    subscribed_at: datetime = field(default_factory=datetime.utcnow)
    event_count: int = 0
    last_event: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'event_types': [e.value for e in self.event_types],
            'subscribed_at': self.subscribed_at.isoformat(),
            'event_count': self.event_count,
            'last_event': self.last_event.isoformat() if self.last_event else None,
        }


@dataclass
class ConnectionStatus:
    """Current state of a named stream connection."""
    name: str
    state: ConnectionState
    url: Optional[str]
    subscriptions: List[str]    # symbol list
    connect_time: Optional[datetime]
    reconnect_count: int
    last_error: Optional[str]

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'state': self.state.value,
            'url': self.url,
            'subscriptions': self.subscriptions,
            'connect_time': (
                self.connect_time.isoformat() if self.connect_time else None
            ),
            'reconnect_count': self.reconnect_count,
            'last_error': self.last_error,
        }


# ────────────────────────────────────────────────────────────────────
# Event bus (synchronous, thread-safe)
# ────────────────────────────────────────────────────────────────────
class EventBus:
    """
    Thread-safe synchronous publish/subscribe event bus.

    Subscribers register callbacks; every ``publish`` call
    dispatches the event to all matching subscribers.
    """

    def __init__(self):
        # symbol -> event_type -> list[callback]
        self._handlers: Dict[str, Dict[str, List[Callable]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # Global handlers (all symbols, all types)
        self._global_handlers: List[Callable] = []
        self._lock = threading.RLock()
        self._stats: Dict[str, int] = defaultdict(int)

    def subscribe(
        self,
        callback: Callable[[StreamEvent], None],
        symbol: Optional[str] = None,
        event_type: Optional[StreamEventType] = None,
    ):
        """
        Register *callback* for matching events.

        Args:
            callback:   Function receiving :class:`StreamEvent`.
            symbol:     Filter by symbol; ``None`` = all symbols.
            event_type: Filter by event type; ``None`` = all types.
        """
        with self._lock:
            if symbol is None and event_type is None:
                self._global_handlers.append(callback)
            else:
                sym_key = symbol or '*'
                type_key = event_type.value if event_type else '*'
                self._handlers[sym_key][type_key].append(callback)

    def unsubscribe(
        self,
        callback: Callable,
        symbol: Optional[str] = None,
        event_type: Optional[StreamEventType] = None,
    ):
        """Unregister a previously registered callback."""
        with self._lock:
            if symbol is None and event_type is None:
                self._global_handlers = [
                    c for c in self._global_handlers if c != callback
                ]
            else:
                sym_key = symbol or '*'
                type_key = event_type.value if event_type else '*'
                if sym_key in self._handlers and type_key in self._handlers[sym_key]:
                    self._handlers[sym_key][type_key] = [
                        c for c in self._handlers[sym_key][type_key]
                        if c != callback
                    ]

    def publish(self, event: StreamEvent):
        """Dispatch *event* to all matching subscribers."""
        self._stats['published'] += 1

        with self._lock:
            callbacks = list(self._global_handlers)
            # Symbol-specific + wildcard
            for sym_key in (event.symbol, '*'):
                sym_handlers = self._handlers.get(sym_key, {})
                # Event-type-specific + wildcard
                for type_key in (event.event_type.value, '*'):
                    callbacks.extend(sym_handlers.get(type_key, []))

        for cb in callbacks:
            try:
                cb(event)
                self._stats['delivered'] += 1
            except Exception:  # noqa: BLE001
                self._stats['errors'] += 1
                logger.exception("EventBus callback error (%s/%s)",
                                 event.symbol, event.event_type)

    def get_stats(self) -> Dict:
        return dict(self._stats)


# ────────────────────────────────────────────────────────────────────
# Stream connection (manages reconnection logic)
# ────────────────────────────────────────────────────────────────────
class StreamConnection:
    """
    Manages a single named WebSocket connection with auto-reconnect.

    In production use a real WebSocket library (websockets, aiohttp,
    etc.).  This class provides the lifecycle skeleton and reconnection
    logic; subclass or inject a *connect_factory* to wire real I/O.
    """

    def __init__(
        self,
        name: str,
        url: str,
        event_bus: EventBus,
        connect_factory: Optional[Callable] = None,
        config: Optional[Dict] = None,
    ):
        """
        Args:
            name:            Human-readable connection identifier.
            url:             WebSocket endpoint URL.
            event_bus:       :class:`EventBus` to publish received events on.
            connect_factory: Async callable ``(url) -> context-manager``
                             yielding the raw WebSocket object.  When
                             *None* the connection stays in CONNECTED
                             state immediately (useful for testing).
            config:          Optional reconnection overrides.
        """
        cfg = config or {}
        self.name = name
        self.url = url
        self._bus = event_bus
        self._factory = connect_factory

        self._state = ConnectionState.DISCONNECTED
        self._reconnect_count = 0
        self._connect_time: Optional[datetime] = None
        self._last_error: Optional[str] = None

        self._reconnect_base: float = cfg.get('reconnect_base', DEFAULT_RECONNECT_BASE)
        self._reconnect_max: float = cfg.get('reconnect_max', DEFAULT_RECONNECT_MAX)
        self._reconnect_factor: float = cfg.get('reconnect_factor',
                                                  DEFAULT_RECONNECT_FACTOR)

        self._subscriptions: Set[str] = set()
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

    # ──────── public API ────────────────────────────────────────────

    def subscribe(self, symbol: str):
        """Add *symbol* to this connection's subscription set."""
        with self._lock:
            self._subscriptions.add(symbol)

    def unsubscribe(self, symbol: str):
        """Remove *symbol* from this connection's subscription set."""
        with self._lock:
            self._subscriptions.discard(symbol)

    def start(self):
        """Start the connection loop in a background daemon thread."""
        self._stop_event.clear()
        t = threading.Thread(target=self._run_loop, daemon=True,
                             name=f"stream-{self.name}")
        t.start()
        logger.info("StreamConnection '%s' started", self.name)

    def stop(self):
        """Signal the connection loop to stop."""
        self._stop_event.set()
        with self._lock:
            self._state = ConnectionState.CLOSED
        logger.info("StreamConnection '%s' stopped", self.name)

    @property
    def state(self) -> ConnectionState:
        return self._state

    def get_status(self) -> ConnectionStatus:
        with self._lock:
            return ConnectionStatus(
                name=self.name,
                state=self._state,
                url=self.url,
                subscriptions=list(self._subscriptions),
                connect_time=self._connect_time,
                reconnect_count=self._reconnect_count,
                last_error=self._last_error,
            )

    # ──────── internal loop ─────────────────────────────────────────

    def _run_loop(self):
        """Reconnection loop executed in a background thread."""
        delay = self._reconnect_base

        while not self._stop_event.is_set():
            try:
                with self._lock:
                    self._state = ConnectionState.CONNECTING

                self._connect_time = datetime.utcnow()

                if self._factory is None:
                    # No real factory – just mark connected and idle
                    with self._lock:
                        self._state = ConnectionState.CONNECTED
                    self._bus.publish(StreamEvent(
                        event_type=StreamEventType.CONNECTION,
                        symbol='*',
                        data={'connection': self.name, 'url': self.url},
                        source=self.name,
                    ))
                    # Wait until stop is requested
                    self._stop_event.wait()
                    break

                # Real connection attempt (synchronous wrapper)
                self._do_connect()

                # Successful run – reset delay
                delay = self._reconnect_base

            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._last_error = str(exc)
                    self._reconnect_count += 1
                    self._state = ConnectionState.RECONNECTING

                logger.warning(
                    "StreamConnection '%s' error (attempt %d): %s – "
                    "retrying in %.1fs",
                    self.name, self._reconnect_count, exc, delay,
                )
                self._bus.publish(StreamEvent(
                    event_type=StreamEventType.ERROR,
                    symbol='*',
                    data={'connection': self.name, 'error': str(exc)},
                    source=self.name,
                ))

                self._stop_event.wait(delay)
                delay = min(delay * self._reconnect_factor, self._reconnect_max)

    def _do_connect(self):
        """
        Placeholder for real WebSocket connection logic.

        Override in subclasses or replace *_factory* for production use.
        """
        with self._lock:
            self._state = ConnectionState.CONNECTED
        # In a real implementation this would block until disconnected


# ────────────────────────────────────────────────────────────────────
# Streaming service (top-level orchestrator)
# ────────────────────────────────────────────────────────────────────
class StreamingService:
    """
    Orchestrates multiple :class:`StreamConnection` instances and
    exposes a unified subscription/publish API.

    Usage::

        bus = EventBus()
        service = StreamingService(event_bus=bus)

        # Subscribe to all XAUUSD events
        def on_trade(event):
            print(event.to_dict())

        service.subscribe('XAUUSD', on_trade,
                          event_type=StreamEventType.TRADE)

        # Add a named connection
        service.add_connection('primary', 'wss://broker.example.com/stream')
        service.start_connection('primary')

        # Publish (broker adapters call this)
        service.publish(StreamEvent(
            event_type=StreamEventType.TRADE,
            symbol='XAUUSD',
            data={'price': 1950.0, 'size': 10.0, 'side': 'buy'},
        ))
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config: Optional[Dict] = None,
    ):
        self._bus = event_bus or EventBus()
        self._config = config or {}

        # Named connections
        self._connections: Dict[str, StreamConnection] = {}

        # Symbol subscriptions metadata
        self._subscriptions: Dict[str, SubscriptionInfo] = {}

        self._lock = threading.RLock()
        logger.info("StreamingService initialized")

    # ──────── connection management ─────────────────────────────────

    def add_connection(
        self,
        name: str,
        url: str,
        connect_factory: Optional[Callable] = None,
        config: Optional[Dict] = None,
    ) -> StreamConnection:
        """
        Register and return a named :class:`StreamConnection`.

        Args:
            name:            Unique connection name.
            url:             WebSocket endpoint URL.
            connect_factory: Optional async factory (see StreamConnection).
            config:          Connection-level overrides.

        Returns:
            The created :class:`StreamConnection`.
        """
        conn = StreamConnection(
            name=name,
            url=url,
            event_bus=self._bus,
            connect_factory=connect_factory,
            config=config or self._config,
        )
        with self._lock:
            self._connections[name] = conn
        logger.info("Connection '%s' added (%s)", name, url)
        return conn

    def start_connection(self, name: str):
        """Start the named connection."""
        with self._lock:
            conn = self._connections.get(name)
        if conn is None:
            raise KeyError(f"Unknown connection: {name}")
        conn.start()

    def stop_connection(self, name: str):
        """Stop the named connection."""
        with self._lock:
            conn = self._connections.get(name)
        if conn:
            conn.stop()

    def start_all(self):
        """Start all registered connections."""
        with self._lock:
            names = list(self._connections.keys())
        for name in names:
            self._connections[name].start()

    def stop_all(self):
        """Stop all registered connections."""
        with self._lock:
            names = list(self._connections.keys())
        for name in names:
            self._connections[name].stop()

    def get_connection_status(self, name: str) -> Optional[ConnectionStatus]:
        """Return status for a named connection."""
        with self._lock:
            conn = self._connections.get(name)
        return conn.get_status() if conn else None

    def get_all_connection_statuses(self) -> List[ConnectionStatus]:
        """Return statuses for all connections."""
        with self._lock:
            conns = list(self._connections.values())
        return [c.get_status() for c in conns]

    # ──────── symbol subscriptions ──────────────────────────────────

    def subscribe_symbol(
        self,
        symbol: str,
        event_types: Optional[List[StreamEventType]] = None,
        connection_name: Optional[str] = None,
    ):
        """
        Subscribe to a symbol across connections.

        Args:
            symbol:          Instrument ticker.
            event_types:     Event types to subscribe; *None* = all.
            connection_name: Target specific connection; *None* = all.
        """
        et_set = set(event_types) if event_types else set(StreamEventType)
        with self._lock:
            if symbol not in self._subscriptions:
                self._subscriptions[symbol] = SubscriptionInfo(
                    symbol=symbol, event_types=et_set
                )
            else:
                self._subscriptions[symbol].event_types.update(et_set)

            target_conns = (
                [self._connections[connection_name]]
                if connection_name and connection_name in self._connections
                else list(self._connections.values())
            )

        for conn in target_conns:
            conn.subscribe(symbol)

        logger.info("Subscribed to %s (%s)", symbol,
                    [e.value for e in et_set])

    def unsubscribe_symbol(
        self,
        symbol: str,
        connection_name: Optional[str] = None,
    ):
        """Unsubscribe from a symbol."""
        with self._lock:
            self._subscriptions.pop(symbol, None)
            target_conns = (
                [self._connections[connection_name]]
                if connection_name and connection_name in self._connections
                else list(self._connections.values())
            )

        for conn in target_conns:
            conn.unsubscribe(symbol)

    def get_subscriptions(self) -> List[SubscriptionInfo]:
        """Return all active subscriptions."""
        with self._lock:
            return list(self._subscriptions.values())

    # ──────── event publishing / bus delegation ──────────────────────

    def subscribe(
        self,
        symbol: Optional[str] = None,
        callback: Optional[Callable[[StreamEvent], None]] = None,
        event_type: Optional[StreamEventType] = None,
    ):
        """
        Register *callback* on the internal event bus.

        Positional form accepted for convenience::

            service.subscribe('XAUUSD', my_handler, StreamEventType.TRADE)
        """
        self._bus.subscribe(callback, symbol=symbol, event_type=event_type)

    def unsubscribe(
        self,
        callback: Callable,
        symbol: Optional[str] = None,
        event_type: Optional[StreamEventType] = None,
    ):
        """Unregister a callback."""
        self._bus.unsubscribe(callback, symbol=symbol, event_type=event_type)

    def publish(self, event: StreamEvent):
        """
        Publish an event to all matching subscribers.

        Broker adapters call this method when they receive market data.
        """
        # Update subscription stats
        with self._lock:
            if event.symbol in self._subscriptions:
                info = self._subscriptions[event.symbol]
                info.event_count += 1
                info.last_event = event.timestamp

        self._bus.publish(event)

    def publish_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        source: str = "unknown",
        timestamp: Optional[datetime] = None,
        **kwargs: Any,
    ):
        """
        Convenience method to publish a TRADE event.

        Args:
            symbol:    Instrument ticker.
            price:     Execution price.
            size:      Trade volume.
            side:      'buy' or 'sell'.
            source:    Data source identifier.
            timestamp: Trade time; defaults to now.
            **kwargs:  Extra data fields.
        """
        data = {'price': price, 'size': size, 'side': side, **kwargs}
        self.publish(StreamEvent(
            event_type=StreamEventType.TRADE,
            symbol=symbol,
            data=data,
            timestamp=timestamp or datetime.utcnow(),
            source=source,
        ))

    def publish_quote(
        self,
        symbol: str,
        bid: float,
        ask: float,
        source: str = "unknown",
        timestamp: Optional[datetime] = None,
        **kwargs: Any,
    ):
        """Convenience method to publish a QUOTE event."""
        data = {'bid': bid, 'ask': ask, **kwargs}
        self.publish(StreamEvent(
            event_type=StreamEventType.QUOTE,
            symbol=symbol,
            data=data,
            timestamp=timestamp or datetime.utcnow(),
            source=source,
        ))

    # ──────── service statistics ─────────────────────────────────────

    def get_stats(self) -> Dict:
        """Return service-level diagnostics."""
        with self._lock:
            subs = {
                s: info.event_count
                for s, info in self._subscriptions.items()
            }
            conn_states = {
                name: conn.state.value
                for name, conn in self._connections.items()
            }

        return {
            'connections': conn_states,
            'subscriptions_count': len(subs),
            'events_by_symbol': subs,
            'bus_stats': self._bus.get_stats(),
        }


# ────────────────────────────────────────────────────────────────────
# FastAPI / WebSocket integration
# ────────────────────────────────────────────────────────────────────

def create_streaming_router(service: StreamingService):
    """
    Build a FastAPI router with streaming endpoints.

    Includes a WebSocket endpoint that pushes events in real time.

    Args:
        service: :class:`StreamingService` instance.

    Returns:
        ``fastapi.APIRouter``
    """
    from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
    import json

    router = APIRouter(prefix="/api/stream", tags=["Streaming"])

    @router.get("/subscriptions")
    async def list_subscriptions():
        """Return active symbol subscriptions."""
        return [s.to_dict() for s in service.get_subscriptions()]

    @router.post("/subscribe/{symbol}")
    async def subscribe_symbol(symbol: str):
        """Subscribe to a symbol."""
        service.subscribe_symbol(symbol)
        return {"status": "subscribed", "symbol": symbol}

    @router.delete("/subscribe/{symbol}")
    async def unsubscribe_symbol(symbol: str):
        """Unsubscribe from a symbol."""
        service.unsubscribe_symbol(symbol)
        return {"status": "unsubscribed", "symbol": symbol}

    @router.get("/connections")
    async def list_connections():
        """Return status of all connections."""
        return [c.to_dict() for c in service.get_all_connection_statuses()]

    @router.get("/connections/{name}")
    async def get_connection(name: str):
        """Return status of a named connection."""
        status = service.get_connection_status(name)
        if status is None:
            raise HTTPException(status_code=404,
                                detail=f"Connection '{name}' not found")
        return status.to_dict()

    @router.get("/stats")
    async def stats():
        """Return streaming service statistics."""
        return service.get_stats()

    @router.websocket("/ws/{symbol}")
    async def websocket_stream(websocket: WebSocket, symbol: str):
        """
        WebSocket endpoint streaming events for *symbol*.

        Connect with any standard WebSocket client::

            ws://host/api/stream/ws/XAUUSD
        """
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=DEFAULT_MAX_QUEUE)
        loop = asyncio.get_event_loop()

        def on_event(event: StreamEvent):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception:  # noqa: BLE001
                pass  # queue full – drop event

        service.subscribe(symbol=symbol, callback=on_event)
        service.subscribe_symbol(symbol)

        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(event.to_dict()))
        except asyncio.TimeoutError:
            # Send heartbeat
            await websocket.send_text(
                json.dumps({'event_type': 'heartbeat', 'symbol': symbol,
                            'timestamp': datetime.utcnow().isoformat()})
            )
        except WebSocketDisconnect:
            pass
        finally:
            service.unsubscribe(on_event, symbol=symbol)

    return router


# ────────────────────────────────────────────────────────────────────
# Global singleton
# ────────────────────────────────────────────────────────────────────
_service: Optional[StreamingService] = None


def get_streaming_service() -> StreamingService:
    """Return the process-wide :class:`StreamingService` instance."""
    global _service
    if _service is None:
        _service = StreamingService()
    return _service
