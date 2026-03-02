"""
Order Flow Analysis — Complete Working Example

Demonstrates all major components of the HOPEFX order flow analysis system:
  - TimeAndSalesService  : live trade tape, aggressor stats, velocity
  - InstitutionalFlowDetector : large-order and smart-money detection
  - AdvancedOrderFlowAnalyzer : aggression, stacked imbalances, oscillator
  - StreamingService + MockDataSource : simulated live data pipeline
  - OrderFlowDashboard : unified multi-component analysis

Run standalone — no broker connection required:
    python examples/order_flow_example.py

Exit cleanly with Ctrl-C.
"""

import logging
import sys
import os
import time
import threading

# ---------------------------------------------------------------------------
# Path setup – makes the example runnable from the repository root or from
# the examples/ subdirectory without needing an installed package.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.streaming import StreamingService, StreamConfig, MockDataSource
from data.time_and_sales import TimeAndSalesService
from analysis.order_flow import OrderFlowAnalyzer
from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer
from analysis.institutional_flow import InstitutionalFlowDetector
from analysis.order_flow_dashboard import OrderFlowDashboard, create_dashboard

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,       # Suppress INFO noise from the framework
    format="%(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("order_flow_example")

# ============================================================================
# SECTION 1: TimeAndSalesService
# ============================================================================


def demo_time_and_sales() -> None:
    """
    Demonstrate the TimeAndSalesService: trade tape, aggressor stats,
    large-trade alerts, and trade velocity.
    """
    print("\n" + "=" * 65)
    print("  SECTION 1 — TimeAndSalesService")
    print("=" * 65)

    svc = TimeAndSalesService(config={"max_trades": 5000})

    # ------------------------------------------------------------------
    # 1a. Large-trade alert callback
    # ------------------------------------------------------------------
    large_trade_alerts = []

    def on_large_trade(trade):
        large_trade_alerts.append(trade)
        print(
            f"  🚨 LARGE TRADE: {trade.side.upper():4s}  "
            f"{trade.size:>7.1f} lots  @ {trade.price:.2f}  "
            f"(notional ${trade.notional_value:>12,.0f})"
        )

    svc.set_large_trade_threshold("XAUUSD", threshold=100.0)
    svc.register_large_trade_callback(on_large_trade)

    # ------------------------------------------------------------------
    # 1b. Feed simulated trades
    # ------------------------------------------------------------------
    import random

    random.seed(42)

    trade_data = [
        (2330.50, 1.5, "buy"),
        (2330.40, 3.0, "sell"),
        (2330.55, 0.8, "buy"),
        (2330.45, 2.2, "sell"),
        (2330.60, 5.0, "buy"),
        (2330.30, 150.0, "sell"),   # <- large trade, will trigger alert
        (2330.70, 0.5, "buy"),
        (2330.25, 200.0, "buy"),    # <- large trade, will trigger alert
        (2330.65, 1.0, "sell"),
        (2330.80, 2.5, "buy"),
    ]

    print("\n  Feeding 10 trades (2 large):")
    for price, size, side in trade_data:
        svc.add_trade("XAUUSD", price=price, size=size, side=side)

    # ------------------------------------------------------------------
    # 1c. Aggressor statistics
    # ------------------------------------------------------------------
    stats = svc.get_aggressor_stats("XAUUSD", lookback_minutes=60.0)
    if stats:
        print(f"\n  Aggressor Statistics (last 60 min):")
        print(f"    Buy  trades : {stats.buy_trades:>4d}  |  "
              f"volume = {stats.buy_volume:>8.2f} lots  ({stats.buy_volume_pct:.1f}%)")
        print(f"    Sell trades : {stats.sell_trades:>4d}  |  "
              f"volume = {stats.sell_volume:>8.2f} lots  ({stats.sell_volume_pct:.1f}%)")
        print(f"    Net delta   : {stats.net_delta:>+8.2f}")
        print(f"    Dominant    : {stats.dominant_side}")

    # ------------------------------------------------------------------
    # 1d. Trade velocity
    # ------------------------------------------------------------------
    velocity = svc.get_trade_velocity("XAUUSD", window_minutes=60.0)
    if velocity:
        print(f"\n  Trade Velocity (60-min window):")
        print(f"    Trades/min  : {velocity.trades_per_minute:.2f}")
        print(f"    Volume/min  : {velocity.volume_per_minute:.2f} lots")
        print(f"    Avg size    : {velocity.avg_trade_size:.2f} lots")

    # ------------------------------------------------------------------
    # 1e. Recent tape
    # ------------------------------------------------------------------
    recent = svc.get_recent_trades("XAUUSD", n=5)
    print(f"\n  Last {len(recent)} trades on the tape:")
    for t in recent:
        flag = " ← LARGE" if t.is_large_trade else ""
        icon = "▲" if t.is_buy else "▼"
        print(f"    {icon}  {t.size:>7.1f} lots  @ {t.price:.2f}{flag}")

    print(f"\n  Large-trade alerts fired: {len(large_trade_alerts)}")


