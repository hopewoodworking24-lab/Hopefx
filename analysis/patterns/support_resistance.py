"""
Support and Resistance Level Detection Module

Identifies key price levels from historical OHLCV data using multiple methods:
- Swing highs / lows (local maxima and minima)
- Volume-weighted price levels (high-activity price clusters)
- Round numbers / psychological levels
- Previous session highs and lows
- Dynamic levels (trendlines, moving averages)
- Fibonacci retracements (23.6 %, 38.2 %, 50 %, 61.8 %, 78.6 %)

Each detected level is assigned a strength score (0–1) based on touch-count
and multi-method confluence, and is classified as *support*, *resistance*, or
*pivot* relative to the current price.

Usage:
    detector = SupportResistanceDetector(config={'sensitivity': 0.003, 'min_touches': 2})
    levels = detector.detect_levels(prices_df, current_price=2350.0)
    for lvl in levels['support']:
        print(lvl.to_dict())
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS: Tuple[str, ...] = ("open", "high", "low", "close", "volume")

# Standard Fibonacci retracement ratios
_FIB_RATIOS: Tuple[float, ...] = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


# ================================================================
# DATACLASS
# ================================================================


@dataclass
class PriceLevel:
    """
    A single detected support, resistance, or pivot price level.

    Attributes:
        price: The absolute price of the level.
        level_type: Classification of the level. One of ``'support'``,
            ``'resistance'``, or ``'pivot'``.
        strength: Normalised strength score in [0, 1].  Higher values
            indicate a more significant level (more touches, more
            method confluence).
        touch_count: Number of times price has tested this level.
        last_touch: UTC datetime of the most recent price touch, or
            ``None`` if the level has never been tested.
        method: Detection method that produced this level. One of
            ``'swing'``, ``'volume'``, ``'fibonacci'``,
            ``'round_number'``, or ``'dynamic'``.
        is_active: ``True`` if the level is considered currently
            relevant (i.e. price has not broken decisively through it).
        description: Optional human-readable note about the level.
        timestamp: UTC datetime when the level was detected.
    """

    price: float
    level_type: str
    strength: float
    touch_count: int
    last_touch: Optional[datetime]
    method: str
    is_active: bool
    description: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialise the level to a plain dictionary.

        Returns:
            Dict with all level fields, suitable for JSON serialisation.
        """
        return {
            "price": round(self.price, 5),
            "level_type": self.level_type,
            "strength": round(self.strength, 4),
            "touch_count": self.touch_count,
            "last_touch": self.last_touch.isoformat() if self.last_touch else None,
            "method": self.method,
            "is_active": self.is_active,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
        }


# ================================================================
# DETECTOR
# ================================================================


