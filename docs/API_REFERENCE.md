# HOPEFX Order Flow — API Reference

> **Version:** 1.0.0 | **Last Updated:** February 2026

Complete HTTP and WebSocket API reference for the HOPEFX Order Flow Analysis system.

---

## 📋 Table of Contents

1. [Base URLs & Authentication](#base-urls--authentication)
2. [WebSocket Protocol](#websocket-protocol)
3. [Time & Sales Endpoints](#time--sales-endpoints)
4. [Order Flow Endpoints](#order-flow-endpoints)
5. [Advanced Order Flow Endpoints](#advanced-order-flow-endpoints)
6. [Institutional Flow Endpoints](#institutional-flow-endpoints)
7. [Dashboard Endpoints](#dashboard-endpoints)
8. [Streaming Endpoints](#streaming-endpoints)
9. [Error Reference](#error-reference)
10. [Data Type Reference](#data-type-reference)

---

## Base URLs & Authentication

```
Development:  http://localhost:5000
Production:   https://api.hopefx.com/v1
```

All endpoints require the standard API key header:

```http
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json
```

For full authentication details see [`docs/API_GUIDE.md`](API_GUIDE.md).

---

## WebSocket Protocol

### Connection

```
ws://localhost:5000/ws/stream?symbols=XAUUSD,EURUSD&types=tick,trade,orderbook
```

**Query Parameters**

| Parameter | Required | Values | Description |
|---|---|---|---|
| `symbols` | Yes | Comma-separated symbols | Symbols to subscribe to |
| `types` | No | `tick`, `trade`, `orderbook` | Data types (default: all three) |

### Handshake

After connecting, the server sends a subscription confirmation:

```json
{
  "type": "subscribed",
  "symbols": ["XAUUSD", "EURUSD"],
  "data_types": ["tick", "trade", "orderbook"],
  "timestamp": "2026-02-15T10:30:00.000000+00:00"
}
```

### Tick Message

```json
{
  "type": "tick",
  "data": {
    "timestamp": "2026-02-15T10:30:00.123456+00:00",
    "symbol": "XAUUSD",
    "bid": 2330.20,
    "ask": 2330.50,
    "bid_size": 5.0,
    "ask_size": 3.5,
    "last_price": 2330.35,
    "spread": 0.30,
    "mid_price": 2330.35,
    "quality": "valid"
  }
}
```

### Trade Message

```json
{
  "type": "trade",
  "data": {
    "timestamp": "2026-02-15T10:30:00.234567+00:00",
    "symbol": "XAUUSD",
    "price": 2330.50,
    "size": 1.5,
    "side": "buy",
    "trade_id": "TRD-00001234"
  }
}
```

### Order Book Message

```json
{
  "type": "orderbook",
  "data": {
    "timestamp": "2026-02-15T10:30:00.345678+00:00",
    "symbol": "XAUUSD",
    "bids": [[2330.20, 5.0], [2330.10, 8.5], [2330.00, 12.0]],
    "asks": [[2330.50, 3.5], [2330.60, 6.0], [2330.70, 9.5]]
  }
}
```

### Keep-Alive / Ping

The server sends a ping every 30 seconds. Respond with the same payload to maintain the connection:

```json
{ "type": "ping", "timestamp": "2026-02-15T10:30:30.000000+00:00" }
```

Client response:
```json
{ "type": "pong" }
```

### Disconnection Codes

| Code | Meaning |
|---|---|
| `1000` | Normal closure |
| `1001` | Server shutting down |
| `1008` | Authentication failed |
| `1011` | Unexpected server error |

---

## Time & Sales Endpoints

Base path: `/api/timesales`

---

### `GET /api/timesales/{symbol}/recent`

Retrieve the most recent trades from the tape.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `symbol` | `string` | Trading symbol (e.g., `XAUUSD`) |

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `count` | `integer` | `50` | Number of trades to return (max 1000) |

**Example Request**

```bash
curl -X GET "http://localhost:5000/api/timesales/XAUUSD/recent?count=5" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Example Response** `200 OK`

```json
[
  {
    "timestamp": "2026-02-15T10:30:01.123456+00:00",
    "symbol": "XAUUSD",
    "price": 2330.50,
    "size": 1.5,
    "side": "buy",
    "trade_id": "TRD-00001234",
    "is_aggressive_buy": true,
    "is_aggressive_sell": false,
    "is_large_trade": false,
    "notional_value": 3495.75
  }
]
```

---

### `GET /api/timesales/{symbol}/aggressor-stats`

Buy vs sell aggressor statistics over a rolling window.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lookback_minutes` | `float` | `15.0` | Analysis window in minutes |

**Example Request**

```bash
curl "http://localhost:5000/api/timesales/XAUUSD/aggressor-stats?lookback_minutes=30" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "lookback_minutes": 30.0,
  "buy_trades": 145,
  "sell_trades": 98,
  "buy_volume": 312.50,
  "sell_volume": 198.75,
  "buy_trades_pct": 59.67,
  "sell_trades_pct": 40.33,
  "buy_volume_pct": 61.12,
  "sell_volume_pct": 38.88,
  "net_delta": 113.75,
  "dominant_side": "buyers",
  "calculated_at": "2026-02-15T10:30:00.000000+00:00"
}
```

---

### `GET /api/timesales/{symbol}/velocity`

Trade velocity and throughput metrics.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `window_minutes` | `float` | `5.0` | Rolling window in minutes |

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "window_minutes": 5.0,
  "trades_per_minute": 8.4,
  "volume_per_minute": 18.75,
  "avg_trade_size": 2.23,
  "buy_trades_pct": 58.3,
  "sell_trades_pct": 41.7,
  "total_trades": 42,
  "total_volume": 93.75,
  "calculated_at": "2026-02-15T10:30:00.000000+00:00"
}
```

---

### `GET /api/timesales/{symbol}/large-trades`

Trades that exceed the configured large-trade threshold.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `min_size` | `float` | symbol threshold | Override minimum size filter |
| `count` | `integer` | `20` | Maximum trades to return |

**Example Response** `200 OK`

```json
[
  {
    "timestamp": "2026-02-15T10:29:45.000000+00:00",
    "symbol": "XAUUSD",
    "price": 2330.00,
    "size": 500.0,
    "side": "buy",
    "is_large_trade": true,
    "notional_value": 1165000.0
  }
]
```

---

### `GET /api/timesales/{symbol}/histogram`

Price-level trade volume distribution.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `num_buckets` | `integer` | `20` | Number of price buckets |
| `lookback_minutes` | `float` | `60.0` | History window |

**Example Response** `200 OK`

```json
[
  {
    "price_low": 2328.00,
    "price_high": 2328.50,
    "price_mid": 2328.25,
    "trade_count": 12,
    "total_volume": 22.5,
    "buy_volume": 14.0,
    "sell_volume": 8.5,
    "buy_pct": 62.22,
    "sell_pct": 37.78
  }
]
```

---

## Order Flow Endpoints

Base path: `/api/orderflow`

---

### `GET /api/orderflow/{symbol}/profile`

Volume profile with Point of Control (POC), Value Area High/Low, and per-level delta.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `buckets` | `integer` | `50` | Number of price levels in the profile |

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "start_time": "2026-02-15T09:30:00.000000",
  "end_time": "2026-02-15T10:30:00.000000",
  "poc_price": 2330.50,
  "vah_price": 2332.10,
  "val_price": 2329.00,
  "total_volume": 1248.75,
  "total_buy_volume": 720.30,
  "total_sell_volume": 528.45,
  "total_delta": 191.85,
  "value_area": {
    "high": 2332.10,
    "low": 2329.00,
    "poc": 2330.50
  },
  "levels": [
    {
      "price": 2329.00,
      "total_volume": 45.2,
      "buy_volume": 30.1,
      "sell_volume": 15.1,
      "trade_count": 22,
      "delta": 15.0,
      "buy_pct": 66.59,
      "sell_pct": 33.41,
      "imbalance": 0.3319
    }
  ]
}
```

---

### `GET /api/orderflow/{symbol}/analysis`

Comprehensive order flow analysis including imbalance, dominant side, key nodes, and signal.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lookback_minutes` | `integer` | `60` | Analysis window |

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000",
  "total_volume": 1248.75,
  "buy_volume": 720.30,
  "sell_volume": 528.45,
  "delta": 191.85,
  "cumulative_delta": 450.20,
  "imbalance_ratio": 0.1536,
  "dominant_side": "buyers",
  "imbalance_strength": "moderate",
  "high_volume_nodes": [
    { "price": 2330.50, "volume": 185.3, "type": "HVN" }
  ],
  "low_volume_nodes": [
    { "price": 2331.25, "volume": 12.1, "type": "LVN" }
  ],
  "absorption_levels": [
    {
      "price": 2330.00,
      "total_volume": 320.5,
      "buy_volume": 85.2,
      "sell_volume": 235.3,
      "side": "buy_absorption"
    }
  ],
  "buying_pressure": 57.69,
  "selling_pressure": 42.31,
  "order_flow_signal": "bullish"
}
```

---

### `GET /api/orderflow/{symbol}/footprint`

Footprint chart showing buy/sell volume at each price level per time bar.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timeframe` | `string` | `5m` | Bar size: `1m`, `5m`, `15m`, `30m`, `1h`, `4h` |
| `bars` | `integer` | `20` | Number of bars to return |

**Example Response** `200 OK`

```json
[
  {
    "symbol": "XAUUSD",
    "timeframe": "5m",
    "timestamp": "2026-02-15T10:25:00.000000",
    "ohlc": {
      "open": 2329.80,
      "high": 2331.20,
      "low": 2329.50,
      "close": 2330.90
    },
    "total_volume": 98.5,
    "delta": 18.3,
    "cumulative_delta": 432.0,
    "levels": {
      "2330.00": { "buy_vol": 22.5, "sell_vol": 14.1, "delta": 8.4 },
      "2330.50": { "buy_vol": 18.3, "sell_vol": 25.1, "delta": -6.8 }
    }
  }
]
```

---

### `GET /api/orderflow/{symbol}/levels`

Key support and resistance levels derived from order flow.

**Example Response** `200 OK`

```json
{
  "support": [
    { "price": 2329.00, "volume": 0, "type": "VAL" },
    { "price": 2329.50, "volume": 112.3, "type": "HVN" }
  ],
  "resistance": [
    { "price": 2332.10, "volume": 0, "type": "VAH" },
    { "price": 2331.80, "volume": 98.7, "type": "HVN" }
  ],
  "poc": { "price": 2330.50, "type": "POC" }
}
```

---

### `GET /api/orderflow/{symbol}/delta`

Cumulative delta for a symbol.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "cumulative_delta": 450.20
}
```

---

### `GET /api/orderflow/stats`

Analyzer-level statistics across all tracked symbols.

**Example Response** `200 OK`

```json
{
  "symbols_tracked": ["XAUUSD", "EURUSD"],
  "total_trades": 15284,
  "trades_by_symbol": {
    "XAUUSD": 12450,
    "EURUSD": 2834
  },
  "cumulative_delta": {
    "XAUUSD": 450.20,
    "EURUSD": -32.15
  }
}
```

---

## Advanced Order Flow Endpoints

Base path: `/api/advanced`

---

### `GET /api/advanced/{symbol}/aggression`

Real-time aggression metrics showing aggressive buyer vs seller balance.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lookback_minutes` | `float` | `60.0` | Analysis window |

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "buy_aggression": 57.4,
  "sell_aggression": 42.6,
  "aggression_score": 14.8,
  "dominant_side": "buyers",
  "aggression_strength": "moderate"
}
```

---

### `GET /api/advanced/{symbol}/imbalances`

Per-price-level volume imbalances.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lookback_minutes` | `float` | `60.0` | Analysis window |
| `min_imbalance` | `float` | `0.70` | Minimum imbalance ratio to include |

**Example Response** `200 OK`

```json
[
  {
    "price": 2330.00,
    "buy_volume": 185.3,
    "sell_volume": 54.2,
    "imbalance_ratio": 3.42,
    "imbalance_pct": 54.8,
    "is_bid_imbalance": true,
    "is_ask_imbalance": false
  }
]
```

---

### `GET /api/advanced/{symbol}/stacked-imbalances`

Consecutive price levels with the same directional imbalance.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lookback_minutes` | `float` | `60.0` | Analysis window |
| `min_levels` | `integer` | `3` | Minimum consecutive levels |

**Example Response** `200 OK`

```json
[
  {
    "start_price": 2328.00,
    "end_price": 2329.50,
    "num_levels": 4,
    "direction": "bullish",
    "avg_imbalance": 2.85,
    "total_buy_volume": 312.5,
    "total_sell_volume": 109.6,
    "strength": "strong",
    "levels": []
  }
]
```

---

### `GET /api/advanced/{symbol}/divergence`

Delta divergence between price direction and cumulative delta direction.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "divergence_type": "bullish",
  "price_direction": "down",
  "delta_direction": "up",
  "price_change_pct": -0.12,
  "delta_change_pct": 8.5,
  "strength": 72.0,
  "confidence": 68.0
}
```

**Returns `null`** when no divergence is currently detected.

---

### `GET /api/advanced/{symbol}/clusters`

High-volume price clusters acting as support or resistance.

**Example Response** `200 OK`

```json
[
  {
    "price_level": 2330.50,
    "total_volume": 485.3,
    "buy_volume": 285.1,
    "sell_volume": 200.2,
    "trade_count": 210,
    "cluster_type": "resistance",
    "strength": 85.4
  }
]
```

---

### `GET /api/advanced/{symbol}/oscillator`

Order flow momentum oscillator based on cumulative delta.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "oscillator_value": 28.5,
  "fast_delta": 125.3,
  "slow_delta": 98.7,
  "signal_line": 22.1,
  "histogram": 6.4,
  "trend": "bullish",
  "momentum": "accelerating"
}
```

---

### `GET /api/advanced/{symbol}/pressure`

Buy and sell pressure gauges.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "buy_pressure": 57.4,
  "sell_pressure": 42.6,
  "net_pressure": 14.8,
  "pressure_trend": "increasing"
}
```

---

### `GET /api/advanced/{symbol}/analysis`

Full advanced analysis including all metrics, overall bias, confidence, and active signals.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "overall_bias": "bullish",
  "confidence": 72,
  "signals": [
    "buy_pressure_building",
    "delta_trending_up",
    "stacked_bid_imbalance_detected"
  ],
  "aggression": {
    "aggression_score": 14.8,
    "dominant_side": "buyers",
    "aggression_strength": "moderate"
  },
  "pressure_gauges": {
    "buy_pressure": 57.4,
    "sell_pressure": 42.6,
    "net_pressure": 14.8,
    "pressure_trend": "increasing"
  }
}
```

---

## Institutional Flow Endpoints

Base path: `/api/institutional`

---

### `GET /api/institutional/{symbol}/flow`

Comprehensive institutional flow analysis report.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "smart_money_direction": "bullish",
  "institutional_volume": 1850.0,
  "retail_volume": 3200.5,
  "net_institutional_delta": 450.0,
  "absorption_detected": true,
  "iceberg_detected": false,
  "momentum_divergence": {
    "detected": true,
    "direction": "bullish",
    "strength": "moderate"
  },
  "signals": [
    {
      "signal_type": "absorption",
      "strength": "strong",
      "direction": "bullish",
      "price_level": 2330.00,
      "volume": 320.5,
      "timestamp": "2026-02-15T10:28:00.000000+00:00",
      "details": {}
    }
  ]
}
```

---

### `GET /api/institutional/{symbol}/large-orders`

Recent institutional / large-order trades.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `min_size` | `float` | configured threshold | Minimum lot size filter |
| `limit` | `integer` | `50` | Maximum records to return |

**Example Response** `200 OK`

```json
[
  {
    "timestamp": "2026-02-15T10:28:30.000000+00:00",
    "symbol": "XAUUSD",
    "price": 2330.00,
    "size": 800.0,
    "side": "buy",
    "classification": "institutional",
    "confidence": 0.92,
    "indicators": [
      "size_exceeds_strong_institutional_threshold",
      "iceberg_pattern_detected"
    ]
  }
]
```

---

### `GET /api/institutional/{symbol}/signals`

Active institutional flow signals (absorption, iceberg, volume spike, smart money).

**Example Response** `200 OK`

```json
[
  {
    "symbol": "XAUUSD",
    "timestamp": "2026-02-15T10:28:00.000000+00:00",
    "signal_type": "volume_spike",
    "strength": "strong",
    "direction": "bullish",
    "price_level": 2330.20,
    "volume": 1250.5,
    "details": {
      "z_score": 4.2,
      "window_avg_volume": 210.3
    }
  }
]
```

---

### `GET /api/institutional/stats`

Detector-level statistics.

**Example Response** `200 OK`

```json
{
  "symbols_tracked": ["XAUUSD"],
  "total_trades": 8432,
  "institutional_trades": 142,
  "retail_trades": 8290,
  "signals_generated": 18
}
```

---

## Dashboard Endpoints

Base path: `/api/dashboard`

---

### `GET /api/dashboard/{symbol}/analysis`

Unified order flow analysis from all five components in a single call.

**Example Request**

```bash
curl "http://localhost:5000/api/dashboard/XAUUSD/analysis" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "time_sales": {
    "aggressor_stats": {
      "buy_volume": 720.3, "sell_volume": 528.4,
      "net_delta": 191.9, "dominant_side": "buyers"
    },
    "velocity": {
      "trades_per_minute": 8.4, "volume_per_minute": 18.75
    }
  },
  "order_book": {
    "imbalance": 0.35, "spread": 0.30, "market_bias": "bullish"
  },
  "order_flow": {
    "delta": 191.85, "cumulative_delta": 450.20,
    "buying_pressure": 57.69, "selling_pressure": 42.31,
    "order_flow_signal": "bullish"
  },
  "volume_profile": {
    "poc_price": 2330.50, "vah_price": 2332.10, "val_price": 2329.00
  },
  "key_levels": {
    "support": [{"price": 2329.00, "type": "VAL"}],
    "resistance": [{"price": 2332.10, "type": "VAH"}],
    "poc": {"price": 2330.50, "type": "POC"}
  },
  "aggression": {
    "overall_bias": "bullish", "confidence": 72,
    "signals": ["buy_pressure_building"]
  },
  "institutional_flow": {
    "smart_money_direction": "bullish",
    "institutional_volume": 1850.0
  },
  "large_orders": [
    {"price": 2330.00, "size": 800.0, "side": "buy", "confidence": 0.92}
  ]
}
```

---

### `GET /api/dashboard/{symbol}/summary`

Lightweight summary for dashboards and ticker widgets.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "timestamp": "2026-02-15T10:30:00.000000+00:00",
  "bias": "bullish",
  "dom_imbalance": 0.35,
  "buy_pressure": 57.69,
  "sell_pressure": 42.31,
  "smart_money_direction": "bullish",
  "cumulative_delta": 450.20,
  "spread": 0.30,
  "large_order_count": 3,
  "signals": ["buy_pressure_building", "delta_trending_up"]
}
```

---

### `GET /api/dashboard/{symbol}/bias`

Overall market bias derived from all configured components.

**Example Response** `200 OK`

```json
{
  "symbol": "XAUUSD",
  "bias": "bullish"
}
```

**Possible `bias` values**

| Value | Meaning |
|---|---|
| `"bullish"` | Aggregated buy-side votes exceed sell-side |
| `"bearish"` | Aggregated sell-side votes exceed buy-side |
| `"neutral"` | Tied or insufficient data |

---

## Streaming Endpoints

Base path: `/api/stream`

---

### `GET /api/stream/status`

Current streaming service connection status.

**Example Response** `200 OK`

```json
{
  "state": "connected",
  "subscribed_symbols": {
    "XAUUSD": ["tick", "trade", "orderbook"],
    "EURUSD": ["tick", "trade"]
  },
  "reconnect_attempts": 0,
  "last_message_at": "2026-02-15T10:29:59.800000+00:00"
}
```

---

### `WebSocket /ws/stream`

Real-time streaming endpoint. See [WebSocket Protocol](#websocket-protocol) above.

**Full URL Example**

```
ws://localhost:5000/ws/stream?symbols=XAUUSD&types=tick,trade
```

**Python Client Example**

```python
import asyncio
import websockets
import json

async def stream():
    uri = "ws://localhost:5000/ws/stream?symbols=XAUUSD&types=tick,trade"
    async with websockets.connect(uri) as ws:
        async for message in ws:
            event = json.loads(message)
            if event['type'] == 'tick':
                t = event['data']
                print(f"TICK  {t['symbol']}  {t['bid']:.2f}/{t['ask']:.2f}")
            elif event['type'] == 'trade':
                t = event['data']
                icon = '▲' if t['side'] == 'buy' else '▼'
                print(f"TRADE {icon} {t['size']} @ {t['price']:.2f}")

asyncio.run(stream())
```

---

## Error Reference

All error responses share the same envelope:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "No data available for XAUUSD",
    "details": {}
  }
}
```

### HTTP Status Codes

| HTTP Status | Code | Description |
|---|---|---|
| `400` | `INVALID_REQUEST` | Missing or invalid query parameter |
| `401` | `UNAUTHORIZED` | Missing or invalid API key |
| `403` | `FORBIDDEN` | Insufficient permissions |
| `404` | `NOT_FOUND` | Symbol not found or no data available yet |
| `429` | `RATE_LIMITED` | Request rate exceeded |
| `500` | `INTERNAL_ERROR` | Unexpected server error — see server logs |

### Common 404 Causes

A `404` from order flow endpoints means no trades have been received for the requested
symbol yet. Allow a warm-up period (typically 5–15 minutes of data) before analysis
endpoints return useful results.

---

## Data Type Reference

### `DataQualityFlag` Values

| Value | Meaning |
|---|---|
| `"valid"` | Data passed all quality checks |
| `"stale"` | Timestamp older than configured staleness threshold |
| `"crossed"` | `bid >= ask` — market data error |
| `"spike"` | Price change exceeds spike threshold |
| `"missing_field"` | Required field absent from source message |

### `ConnectionState` Values

| Value | Meaning |
|---|---|
| `"disconnected"` | No active connection |
| `"connecting"` | Connection in progress |
| `"connected"` | Fully connected and streaming |
| `"reconnecting"` | Attempting to re-establish connection |
| `"stopped"` | Service has been permanently stopped |

### Signal Types

| `signal_type` | Source | Description |
|---|---|---|
| `absorption` | `InstitutionalFlowDetector` | High volume with low price movement |
| `iceberg` | `InstitutionalFlowDetector` | Repeated fills at the same price level |
| `volume_spike` | `InstitutionalFlowDetector` | Volume spike above rolling mean + N sigma |
| `smart_money` | `InstitutionalFlowDetector` | Net institutional directional bias |
| `momentum_divergence` | `InstitutionalFlowDetector` | Price/delta divergence |

### Timeframe Codes

| Code | Duration |
|---|---|
| `1m` | 1 minute |
| `5m` | 5 minutes |
| `15m` | 15 minutes |
| `30m` | 30 minutes |
| `1h` | 1 hour |
| `4h` | 4 hours |
| `1d` | 1 day |

---

## Support

- **Order Flow Guide:** [`docs/ORDER_FLOW_GUIDE.md`](ORDER_FLOW_GUIDE.md)
- **General API Guide:** [`docs/API_GUIDE.md`](API_GUIDE.md)
- **Working Example:** [`examples/order_flow_example.py`](../examples/order_flow_example.py)
- **Discord:** https://discord.gg/hopefx
- **Email:** api-support@hopefx.com

---

*This API reference is part of the HOPEFX AI Trading Framework documentation.*