# ============================================================================
# SECTION 2: InstitutionalFlowDetector
# ============================================================================


def demo_institutional_flow() -> None:
    """
    Demonstrate institutional flow detection: large orders, iceberg signals,
    volume spikes, and smart money direction.
    """
    print("\n" + "=" * 65)
    print("  SECTION 2 — InstitutionalFlowDetector")
    print("=" * 65)

    detector = InstitutionalFlowDetector(
        config={
            "min_institutional_size": 200.0,   # lots
            "volume_spike_threshold": 2.5,      # standard deviations
            "iceberg_window_seconds": 120,
            "max_trades_per_symbol": 50_000,
        }
    )

    # ------------------------------------------------------------------
    # 2a. Build a realistic trade history with institutional activity
    # ------------------------------------------------------------------
    import random

    random.seed(7)

    # 80 retail-sized trades
    for _ in range(80):
        side = "buy" if random.random() > 0.45 else "sell"
        detector.add_trade(
            "XAUUSD",
            price=2330.0 + random.uniform(-3, 3),
            size=random.uniform(0.5, 20.0),
            side=side,
        )

    # Simulated iceberg: 5 large fills at the same price
    for _ in range(5):
        detector.add_trade("XAUUSD", price=2330.00, size=250.0, side="sell")

    # A genuine large block trade
    detector.add_trade("XAUUSD", price=2329.80, size=1500.0, side="buy")

    # ------------------------------------------------------------------
    # 2b. Detect large orders
    # ------------------------------------------------------------------
    large_orders = detector.detect_large_orders("XAUUSD")
    print(f"\n  Detected {len(large_orders)} institutional / large order(s):")
    for order in large_orders:
        print(
            f"    {order.side.upper():4s}  {order.size:>7.1f} lots  "
            f"@ {order.price:.2f}  conf={order.confidence:.2f}"
        )
        if order.indicators:
            print(f"         → {', '.join(order.indicators)}")

    # ------------------------------------------------------------------
    # 2c. Iceberg detection
    # ------------------------------------------------------------------
    iceberg_signals = detector.detect_iceberg_orders("XAUUSD")
    print(f"\n  Iceberg signals detected: {len(iceberg_signals)}")
    for sig in iceberg_signals:
        print(
            f"    🧊 {sig.direction:8s}  strength={sig.strength:8s}  "
            f"@ {sig.price_level:.2f}  fills={sig.details.get('fill_count', '?')}"
        )

    # ------------------------------------------------------------------
    # 2d. Smart money direction
    # ------------------------------------------------------------------
    direction = detector.get_smart_money_direction("XAUUSD")
    print(f"\n  Smart money direction : {direction}")

    # ------------------------------------------------------------------
    # 2e. Full flow report
    # ------------------------------------------------------------------
    report = detector.analyze_flow("XAUUSD")
    print(f"\n  Full flow report:")
    print(f"    Institutional volume : {report.get('institutional_volume', 0):.2f}")
    print(f"    Retail volume        : {report.get('retail_volume', 0):.2f}")
    print(f"    Net inst. delta      : {report.get('net_institutional_delta', 0):+.2f}")
    print(f"    Active signals       : {len(report.get('signals', []))}")


