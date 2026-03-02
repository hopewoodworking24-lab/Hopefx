"""
Chart Pattern Detection Module

Detects classic technical analysis chart patterns from OHLCV price data:
- Head and Shoulders (bearish) / Inverse Head and Shoulders (bullish)
- Double Top (bearish) / Double Bottom (bullish)
- Ascending, Descending, and Symmetrical Triangle patterns
- Bull Flag, Bear Flag, Bull Pennant, Bear Pennant (continuation patterns)
- Rising Wedge (bearish) / Falling Wedge (bullish)

Usage:
    detector = ChartPatternDetector(config={'sensitivity': 0.02})
    patterns = detector.detect_patterns(prices_df, min_confidence=0.6)
    for pattern in patterns:
        print(pattern.to_dict())
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ================================================================
# DATACLASS
# ================================================================


@dataclass
class ChartPattern:
    """
    Detected chart pattern with metadata.

    Attributes:
        pattern_type: Pattern identifier (e.g., 'head_and_shoulders',
            'double_top', 'ascending_triangle', 'bull_flag', 'rising_wedge').
        direction: Expected price direction after pattern completion.
            One of 'bullish', 'bearish', or 'neutral'.
        confidence: Detection confidence score in the range [0, 1].
        start_index: Positional index in the price DataFrame where the
            pattern begins.
        end_index: Positional index in the price DataFrame where the
            pattern ends.
        key_levels: Named price levels relevant to the pattern, e.g.
            ``{'neckline': 2350.0, 'target': 2300.0}``.
        description: Human-readable summary of the detected pattern.
        timestamp: UTC datetime when the pattern was detected.
    """

    pattern_type: str
    direction: str
    confidence: float
    start_index: int
    end_index: int
    key_levels: Dict[str, float]
    description: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the pattern to a plain dictionary.

        Returns:
            Dict with all pattern fields, suitable for JSON serialisation.
        """
        return {
            "pattern_type": self.pattern_type,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "start_index": self.start_index,
            "end_index": self.end_index,
            "key_levels": {k: round(v, 5) for k, v in self.key_levels.items()},
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
        }


# ================================================================
# DETECTOR
# ================================================================


