"""
Order Flow Dashboard

Unified dashboard integrating all order flow analysis components:
- Time & Sales (trade tape and aggressor statistics)
- Depth of Market (Level 2 order book)
- Core Order Flow Analysis (volume profile, delta, key levels)
- Advanced Order Flow (aggression metrics, stacked imbalances, pressure gauges)
- Institutional Flow Detection (large orders, iceberg signals, smart money)

Typical usage::

    from analysis.order_flow_dashboard import create_dashboard

    dashboard = create_dashboard()
    dashboard.add_trade('XAUUSD', 1950.00, 1.0, 'buy')

    analysis = dashboard.get_complete_analysis('XAUUSD')
    summary  = dashboard.get_summary('XAUUSD')
    bias     = dashboard.get_bias('XAUUSD')
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer
from analysis.institutional_flow import InstitutionalFlowDetector
from analysis.order_flow import OrderFlowAnalyzer
from data.depth_of_market import DepthOfMarketService
from data.time_and_sales import TimeAndSalesService

logger = logging.getLogger(__name__)


class OrderFlowDashboard:
    """
    Unified dashboard that aggregates all order flow analysis components.

    Each service is optional; missing components are gracefully skipped
    during analysis and their corresponding keys are returned as ``None``.

    Attributes:
        _ts: TimeAndSalesService instance (optional).
        _dom: DepthOfMarketService instance (optional).
        _ofa: OrderFlowAnalyzer instance (optional).
        _adv: AdvancedOrderFlowAnalyzer instance (optional).
        _inst: InstitutionalFlowDetector instance (optional).

    Note:
        :class:`~analysis.order_flow.OrderFlowAnalyzer` stores trades with
        naive UTC datetimes (``datetime.utcnow()``), while all other components
        use timezone-aware UTC datetimes (``datetime.now(timezone.utc)``).
        :meth:`add_trade` automatically strips ``tzinfo`` before forwarding to
        ``OrderFlowAnalyzer`` to prevent ``TypeError`` on timestamp comparisons.
        This is an implementation detail of the underlying component and does not
        affect the correctness of the analysis.

    Example:
        >>> dashboard = create_dashboard()
        >>> dashboard.add_trade('XAUUSD', 1950.00, 1.0, 'buy')
        >>> result = dashboard.get_complete_analysis('XAUUSD')
    """

    def __init__(
        self,
        time_and_sales: Optional[TimeAndSalesService] = None,
        dom_service: Optional[DepthOfMarketService] = None,
        order_flow_analyzer: Optional[OrderFlowAnalyzer] = None,
        advanced_analyzer: Optional[AdvancedOrderFlowAnalyzer] = None,
        institutional_detector: Optional[InstitutionalFlowDetector] = None,
    ) -> None:
        """
        Initialise the dashboard with optional service components.

        Args:
            time_and_sales: Trade tape service for time & sales data.
            dom_service: Depth-of-market service for Level 2 order book.
            order_flow_analyzer: Core order flow and volume profile analyzer.
            advanced_analyzer: Advanced order flow analyzer (aggression metrics,
                stacked imbalances, pressure gauges).
            institutional_detector: Institutional flow and large-order detector.
        """
        self._ts: Optional[TimeAndSalesService] = time_and_sales
        self._dom: Optional[DepthOfMarketService] = dom_service
        self._ofa: Optional[OrderFlowAnalyzer] = order_flow_analyzer
        self._adv: Optional[AdvancedOrderFlowAnalyzer] = advanced_analyzer
        self._inst: Optional[InstitutionalFlowDetector] = institutional_detector

        logger.info(
            "OrderFlowDashboard initialised — components: "
            "time_sales=%s, dom=%s, order_flow=%s, advanced=%s, institutional=%s",
            self._ts is not None,
            self._dom is not None,
            self._ofa is not None,
            self._adv is not None,
            self._inst is not None,
        )

    # ================================================================
    # TRADE INGESTION
    # ================================================================

    def add_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        timestamp: Optional[datetime] = None,
        trade_id: Optional[str] = None,
    ) -> None:
        """
        Propagate a single trade to all configured components.

        Each component receives the trade independently; a failure in one
        component does not prevent delivery to the others.  ``Exception`` is
        caught broadly here because this aggregator must remain operational even
        when an individual component encounters an unexpected error.

        Args:
            symbol: Trading symbol (e.g., ``'XAUUSD'``).
            price: Execution price.
            size: Trade size (must be > 0).
            side: Aggressor side — ``'buy'`` or ``'sell'``.
            timestamp: UTC trade time. Defaults to ``datetime.now(timezone.utc)``.
            trade_id: Optional broker-assigned trade identifier.
        """
        ts = timestamp or datetime.now(timezone.utc)

        if self._ts is not None:
            try:
                self._ts.add_trade(symbol, price, size, side, ts, trade_id)
            except Exception:
                logger.exception(
                    "TimeAndSalesService.add_trade failed for %s", symbol
                )

        if self._ofa is not None:
            try:
                # OrderFlowAnalyzer uses naive UTC datetimes internally; strip tzinfo.
                naive_ts = ts.replace(tzinfo=None) if ts.tzinfo is not None else ts
                self._ofa.add_trade(symbol, price, size, side, naive_ts, trade_id)
            except Exception:
                logger.exception(
                    "OrderFlowAnalyzer.add_trade failed for %s", symbol
                )

        if self._adv is not None:
            try:
                self._adv.add_trade(symbol, price, size, side, ts)
            except Exception:
                logger.exception(
                    "AdvancedOrderFlowAnalyzer.add_trade failed for %s", symbol
                )

        if self._inst is not None:
            try:
                self._inst.add_trade(symbol, price, size, side, ts, trade_id)
            except Exception:
                logger.exception(
                    "InstitutionalFlowDetector.add_trade failed for %s", symbol
                )

    # ================================================================
    # FULL ANALYSIS
    # ================================================================

    def get_complete_analysis(self, symbol: str) -> Dict[str, Any]:
        """
        Retrieve a comprehensive, unified order flow analysis for a symbol.

        Aggregates all available component data into a single dictionary.
        Components that are not configured or have no data return ``None``
        for their respective keys.

        Args:
            symbol: Trading symbol to analyse.

        Returns:
            Dictionary with the following structure::

                {
                    'symbol': str,
                    'timestamp': str,           # ISO 8601 UTC
                    'time_sales': dict | None,  # aggressor stats + velocity
                    'order_book': dict | None,  # Level 2 analysis
                    'order_flow': dict | None,  # delta, imbalance, signal
                    'institutional_flow': dict | None,  # smart money report
                    'volume_profile': dict | None,      # POC, VAH, VAL, levels
                    'key_levels': dict | None,  # support, resistance, POC
                    'aggression': dict | None,  # metrics, pressure, bias
                    'large_orders': list[dict] | None,  # institutional trades
                }
        """
        logger.debug("get_complete_analysis called for %s", symbol)

        result: Dict[str, Any] = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "time_sales": None,
            "order_book": None,
            "order_flow": None,
            "institutional_flow": None,
            "volume_profile": None,
            "key_levels": None,
            "aggression": None,
            "large_orders": None,
        }

        # ── Time & Sales ────────────────────────────────────────────
        if self._ts is not None:
            try:
                aggressor_stats = self._ts.get_aggressor_stats(symbol)
                velocity = self._ts.get_trade_velocity(symbol)
                result["time_sales"] = {
                    "aggressor_stats": (
                        aggressor_stats.to_dict() if aggressor_stats else None
                    ),
                    "velocity": velocity.to_dict() if velocity else None,
                }
            except Exception:
                logger.exception(
                    "Failed to retrieve time & sales data for %s", symbol
                )

        # ── Depth of Market ──────────────────────────────────────────
        if self._dom is not None:
            try:
                ob_analysis = self._dom.get_order_book_analysis(symbol)
                result["order_book"] = (
                    ob_analysis.to_dict() if ob_analysis else None
                )
            except Exception:
                logger.exception(
                    "Failed to retrieve order book analysis for %s", symbol
                )

        # ── Core Order Flow ──────────────────────────────────────────
        if self._ofa is not None:
            try:
                flow = self._ofa.analyze(symbol)
                result["order_flow"] = flow.to_dict() if flow else None
            except Exception:
                logger.exception(
                    "Failed to retrieve order flow analysis for %s", symbol
                )

            try:
                profile = self._ofa.get_volume_profile(symbol)
                result["volume_profile"] = profile.to_dict() if profile else None
            except Exception:
                logger.exception(
                    "Failed to retrieve volume profile for %s", symbol
                )

            try:
                result["key_levels"] = self._ofa.get_key_levels(symbol)
            except Exception:
                logger.exception(
                    "Failed to retrieve key levels for %s", symbol
                )

        # ── Advanced Order Flow ───────────────────────────────────────
        if self._adv is not None:
            try:
                adv_result = self._adv.analyze(symbol)
                if adv_result is not None:
                    aggression = adv_result.aggression
                    pressure = adv_result.pressure_gauges
                    result["aggression"] = {
                        "metrics": (
                            aggression.to_dict() if aggression else None
                        ),
                        "pressure": (
                            pressure.to_dict() if pressure else None
                        ),
                        "overall_bias": adv_result.overall_bias,
                        "confidence": adv_result.confidence,
                        "signals": adv_result.signals or [],
                    }
            except Exception:
                logger.exception(
                    "Failed to retrieve advanced order flow analysis for %s",
                    symbol,
                )

        # ── Institutional Flow ────────────────────────────────────────
        if self._inst is not None:
            try:
                result["institutional_flow"] = self._inst.analyze_flow(symbol)
            except Exception:
                logger.exception(
                    "Failed to retrieve institutional flow analysis for %s",
                    symbol,
                )

            try:
                result["large_orders"] = self._inst.get_large_orders(symbol)
            except Exception:
                logger.exception(
                    "Failed to retrieve large orders for %s", symbol
                )

        return result

    # ================================================================
    # SUMMARY
    # ================================================================

    def get_summary(self, symbol: str) -> Dict[str, Any]:
        """
        Return a quick high-level summary for a symbol.

        Provides the most essential metrics without the full detail of
        :meth:`get_complete_analysis`, making it suitable for dashboard
        widgets and real-time ticker displays.

        Args:
            symbol: Trading symbol.

        Returns:
            Dictionary with the following keys::

                {
                    'symbol': str,
                    'timestamp': str,
                    'bias': str,                    # 'bullish' | 'bearish' | 'neutral' | 'unknown'
                    'dom_imbalance': float | None,  # -1 to +1
                    'buy_pressure': float | None,   # 0-100
                    'sell_pressure': float | None,  # 0-100
                    'smart_money_direction': str | None,
                    'cumulative_delta': float | None,
                    'spread': float | None,
                    'large_order_count': int | None,
                    'signals': list[str],
                }
        """
        summary: Dict[str, Any] = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bias": "unknown",
            "dom_imbalance": None,
            "buy_pressure": None,
            "sell_pressure": None,
            "smart_money_direction": None,
            "cumulative_delta": None,
            "spread": None,
            "large_order_count": None,
            "signals": [],
        }

        # DOM metrics
        if self._dom is not None:
            try:
                ob = self._dom.get_order_book_analysis(symbol)
                if ob is not None:
                    summary["dom_imbalance"] = ob.imbalance
                    summary["spread"] = ob.spread
            except Exception:
                logger.exception(
                    "Summary: DOM analysis failed for %s", symbol
                )

        # Core order flow delta & pressure
        if self._ofa is not None:
            try:
                flow = self._ofa.analyze(symbol)
                if flow is not None:
                    summary["buy_pressure"] = flow.buying_pressure
                    summary["sell_pressure"] = flow.selling_pressure
                    summary["cumulative_delta"] = flow.cumulative_delta
            except Exception:
                logger.exception(
                    "Summary: order flow analysis failed for %s", symbol
                )

        # Institutional signals
        if self._inst is not None:
            try:
                summary["smart_money_direction"] = (
                    self._inst.get_smart_money_direction(symbol)
                )
            except Exception:
                logger.exception(
                    "Summary: smart money direction failed for %s", symbol
                )

            try:
                large_orders: List[Dict] = self._inst.get_large_orders(symbol)
                summary["large_order_count"] = (
                    len(large_orders) if large_orders is not None else 0
                )
            except Exception:
                logger.exception(
                    "Summary: large order count failed for %s", symbol
                )

        # Advanced signals list
        if self._adv is not None:
            try:
                adv = self._adv.analyze(symbol)
                if adv is not None:
                    summary["signals"] = adv.signals or []
            except Exception:
                logger.exception(
                    "Summary: advanced analysis failed for %s", symbol
                )

        summary["bias"] = self.get_bias(symbol)
        return summary

    # ================================================================
    # BIAS
    # ================================================================

    def get_bias(self, symbol: str) -> str:
        """
        Derive an overall market bias by aggregating component signals.

        Votes are collected from each available component.  The advanced
        analyzer and institutional detector carry double weight due to the
        depth of their signal generation.  Ties resolve to ``'neutral'``.

        Args:
            symbol: Trading symbol.

        Returns:
            One of ``'bullish'``, ``'bearish'``, or ``'neutral'``.
        """
        bullish_votes = 0
        bearish_votes = 0

        # Order book bias (weight 1)
        if self._dom is not None:
            try:
                ob = self._dom.get_order_book_analysis(symbol)
                if ob is not None:
                    if ob.market_bias == "bullish":
                        bullish_votes += 1
                    elif ob.market_bias == "bearish":
                        bearish_votes += 1
            except Exception:
                logger.exception("Bias: DOM analysis failed for %s", symbol)

        # Core order flow signal (weight 1)
        if self._ofa is not None:
            try:
                flow = self._ofa.analyze(symbol)
                if flow is not None:
                    if flow.order_flow_signal == "bullish":
                        bullish_votes += 1
                    elif flow.order_flow_signal == "bearish":
                        bearish_votes += 1
            except Exception:
                logger.exception(
                    "Bias: order flow signal failed for %s", symbol
                )

        # Advanced overall bias (weight 2 — richer signal)
        if self._adv is not None:
            try:
                adv = self._adv.analyze(symbol)
                if adv is not None:
                    if adv.overall_bias == "bullish":
                        bullish_votes += 2
                    elif adv.overall_bias == "bearish":
                        bearish_votes += 2
            except Exception:
                logger.exception(
                    "Bias: advanced analysis failed for %s", symbol
                )

        # Smart money direction (weight 2 — institutional confirmation)
        if self._inst is not None:
            try:
                direction = self._inst.get_smart_money_direction(symbol)
                if direction == "bullish":
                    bullish_votes += 2
                elif direction == "bearish":
                    bearish_votes += 2
            except Exception:
                logger.exception(
                    "Bias: institutional flow failed for %s", symbol
                )

        if bullish_votes > bearish_votes:
            return "bullish"
        if bearish_votes > bullish_votes:
            return "bearish"
        return "neutral"


# ================================================================
# FACTORY
# ================================================================


def create_dashboard(
    order_flow_config: Optional[Dict] = None,
    dom_config: Optional[Dict] = None,
    time_sales_config: Optional[Dict] = None,
    advanced_config: Optional[Dict] = None,
    institutional_config: Optional[Dict] = None,
) -> OrderFlowDashboard:
    """
    Factory function that creates an :class:`OrderFlowDashboard` with all
    components initialised using default (or provided) configurations.

    Args:
        order_flow_config: Config overrides for :class:`~analysis.order_flow.OrderFlowAnalyzer`.
        dom_config: Config overrides for :class:`~data.depth_of_market.DepthOfMarketService`.
        time_sales_config: Config overrides for :class:`~data.time_and_sales.TimeAndSalesService`.
        advanced_config: Config overrides for
            :class:`~analysis.advanced_order_flow.AdvancedOrderFlowAnalyzer`.
        institutional_config: Config overrides for
            :class:`~analysis.institutional_flow.InstitutionalFlowDetector`.

    Returns:
        A fully configured :class:`OrderFlowDashboard` instance with all
        five components initialised.

    Example:
        >>> dashboard = create_dashboard()
        >>> dashboard.add_trade('XAUUSD', 1950.00, 1.0, 'buy')
    """
    logger.info("Creating OrderFlowDashboard with all components")

    return OrderFlowDashboard(
        time_and_sales=TimeAndSalesService(config=time_sales_config or {}),
        dom_service=DepthOfMarketService(config=dom_config or {}),
        order_flow_analyzer=OrderFlowAnalyzer(config=order_flow_config or {}),
        advanced_analyzer=AdvancedOrderFlowAnalyzer(config=advanced_config or {}),
        institutional_detector=InstitutionalFlowDetector(
            config=institutional_config or {}
        ),
    )


# ================================================================
# FASTAPI ROUTER
# ================================================================


def create_dashboard_router(dashboard: OrderFlowDashboard):
    """
    Create a FastAPI router exposing the dashboard's three core endpoints.

    Endpoints:
        - ``GET /{symbol}/analysis`` — full unified order flow analysis.
        - ``GET /{symbol}/summary`` — high-level summary for dashboards.
        - ``GET /{symbol}/bias`` — overall market bias (bullish/bearish/neutral).

    Args:
        dashboard: A configured :class:`OrderFlowDashboard` instance.

    Returns:
        A ``fastapi.APIRouter`` instance mounted at ``/api/dashboard``.

    Example:
        >>> from fastapi import FastAPI
        >>> app = FastAPI()
        >>> db = create_dashboard()
        >>> app.include_router(create_dashboard_router(db))
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/dashboard", tags=["Order Flow Dashboard"])

    @router.get("/{symbol}/analysis", summary="Full order flow analysis")
    async def get_complete_analysis(symbol: str) -> Dict[str, Any]:
        """Return a comprehensive, unified order flow analysis for *symbol*."""
        try:
            return dashboard.get_complete_analysis(symbol.upper())
        except Exception as exc:
            logger.exception(
                "Dashboard analysis endpoint error for %s", symbol
            )
            raise HTTPException(
                status_code=500, detail="Analysis failed — see server logs."
            ) from exc

    @router.get("/{symbol}/summary", summary="High-level summary")
    async def get_summary(symbol: str) -> Dict[str, Any]:
        """Return a quick high-level summary for *symbol*."""
        try:
            return dashboard.get_summary(symbol.upper())
        except Exception as exc:
            logger.exception(
                "Dashboard summary endpoint error for %s", symbol
            )
            raise HTTPException(
                status_code=500, detail="Summary failed — see server logs."
            ) from exc

    @router.get("/{symbol}/bias", summary="Overall market bias")
    async def get_bias(symbol: str) -> Dict[str, str]:
        """Return the overall market bias for *symbol*."""
        try:
            bias = dashboard.get_bias(symbol.upper())
            return {"symbol": symbol.upper(), "bias": bias}
        except Exception as exc:
            logger.exception(
                "Dashboard bias endpoint error for %s", symbol
            )
            raise HTTPException(
                status_code=500, detail="Bias calculation failed — see server logs."
            ) from exc

    return router