# ============================================================================
# SECTION 3: AdvancedOrderFlowAnalyzer
# ============================================================================


def demo_advanced_order_flow() -> None:
    """
    Demonstrate the AdvancedOrderFlowAnalyzer: aggression metrics, stacked
    imbalances, delta divergence, oscillator, and pressure gauges.
    """
    print("\n" + "=" * 65)
    print("  SECTION 3 — AdvancedOrderFlowAnalyzer")
    print("=" * 65)

    analyzer = AdvancedOrderFlowAnalyzer(
        config={
            "lookback_minutes": 60.0,
            "imbalance_threshold": 0.70,
            "stacked_imbalance_levels": 3,
            "large_trade_percentile": 90.0,
        }
    )

    # ------------------------------------------------------------------
    # Build trade history with a bullish bias
    # ------------------------------------------------------------------
    import random

    random.seed(99)
    base_price = 2330.0

    for i in range(300):
        # Drift the price up slowly
        base_price += random.normalvariate(0.005, 0.5)
        side = "buy" if random.random() > 0.38 else "sell"   # 62% buyers
        analyzer.add_trade(
            "XAUUSD",
            price=base_price,
            size=random.uniform(0.5, 40.0),
            side=side,
        )

    # ------------------------------------------------------------------
    # 3a. Aggression metrics
    # ------------------------------------------------------------------
    metrics = analyzer.calculate_aggression_metrics("XAUUSD")
    if metrics:
        print(f"\n  Aggression Metrics:")
        print(f"    Buy aggression  : {metrics.buy_aggression:.1f}%")
        print(f"    Sell aggression : {metrics.sell_aggression:.1f}%")
        print(f"    Score (−100/+100): {metrics.aggression_score:+.1f}")
        print(f"    Dominant side   : {metrics.dominant_side}")
        print(f"    Strength        : {metrics.aggression_strength}")

    # ------------------------------------------------------------------
    # 3b. Stacked imbalances
    # ------------------------------------------------------------------
    stacks = analyzer.detect_stacked_imbalances("XAUUSD")
    print(f"\n  Stacked Imbalance Zones: {len(stacks)}")
    for zone in stacks[:3]:
        icon = "🟢" if zone.direction == "bullish" else "🔴"
        print(
            f"    {icon} {zone.direction:8s}  "
            f"{zone.start_price:.2f} – {zone.end_price:.2f}  "
            f"levels={zone.num_levels}  strength={zone.strength}"
        )

    # ------------------------------------------------------------------
    # 3c. Delta divergence
    # ------------------------------------------------------------------
    divergence = analyzer.detect_delta_divergence("XAUUSD")
    if divergence:
        print(f"\n  Delta Divergence Detected:")
        print(f"    Type       : {divergence.divergence_type}")
        print(f"    Price dir  : {divergence.price_direction}")
        print(f"    Delta dir  : {divergence.delta_direction}")
        print(f"    Strength   : {divergence.strength:.0f}/100")
        print(f"    Confidence : {divergence.confidence:.0f}/100")
    else:
        print(f"\n  Delta Divergence : none detected")

    # ------------------------------------------------------------------
    # 3d. Oscillator
    # ------------------------------------------------------------------
    osc = analyzer.calculate_order_flow_oscillator("XAUUSD")
    if osc:
        print(f"\n  Order Flow Oscillator:")
        print(f"    Value     : {osc.oscillator_value:+.1f}")
        print(f"    Trend     : {osc.trend}")
        print(f"    Momentum  : {osc.momentum}")
        print(f"    Histogram : {osc.histogram:+.2f}")

    # ------------------------------------------------------------------
    # 3e. Pressure gauges
    # ------------------------------------------------------------------
    pressure = analyzer.get_pressure_gauges("XAUUSD")
    if pressure:
        buy_bar  = "█" * int(pressure.buy_pressure  / 5)
        sell_bar = "█" * int(pressure.sell_pressure / 5)
        print(f"\n  Pressure Gauges:")
        print(f"    Buy  [{buy_bar:<20}] {pressure.buy_pressure:.1f}%")
        print(f"    Sell [{sell_bar:<20}] {pressure.sell_pressure:.1f}%")
        print(f"    Net  : {pressure.net_pressure:+.1f}  ({pressure.pressure_trend})")

    # ------------------------------------------------------------------
    # 3f. Full advanced result
    # ------------------------------------------------------------------
    result = analyzer.analyze("XAUUSD")
    if result:
        print(f"\n  Overall Bias  : {result.overall_bias}")
        print(f"  Confidence    : {result.confidence:.0f}/100")
        if result.signals:
            print(f"  Active signals: {', '.join(result.signals)}")