class SupportResistanceDetector:
    """
    Detects support and resistance levels from OHLCV price data.

    Detection methods:
    - **Swing highs/lows** – local price extremes within a rolling window.
    - **Volume levels** – price buckets with disproportionately high traded
      volume (high-volume nodes).
    - **Fibonacci retracements** – standard ratios applied to the dominant
      price swing.
    - **Round numbers** – psychological levels at round-number increments.
    - **Dynamic levels** – current values of key moving averages and a
      linear trendline of recent swing points.

    The prices DataFrame must have lowercase columns:
    ``open``, ``high``, ``low``, ``close``, ``volume`` and a datetime index.

    Usage:
        detector = SupportResistanceDetector(config={'sensitivity': 0.003})
        levels = detector.detect_levels(prices, current_price=2350.0)
        for lvl in levels['resistance']:
            print(lvl.to_dict())
    """

    def __init__(self, config: Optional[Dict] = None) -> None:
        """
        Initialise the support/resistance detector.

        Args:
            config: Optional configuration dict. Supported keys:

                - ``sensitivity`` (float): Fractional price tolerance used
                  when merging nearby levels. Default ``0.003`` (0.3 %).
                - ``swing_window`` (int): Number of bars on each side
                  required to confirm a local swing high or low.
                  Default ``5``.
                - ``min_touches`` (int): Minimum number of times price
                  must touch a level for it to be retained (swing /
                  volume methods only). Default ``1``.
                - ``min_bars`` (int): Minimum rows required in the
                  DataFrame. Default ``30``.
                - ``round_number_increment`` (float): Price increment used
                  to generate round-number levels. Default ``50.0``.
                - ``volume_buckets`` (int): Number of price buckets used
                  when computing volume-weighted levels. Default ``50``.
                - ``ma_periods`` (list): Moving-average periods to include
                  as dynamic levels. Default ``[20, 50, 200]``.
                - ``max_levels_per_method`` (int): Maximum levels returned
                  by each detection method. Default ``10``.
        """
        self.config: Dict = config or {}
        self.sensitivity: float = self.config.get("sensitivity", 0.003)
        self.swing_window: int = self.config.get("swing_window", 5)
        self.min_touches: int = self.config.get("min_touches", 1)
        self.min_bars: int = self.config.get("min_bars", 30)
        self.round_number_increment: float = self.config.get(
            "round_number_increment", 50.0
        )
        self.volume_buckets: int = self.config.get("volume_buckets", 50)
        self.ma_periods: List[int] = self.config.get("ma_periods", [20, 50, 200])
        self.max_levels_per_method: int = self.config.get("max_levels_per_method", 10)

        # Lock for thread-safe access to any mutable state
        self._lock = threading.Lock()

        logger.info("SupportResistanceDetector initialised with config=%s", self.config)

    # ================================================================
    # PUBLIC API
    # ================================================================

    def detect_levels(
        self,
        prices: pd.DataFrame,
        current_price: Optional[float] = None,
    ) -> Dict[str, List[PriceLevel]]:
        """
        Detect all support and resistance levels in the given price data.

        Runs all detection methods, merges nearby duplicate levels, scores
        each level, and classifies it as *support*, *resistance*, or *pivot*
        relative to ``current_price``.

        Args:
            prices: DataFrame with columns ``open``, ``high``, ``low``,
                ``close``, ``volume`` and a datetime index.
            current_price: The price used to classify levels. If ``None``,
                the last ``close`` value is used.

        Returns:
            Dict with keys ``'support'``, ``'resistance'``, and ``'pivot'``,
            each containing a list of :class:`PriceLevel` objects sorted by
            strength descending.
        """
        result: Dict[str, List[PriceLevel]] = {
            "support": [],
            "resistance": [],
            "pivot": [],
        }

        if not self._validate_dataframe(prices):
            return result

        ref_price = (
            current_price
            if current_price is not None
            else float(prices["close"].iloc[-1])
        )

        all_levels: List[PriceLevel] = []

        detection_methods = [
            self.get_swing_levels,
            self.get_volume_levels,
            self.get_fibonacci_levels,
            self.get_round_number_levels,
            self.get_dynamic_levels,
        ]

        for method_fn in detection_methods:
            try:
                levels = method_fn(prices)
                all_levels.extend(levels)
            except Exception as exc:
                logger.error(
                    "Error in %s: %s", method_fn.__name__, exc, exc_info=True
                )

        merged = self._merge_levels(all_levels)

        for lvl in merged:
            lvl.level_type = self.classify_level(lvl, ref_price)
            result[lvl.level_type].append(lvl)

        for key in result:
            result[key].sort(key=lambda lv: lv.strength, reverse=True)

        logger.debug(
            "detect_levels: support=%d resistance=%d pivot=%d (ref=%.5f)",
            len(result["support"]),
            len(result["resistance"]),
            len(result["pivot"]),
            ref_price,
        )
        return result

    def get_swing_levels(self, prices: pd.DataFrame) -> List[PriceLevel]:
        """
        Identify swing high and swing low price levels.

        A swing high is a bar whose ``high`` is greater than the highs of
        ``swing_window`` bars on both sides.  A swing low mirrors this using
        ``low`` values.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of :class:`PriceLevel` objects (method ``'swing'``).
        """
        if not self._validate_dataframe(prices):
            return []

        levels: List[PriceLevel] = []

        highs = prices["high"].values
        lows = prices["low"].values
        closes = prices["close"].values
        w = self.swing_window

        swing_high_idx = self._find_swing_highs(prices)
        swing_low_idx = self._find_swing_lows(prices)

        # --- swing highs → candidate resistance ---
        for idx in swing_high_idx:
            price = float(highs[idx])
            touch_count = self._count_touches(price, highs, closes)
            if touch_count < self.min_touches:
                continue
            last_touch = self._last_touch_datetime(price, prices)
            levels.append(
                PriceLevel(
                    price=price,
                    level_type="resistance",
                    strength=0.0,  # scored later
                    touch_count=touch_count,
                    last_touch=last_touch,
                    method="swing",
                    is_active=True,
                    description=f"Swing high at index {idx}",
                )
            )

        # --- swing lows → candidate support ---
        for idx in swing_low_idx:
            price = float(lows[idx])
            touch_count = self._count_touches(price, lows, closes)
            if touch_count < self.min_touches:
                continue
            last_touch = self._last_touch_datetime(price, prices)
            levels.append(
                PriceLevel(
                    price=price,
                    level_type="support",
                    strength=0.0,
                    touch_count=touch_count,
                    last_touch=last_touch,
                    method="swing",
                    is_active=True,
                    description=f"Swing low at index {idx}",
                )
            )

        self._score_levels(levels, prices)
        levels.sort(key=lambda lv: lv.strength, reverse=True)
        return levels[: self.max_levels_per_method]

    def get_fibonacci_levels(
        self,
        prices: pd.DataFrame,
        trend: str = "auto",
    ) -> List[PriceLevel]:
        """
        Compute Fibonacci retracement levels for the dominant price swing.

        Standard ratios applied: 0 %, 23.6 %, 38.2 %, 50 %, 61.8 %, 78.6 %,
        100 %.

        Args:
            prices: OHLCV DataFrame with datetime index.
            trend: Direction of the dominant swing used to anchor the
                retracement grid.  ``'up'`` uses the lowest low as the
                swing start and the highest high as the swing end.
                ``'down'`` reverses the anchor.  ``'auto'`` (default)
                infers the dominant trend from the net close-to-close
                direction of the series.

        Returns:
            List of :class:`PriceLevel` objects (method ``'fibonacci'``).
        """
        if not self._validate_dataframe(prices):
            return []

        levels: List[PriceLevel] = []

        swing_low = float(prices["low"].min())
        swing_high = float(prices["high"].max())
        swing_range = swing_high - swing_low

        if swing_range <= 0:
            logger.warning("get_fibonacci_levels: zero price range, skipping")
            return []

        # Determine dominant trend
        if trend == "auto":
            net_move = float(prices["close"].iloc[-1]) - float(
                prices["close"].iloc[0]
            )
            trend = "up" if net_move >= 0 else "down"

        for ratio in _FIB_RATIOS:
            if trend == "up":
                # Retrace from high back toward low
                price = swing_high - ratio * swing_range
            else:
                # Retrace from low back toward high
                price = swing_low + ratio * swing_range

            label_pct = f"{ratio * 100:.1f}%"
            levels.append(
                PriceLevel(
                    price=price,
                    level_type="pivot",
                    strength=self._fib_strength(ratio),
                    touch_count=0,
                    last_touch=None,
                    method="fibonacci",
                    is_active=True,
                    description=f"Fibonacci {label_pct} retracement ({trend} swing)",
                )
            )

        return levels[: self.max_levels_per_method]

    def get_round_number_levels(self, prices: pd.DataFrame) -> List[PriceLevel]:
        """
        Generate psychological / round-number price levels.

        Levels are spaced at ``round_number_increment`` intervals and
        filtered to the price range visible in the data.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of :class:`PriceLevel` objects (method ``'round_number'``).
        """
        if not self._validate_dataframe(prices):
            return []

        price_min = float(prices["low"].min())
        price_max = float(prices["high"].max())
        inc = self.round_number_increment

        first = np.floor(price_min / inc) * inc
        last = np.ceil(price_max / inc) * inc
        candidates = np.arange(first, last + inc * 0.5, inc)

        levels: List[PriceLevel] = []
        closes = prices["close"].values
        highs = prices["high"].values
        lows = prices["low"].values
        combined = np.concatenate([highs, lows, closes])

        for rn_price in candidates:
            rn_price = float(rn_price)
            touch_count = self._count_touches(rn_price, combined, closes)
            levels.append(
                PriceLevel(
                    price=rn_price,
                    level_type="pivot",
                    strength=0.5,  # base strength; refined in _score_levels
                    touch_count=touch_count,
                    last_touch=self._last_touch_datetime(rn_price, prices),
                    method="round_number",
                    is_active=True,
                    description=f"Psychological round number {rn_price:.0f}",
                )
            )

        self._score_levels(levels, prices)
        levels.sort(key=lambda lv: lv.strength, reverse=True)
        return levels[: self.max_levels_per_method]

    def get_volume_levels(self, prices: pd.DataFrame) -> List[PriceLevel]:
        """
        Identify high-volume price nodes as potential support/resistance.

        Splits the price range into ``volume_buckets`` equal-width price
        bands and sums the traded volume in each band.  Bands with volume
        exceeding the 75th-percentile threshold are returned as levels.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of :class:`PriceLevel` objects (method ``'volume'``).
        """
        if not self._validate_dataframe(prices):
            return []

        price_min = float(prices["low"].min())
        price_max = float(prices["high"].max())
        price_range = price_max - price_min

        if price_range <= 0:
            logger.warning("get_volume_levels: zero price range, skipping")
            return []

        n_buckets = self.volume_buckets
        bucket_size = price_range / n_buckets
        bucket_volume = np.zeros(n_buckets)

        for _, row in prices.iterrows():
            bar_low = float(row["low"])
            bar_high = float(row["high"])
            bar_vol = float(row["volume"])
            bar_range = bar_high - bar_low or bucket_size

            for b in range(n_buckets):
                bucket_lo = price_min + b * bucket_size
                bucket_hi = bucket_lo + bucket_size
                overlap = max(
                    0.0,
                    min(bar_high, bucket_hi) - max(bar_low, bucket_lo),
                )
                bucket_volume[b] += bar_vol * (overlap / bar_range)

        threshold = float(np.percentile(bucket_volume, 75))
        levels: List[PriceLevel] = []
        closes = prices["close"].values

        for b in range(n_buckets):
            if bucket_volume[b] < threshold:
                continue
            mid_price = price_min + (b + 0.5) * bucket_size
            touch_count = self._count_touches(mid_price, closes, closes)
            norm_vol = float(
                bucket_volume[b] / (bucket_volume.max() or 1.0)
            )
            levels.append(
                PriceLevel(
                    price=mid_price,
                    level_type="pivot",
                    strength=norm_vol,
                    touch_count=touch_count,
                    last_touch=self._last_touch_datetime(mid_price, prices),
                    method="volume",
                    is_active=True,
                    description=f"High-volume node (bucket {b}, vol={bucket_volume[b]:.0f})",
                )
            )

        levels.sort(key=lambda lv: lv.strength, reverse=True)
        return levels[: self.max_levels_per_method]

    def get_dynamic_levels(self, prices: pd.DataFrame) -> List[PriceLevel]:
        """
        Compute dynamic levels from moving averages and a swing trendline.

        Moving averages (``ma_periods``) provide widely-watched dynamic S/R
        levels.  A linear trendline is also fitted through the most recent
        swing highs and lows to capture diagonal support/resistance.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of :class:`PriceLevel` objects (method ``'dynamic'``).
        """
        if not self._validate_dataframe(prices):
            return []

        levels: List[PriceLevel] = []
        closes = prices["close"]

        # --- Moving averages ---
        for period in self.ma_periods:
            if len(prices) < period:
                continue
            ma_value = float(closes.rolling(period).mean().iloc[-1])
            if np.isnan(ma_value):
                continue
            levels.append(
                PriceLevel(
                    price=ma_value,
                    level_type="pivot",
                    strength=0.6,
                    touch_count=0,
                    last_touch=None,
                    method="dynamic",
                    is_active=True,
                    description=f"MA{period} = {ma_value:.5f}",
                )
            )

        # --- Linear trendline through recent swing extremes ---
        trendline_levels = self._compute_trendline_levels(prices)
        levels.extend(trendline_levels)

        return levels[: self.max_levels_per_method]

    def classify_level(self, level: PriceLevel, current_price: float) -> str:
        """
        Classify a price level as support, resistance, or pivot.

        Args:
            level: The :class:`PriceLevel` to classify.
            current_price: Reference price (typically the current market price).

        Returns:
            ``'support'`` if the level is below ``current_price``,
            ``'resistance'`` if above, or ``'pivot'`` if within the
            ``sensitivity`` band around ``current_price``.
        """
        band = current_price * self.sensitivity
        if abs(level.price - current_price) <= band:
            return "pivot"
        return "support" if level.price < current_price else "resistance"

    # ================================================================
    # PRIVATE HELPERS – swing detection
    # ================================================================

    def _find_swing_highs(self, prices: pd.DataFrame) -> List[int]:
        """
        Return positional indices of swing-high bars.

        A bar at index ``i`` is a swing high when its ``high`` value is
        strictly greater than the highs of the ``swing_window`` bars on
        each side.

        Args:
            prices: OHLCV DataFrame.

        Returns:
            List of positional bar indices.
        """
        highs = prices["high"].values
        w = self.swing_window
        n = len(highs)
        indices: List[int] = []

        for i in range(w, n - w):
            window = highs[i - w : i + w + 1]
            if highs[i] == window.max() and np.sum(window == highs[i]) == 1:
                indices.append(i)

        return indices

    def _find_swing_lows(self, prices: pd.DataFrame) -> List[int]:
        """
        Return positional indices of swing-low bars.

        A bar at index ``i`` is a swing low when its ``low`` value is
        strictly less than the lows of the ``swing_window`` bars on each
        side.

        Args:
            prices: OHLCV DataFrame.

        Returns:
            List of positional bar indices.
        """
        lows = prices["low"].values
        w = self.swing_window
        n = len(lows)
        indices: List[int] = []

        for i in range(w, n - w):
            window = lows[i - w : i + w + 1]
            if lows[i] == window.min() and np.sum(window == lows[i]) == 1:
                indices.append(i)

        return indices

    # ================================================================
    # PRIVATE HELPERS – trendline
    # ================================================================

    def _compute_trendline_levels(
        self, prices: pd.DataFrame
    ) -> List[PriceLevel]:
        """
        Fit linear trendlines through recent swing highs and lows.

        Requires at least 2 swing points of each type.  Returns the
        extrapolated trendline value at the most recent bar as a dynamic
        level.

        Args:
            prices: OHLCV DataFrame.

        Returns:
            Up to two :class:`PriceLevel` objects for the high and low
            trendlines.
        """
        levels: List[PriceLevel] = []

        for col, label in (("high", "resistance"), ("low", "support")):
            if col == "high":
                idxs = self._find_swing_highs(prices)
            else:
                idxs = self._find_swing_lows(prices)

            if len(idxs) < 2:
                continue

            # Use the most recent swing_window * 3 swing points
            recent_idxs = idxs[-min(len(idxs), self.swing_window * 3):]
            x = np.array(recent_idxs, dtype=float)
            y = prices[col].values[recent_idxs].astype(float)

            coeffs = np.polyfit(x, y, 1)
            # Project to the last bar
            last_x = float(len(prices) - 1)
            trend_price = float(np.polyval(coeffs, last_x))

            if np.isnan(trend_price) or trend_price <= 0:
                continue

            levels.append(
                PriceLevel(
                    price=trend_price,
                    level_type=label,
                    strength=0.55,
                    touch_count=len(idxs),
                    last_touch=None,
                    method="dynamic",
                    is_active=True,
                    description=f"Trendline ({col}) extrapolated to {trend_price:.5f}",
                )
            )

        return levels

    # ================================================================
    # PRIVATE HELPERS – scoring and merging
    # ================================================================

    def _score_levels(
        self, levels: List[PriceLevel], prices: pd.DataFrame
    ) -> None:
        """
        Assign a normalised strength score to each level in-place.

        Strength is proportional to ``touch_count`` / max_touch_count,
        capped at 1.0.

        Args:
            levels: List of :class:`PriceLevel` objects to score.
            prices: OHLCV DataFrame (unused directly but kept for future
                extensions such as recency weighting).
        """
        if not levels:
            return

        max_touches = max(lv.touch_count for lv in levels) or 1
        for lv in levels:
            lv.strength = min(1.0, lv.touch_count / max_touches)

    def _merge_levels(self, levels: List[PriceLevel]) -> List[PriceLevel]:
        """
        Merge levels that are within ``sensitivity`` of each other.

        When multiple levels cluster around the same price, they are
        collapsed into a single representative level.  The merged level
        inherits the highest ``strength``, the sum of ``touch_count``
        values, and a ``method`` string listing all contributing methods.

        Args:
            levels: Raw list of levels from all detection methods.

        Returns:
            Deduplicated list of :class:`PriceLevel` objects.
        """
        if not levels:
            return []

        sorted_levels = sorted(levels, key=lambda lv: lv.price)
        merged: List[PriceLevel] = []
        current_group: List[PriceLevel] = [sorted_levels[0]]

        for lv in sorted_levels[1:]:
            ref_price = current_group[0].price
            if abs(lv.price - ref_price) / (abs(ref_price) + 1e-10) <= self.sensitivity:
                current_group.append(lv)
            else:
                merged.append(self._merge_group(current_group))
                current_group = [lv]

        merged.append(self._merge_group(current_group))
        return merged

    def _merge_group(self, group: List[PriceLevel]) -> PriceLevel:
        """
        Collapse a group of nearby levels into one representative level.

        Args:
            group: Non-empty list of :class:`PriceLevel` objects to merge.

        Returns:
            A single merged :class:`PriceLevel`.
        """
        prices_arr = np.array([lv.price for lv in group])
        strengths = np.array([lv.strength for lv in group])

        # Weighted average price (weight by strength)
        weights = strengths if strengths.sum() > 0 else np.ones(len(group))
        merged_price = float(np.average(prices_arr, weights=weights))

        total_touches = sum(lv.touch_count for lv in group)
        max_strength = float(strengths.max())
        # Boost strength by confluence (more methods → stronger level)
        confluence_boost = min(0.2, 0.05 * (len(group) - 1))
        merged_strength = min(1.0, max_strength + confluence_boost)

        methods = list(dict.fromkeys(lv.method for lv in group))
        method_str = "+".join(methods) if len(methods) > 1 else methods[0]

        last_touches = [lv.last_touch for lv in group if lv.last_touch is not None]
        latest_touch = max(last_touches) if last_touches else None

        # Inherit level_type from the strongest member
        dominant = max(group, key=lambda lv: lv.strength)

        return PriceLevel(
            price=merged_price,
            level_type=dominant.level_type,
            strength=merged_strength,
            touch_count=total_touches,
            last_touch=latest_touch,
            method=method_str,
            is_active=all(lv.is_active for lv in group),
            description="; ".join(lv.description for lv in group if lv.description),
        )

    # ================================================================
    # PRIVATE HELPERS – touch counting
    # ================================================================

    def _count_touches(
        self,
        price: float,
        probe_values: np.ndarray,
        closes: np.ndarray,
    ) -> int:
        """
        Count how many bars have come within ``sensitivity`` of ``price``.

        Args:
            price: The price level to test.
            probe_values: Array of bar values to test (e.g. highs or lows).
            closes: Array of closing prices (unused here; reserved for
                future direction-aware counting).

        Returns:
            Number of touches.
        """
        if price == 0:
            return 0
        band = price * self.sensitivity
        return int(np.sum(np.abs(probe_values - price) <= band))

    def _last_touch_datetime(
        self, price: float, prices: pd.DataFrame
    ) -> Optional[datetime]:
        """
        Find the most recent datetime at which price touched a level.

        Args:
            price: The level price.
            prices: OHLCV DataFrame with datetime index.

        Returns:
            UTC-aware :class:`datetime` of the last touch, or ``None``.
        """
        if price == 0:
            return None
        band = price * self.sensitivity
        mask = (
            (prices["low"] <= price + band) & (prices["high"] >= price - band)
        )
        touched = prices.index[mask]
        if len(touched) == 0:
            return None
        last = touched[-1]
        if isinstance(last, pd.Timestamp):
            dt = last.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return None

    # ================================================================
    # PRIVATE HELPERS – fibonacci strength
    # ================================================================

    @staticmethod
    def _fib_strength(ratio: float) -> float:
        """
        Return an opinionated strength score for a Fibonacci ratio.

        The ``61.8 %`` (golden ratio) and ``38.2 %`` levels are generally
        considered the most significant; the ``50 %`` level is also widely
        watched.  The ``0 %`` and ``100 %`` levels map to swing
        high/low extremes and receive the highest base score.

        Args:
            ratio: A Fibonacci ratio from ``_FIB_RATIOS``.

        Returns:
            Strength score in [0, 1].
        """
        strength_map: Dict[float, float] = {
            0.0: 1.0,
            0.236: 0.5,
            0.382: 0.8,
            0.5: 0.7,
            0.618: 0.9,
            0.786: 0.6,
            1.0: 1.0,
        }
        return strength_map.get(round(ratio, 3), 0.5)

    # ================================================================
    # PRIVATE HELPERS – validation
    # ================================================================

    def _validate_dataframe(self, prices: pd.DataFrame) -> bool:
        """
        Validate that ``prices`` meets the minimum requirements.

        Args:
            prices: DataFrame to validate.

        Returns:
            ``True`` if the DataFrame is usable, ``False`` otherwise.
        """
        if not isinstance(prices, pd.DataFrame):
            logger.error("prices must be a pandas DataFrame")
            return False

        missing = [c for c in _REQUIRED_COLUMNS if c not in prices.columns]
        if missing:
            logger.error("prices DataFrame missing columns: %s", missing)
            return False

        if len(prices) < self.min_bars:
            logger.warning(
                "prices has only %d rows (min_bars=%d); skipping detection",
                len(prices),
                self.min_bars,
            )
            return False

        return True
