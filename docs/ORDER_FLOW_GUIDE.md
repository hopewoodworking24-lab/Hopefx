# HOPEFX Order Flow Analysis Guide

> **Version:** 1.0.0 | **Last Updated:** February 2026

A comprehensive guide for the HOPEFX Order Flow Analysis system — professional-grade tools
for volume profile analysis, institutional flow detection, and real-time market microstructure
monitoring of XAU/USD and other instruments.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Module Architecture](#module-architecture)
3. [Quick Start](#quick-start)
4. [TimeAndSalesService](#timeandssalesservice)
5. [InstitutionalFlowDetector](#institutionalflowdetector)
6. [AdvancedOrderFlowAnalyzer](#advancedorderflowanalyzer)
7. [StreamingService & MockDataSource](#streamingservice--mockdatasource)
8. [OrderFlowDashboard](#orderflowdashboard)
9. [Integration Patterns](#integration-patterns)
10. [Configuration Reference](#configuration-reference)
11. [Best Practices](#best-practices)

---

## Overview

The Order Flow Analysis system provides four tightly integrated modules for understanding
**who** is trading, **how aggressively**, and **at which price levels**. Together they give
you a picture of market microstructure that goes far beyond candlestick charts.

### Key Capabilities

| Capability | Module |
|---|---|
| Live trade tape with aggressor stats | `TimeAndSalesService` |
| Institutional / large-order detection | `InstitutionalFlowDetector` |
| Volume profile, delta, footprint charts | `OrderFlowAnalyzer` |
| Aggression metrics, stacked imbalances, oscillator | `AdvancedOrderFlowAnalyzer` |
| Simulated & live data streaming pipeline | `StreamingService` / `MockDataSource` |
| Unified multi-component dashboard | `OrderFlowDashboard` |

### Supported Instruments

The system is instrument-agnostic. Any symbol can be fed as a string — `"XAUUSD"`,
`"EURUSD"`, `"BTCUSD"`, etc. Seed prices for common instruments are pre-configured in
`MockDataSource`.

---

## Module Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   OrderFlowDashboard                    │
│  (unified aggregator – combines all 5 components)       │
└────────────┬────────────┬─────────────┬────────────┬───┘
             │            │             │            │
    ┌────────▼──┐  ┌──────▼────┐  ┌────▼──────┐  ┌─▼──────────┐
    │Time&Sales │  │OrderFlow  │  │Advanced   │  │Institutional│
    │Service    │  │Analyzer   │  │Analyzer   │  │Detector     │
    └────────┬──┘  └──────┬────┘  └────┬──────┘  └─┬──────────┘
             │            │             │            │
             └────────────┴─────────────┴────────────┘
                                  ▲
                    ┌─────────────┴──────────────┐
                    │   StreamingService          │
                    │   (+ MockDataSource)        │
                    └─────────────────────────────┘
```

All components accept trades via their `add_trade()` method. The `OrderFlowDashboard`
acts as a fan-out layer, propagating each trade to every configured component automatically.

---

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Minimal Example

```python
from analysis.order_flow_dashboard import create_dashboard

# Create dashboard with all components pre-wired
dashboard = create_dashboard()

# Feed some trades
dashboard.add_trade('XAUUSD', price=2330.50, size=1.0, side='buy')
dashboard.add_trade('XAUUSD', price=2330.40, size=2.5, side='sell')
dashboard.add_trade('XAUUSD', price=2330.60, size=0.5, side='buy')

# Get a quick summary
summary = dashboard.get_summary('XAUUSD')
print(f"Bias: {summary['bias']}")
print(f"Buy pressure: {summary['buy_pressure']:.1f}%")
print(f"Cumulative delta: {summary['cumulative_delta']:.2f}")
```

### With Live Streaming

```python
import time
from data.streaming import StreamingService, StreamConfig, MockDataSource
from analysis.order_flow_dashboard import create_dashboard

config = StreamConfig(symbols=['XAUUSD'])
service = StreamingService(config)
dashboard = create_dashboard()

# Wire streaming trades into the dashboard
def on_trade(trade):
    dashboard.add_trade(trade.symbol, trade.price, trade.size, trade.side)

service.on_trade(on_trade)
service.subscribe('XAUUSD')

mock = MockDataSource(service, symbols=['XAUUSD'])
service.start_streaming()
mock.start()

time.sleep(30)  # Collect 30 seconds of data

mock.stop()
service.stop_streaming()

analysis = dashboard.get_complete_analysis('XAUUSD')
print(analysis)
```

---

## TimeAndSalesService

**Module:** `data/time_and_sales.py`

The Time & Sales service maintains a thread-safe circular buffer of executed trades per
symbol, providing real-time statistics on trade velocity, aggressor balance, and large-trade
alerts.

### Key Data Structures

#### `ExecutedTrade`

| Field | Type | Description |
|---|---|---|
| `timestamp` | `datetime` | UTC execution time |
| `symbol` | `str` | Trading symbol |
| `price` | `float` | Execution price |
| `size` | `float` | Trade size in lots |
| `side` | `str` | `'buy'` or `'sell'` (aggressor) |
| `is_large_trade` | `bool` | True when size ≥ threshold |
| `notional_value` | `float` | `price × size` (computed) |

#### `AggressorStats`

| Field | Type | Description |
|---|---|---|
| `buy_trades` | `int` | Number of buy-aggressed trades |
| `sell_trades` | `int` | Number of sell-aggressed trades |
| `buy_volume` | `float` | Total buy volume |
| `sell_volume` | `float` | Total sell volume |
| `net_delta` | `float` | `buy_volume − sell_volume` |
| `dominant_side` | `str` | `'buyers'`, `'sellers'`, or `'neutral'` |

#### `TradeVelocity`

| Field | Type | Description |
|---|---|---|
| `trades_per_minute` | `float` | Trade rate over the window |
| `volume_per_minute` | `float` | Volume rate over the window |
| `avg_trade_size` | `float` | Mean trade size |
| `buy_trades_pct` | `float` | Buy % of all trades (0–100) |
| `sell_trades_pct` | `float` | Sell % of all trades (0–100) |

### Usage Examples

#### Basic Trade Capture

```python
from data.time_and_sales import TimeAndSalesService
from datetime import datetime, timezone

svc = TimeAndSalesService()

# Add individual trades
svc.add_trade('XAUUSD', price=2330.50, size=1.0, side='buy')
svc.add_trade('XAUUSD', price=2330.40, size=3.0, side='sell')
svc.add_trade('XAUUSD', price=2330.55, size=0.5, side='buy')

# Retrieve recent tape
recent = svc.get_recent_trades('XAUUSD', n=50)
for trade in recent:
    print(f"  {trade.timestamp.time()}  {trade.side:4s}  {trade.size} @ {trade.price}")
```

#### Aggressor Statistics

```python
# Statistics over the last 15 minutes (default)
stats = svc.get_aggressor_stats('XAUUSD', lookback_minutes=15.0)

if stats:
    print(f"Buy volume:  {stats.buy_volume:.2f} lots ({stats.buy_volume_pct:.1f}%)")
    print(f"Sell volume: {stats.sell_volume:.2f} lots ({stats.sell_volume_pct:.1f}%)")
    print(f"Net delta:   {stats.net_delta:+.2f}")
    print(f"Dominant:    {stats.dominant_side}")
```

#### Trade Velocity

```python
velocity = svc.get_trade_velocity('XAUUSD', window_minutes=5.0)

if velocity:
    print(f"Trades/min:  {velocity.trades_per_minute:.1f}")
    print(f"Volume/min:  {velocity.volume_per_minute:.2f}")
    print(f"Avg size:    {velocity.avg_trade_size:.2f}")
```

#### Large Trade Alerts

```python
# Set a per-symbol threshold (lots)
svc.set_large_trade_threshold('XAUUSD', threshold=100.0)

# Register an alert callback (applies to all symbols)
def on_large_trade(trade):
    print(f"🚨 Large trade: {trade.side.upper()} {trade.size} lots @ {trade.price}")
    print(f"   Notional: ${trade.notional_value:,.0f}")

svc.register_large_trade_callback(on_large_trade)

# Any trade ≥ 100 lots will now trigger the callback
svc.add_trade('XAUUSD', price=2330.00, size=150.0, side='buy')
```

#### Trade Histogram

```python
# Volume distribution across 20 price buckets
histogram = svc.get_trade_histogram('XAUUSD', num_buckets=20)

for bucket in histogram:
    bar = '█' * int(bucket.total_volume / 10)
    print(f"  {bucket.price_mid:8.2f}  {bar}  "
          f"buy={bucket.buy_pct:.0f}%  sell={bucket.sell_pct:.0f}%")
```

---

## InstitutionalFlowDetector

**Module:** `analysis/institutional_flow.py`

Identifies large institutional participants, iceberg orders, volume spikes, absorption
zones, and smart money directional bias from streaming trade data.

### Key Data Structures

#### `InstitutionalTrade`

| Field | Type | Description |
|---|---|---|
| `classification` | `str` | `'institutional'`, `'retail'`, or `'unknown'` |
| `confidence` | `float` | 0.0 – 1.0 classification confidence |
| `indicators` | `List[str]` | Human-readable reasons for classification |

#### `FlowSignal`

| Field | Type | Description |
|---|---|---|
| `signal_type` | `str` | `'absorption'`, `'iceberg'`, `'volume_spike'`, `'smart_money'`, `'momentum_divergence'` |
| `strength` | `str` | `'strong'`, `'moderate'`, or `'weak'` |
| `direction` | `str` | `'bullish'`, `'bearish'`, or `'neutral'` |
| `price_level` | `float` | Price at which the signal was detected |
| `volume` | `float` | Volume associated with the signal |

### Usage Examples

#### Detecting Large Orders

```python
from analysis.institutional_flow import InstitutionalFlowDetector

detector = InstitutionalFlowDetector(config={
    'min_institutional_size': 500.0,   # lots
    'volume_spike_threshold': 3.0,     # standard deviations
    'iceberg_window_seconds': 60,
    'max_trades_per_symbol': 50000,
})

# Feed trades
for price, size, side in [
    (2330.00, 50.0,   'buy'),
    (2330.00, 800.0,  'sell'),   # <- institutional size
    (2330.05, 35.0,   'buy'),
    (2330.00, 750.0,  'sell'),   # <- another large fill at same price (iceberg?)
    (2330.00, 600.0,  'sell'),
]:
    detector.add_trade('XAUUSD', price=price, size=size, side=side)

# Detect large institutional orders
large_orders = detector.detect_large_orders('XAUUSD')
for order in large_orders:
    print(f"  {order.side.upper()} {order.size} lots @ {order.price}"
          f"  confidence={order.confidence:.2f}")
    print(f"  Indicators: {', '.join(order.indicators)}")
```

#### Iceberg Detection

```python
# Icebergs show up as repeated fills at the same price level
signals = detector.detect_iceberg_orders('XAUUSD')

for sig in signals:
    print(f"🧊 Iceberg {sig.direction}: {sig.strength} at {sig.price_level}"
          f"  fills={sig.details.get('fill_count')}")
```

#### Volume Spike Detection

```python
spikes = detector.detect_volume_spikes('XAUUSD')

for spike in spikes:
    print(f"📈 Volume spike ({spike.strength}): z-score={spike.details.get('z_score'):.1f}"
          f"  @ {spike.price_level}")
```

#### Full Flow Analysis

```python
# Comprehensive report in one call
report = detector.analyze_flow('XAUUSD')

print(f"Smart money direction: {report['smart_money_direction']}")
print(f"Institutional volume:  {report['institutional_volume']:.2f}")
print(f"Retail volume:         {report['retail_volume']:.2f}")
print(f"Net institutional delta: {report['net_institutional_delta']:+.2f}")
print(f"Active signals: {len(report['signals'])}")

for signal in report['signals']:
    print(f"  [{signal['signal_type']:20s}] {signal['direction']:8s} {signal['strength']}")
```

#### Smart Money Direction

```python
direction = detector.get_smart_money_direction('XAUUSD')
# Returns: 'bullish', 'bearish', or 'neutral'
print(f"Smart money: {direction}")
```

---

## AdvancedOrderFlowAnalyzer

**Module:** `analysis/advanced_order_flow.py`

Provides institutional-grade microstructure metrics including real-time aggression scoring,
stacked imbalance detection, delta divergence, volume clusters, and an order flow oscillator.

### Key Data Structures

#### `AggressionMetrics`

| Field | Type | Description |
|---|---|---|
| `buy_aggression` | `float` | Aggressive buy percentage (0–100) |
| `sell_aggression` | `float` | Aggressive sell percentage (0–100) |
| `aggression_score` | `float` | Net score −100 (bearish) to +100 (bullish) |
| `dominant_side` | `str` | `'buyers'`, `'sellers'`, or `'neutral'` |
| `aggression_strength` | `str` | `'extreme'`, `'strong'`, `'moderate'`, `'weak'` |

#### `StackedImbalance`

| Field | Type | Description |
|---|---|---|
| `start_price` | `float` | Bottom of the stacked zone |
| `end_price` | `float` | Top of the stacked zone |
| `num_levels` | `int` | Number of consecutive imbalance levels |
| `direction` | `str` | `'bullish'` or `'bearish'` |
| `avg_imbalance` | `float` | Mean imbalance ratio across all levels |
| `strength` | `str` | `'extreme'`, `'strong'`, `'moderate'`, `'weak'` |

#### `DeltaDivergence`

| Field | Type | Description |
|---|---|---|
| `divergence_type` | `str` | `'bullish'`, `'bearish'`, `'hidden_bullish'`, `'hidden_bearish'` |
| `price_direction` | `str` | `'up'`, `'down'`, or `'flat'` |
| `delta_direction` | `str` | `'up'`, `'down'`, or `'flat'` |
| `strength` | `float` | 0–100 |
| `confidence` | `float` | 0–100 |

#### `PressureGauges`

| Field | Type | Description |
|---|---|---|
| `buy_pressure` | `float` | Buy pressure 0–100 |
| `sell_pressure` | `float` | Sell pressure 0–100 |
| `net_pressure` | `float` | Net −100 to +100 |
| `pressure_trend` | `str` | `'increasing'`, `'decreasing'`, `'stable'` |

### Usage Examples

#### Aggression Metrics

```python
from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

analyzer = AdvancedOrderFlowAnalyzer(config={
    'lookback_minutes': 60,
    'imbalance_threshold': 0.70,    # 70% imbalance to flag a level
    'stacked_imbalance_levels': 3,  # min consecutive levels for stacking
    'large_trade_percentile': 90,
})

# Feed trades
import random
from datetime import datetime, timezone

for _ in range(200):
    side = 'buy' if random.random() > 0.4 else 'sell'
    analyzer.add_trade('XAUUSD',
                       price=2330.0 + random.uniform(-2, 2),
                       size=random.uniform(0.5, 50.0),
                       side=side)

# Calculate aggression metrics
metrics = analyzer.calculate_aggression_metrics('XAUUSD')
if metrics:
    print(f"Buy aggression:  {metrics.buy_aggression:.1f}%")
    print(f"Sell aggression: {metrics.sell_aggression:.1f}%")
    print(f"Score:           {metrics.aggression_score:+.1f}")
    print(f"Strength:        {metrics.aggression_strength}")
```

#### Stacked Imbalances

```python
# Stacked imbalances are consecutive price levels biased the same direction
# — they act as strong support/resistance zones
imbalances = analyzer.detect_stacked_imbalances('XAUUSD')

for zone in imbalances:
    print(f"{'🟢' if zone.direction == 'bullish' else '🔴'} "
          f"{zone.direction.upper()} stack: "
          f"{zone.start_price:.2f} – {zone.end_price:.2f}  "
          f"levels={zone.num_levels}  strength={zone.strength}")
```

#### Delta Divergence

```python
# A bullish divergence: price makes new lows but delta does not → reversal signal
divergence = analyzer.detect_delta_divergence('XAUUSD')

if divergence:
    print(f"⚡ Divergence: {divergence.divergence_type}")
    print(f"   Price: {divergence.price_direction}  Delta: {divergence.delta_direction}")
    print(f"   Strength: {divergence.strength:.0f}/100  Confidence: {divergence.confidence:.0f}/100")
```

#### Order Flow Oscillator

```python
osc = analyzer.calculate_order_flow_oscillator('XAUUSD')

if osc:
    print(f"Oscillator: {osc.oscillator_value:+.1f}")
    print(f"Trend:      {osc.trend}")
    print(f"Momentum:   {osc.momentum}")
    print(f"Histogram:  {osc.histogram:+.2f}")
```

#### Pressure Gauges

```python
pressure = analyzer.get_pressure_gauges('XAUUSD')

if pressure:
    buy_bar  = '█' * int(pressure.buy_pressure  / 5)
    sell_bar = '█' * int(pressure.sell_pressure / 5)
    print(f"Buy  [{buy_bar:<20}] {pressure.buy_pressure:.1f}%")
    print(f"Sell [{sell_bar:<20}] {pressure.sell_pressure:.1f}%")
    print(f"Net:  {pressure.net_pressure:+.1f}  Trend: {pressure.pressure_trend}")
```

#### Full Advanced Analysis

```python
result = analyzer.analyze('XAUUSD')

if result:
    print(f"Overall bias:  {result.overall_bias}")
    print(f"Confidence:    {result.confidence:.0f}/100")
    print(f"Signals:       {result.signals}")
```

---

## StreamingService & MockDataSource

**Module:** `data/streaming.py`

The `StreamingService` is an event-driven pipeline for live or simulated market data.
`MockDataSource` drives it with geometric Brownian motion tick simulation — ideal for
testing and development without live broker connections.

### Key Data Structures

#### `TickData`

| Field | Type | Description |
|---|---|---|
| `bid` | `float` | Best bid price |
| `ask` | `float` | Best ask price |
| `spread` | `float` | `ask − bid` (computed) |
| `mid_price` | `float` | `(bid + ask) / 2` (computed) |
| `quality` | `DataQualityFlag` | `VALID`, `STALE`, `CROSSED`, `SPIKE` |

#### `TradeData`

| Field | Type | Description |
|---|---|---|
| `price` | `float` | Execution price |
| `size` | `float` | Trade size |
| `side` | `str` | `'buy'` or `'sell'` |

#### `StreamConfig`

| Parameter | Default | Description |
|---|---|---|
| `symbols` | `['XAUUSD']` | Symbols to subscribe |
| `reconnect_delay_s` | `5.0` | Seconds before reconnect attempt |
| `max_reconnect_attempts` | `10` | Max reconnect retries |
| `throttle_ms` | `100` | Min ms between tick callbacks |
| `tick_buffer_size` | `1000` | In-memory tick history per symbol |
| `spike_threshold_pct` | `2.0` | % change that flags a price spike |

### Usage Examples

#### MockDataSource — Standalone Test

```python
import time
from data.streaming import StreamingService, StreamConfig, MockDataSource

config = StreamConfig(symbols=['XAUUSD', 'EURUSD'])
service = StreamingService(config)

# Register callbacks
def on_tick(tick):
    print(f"[TICK]  {tick.symbol}  bid={tick.bid:.5f}  ask={tick.ask:.5f}"
          f"  spread={tick.spread:.5f}")

def on_trade(trade):
    icon = '🟢' if trade.side == 'buy' else '🔴'
    print(f"[TRADE] {icon} {trade.symbol}  {trade.size:.1f} @ {trade.price:.2f}")

service.on_tick(on_tick)
service.on_trade(on_trade)
service.subscribe('XAUUSD')
service.subscribe('EURUSD')

# Start mock data generation
mock = MockDataSource(
    service,
    symbols=['XAUUSD', 'EURUSD'],
    tick_interval_ms=500,  # tick every 500 ms
    volatility=0.0002,
    spread_pct=0.0003,
)

service.start_streaming()
mock.start()

print("Streaming for 10 seconds...")
time.sleep(10)

mock.stop()
service.stop_streaming()
```

#### Buffered Data Access

```python
# Access the in-memory tick buffer after streaming
ticks = service.get_tick_buffer('XAUUSD')
trades = service.get_trade_buffer('XAUUSD')

print(f"Buffered ticks:  {len(ticks)}")
print(f"Buffered trades: {len(trades)}")

if ticks:
    latest = ticks[-1]
    print(f"Last tick: {latest.symbol} @ {latest.mid_price:.5f}")
```

#### Connection Status

```python
status = service.get_connection_status()
print(f"State:   {status['state']}")
print(f"Symbols: {status['subscribed_symbols']}")
```

---

## OrderFlowDashboard

**Module:** `analysis/order_flow_dashboard.py`

The `OrderFlowDashboard` is the top-level aggregator. It fans out every `add_trade()` call
to all five underlying components and provides three consolidated query methods:
`get_complete_analysis()`, `get_summary()`, and `get_bias()`.

### Factory Function

```python
from analysis.order_flow_dashboard import create_dashboard

# Zero-config — sane defaults for all components
dashboard = create_dashboard()

# Or pass per-component configuration dicts
dashboard = create_dashboard(
    order_flow_config={'tick_size': 0.01, 'value_area_pct': 0.70},
    institutional_config={'min_institutional_size': 500.0},
    advanced_config={'lookback_minutes': 60, 'imbalance_threshold': 0.70},
)
```

### `get_complete_analysis(symbol)` — Response Structure

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "time_sales": {
    "aggressor_stats": { "buy_volume": 120.5, "sell_volume": 89.3, "net_delta": 31.2, "dominant_side": "buyers" },
    "velocity":        { "trades_per_minute": 4.2, "volume_per_minute": 8.1, "avg_trade_size": 1.9 }
  },
  "order_book": { "imbalance": 0.35, "spread": 0.30, "market_bias": "bullish" },
  "order_flow": {
    "delta": 31.2, "cumulative_delta": 105.6,
    "imbalance_ratio": 0.15, "dominant_side": "buyers",
    "buying_pressure": 57.4, "selling_pressure": 42.6,
    "order_flow_signal": "bullish"
  },
  "volume_profile": {
    "poc_price": 2330.50, "vah_price": 2332.10, "val_price": 2329.00,
    "total_volume": 210.2
  },
  "key_levels": {
    "support":    [{ "price": 2329.00, "type": "VAL" }],
    "resistance": [{ "price": 2332.10, "type": "VAH" }],
    "poc":        { "price": 2330.50, "type": "POC" }
  },
  "aggression": {
    "metrics":      { "aggression_score": 28.4, "dominant_side": "buyers" },
    "pressure":     { "buy_pressure": 57.0, "sell_pressure": 43.0, "net_pressure": 14.0 },
    "overall_bias": "bullish",
    "confidence":   72,
    "signals":      ["buy_pressure_building", "delta_trending_up"]
  },
  "institutional_flow": {
    "smart_money_direction": "bullish",
    "institutional_volume": 85.0,
    "retail_volume": 125.2,
    "signals": []
  },
  "large_orders": [
    { "price": 2330.00, "size": 500.0, "side": "buy", "classification": "institutional", "confidence": 0.92 }
  ]
}
```

### `get_summary(symbol)` — Response Structure

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "bias": "bullish",
  "dom_imbalance": 0.35,
  "buy_pressure": 57.4,
  "sell_pressure": 42.6,
  "smart_money_direction": "bullish",
  "cumulative_delta": 105.6,
  "spread": 0.30,
  "large_order_count": 1,
  "signals": ["buy_pressure_building"]
}
```

### Bias Scoring

`get_bias()` aggregates votes from four components using different weights:

| Component | Weight | Reason |
|---|---|---|
| DOM order book | 1 | Level 2 snapshot signal |
| Core order flow | 1 | Delta and imbalance |
| Advanced analyzer | 2 | Richer multi-metric signal |
| Institutional detector | 2 | Smart money confirmation |

The side with more total votes wins. Ties resolve to `'neutral'`.

---

## Integration Patterns

### Pattern 1: Feed from Live Streaming

```python
import time
from data.streaming import StreamingService, StreamConfig, MockDataSource
from analysis.order_flow_dashboard import create_dashboard

config = StreamConfig(symbols=['XAUUSD'])
service = StreamingService(config)
dashboard = create_dashboard()

def on_trade(trade):
    dashboard.add_trade(trade.symbol, trade.price, trade.size, trade.side,
                        timestamp=trade.timestamp)

service.on_trade(on_trade)
service.subscribe('XAUUSD')

mock = MockDataSource(service, symbols=['XAUUSD'])
service.start_streaming()
mock.start()

try:
    while True:
        summary = dashboard.get_summary('XAUUSD')
        print(f"\rBias: {summary['bias']:8s}  "
              f"Buy: {summary['buy_pressure'] or 0:.1f}%  "
              f"Delta: {summary['cumulative_delta'] or 0:+.1f}",
              end='', flush=True)
        time.sleep(2)
except KeyboardInterrupt:
    pass
finally:
    mock.stop()
    service.stop_streaming()
```

### Pattern 2: FastAPI Integration

```python
from fastapi import FastAPI
from analysis.order_flow_dashboard import create_dashboard, create_dashboard_router
from analysis.order_flow import create_order_flow_router, get_order_flow_analyzer
from analysis.institutional_flow import create_institutional_flow_router, get_institutional_flow_detector

app = FastAPI(title="HOPEFX Order Flow API")

# Create components
dashboard = create_dashboard()
analyzer = get_order_flow_analyzer()
detector = get_institutional_flow_detector()

# Mount routers
app.include_router(create_dashboard_router(dashboard))
app.include_router(create_order_flow_router(analyzer))
app.include_router(create_institutional_flow_router(detector))

# Endpoints available:
#   GET /api/dashboard/{symbol}/analysis
#   GET /api/dashboard/{symbol}/summary
#   GET /api/dashboard/{symbol}/bias
#   GET /api/orderflow/{symbol}/profile
#   GET /api/orderflow/{symbol}/analysis
#   GET /api/orderflow/{symbol}/footprint
#   GET /api/orderflow/{symbol}/levels
#   GET /api/institutional/{symbol}/flow
#   GET /api/institutional/{symbol}/large-orders
#   GET /api/institutional/{symbol}/signals
```

### Pattern 3: Alert-Driven Monitoring

```python
from data.time_and_sales import TimeAndSalesService
from analysis.institutional_flow import InstitutionalFlowDetector
import logging

logging.basicConfig(level=logging.INFO)

ts_svc = TimeAndSalesService()
detector = InstitutionalFlowDetector(config={'min_institutional_size': 200.0})

# Large trade alert
ts_svc.set_large_trade_threshold('XAUUSD', threshold=200.0)
ts_svc.register_large_trade_callback('XAUUSD', lambda t: logging.warning(
    "LARGE TRADE: %s %s lots @ %.2f  (notional $%.0f)",
    t.side.upper(), t.size, t.price, t.notional_value
))

# Periodically scan for institutional signals
def check_signals():
    signals = detector.get_flow_signals('XAUUSD')
    strong = [s for s in signals if s['strength'] == 'strong']
    if strong:
        for sig in strong:
            logging.warning("INSTITUTIONAL SIGNAL: %s %s @ %.2f",
                            sig['signal_type'], sig['direction'], sig['price_level'])
```

---

## Configuration Reference

### `TimeAndSalesService`

| Key | Type | Default | Description |
|---|---|---|---|
| `max_trades` | `int` | `10000` | Circular buffer size per symbol |
| `default_large_trade_threshold` | `float` | `100.0` | Default lot size for large-trade flag |

### `InstitutionalFlowDetector`

| Key | Type | Default | Description |
|---|---|---|---|
| `min_institutional_size` | `float` | `1000.0` | Minimum lot size for institutional classification |
| `volume_spike_threshold` | `float` | `3.0` | Sigma above mean to flag a volume spike |
| `iceberg_window_seconds` | `int` | `60` | Lookback window for iceberg fill grouping |
| `absorption_window_seconds` | `int` | `30` | Window for absorption detection |
| `max_trades_per_symbol` | `int` | `50000` | Maximum trades stored per symbol |

### `OrderFlowAnalyzer`

| Key | Type | Default | Description |
|---|---|---|---|
| `tick_size` | `float` | `0.01` | Minimum price increment for bucketing |
| `value_area_pct` | `float` | `0.70` | Fraction of volume in the value area (70%) |
| `max_trades` | `int` | `100000` | Maximum trades in the circular buffer |
| `imbalance_threshold` | `float` | `0.30` | Ratio to classify dominant side |

### `AdvancedOrderFlowAnalyzer`

| Key | Type | Default | Description |
|---|---|---|---|
| `lookback_minutes` | `float` | `60.0` | Default analysis window |
| `imbalance_threshold` | `float` | `0.70` | Fraction needed to flag imbalance at a level |
| `stacked_imbalance_levels` | `int` | `3` | Minimum consecutive levels to form a stack |
| `large_trade_percentile` | `float` | `90.0` | Percentile to classify a trade as large |

### `MockDataSource`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tick_interval_ms` | `int` | `250` | Milliseconds between generated ticks |
| `volatility` | `float` | `0.0002` | Per-tick log-return standard deviation |
| `spread_pct` | `float` | `0.0003` | Bid-ask spread as a fraction of mid price |

---

## Best Practices

### 1. Use `create_dashboard()` for New Projects

The factory function wires all five components together with sensible defaults. Unless you
need fine-grained control, always start with `create_dashboard()`.

### 2. Configure Symbol-Specific Thresholds

Large-order thresholds vary enormously by instrument. XAU/USD retail lots are typically
0.01–1.0; institutional orders start at 100+ lots. Calibrate `min_institutional_size` and
`set_large_trade_threshold` for each symbol.

```python
ts_svc.set_large_trade_threshold('XAUUSD', threshold=100.0)
ts_svc.set_large_trade_threshold('EURUSD', threshold=50.0)
```

### 3. Allow a Warm-Up Period

Most analytics (volume spikes, oscillator, divergence) require a history of trades before
producing reliable signals. Allow at least **5–15 minutes** of data to accumulate before
acting on outputs.

### 4. Trust the Bias Score, Not Individual Signals

The `get_bias()` method aggregates four independent sources. Individual signals from a
single component can be noisy. Use the dashboard bias for trading decisions and
individual signals for context.

### 5. Handle `None` Returns Gracefully

All query methods return `None` (or an empty list) when there is insufficient data.
Always check before using the result.

```python
stats = svc.get_aggressor_stats('XAUUSD')
if stats is None:
    return  # Not enough data yet

print(stats.dominant_side)
```

### 6. Keep `MockDataSource` in Tests

Use `MockDataSource` in all unit and integration tests to avoid broker dependencies.
It generates realistic geometric Brownian motion prices and produces the same data
types as live feeds.

### 7. Log at `DEBUG` Level in Production

All components emit structured log messages at `DEBUG` level. Set the logger to `DEBUG`
during development; use `INFO` or higher in production to reduce noise.

```python
import logging
logging.getLogger('analysis').setLevel(logging.DEBUG)
logging.getLogger('data').setLevel(logging.DEBUG)
```

### 8. Thread Safety

`TimeAndSalesService`, `InstitutionalFlowDetector`, and `AdvancedOrderFlowAnalyzer` are
all thread-safe — they use internal locks to protect shared state. You can safely call
`add_trade()` from multiple threads (e.g., a streaming callback thread + analysis thread).

---

## Support

- **API Reference:** [`docs/API_REFERENCE.md`](API_REFERENCE.md)
- **Full Example:** [`examples/order_flow_example.py`](../examples/order_flow_example.py)
- **General API Guide:** [`docs/API_GUIDE.md`](API_GUIDE.md)
- **Discord:** https://discord.gg/hopefx
- **Email:** api-support@hopefx.com

---

*This guide is part of the HOPEFX AI Trading Framework documentation.*