# ============================================================================
# SECTION 4: StreamingService + MockDataSource
# ============================================================================


def demo_streaming(duration_seconds: float = 8.0) -> None:
    """
    Demonstrate real-time data streaming using MockDataSource (no broker needed).

    Subscribes to XAUUSD ticks and trades, prints a live summary line every
    second, and stops cleanly after *duration_seconds*.
    """
    print("\n" + "=" * 65)
    print("  SECTION 4 — StreamingService + MockDataSource")
    print(f"           (running for {duration_seconds:.0f} seconds)")
    print("=" * 65)

    config = StreamConfig(symbols=["XAUUSD"])
    service = StreamingService(config)

    tick_count = [0]
    trade_count = [0]
    last_bid = [None]
    last_ask = [None]

    def on_tick(tick):
        tick_count[0] += 1
        last_bid[0] = tick.bid
        last_ask[0] = tick.ask

    def on_trade(trade):
        trade_count[0] += 1

    service.on_tick(on_tick)
    service.on_trade(on_trade)
    service.subscribe("XAUUSD")

    mock = MockDataSource(
        service,
        symbols=["XAUUSD"],
        tick_interval_ms=200,    # 5 ticks / second
        volatility=0.0002,
        spread_pct=0.0003,
    )

    service.start_streaming()
    mock.start()

    print("\n  Streaming XAUUSD (press Ctrl-C to stop early):\n")
    deadline = time.monotonic() + duration_seconds

    try:
        while time.monotonic() < deadline:
            bid = last_bid[0]
            ask = last_ask[0]
            if bid and ask:
                spread = ask - bid
                print(
                    f"\r  ticks={tick_count[0]:>4d}  "
                    f"trades={trade_count[0]:>3d}  "
                    f"bid={bid:.2f}  ask={ask:.2f}  "
                    f"spread={spread:.3f}     ",
                    end="",
                    flush=True,
                )
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    print()   # newline after the \r line

    mock.stop()
    service.stop_streaming()

    # Show buffered data
    ticks  = service.get_tick_buffer("XAUUSD")
    trades = service.get_trade_buffer("XAUUSD")
    print(f"\n  Buffered:  {len(ticks)} ticks  |  {len(trades)} trades")

    status = service.get_connection_status()
    print(f"  Final state: {status.get('state', 'unknown')}")


# ============================================================================
# SECTION 5: OrderFlowDashboard — end-to-end integration
# ============================================================================