class ChartPatternDetector:
    """
    Detects classic chart patterns from OHLCV price data.

    Supported patterns:
    - Head and Shoulders (bearish) / Inverse Head and Shoulders (bullish)
    - Double Top (bearish) / Double Bottom (bullish)
    - Ascending Triangle (bullish) / Descending Triangle (bearish) /
      Symmetrical Triangle (neutral)
    - Bull Flag / Bear Flag / Bull Pennant / Bear Pennant (continuation)
    - Rising Wedge (bearish) / Falling Wedge (bullish)

    The prices DataFrame must have lowercase columns:
    ``open``, ``high``, ``low``, ``close``, ``volume`` and a datetime index.

    Usage:
        detector = ChartPatternDetector(config={'min_bars': 20, 'sensitivity': 0.02})
        patterns = detector.detect_patterns(prices, min_confidence=0.65)
        for p in patterns:
            print(p.to_dict())
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the chart pattern detector.

        Args:
            config: Optional configuration dict. Supported keys:

                - ``min_bars`` (int): Minimum bars required for any
                  detection. Default ``20``.
                - ``sensitivity`` (float): Fractional price tolerance used
                  when comparing price levels (e.g. shoulder symmetry,
                  double-top similarity). Default ``0.02`` (2 %).
                - ``swing_window`` (int): Number of bars on each side
                  required to confirm a local swing high or low.
                  Default ``3``.
                - ``triangle_min_bars`` (int): Minimum bars in a window
                  examined for triangle / wedge patterns. Default ``15``.
                - ``flag_pole_min_pct`` (float): Minimum fractional price
                  move to qualify as a flag pole. Default ``0.01`` (1 %).
                - ``max_patterns_per_type`` (int): Maximum patterns
                  returned per detection method. Default ``5``.
                - ``min_pullback_pct`` (float): Minimum retracement between
                  two peaks / troughs to qualify as a double top/bottom.
                  Default ``0.005`` (0.5 %).
        """
        self.config = config or {}
        self.min_bars: int = self.config.get("min_bars", 20)
        self.sensitivity: float = self.config.get("sensitivity", 0.02)
        self.swing_window: int = self.config.get("swing_window", 3)
        self.triangle_min_bars: int = self.config.get("triangle_min_bars", 15)
        self.flag_pole_min_pct: float = self.config.get("flag_pole_min_pct", 0.01)
        self.max_patterns_per_type: int = self.config.get("max_patterns_per_type", 5)
        self.min_pullback_pct: float = self.config.get("min_pullback_pct", 0.005)

        # Lock for thread-safe access to any mutable state
        self._lock = threading.Lock()

        logger.info("Chart Pattern Detector initialized")

    # ================================================================
    # PUBLIC API
    # ================================================================

    def detect_patterns(
        self,
        prices: pd.DataFrame,
        min_confidence: float = 0.6,
    ) -> List[ChartPattern]:
        """
        Detect all supported chart patterns in the given price data.

        Runs every individual detection method and aggregates the results,
        filtering by ``min_confidence`` and sorting by confidence descending.

        Args:
            prices: DataFrame with columns ``open``, ``high``, ``low``,
                ``close``, ``volume`` and a datetime index. Must contain at
                least ``min_bars`` rows.
            min_confidence: Minimum confidence threshold (inclusive) for
                returned patterns. Must be in [0, 1]. Default ``0.6``.

        Returns:
            List of :class:`ChartPattern` objects sorted by confidence
            descending.
        """
        if not self._validate_dataframe(prices):
            return []

        all_patterns: List[ChartPattern] = []

        detectors = [
            self.detect_head_and_shoulders,
            self.detect_double_tops_bottoms,
            self.detect_triangles,
            self.detect_flags_pennants,
            self.detect_wedges,
        ]

        for detect_fn in detectors:
            try:
                patterns = detect_fn(prices)
                all_patterns.extend(patterns)
            except Exception as exc:
                logger.error(
                    "Error in %s: %s", detect_fn.__name__, exc, exc_info=True
                )

        filtered = [p for p in all_patterns if p.confidence >= min_confidence]
        filtered.sort(key=lambda p: p.confidence, reverse=True)

        logger.debug(
            "detect_patterns: found %d pattern(s) above confidence %.2f",
            len(filtered),
            min_confidence,
        )
        return filtered

    # ================================================================
    # HEAD AND SHOULDERS
    # ================================================================

    def detect_head_and_shoulders(
        self, prices: pd.DataFrame
    ) -> List[ChartPattern]:
        """
        Detect Head and Shoulders and Inverse Head and Shoulders patterns.

        **Head and Shoulders** (bearish reversal): three consecutive swing
        highs where the middle peak (head) is the tallest and the two outer
        peaks (shoulders) are at approximately the same level.  The neckline
        is drawn through the two troughs between the peaks.

        **Inverse Head and Shoulders** (bullish reversal): mirror image using
        swing lows — the middle trough is the deepest.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`ChartPattern` objects.
        """
        if not self._validate_dataframe(prices):
            return []

        patterns: List[ChartPattern] = []

        try:
            highs_idx = self._find_swing_highs(prices)
            patterns.extend(
                self._scan_head_and_shoulders(prices, highs_idx, inverse=False)
            )

            lows_idx = self._find_swing_lows(prices)
            patterns.extend(
                self._scan_head_and_shoulders(prices, lows_idx, inverse=True)
            )
        except Exception as exc:
            logger.error(
                "Error detecting head and shoulders: %s", exc, exc_info=True
            )

        return patterns[: self.max_patterns_per_type]

    def _scan_head_and_shoulders(
        self,
        prices: pd.DataFrame,
        pivot_indices: List[int],
        inverse: bool,
    ) -> List[ChartPattern]:
        """
        Scan a list of swing-point indices for H&S / inverse H&S formations.

        Args:
            prices: OHLCV DataFrame.
            pivot_indices: Positional indices of swing highs (regular H&S) or
                swing lows (inverse H&S).
            inverse: ``True`` for inverse (bullish) variant.

        Returns:
            List of detected patterns.
        """
        patterns: List[ChartPattern] = []
        close = prices["close"].values
        n = len(pivot_indices)

        if n < 3:
            return patterns

        for i in range(n - 2):
            ls_idx = pivot_indices[i]
            h_idx = pivot_indices[i + 1]
            rs_idx = pivot_indices[i + 2]

            ls_price = close[ls_idx]
            h_price = close[h_idx]
            rs_price = close[rs_idx]

            # Head must be more extreme than both shoulders
            if inverse:
                if not (h_price < ls_price and h_price < rs_price):
                    continue
            else:
                if not (h_price > ls_price and h_price > rs_price):
                    continue

            # Shoulders must be at approximately the same level
            shoulder_diff = abs(ls_price - rs_price) / (abs(ls_price) + 1e-10)
            if shoulder_diff > self.sensitivity * 3:
                continue

            # Neckline: average of the two intermediate extremes
            between1 = close[ls_idx : h_idx + 1]
            between2 = close[h_idx : rs_idx + 1]

            if len(between1) < 2 or len(between2) < 2:
                continue

            if inverse:
                trough1 = float(np.max(between1))
                trough2 = float(np.max(between2))
            else:
                trough1 = float(np.min(between1))
                trough2 = float(np.min(between2))

            neckline = (trough1 + trough2) / 2.0

            # Price target: project pattern height from neckline
            if inverse:
                pattern_height = neckline - h_price
                target = neckline + pattern_height
            else:
                pattern_height = h_price - neckline
                target = neckline - pattern_height

            # Confidence components
            symmetry_score = 1.0 - (shoulder_diff / (self.sensitivity * 3 + 1e-10))
            head_prominence = abs(h_price - (ls_price + rs_price) / 2) / (
                abs(neckline) + 1e-10
            )
            prominence_score = min(head_prominence / 0.05, 1.0)
            neckline_flatness = 1.0 - min(
                abs(trough1 - trough2) / (abs(neckline) + 1e-10) / 0.02, 1.0
            )

            confidence = float(
                np.clip(
                    0.4 * symmetry_score
                    + 0.4 * prominence_score
                    + 0.2 * neckline_flatness,
                    0.0,
                    1.0,
                )
            )

            direction = "bullish" if inverse else "bearish"
            ptype = (
                "inverse_head_and_shoulders" if inverse else "head_and_shoulders"
            )
            desc_dir = "bullish reversal" if inverse else "bearish reversal"

            pattern = ChartPattern(
                pattern_type=ptype,
                direction=direction,
                confidence=confidence,
                start_index=ls_idx,
                end_index=rs_idx,
                key_levels={
                    "left_shoulder": round(float(ls_price), 5),
                    "head": round(float(h_price), 5),
                    "right_shoulder": round(float(rs_price), 5),
                    "neckline": round(neckline, 5),
                    "target": round(target, 5),
                },
                description=(
                    f"{'Inverse ' if inverse else ''}Head and Shoulders pattern "
                    f"detected ({desc_dir}). "
                    f"Neckline at {neckline:.4f}, target {target:.4f}."
                ),
            )
            patterns.append(pattern)

        return patterns

    # ================================================================
    # DOUBLE TOPS / DOUBLE BOTTOMS
    # ================================================================

    def detect_double_tops_bottoms(
        self, prices: pd.DataFrame
    ) -> List[ChartPattern]:
        """
        Detect Double Top (bearish) and Double Bottom (bullish) patterns.

        **Double Top**: two consecutive swing highs at approximately the same
        price, separated by a meaningful trough.

        **Double Bottom**: two consecutive swing lows at approximately the
        same price, separated by a meaningful peak.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`ChartPattern` objects.
        """
        if not self._validate_dataframe(prices):
            return []

        patterns: List[ChartPattern] = []

        try:
            highs_idx = self._find_swing_highs(prices)
            patterns.extend(
                self._scan_double_extrema(prices, highs_idx, top=True)
            )

            lows_idx = self._find_swing_lows(prices)
            patterns.extend(
                self._scan_double_extrema(prices, lows_idx, top=False)
            )
        except Exception as exc:
            logger.error(
                "Error detecting double tops/bottoms: %s", exc, exc_info=True
            )

        return patterns[: self.max_patterns_per_type]

    def _scan_double_extrema(
        self,
        prices: pd.DataFrame,
        pivot_indices: List[int],
        top: bool,
    ) -> List[ChartPattern]:
        """
        Scan pivot indices for double top or double bottom formations.

        Args:
            prices: OHLCV DataFrame.
            pivot_indices: Positional indices of swing highs (top) or lows.
            top: ``True`` for double top, ``False`` for double bottom.

        Returns:
            List of detected patterns.
        """
        patterns: List[ChartPattern] = []
        close = prices["close"].values
        n = len(pivot_indices)

        for i in range(n - 1):
            p1_idx = pivot_indices[i]
            p2_idx = pivot_indices[i + 1]

            # Require meaningful separation between the two extremes
            if p2_idx - p1_idx < self.swing_window * 2:
                continue

            p1_price = close[p1_idx]
            p2_price = close[p2_idx]

            # The two extremes must be at similar price levels
            price_diff = abs(p1_price - p2_price) / (abs(p1_price) + 1e-10)
            if price_diff > self.sensitivity:
                continue

            # The intermediate region must show a meaningful retracement
            middle_slice = close[p1_idx : p2_idx + 1]
            if len(middle_slice) < 3:
                continue

            avg_extreme = (p1_price + p2_price) / 2.0

            if top:
                middle_extreme = float(np.min(middle_slice))
                pullback_pct = (avg_extreme - middle_extreme) / (
                    avg_extreme + 1e-10
                )
                if pullback_pct < self.min_pullback_pct:
                    continue
                neckline = middle_extreme
                target = neckline - (avg_extreme - neckline)
            else:
                middle_extreme = float(np.max(middle_slice))
                pullback_pct = (middle_extreme - avg_extreme) / (
                    abs(avg_extreme) + 1e-10
                )
                if pullback_pct < self.min_pullback_pct:
                    continue
                neckline = middle_extreme
                target = neckline + (neckline - avg_extreme)

            similarity_score = 1.0 - (price_diff / (self.sensitivity + 1e-10))
            pullback_score = min(pullback_pct / (self.sensitivity * 3), 1.0)
            confidence = float(
                np.clip(
                    0.6 * similarity_score + 0.4 * pullback_score, 0.0, 1.0
                )
            )

            if top:
                ptype = "double_top"
                direction = "bearish"
                desc = (
                    f"Double Top at {avg_extreme:.4f}. "
                    f"Neckline at {neckline:.4f}, target {target:.4f}."
                )
            else:
                ptype = "double_bottom"
                direction = "bullish"
                desc = (
                    f"Double Bottom at {avg_extreme:.4f}. "
                    f"Neckline at {neckline:.4f}, target {target:.4f}."
                )

            pattern = ChartPattern(
                pattern_type=ptype,
                direction=direction,
                confidence=confidence,
                start_index=p1_idx,
                end_index=p2_idx,
                key_levels={
                    "peak_1": round(float(p1_price), 5),
                    "peak_2": round(float(p2_price), 5),
                    "neckline": round(neckline, 5),
                    "target": round(target, 5),
                },
                description=desc,
            )
            patterns.append(pattern)

        return patterns

    # ================================================================
    # TRIANGLES
    # ================================================================

    def detect_triangles(self, prices: pd.DataFrame) -> List[ChartPattern]:
        """
        Detect ascending, descending, and symmetrical triangle patterns.

        Triangles are identified by fitting linear trendlines to the swing
        highs (resistance) and swing lows (support).  The trendlines must
        converge over the window:

        - **Ascending triangle**: flat resistance, rising support → bullish.
        - **Descending triangle**: falling resistance, flat support → bearish.
        - **Symmetrical triangle**: falling resistance + rising support →
          neutral (direction of breakout determines bias).

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`ChartPattern` objects.
        """
        if (
            not self._validate_dataframe(prices)
            or len(prices) < self.triangle_min_bars
        ):
            return []

        patterns: List[ChartPattern] = []

        try:
            window_sizes = [
                self.triangle_min_bars,
                self.triangle_min_bars * 2,
                len(prices),
            ]
            seen_ends: set = set()

            for window in window_sizes:
                window = min(window, len(prices))
                start = len(prices) - window
                sub = prices.iloc[start:]
                detected = self._detect_triangle_in_window(sub, start)
                for p in detected:
                    if p.end_index not in seen_ends:
                        patterns.append(p)
                        seen_ends.add(p.end_index)
        except Exception as exc:
            logger.error("Error detecting triangles: %s", exc, exc_info=True)

        return patterns[: self.max_patterns_per_type]

    def _detect_triangle_in_window(
        self,
        prices: pd.DataFrame,
        index_offset: int,
    ) -> List[ChartPattern]:
        """
        Detect triangle patterns within a price sub-window.

        Args:
            prices: Sub-window of the OHLCV DataFrame.
            index_offset: Positional offset of the sub-window start in the
                original DataFrame.

        Returns:
            List of detected patterns (0 or 1 entries).
        """
        patterns: List[ChartPattern] = []
        high = prices["high"].values
        low = prices["low"].values
        close = prices["close"].values
        n = len(prices)

        if n < self.triangle_min_bars:
            return patterns

        x = np.arange(n, dtype=float)

        high_slope, high_intercept, high_r2 = self._fit_trendline(x, high)
        low_slope, low_intercept, low_r2 = self._fit_trendline(x, low)

        if high_r2 < 0.3 or low_r2 < 0.3:
            return patterns

        # Trendlines must converge
        convergence = high_slope - low_slope
        if convergence >= 0:
            return patterns

        # Classify by slope characteristics.
        # flat_threshold: slope magnitude that corresponds to < 5 % of total
        # price range over the full window.  This is relative to range/bar so
        # it works across all price scales.
        max_range = float(np.max(high) - np.min(low))
        if max_range <= 0:
            return patterns
        flat_threshold = max_range * 0.05 / n

        high_is_flat = abs(high_slope) < flat_threshold
        low_is_flat = abs(low_slope) < flat_threshold

        if high_is_flat and low_slope > flat_threshold:
            ptype = "ascending_triangle"
            direction = "bullish"
        elif low_is_flat and high_slope < -flat_threshold:
            ptype = "descending_triangle"
            direction = "bearish"
        elif high_slope < -flat_threshold and low_slope > flat_threshold:
            ptype = "symmetrical_triangle"
            direction = "neutral"
        else:
            return patterns

        # Apex: intersection of the two trendlines
        denom = high_slope - low_slope
        if abs(denom) < 1e-10:
            return patterns
        x_apex = (low_intercept - high_intercept) / denom
        apex_price = float(high_slope * x_apex + high_intercept)

        resistance_now = float(high_slope * (n - 1) + high_intercept)
        support_now = float(low_slope * (n - 1) + low_intercept)
        base_width = float(high[0] - low[0])

        if direction == "bullish":
            target = resistance_now + base_width
        elif direction == "bearish":
            target = support_now - base_width
        else:
            target = apex_price

        # max_range already computed above; reuse it for convergence scoring
        convergence_ratio = abs(convergence * n) / (max_range + 1e-10)
        # Best convergence_ratio ≈ 0.5 (half the range consumed over the window)
        convergence_score = (
            min(convergence_ratio / 0.5, 1.0)
            if convergence_ratio <= 0.5
            else max(0.0, 1.0 - (convergence_ratio - 0.5))
        )
        avg_r2 = (high_r2 + low_r2) / 2.0
        confidence = float(
            np.clip(0.7 * avg_r2 + 0.3 * convergence_score, 0.0, 1.0)
        )

        pattern = ChartPattern(
            pattern_type=ptype,
            direction=direction,
            confidence=confidence,
            start_index=index_offset,
            end_index=index_offset + n - 1,
            key_levels={
                "resistance": round(resistance_now, 5),
                "support": round(support_now, 5),
                "apex": round(apex_price, 5),
                "target": round(target, 5),
            },
            description=(
                f"{ptype.replace('_', ' ').title()} pattern detected "
                f"({direction}). "
                f"Resistance: {resistance_now:.4f}, "
                f"Support: {support_now:.4f}, "
                f"Apex at bar ~{int(x_apex)}, target {target:.4f}."
            ),
        )
        patterns.append(pattern)
        return patterns

    # ================================================================
    # FLAGS AND PENNANTS
    # ================================================================

    def detect_flags_pennants(self, prices: pd.DataFrame) -> List[ChartPattern]:
        """
        Detect flag and pennant continuation patterns.

        Both patterns share a strong directional move (the **pole**) followed
        by a lower-volatility consolidation phase:

        - **Bull / Bear Flag**: consolidation forms a slightly counter-trend
          parallel channel.
        - **Bull / Bear Pennant**: consolidation forms a converging
          (symmetrical) triangle.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`ChartPattern` objects.
        """
        if (
            not self._validate_dataframe(prices)
            or len(prices) < self.min_bars
        ):
            return []

        patterns: List[ChartPattern] = []

        try:
            close = prices["close"].values
            n = len(close)

            pole_lengths = [5, 8, 12]
            consolidation_lengths = [5, 8, 12]
            seen_keys: set = set()

            for pole_len in pole_lengths:
                for consol_len in consolidation_lengths:
                    required = pole_len + consol_len
                    if required > n:
                        continue
                    for end in range(required, n + 1):
                        pole_start = end - pole_len - consol_len
                        pole_end = pole_start + pole_len
                        consol_end = end

                        key = (pole_start, consol_end)
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)

                        detected = self._detect_flag_pennant(
                            prices, pole_start, pole_end - 1,
                            pole_end, consol_end - 1,
                        )
                        patterns.extend(detected)
        except Exception as exc:
            logger.error(
                "Error detecting flags/pennants: %s", exc, exc_info=True
            )

        unique = self._deduplicate_patterns(patterns)
        return unique[: self.max_patterns_per_type]

    def _detect_flag_pennant(
        self,
        prices: pd.DataFrame,
        pole_start: int,
        pole_end: int,
        consol_start: int,
        consol_end: int,
    ) -> List[ChartPattern]:
        """
        Attempt to classify a single pole + consolidation window as a flag or
        pennant.

        Args:
            prices: Full OHLCV DataFrame.
            pole_start: Positional start of the pole.
            pole_end: Positional end of the pole.
            consol_start: Positional start of the consolidation.
            consol_end: Positional end of the consolidation.

        Returns:
            List with at most one detected pattern.
        """
        close = prices["close"].values

        if pole_end >= len(close) or consol_end >= len(close):
            return []

        pole_move = close[pole_end] - close[pole_start]
        pole_pct = abs(pole_move) / (abs(close[pole_start]) + 1e-10)

        if pole_pct < self.flag_pole_min_pct:
            return []

        bull = pole_move > 0

        consol_high = prices["high"].values[consol_start : consol_end + 1]
        consol_low = prices["low"].values[consol_start : consol_end + 1]
        consol_close = close[consol_start : consol_end + 1]

        if len(consol_close) < 2:
            return []

        x = np.arange(len(consol_close), dtype=float)
        high_slope, high_intercept, high_r2 = self._fit_trendline(x, consol_high)
        low_slope, low_intercept, low_r2 = self._fit_trendline(x, consol_low)

        convergence = high_slope - low_slope
        is_pennant = convergence < 0

        # Flag: both trendlines roughly parallel (slope difference small)
        mean_price = float(np.mean(consol_close))
        is_flag = abs(high_slope - low_slope) < mean_price * 0.002

        if not (is_pennant or is_flag):
            return []

        # Consolidation must be counter-trend or sideways (not extending the move)
        consol_slope = (consol_close[-1] - consol_close[0]) / (
            len(consol_close) + 1e-10
        )
        if bull and consol_slope > pole_pct * 0.5 * mean_price:
            return []
        if not bull and consol_slope < -pole_pct * 0.5 * mean_price:
            return []

        pole_height = abs(pole_move)
        if bull:
            breakout_price = float(np.max(consol_high))
            target = breakout_price + pole_height
        else:
            breakout_price = float(np.min(consol_low))
            target = breakout_price - pole_height

        pole_score = min(pole_pct / (self.flag_pole_min_pct * 5), 1.0)
        r2_score = (high_r2 + low_r2) / 2.0
        confidence = float(np.clip(0.5 * pole_score + 0.5 * r2_score, 0.0, 1.0))

        if is_pennant:
            ptype = "bull_pennant" if bull else "bear_pennant"
            type_label = "Pennant"
        else:
            ptype = "bull_flag" if bull else "bear_flag"
            type_label = "Flag"

        direction = "bullish" if bull else "bearish"

        pattern = ChartPattern(
            pattern_type=ptype,
            direction=direction,
            confidence=confidence,
            start_index=pole_start,
            end_index=consol_end,
            key_levels={
                "pole_start": round(float(close[pole_start]), 5),
                "pole_end": round(float(close[pole_end]), 5),
                "pole_height": round(pole_height, 5),
                "breakout_level": round(breakout_price, 5),
                "target": round(target, 5),
            },
            description=(
                f"{'Bull' if bull else 'Bear'} {type_label} pattern detected "
                f"({direction} continuation). "
                f"Pole move: {pole_pct * 100:.2f}%, "
                f"target {target:.4f}."
            ),
        )
        return [pattern]

    # ================================================================
    # WEDGES
    # ================================================================

    def detect_wedges(self, prices: pd.DataFrame) -> List[ChartPattern]:
        """
        Detect rising and falling wedge patterns.

        A wedge is formed when both the resistance and support trendlines
        slope in the **same** direction but converge toward each other:

        - **Rising Wedge**: both trendlines slope upward, converging →
          bearish reversal signal.
        - **Falling Wedge**: both trendlines slope downward, converging →
          bullish reversal signal.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`ChartPattern` objects.
        """
        if (
            not self._validate_dataframe(prices)
            or len(prices) < self.triangle_min_bars
        ):
            return []

        patterns: List[ChartPattern] = []

        try:
            window_sizes = [
                self.triangle_min_bars,
                min(self.triangle_min_bars * 2, len(prices)),
            ]
            seen_ends: set = set()

            for window in window_sizes:
                window = min(window, len(prices))
                start = len(prices) - window
                sub = prices.iloc[start:]
                detected = self._detect_wedge_in_window(sub, start)
                for p in detected:
                    if p.end_index not in seen_ends:
                        patterns.append(p)
                        seen_ends.add(p.end_index)
        except Exception as exc:
            logger.error("Error detecting wedges: %s", exc, exc_info=True)

        return patterns[: self.max_patterns_per_type]

    def _detect_wedge_in_window(
        self,
        prices: pd.DataFrame,
        index_offset: int,
    ) -> List[ChartPattern]:
        """
        Detect a wedge pattern within a price sub-window.

        Args:
            prices: Sub-window of the OHLCV DataFrame.
            index_offset: Positional offset of the sub-window start in the
                original DataFrame.

        Returns:
            List of detected patterns (0 or 1 entries).
        """
        patterns: List[ChartPattern] = []
        high = prices["high"].values
        low = prices["low"].values
        close = prices["close"].values
        n = len(prices)

        x = np.arange(n, dtype=float)

        high_slope, high_intercept, high_r2 = self._fit_trendline(x, high)
        low_slope, low_intercept, low_r2 = self._fit_trendline(x, low)

        if high_r2 < 0.3 or low_r2 < 0.3:
            return patterns

        # Must converge (high slope < low slope when both positive, or |high| > |low| when both negative)
        convergence = high_slope - low_slope
        if convergence >= 0:
            return patterns

        both_up = high_slope > 0 and low_slope > 0
        both_down = high_slope < 0 and low_slope < 0

        if not (both_up or both_down):
            return patterns

        # Require at least 10 % compression of the channel width
        start_width = float(high[0] - low[0])
        end_width = float(high[-1] - low[-1])

        if start_width <= 1e-10:
            return patterns

        compression = (start_width - end_width) / start_width
        if compression < 0.10:
            return patterns

        price_range = float(np.mean(high) - np.mean(low))
        resistance_now = float(high_slope * (n - 1) + high_intercept)
        support_now = float(low_slope * (n - 1) + low_intercept)

        if both_up:
            ptype = "rising_wedge"
            direction = "bearish"
            target = support_now - price_range
        else:
            ptype = "falling_wedge"
            direction = "bullish"
            target = resistance_now + price_range

        avg_r2 = (high_r2 + low_r2) / 2.0
        compression_score = min(compression / 0.5, 1.0)
        confidence = float(
            np.clip(0.65 * avg_r2 + 0.35 * compression_score, 0.0, 1.0)
        )

        pattern = ChartPattern(
            pattern_type=ptype,
            direction=direction,
            confidence=confidence,
            start_index=index_offset,
            end_index=index_offset + n - 1,
            key_levels={
                "resistance": round(resistance_now, 5),
                "support": round(support_now, 5),
                "target": round(target, 5),
                "compression_pct": round(compression * 100, 2),
            },
            description=(
                f"{'Rising' if both_up else 'Falling'} Wedge detected "
                f"({direction} reversal signal). "
                f"Resistance: {resistance_now:.4f}, "
                f"Support: {support_now:.4f}, "
                f"Compression: {compression * 100:.1f}%, "
                f"target {target:.4f}."
            ),
        )
        patterns.append(pattern)
        return patterns

    # ================================================================
    # HELPER METHODS
    # ================================================================

    def _validate_dataframe(self, prices: pd.DataFrame) -> bool:
        """
        Validate that a DataFrame has the required columns and row count.

        Args:
            prices: DataFrame to validate.

        Returns:
            ``True`` if the DataFrame is suitable for pattern detection,
            ``False`` otherwise.
        """
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(prices.columns):
            missing = required_cols - set(prices.columns)
            logger.warning("Missing required columns: %s", missing)
            return False
        if len(prices) < self.min_bars:
            logger.debug(
                "Insufficient data: %d rows, minimum required %d",
                len(prices),
                self.min_bars,
            )
            return False
        return True

    def _find_swing_highs(self, prices: pd.DataFrame) -> List[int]:
        """
        Identify positional indices of swing high bars.

        A bar at index ``i`` is a swing high when its ``high`` value is
        greater than or equal to the ``high`` of every bar within
        ``swing_window`` bars on either side.

        Args:
            prices: OHLCV DataFrame.

        Returns:
            List of positional indices (integers) of confirmed swing highs.
        """
        high = prices["high"].values
        n = len(high)
        w = self.swing_window
        indices: List[int] = []

        for i in range(w, n - w):
            if high[i] >= np.max(high[i - w : i]) and high[i] >= np.max(
                high[i + 1 : i + w + 1]
            ):
                indices.append(i)

        return indices

    def _find_swing_lows(self, prices: pd.DataFrame) -> List[int]:
        """
        Identify positional indices of swing low bars.

        A bar at index ``i`` is a swing low when its ``low`` value is less
        than or equal to the ``low`` of every bar within ``swing_window``
        bars on either side.

        Args:
            prices: OHLCV DataFrame.

        Returns:
            List of positional indices (integers) of confirmed swing lows.
        """
        low = prices["low"].values
        n = len(low)
        w = self.swing_window
        indices: List[int] = []

        for i in range(w, n - w):
            if low[i] <= np.min(low[i - w : i]) and low[i] <= np.min(
                low[i + 1 : i + w + 1]
            ):
                indices.append(i)

        return indices

    def _fit_trendline(
        self,
        x: np.ndarray,
        y: np.ndarray,
    ) -> Tuple[float, float, float]:
        """
        Fit a linear trendline to an array of values.

        Args:
            x: Independent variable (bar indices).
            y: Dependent variable (price values).

        Returns:
            Tuple of ``(slope, intercept, r_squared)`` where ``r_squared``
            is clipped to ``[0, 1]``.  Returns ``(0.0, mean(y), 0.0)`` on
            failure.
        """
        if len(x) < 2:
            mean_y = float(np.mean(y)) if len(y) > 0 else 0.0
            return 0.0, mean_y, 0.0

        try:
            coeffs = np.polyfit(x, y, 1)
            slope = float(coeffs[0])
            intercept = float(coeffs[1])
            y_pred = slope * x + intercept
            ss_res = float(np.sum((y - y_pred) ** 2))
            ss_tot = float(np.sum((y - np.mean(y)) ** 2))
            r_squared = (
                1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 1.0
            )
            return slope, intercept, float(np.clip(r_squared, 0.0, 1.0))
        except (np.linalg.LinAlgError, ValueError) as exc:
            logger.debug("Trendline fit failed: %s", exc)
            mean_y = float(np.mean(y)) if len(y) > 0 else 0.0
            return 0.0, mean_y, 0.0

    def _deduplicate_patterns(
        self, patterns: List[ChartPattern]
    ) -> List[ChartPattern]:
        """
        Remove overlapping patterns of the same type, retaining the one with
        the highest confidence.

        Two patterns of the same type are considered overlapping when their
        ``start_index`` or ``end_index`` values are within
        ``min_bars // 2`` bars of each other.

        Args:
            patterns: Raw list of detected patterns (may contain duplicates).

        Returns:
            Deduplicated list sorted by confidence descending.
        """
        if not patterns:
            return []

        by_type: Dict[str, List[ChartPattern]] = {}
        for p in patterns:
            by_type.setdefault(p.pattern_type, []).append(p)

        overlap_threshold = max(self.min_bars // 2, 1)
        result: List[ChartPattern] = []

        for _ptype, group in by_type.items():
            group.sort(key=lambda p: p.confidence, reverse=True)
            kept: List[ChartPattern] = []
            for candidate in group:
                overlapping = any(
                    abs(candidate.start_index - k.start_index) < overlap_threshold
                    or abs(candidate.end_index - k.end_index) < overlap_threshold
                    for k in kept
                )
                if not overlapping:
                    kept.append(candidate)
            result.extend(kept)

        result.sort(key=lambda p: p.confidence, reverse=True)
        return result