def demo_dashboard(duration_seconds: float = 15.0) -> None:
    """
    End-to-end demonstration wiring MockDataSource → OrderFlowDashboard.

    All five components (TimeAndSales, OrderFlow, Advanced, Institutional,
    DepthOfMarket) receive every trade automatically.  After the warm-up
    window, the example prints:
      - get_summary()
      - get_bias()
      - selected fields from get_complete_analysis()
    """
    print("\n" + "=" * 65)
    print("  SECTION 5 — OrderFlowDashboard (full integration)")
    print(f"           ({duration_seconds:.0f}s warm-up with MockDataSource)")
    print("=" * 65)

    # ------------------------------------------------------------------
    # 5a. Create dashboard with custom per-component configuration
    # ------------------------------------------------------------------
    dashboard = create_dashboard(
        order_flow_config={
            "tick_size": 0.01,
            "value_area_pct": 0.70,
            "imbalance_threshold": 0.30,
        },
        institutional_config={
            "min_institutional_size": 50.0,   # Low threshold for demo
        },
        advanced_config={
            "lookback_minutes": 60.0,
            "imbalance_threshold": 0.60,
        },
    )

    # ------------------------------------------------------------------
    # 5b. Set up streaming and wire trades into the dashboard
    # ------------------------------------------------------------------
    config = StreamConfig(symbols=["XAUUSD"])
    service = StreamingService(config)

    def on_trade(trade):
        dashboard.add_trade(
            trade.symbol,
            trade.price,
            trade.size,
            trade.side,
            timestamp=trade.timestamp,
        )

    service.on_trade(on_trade)
    service.subscribe("XAUUSD")

    mock = MockDataSource(
        service,
        symbols=["XAUUSD"],
        tick_interval_ms=150,
        volatility=0.0002,
        spread_pct=0.0003,
    )

    # ------------------------------------------------------------------
    # 5c. Configure a large-trade alert on the dashboard's TimeAndSales
    #     component (accessible via dashboard._ts)
    # ------------------------------------------------------------------
    large_trade_log = []

    if dashboard._ts is not None:
        dashboard._ts.set_large_trade_threshold("XAUUSD", threshold=50.0)
        dashboard._ts.register_large_trade_callback(
            lambda t: large_trade_log.append(t),
        )

    service.start_streaming()
    mock.start()

    print(f"\n  Collecting data for {duration_seconds:.0f} seconds…", flush=True)

    # Show a live counter while collecting data
    deadline = time.monotonic() + duration_seconds
    trade_count = [0]

    def count_trades(trade):
        trade_count[0] += 1

    service.on_trade(count_trades)

    try:
        while time.monotonic() < deadline:
            remaining = max(0, deadline - time.monotonic())
            print(
                f"\r  {trade_count[0]:>4d} trades received  "
                f"({remaining:.0f}s remaining)   ",
                end="",
                flush=True,
            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    print()
    mock.stop()
    service.stop_streaming()

    # ------------------------------------------------------------------
    # 5d. Summary
    # ------------------------------------------------------------------
    summary = dashboard.get_summary("XAUUSD")

    print(f"\n  ── Dashboard Summary ──────────────────────────────────")
    print(f"  Bias                  : {summary.get('bias', 'unknown')}")
    print(f"  DOM imbalance         : {summary.get('dom_imbalance', 'n/a')}")
    buy_p = summary.get("buy_pressure")
    sell_p = summary.get("sell_pressure")
    if buy_p is not None:
        print(f"  Buy pressure          : {buy_p:.1f}%")
        print(f"  Sell pressure         : {sell_p:.1f}%")
    delta = summary.get("cumulative_delta")
    if delta is not None:
        print(f"  Cumulative delta      : {delta:+.2f}")
    print(f"  Smart money direction : {summary.get('smart_money_direction', 'n/a')}")
    print(f"  Large order count     : {summary.get('large_order_count', 0)}")
    signals = summary.get("signals") or []
    if signals:
        print(f"  Active signals        : {', '.join(signals)}")
    print(f"  Large trade alerts    : {len(large_trade_log)}")

    # ------------------------------------------------------------------
    # 5e. Bias
    # ------------------------------------------------------------------
    bias = dashboard.get_bias("XAUUSD")
    print(f"\n  Overall bias: {bias.upper()}")

    # ------------------------------------------------------------------
    # 5f. Key excerpts from get_complete_analysis()
    # ------------------------------------------------------------------
    analysis = dashboard.get_complete_analysis("XAUUSD")

    print(f"\n  ── Complete Analysis Excerpt ──────────────────────────")

    # Order flow
    of = analysis.get("order_flow")
    if of:
        print(f"  Order flow signal     : {of.get('order_flow_signal')}")
        print(f"  Imbalance (ratio)     : {of.get('imbalance_ratio'):+.4f}")

    # Volume profile
    vp = analysis.get("volume_profile")
    if vp:
        print(f"  POC                   : {vp.get('poc_price'):.2f}")
        print(f"  Value Area            : "
              f"{vp.get('val_price'):.2f} – {vp.get('vah_price'):.2f}")

    # Advanced
    adv = analysis.get("aggression")
    if adv:
        print(f"  Advanced bias         : {adv.get('overall_bias')}")
        print(f"  Confidence            : {adv.get('confidence')}/100")

    # Institutional
    inst = analysis.get("institutional_flow")
    if inst:
        print(f"  Institutional dir     : {inst.get('smart_money_direction')}")

    print(f"\n  ── Key Support / Resistance Levels ────────────────────")
    levels = analysis.get("key_levels") or {}
    poc = levels.get("poc")
    if poc:
        print(f"  POC                   : {poc.get('price', '?'):.2f}")
    for lvl in (levels.get("resistance") or [])[:2]:
        print(f"  Resistance            : {lvl.get('price', '?'):.2f}  ({lvl.get('type')})")
    for lvl in (levels.get("support") or [])[:2]:
        print(f"  Support               : {lvl.get('price', '?'):.2f}  ({lvl.get('type')})")


# ============================================================================
# SECTION 6: Real-Time Monitoring Loop Pattern
# ============================================================================


def demo_monitoring_loop(duration_seconds: float = 10.0) -> None:
    """
    Show the canonical pattern for a production monitoring loop:
    stream → dashboard → periodic bias/summary print.
    """
    print("\n" + "=" * 65)
    print("  SECTION 6 — Real-Time Monitoring Loop")
    print(f"           ({duration_seconds:.0f}s live loop)")
    print("=" * 65)

    dashboard = create_dashboard()
    config = StreamConfig(symbols=["XAUUSD"])
    service = StreamingService(config)

    def on_trade(trade):
        dashboard.add_trade(
            trade.symbol, trade.price, trade.size, trade.side,
            timestamp=trade.timestamp,
        )

    service.on_trade(on_trade)
    service.subscribe("XAUUSD")

    mock = MockDataSource(service, symbols=["XAUUSD"], tick_interval_ms=100)
    service.start_streaming()
    mock.start()

    print("\n  time         bias      buy%   sell%   Δcum")
    print("  " + "-" * 52)

    stop_event = threading.Event()

    def monitor():
        while not stop_event.is_set():
            summary = dashboard.get_summary("XAUUSD")
            ts_str = summary["timestamp"][11:19]   # HH:MM:SS
            bias = summary.get("bias", "?")
            buy_p = summary.get("buy_pressure") or 0.0
            sell_p = summary.get("sell_pressure") or 0.0
            delta = summary.get("cumulative_delta") or 0.0
            bias_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(bias, " ")
            print(
                f"  {ts_str}  {bias_icon} {bias:8s}  "
                f"{buy_p:5.1f}%  {sell_p:5.1f}%  {delta:+8.2f}"
            )
            stop_event.wait(timeout=2.0)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()

    try:
        time.sleep(duration_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        monitor_thread.join(timeout=3)
        mock.stop()
        service.stop_streaming()

    print("\n  Monitoring loop complete.")


# ============================================================================
# Main entry point
# ============================================================================


def main() -> None:
    """Run all demonstration sections sequentially."""

    print()
    print("╔" + "═" * 63 + "╗")
    print("║  HOPEFX  —  Order Flow Analysis  —  Complete Example     ║")
    print("╚" + "═" * 63 + "╝")

    try:
        demo_time_and_sales()
        demo_institutional_flow()
        demo_advanced_order_flow()
        demo_streaming(duration_seconds=8)
        demo_dashboard(duration_seconds=15)
        demo_monitoring_loop(duration_seconds=10)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")

    print("\n" + "=" * 65)
    print("  All sections complete.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
