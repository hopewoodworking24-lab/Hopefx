"""
Candlestick Pattern Detection Module

Detects classic Japanese candlestick patterns from OHLCV price data:

Single-candle:  Doji, Hammer, Hanging Man, Shooting Star, Inverted Hammer,
                Marubozu, Spinning Top
Two-candle:     Bullish/Bearish Engulfing, Bullish/Bearish Harami,
                Piercing Line, Dark Cloud Cover
Three-candle:   Morning Star, Evening Star, Three White Soldiers,
                Three Black Crows

Usage:
    detector = CandlestickPatternDetector(config={'doji_threshold': 0.05})
    patterns = detector.detect_patterns(prices_df, min_confidence=0.5)
    for pattern in patterns:
        print(pattern.to_dict())
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ================================================================
# DATACLASS
# ================================================================

_REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


@dataclass
class CandlestickPattern:
    """
    Detected candlestick pattern with metadata.

    Attributes:
        pattern_name: Human-readable name (e.g., ``'Hammer'``, ``'Doji'``).
        pattern_type: Broad category of the pattern.
            One of ``'reversal'``, ``'continuation'``, or ``'indecision'``.
        direction: Expected price direction implied by the pattern.
            One of ``'bullish'``, ``'bearish'``, or ``'neutral'``.
        confidence: Detection confidence score in the range [0, 1].
        index: Positional integer index in the price DataFrame at which
            the **last** candle of the pattern occurs.
        candles_count: Number of candles that form the pattern (1, 2 or 3).
        description: Human-readable summary of the detected pattern.
        timestamp: UTC datetime of the last candle in the pattern.
    """

    pattern_name: str
    pattern_type: str
    direction: str
    confidence: float
    index: int
    candles_count: int
    description: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the pattern to a plain dictionary.

        Returns:
            Dict with all pattern fields, suitable for JSON serialisation.
        """
        return {
            "pattern_name": self.pattern_name,
            "pattern_type": self.pattern_type,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "index": self.index,
            "candles_count": self.candles_count,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
        }


# ================================================================
# DETECTOR
# ================================================================


class CandlestickPatternDetector:
    """
    Detects Japanese candlestick patterns from OHLCV price data.

    Supported single-candle patterns:
        Doji, Hammer, Hanging Man, Shooting Star, Inverted Hammer,
        Marubozu, Spinning Top

    Supported two-candle patterns:
        Bullish Engulfing, Bearish Engulfing, Bullish Harami,
        Bearish Harami, Piercing Line, Dark Cloud Cover

    Supported three-candle patterns:
        Morning Star, Evening Star, Three White Soldiers,
        Three Black Crows

    The prices DataFrame must have lowercase columns:
    ``open``, ``high``, ``low``, ``close``, ``volume`` and a datetime index.

    Usage:
        detector = CandlestickPatternDetector(config={'doji_threshold': 0.05})
        patterns = detector.detect_patterns(prices, min_confidence=0.5)
        for p in patterns:
            print(p.to_dict())
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the candlestick pattern detector.

        Args:
            config: Optional configuration dict. Supported keys:

                - ``doji_threshold`` (float): Maximum ratio of body size to
                  total candle range for a candle to qualify as a Doji.
                  Default ``0.05`` (5 %).
                - ``wick_ratio`` (float): Minimum ratio of wick length to
                  body size required for Hammer / Shooting Star patterns.
                  Default ``2.0``.
                - ``marubozu_threshold`` (float): Maximum ratio of total wick
                  length to body size for a Marubozu candle. Default ``0.05``.
                - ``spinning_top_body_ratio`` (float): Maximum ratio of body
                  to total range to qualify as a Spinning Top. Default ``0.3``.
                - ``engulfing_min_body_ratio`` (float): Minimum ratio by which
                  the engulfing body must exceed the prior body. Default ``1.0``.
                - ``star_gap_pct`` (float): Minimum fractional gap (of close
                  price) between the star body and the prior candle body for
                  Morning / Evening Star. Default ``0.0`` (gaps not required;
                  many data feeds include after-hours gaps already).
                - ``soldiers_crows_min_body_ratio`` (float): Minimum ratio of
                  body to range for each candle in Three White Soldiers / Three
                  Black Crows. Default ``0.6``.
                - ``max_patterns_per_type`` (int): Maximum patterns returned
                  per detection method. Default ``10``.
        """
        self.config: Dict = config or {}

        self.doji_threshold: float = self.config.get("doji_threshold", 0.05)
        self.wick_ratio: float = self.config.get("wick_ratio", 2.0)
        self.marubozu_threshold: float = self.config.get("marubozu_threshold", 0.05)
        self.spinning_top_body_ratio: float = self.config.get(
            "spinning_top_body_ratio", 0.3
        )
        self.engulfing_min_body_ratio: float = self.config.get(
            "engulfing_min_body_ratio", 1.0
        )
        self.star_gap_pct: float = self.config.get("star_gap_pct", 0.0)
        self.soldiers_crows_min_body_ratio: float = self.config.get(
            "soldiers_crows_min_body_ratio", 0.6
        )
        self.max_patterns_per_type: int = self.config.get("max_patterns_per_type", 10)

        # Lock for thread-safe access to any mutable state
        self._lock = threading.Lock()

        logger.info("CandlestickPatternDetector initialized with config=%s", self.config)

    # ================================================================
    # PUBLIC API
    # ================================================================

    def detect_patterns(
        self,
        prices: pd.DataFrame,
        min_confidence: float = 0.5,
    ) -> List[CandlestickPattern]:
        """
        Detect all supported candlestick patterns in the given price data.

        Runs every individual detection group and aggregates the results,
        filtering by ``min_confidence`` and sorting by index ascending (then
        confidence descending for ties).

        Args:
            prices: DataFrame with columns ``open``, ``high``, ``low``,
                ``close``, ``volume`` and a datetime index. Must contain at
                least 3 rows.
            min_confidence: Minimum confidence threshold (inclusive) for
                returned patterns. Must be in [0, 1]. Default ``0.5``.

        Returns:
            List of :class:`CandlestickPattern` objects sorted by index
            ascending, confidence descending within the same index.
        """
        if not self._validate_dataframe(prices):
            return []

        all_patterns: List[CandlestickPattern] = []

        detectors = [
            self.detect_single_candle_patterns,
            self.detect_two_candle_patterns,
            self.detect_three_candle_patterns,
        ]

        for detect_fn in detectors:
            try:
                all_patterns.extend(detect_fn(prices))
            except Exception as exc:
                logger.error(
                    "Error in %s: %s", detect_fn.__name__, exc, exc_info=True
                )

        filtered = [p for p in all_patterns if p.confidence >= min_confidence]
        filtered.sort(key=lambda p: (p.index, -p.confidence))

        logger.debug(
            "detect_patterns: found %d pattern(s) above confidence %.2f",
            len(filtered),
            min_confidence,
        )
        return filtered

    def detect_single_candle_patterns(
        self, prices: pd.DataFrame
    ) -> List[CandlestickPattern]:
        """
        Detect single-candle patterns across the entire price DataFrame.

        Detected patterns: Doji, Hammer, Hanging Man, Shooting Star,
        Inverted Hammer, Marubozu, Spinning Top.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`CandlestickPattern` objects.
        """
        if not self._validate_dataframe(prices):
            return []

        patterns: List[CandlestickPattern] = []
        o = prices["open"].values
        h = prices["high"].values
        lows = prices["low"].values
        c = prices["close"].values
        timestamps = prices.index

        for i in range(len(prices)):
            ts = self._to_utc_datetime(timestamps[i])
            candle_range = h[i] - lows[i]
            if candle_range <= 0:
                continue

            body = abs(c[i] - o[i])
            body_mid = (o[i] + c[i]) / 2.0
            upper_wick = h[i] - max(o[i], c[i])
            lower_wick = min(o[i], c[i]) - lows[i]
            is_bullish = c[i] >= o[i]

            # Use simple moving window (20 bars) to decide trend context
            trend = self._trend_context(c, i, window=20)

            # ---- Doji ----
            if body / candle_range <= self.doji_threshold:
                confidence = round(1.0 - (body / candle_range) / self.doji_threshold, 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Doji",
                        pattern_type="indecision",
                        direction="neutral",
                        confidence=min(confidence, 1.0),
                        index=i,
                        candles_count=1,
                        description=(
                            "Open and close are nearly equal, signalling market"
                            " indecision and a potential trend reversal."
                        ),
                        timestamp=ts,
                    )
                )
                continue  # A pure Doji supersedes other single-candle labels

            # ---- Marubozu ----
            total_wick = upper_wick + lower_wick
            if body > 0 and total_wick / body <= self.marubozu_threshold:
                confidence = round(
                    1.0 - (total_wick / body) / max(self.marubozu_threshold, 1e-9), 4
                )
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Marubozu",
                        pattern_type="continuation",
                        direction="bullish" if is_bullish else "bearish",
                        confidence=min(confidence, 1.0),
                        index=i,
                        candles_count=1,
                        description=(
                            "Full-body candle with virtually no wicks, indicating"
                            " strong momentum in the candle direction."
                        ),
                        timestamp=ts,
                    )
                )
                continue

            # ---- Spinning Top ----
            if (
                body / candle_range <= self.spinning_top_body_ratio
                and upper_wick > 0
                and lower_wick > 0
                and abs(upper_wick - lower_wick) / candle_range < 0.15
            ):
                confidence = round(
                    0.5
                    + 0.5 * (1.0 - body / (candle_range * self.spinning_top_body_ratio)),
                    4,
                )
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Spinning Top",
                        pattern_type="indecision",
                        direction="neutral",
                        confidence=min(confidence, 1.0),
                        index=i,
                        candles_count=1,
                        description=(
                            "Small body with approximately equal upper and lower wicks,"
                            " indicating indecision between buyers and sellers."
                        ),
                        timestamp=ts,
                    )
                )
                continue

            # ---- Hammer / Hanging Man ----
            # Long lower wick, small upper wick, body in upper portion
            if (
                body > 0
                and lower_wick / body >= self.wick_ratio
                and upper_wick / candle_range <= 0.1
            ):
                confidence = round(
                    min(lower_wick / (body * self.wick_ratio), 1.0) * 0.85 + 0.1, 4
                )
                if trend == "downtrend":
                    patterns.append(
                        CandlestickPattern(
                            pattern_name="Hammer",
                            pattern_type="reversal",
                            direction="bullish",
                            confidence=confidence,
                            index=i,
                            candles_count=1,
                            description=(
                                "Long lower wick with small body near the high,"
                                " appearing after a downtrend; bullish reversal signal."
                            ),
                            timestamp=ts,
                        )
                    )
                else:
                    patterns.append(
                        CandlestickPattern(
                            pattern_name="Hanging Man",
                            pattern_type="reversal",
                            direction="bearish",
                            confidence=confidence * 0.9,
                            index=i,
                            candles_count=1,
                            description=(
                                "Long lower wick with small body near the high,"
                                " appearing after an uptrend; bearish reversal signal."
                            ),
                            timestamp=ts,
                        )
                    )

            # ---- Shooting Star / Inverted Hammer ----
            # Long upper wick, small lower wick, body in lower portion
            elif (
                body > 0
                and upper_wick / body >= self.wick_ratio
                and lower_wick / candle_range <= 0.1
            ):
                confidence = round(
                    min(upper_wick / (body * self.wick_ratio), 1.0) * 0.85 + 0.1, 4
                )
                if trend == "uptrend":
                    patterns.append(
                        CandlestickPattern(
                            pattern_name="Shooting Star",
                            pattern_type="reversal",
                            direction="bearish",
                            confidence=confidence,
                            index=i,
                            candles_count=1,
                            description=(
                                "Long upper wick with small body near the low,"
                                " appearing after an uptrend; bearish reversal signal."
                            ),
                            timestamp=ts,
                        )
                    )
                else:
                    patterns.append(
                        CandlestickPattern(
                            pattern_name="Inverted Hammer",
                            pattern_type="reversal",
                            direction="bullish",
                            confidence=confidence * 0.9,
                            index=i,
                            candles_count=1,
                            description=(
                                "Long upper wick with small body near the low,"
                                " appearing after a downtrend; bullish reversal signal."
                            ),
                            timestamp=ts,
                        )
                    )

        return patterns[: self.max_patterns_per_type]

    def detect_two_candle_patterns(
        self, prices: pd.DataFrame
    ) -> List[CandlestickPattern]:
        """
        Detect two-candle patterns across the entire price DataFrame.

        Detected patterns: Bullish Engulfing, Bearish Engulfing,
        Bullish Harami, Bearish Harami, Piercing Line, Dark Cloud Cover.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`CandlestickPattern` objects.
        """
        if not self._validate_dataframe(prices) or len(prices) < 2:
            return []

        patterns: List[CandlestickPattern] = []
        o = prices["open"].values
        h = prices["high"].values
        lows = prices["low"].values
        c = prices["close"].values
        timestamps = prices.index

        for i in range(1, len(prices)):
            ts = self._to_utc_datetime(timestamps[i])
            p_o, p_c = o[i - 1], c[i - 1]  # prior candle
            c_o, c_c = o[i], c[i]           # current candle

            p_body = abs(p_c - p_o)
            c_body = abs(c_c - c_o)

            p_is_bull = p_c >= p_o
            c_is_bull = c_c >= c_o

            p_body_high = max(p_o, p_c)
            p_body_low = min(p_o, p_c)
            c_body_high = max(c_o, c_c)
            c_body_low = min(c_o, c_c)

            trend = self._trend_context(c, i, window=20)

            if p_body <= 0 or c_body <= 0:
                continue

            # ---- Bullish Engulfing ----
            if (
                not p_is_bull
                and c_is_bull
                and c_body >= p_body * self.engulfing_min_body_ratio
                and c_o <= p_c
                and c_c >= p_o
            ):
                ratio = min(c_body / p_body, 2.0)
                confidence = round(0.5 + 0.4 * min(ratio / 1.5, 1.0), 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Bullish Engulfing",
                        pattern_type="reversal",
                        direction="bullish",
                        confidence=confidence,
                        index=i,
                        candles_count=2,
                        description=(
                            "A large bullish candle fully engulfs the prior bearish"
                            " candle; strong bullish reversal signal."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Bearish Engulfing ----
            elif (
                p_is_bull
                and not c_is_bull
                and c_body >= p_body * self.engulfing_min_body_ratio
                and c_o >= p_c
                and c_c <= p_o
            ):
                ratio = min(c_body / p_body, 2.0)
                confidence = round(0.5 + 0.4 * min(ratio / 1.5, 1.0), 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Bearish Engulfing",
                        pattern_type="reversal",
                        direction="bearish",
                        confidence=confidence,
                        index=i,
                        candles_count=2,
                        description=(
                            "A large bearish candle fully engulfs the prior bullish"
                            " candle; strong bearish reversal signal."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Bullish Harami ----
            elif (
                not p_is_bull
                and c_is_bull
                and c_body_high <= p_body_high
                and c_body_low >= p_body_low
                and c_body < p_body
            ):
                containment = 1.0 - c_body / p_body
                confidence = round(0.5 + 0.35 * containment, 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Bullish Harami",
                        pattern_type="reversal",
                        direction="bullish",
                        confidence=confidence,
                        index=i,
                        candles_count=2,
                        description=(
                            "A small bullish candle contained within the prior large"
                            " bearish candle; potential bullish reversal."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Bearish Harami ----
            elif (
                p_is_bull
                and not c_is_bull
                and c_body_high <= p_body_high
                and c_body_low >= p_body_low
                and c_body < p_body
            ):
                containment = 1.0 - c_body / p_body
                confidence = round(0.5 + 0.35 * containment, 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Bearish Harami",
                        pattern_type="reversal",
                        direction="bearish",
                        confidence=confidence,
                        index=i,
                        candles_count=2,
                        description=(
                            "A small bearish candle contained within the prior large"
                            " bullish candle; potential bearish reversal."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Piercing Line ----
            # Prior bearish candle, current bullish opens below prior low
            # and closes above midpoint of prior body
            elif (
                not p_is_bull
                and c_is_bull
                and c_o < p_c
                and c_c > p_o + p_body * 0.5
                and c_c < p_o
            ):
                penetration = (c_c - p_c) / p_body
                confidence = round(0.5 + 0.45 * min(penetration, 1.0), 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Piercing Line",
                        pattern_type="reversal",
                        direction="bullish",
                        confidence=confidence,
                        index=i,
                        candles_count=2,
                        description=(
                            "A bullish candle opens below the prior close and closes"
                            " above the midpoint of the prior bearish body;"
                            " bullish reversal signal."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Dark Cloud Cover ----
            # Prior bullish candle, current bearish opens above prior high
            # and closes below midpoint of prior body
            elif (
                p_is_bull
                and not c_is_bull
                and c_o > p_c
                and c_c < p_o + p_body * 0.5
                and c_c > p_o
            ):
                penetration = (p_c - c_c) / p_body
                confidence = round(0.5 + 0.45 * min(penetration, 1.0), 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Dark Cloud Cover",
                        pattern_type="reversal",
                        direction="bearish",
                        confidence=confidence,
                        index=i,
                        candles_count=2,
                        description=(
                            "A bearish candle opens above the prior close and closes"
                            " below the midpoint of the prior bullish body;"
                            " bearish reversal signal."
                        ),
                        timestamp=ts,
                    )
                )

        return patterns[: self.max_patterns_per_type]

    def detect_three_candle_patterns(
        self, prices: pd.DataFrame
    ) -> List[CandlestickPattern]:
        """
        Detect three-candle patterns across the entire price DataFrame.

        Detected patterns: Morning Star, Evening Star,
        Three White Soldiers, Three Black Crows.

        Args:
            prices: OHLCV DataFrame with datetime index.

        Returns:
            List of detected :class:`CandlestickPattern` objects.
        """
        if not self._validate_dataframe(prices) or len(prices) < 3:
            return []

        patterns: List[CandlestickPattern] = []
        o = prices["open"].values
        h = prices["high"].values
        lows = prices["low"].values
        c = prices["close"].values
        timestamps = prices.index

        for i in range(2, len(prices)):
            ts = self._to_utc_datetime(timestamps[i])

            # Candle indices: first=i-2, second=i-1, third=i
            o1, c1 = o[i - 2], c[i - 2]
            o2, c2 = o[i - 1], c[i - 1]
            o3, c3 = o[i], c[i]

            h1, l1 = h[i - 2], lows[i - 2]
            h2, l2 = h[i - 1], lows[i - 1]
            h3, l3 = h[i], lows[i]

            body1 = abs(c1 - o1)
            body2 = abs(c2 - o2)
            body3 = abs(c3 - o3)

            range1 = h1 - l1
            range2 = h2 - l2
            range3 = h3 - l3

            is_bull1 = c1 >= o1
            is_bull2 = c2 >= o2
            is_bull3 = c3 >= o3

            if range1 <= 0 or range3 <= 0:
                continue

            # ---- Morning Star ----
            # Candle 1: large bearish; Candle 2: small body (star) gaps down;
            # Candle 3: large bullish closing well into candle 1 body
            if (
                not is_bull1
                and body1 / range1 >= 0.5
                and body2 / max(range2, 1e-9) <= 0.35
                and is_bull3
                and body3 / range3 >= 0.5
                and c3 > o1 + body1 * 0.5
                and max(o2, c2) < min(o1, c1)
            ):
                penetration = (c3 - (o1 - body1 * 0.5)) / body1
                confidence = round(0.55 + 0.40 * min(penetration, 1.0), 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Morning Star",
                        pattern_type="reversal",
                        direction="bullish",
                        confidence=min(confidence, 0.95),
                        index=i,
                        candles_count=3,
                        description=(
                            "Three-candle bullish reversal: large bearish candle,"
                            " small star candle gapping down, followed by a large"
                            " bullish candle closing into the first candle's body."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Evening Star ----
            # Candle 1: large bullish; Candle 2: small body (star) gaps up;
            # Candle 3: large bearish closing well into candle 1 body
            elif (
                is_bull1
                and body1 / range1 >= 0.5
                and body2 / max(range2, 1e-9) <= 0.35
                and not is_bull3
                and body3 / range3 >= 0.5
                and c3 < o1 + body1 * 0.5
                and min(o2, c2) > max(o1, c1)
            ):
                penetration = ((o1 + body1 * 0.5) - c3) / body1
                confidence = round(0.55 + 0.40 * min(penetration, 1.0), 4)
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Evening Star",
                        pattern_type="reversal",
                        direction="bearish",
                        confidence=min(confidence, 0.95),
                        index=i,
                        candles_count=3,
                        description=(
                            "Three-candle bearish reversal: large bullish candle,"
                            " small star candle gapping up, followed by a large"
                            " bearish candle closing into the first candle's body."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Three White Soldiers ----
            # Three consecutive bullish candles, each closing higher with
            # large bodies and opening within the prior body
            elif (
                is_bull1
                and is_bull2
                and is_bull3
                and c3 > c2 > c1
                and body1 / range1 >= self.soldiers_crows_min_body_ratio
                and body2 / range2 >= self.soldiers_crows_min_body_ratio
                and body3 / range3 >= self.soldiers_crows_min_body_ratio
                and o2 >= o1
                and o2 <= c1
                and o3 >= o2
                and o3 <= c2
            ):
                avg_body_ratio = (
                    body1 / range1 + body2 / range2 + body3 / range3
                ) / 3.0
                confidence = round(
                    0.6 + 0.35 * min(avg_body_ratio / self.soldiers_crows_min_body_ratio - 1.0, 1.0),
                    4,
                )
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Three White Soldiers",
                        pattern_type="continuation",
                        direction="bullish",
                        confidence=min(confidence, 0.95),
                        index=i,
                        candles_count=3,
                        description=(
                            "Three consecutive large bullish candles each closing"
                            " progressively higher; strong bullish continuation signal."
                        ),
                        timestamp=ts,
                    )
                )

            # ---- Three Black Crows ----
            # Three consecutive bearish candles, each closing lower with
            # large bodies and opening within the prior body
            elif (
                not is_bull1
                and not is_bull2
                and not is_bull3
                and c3 < c2 < c1
                and body1 / range1 >= self.soldiers_crows_min_body_ratio
                and body2 / range2 >= self.soldiers_crows_min_body_ratio
                and body3 / range3 >= self.soldiers_crows_min_body_ratio
                and o2 <= o1
                and o2 >= c1
                and o3 <= o2
                and o3 >= c2
            ):
                avg_body_ratio = (
                    body1 / range1 + body2 / range2 + body3 / range3
                ) / 3.0
                confidence = round(
                    0.6 + 0.35 * min(avg_body_ratio / self.soldiers_crows_min_body_ratio - 1.0, 1.0),
                    4,
                )
                patterns.append(
                    CandlestickPattern(
                        pattern_name="Three Black Crows",
                        pattern_type="continuation",
                        direction="bearish",
                        confidence=min(confidence, 0.95),
                        index=i,
                        candles_count=3,
                        description=(
                            "Three consecutive large bearish candles each closing"
                            " progressively lower; strong bearish continuation signal."
                        ),
                        timestamp=ts,
                    )
                )

        return patterns[: self.max_patterns_per_type]

    def get_pattern_at_index(
        self,
        patterns: List[CandlestickPattern],
        index: int,
    ) -> List[CandlestickPattern]:
        """
        Filter a list of patterns to those occurring at a specific index.

        Args:
            patterns: List of :class:`CandlestickPattern` objects to filter.
            index: Positional integer index in the originating price DataFrame.

        Returns:
            List of patterns whose ``index`` attribute equals ``index``,
            sorted by confidence descending.
        """
        result = [p for p in patterns if p.index == index]
        result.sort(key=lambda p: p.confidence, reverse=True)
        return result

    # ================================================================
    # PRIVATE HELPERS
    # ================================================================

    def _validate_dataframe(self, prices: pd.DataFrame) -> bool:
        """
        Validate that the prices DataFrame has the required structure.

        Args:
            prices: DataFrame to validate.

        Returns:
            ``True`` if the DataFrame is valid; ``False`` otherwise (a
            warning is logged).
        """
        if not isinstance(prices, pd.DataFrame):
            logger.warning("prices must be a pandas DataFrame")
            return False

        missing = _REQUIRED_COLUMNS - set(prices.columns)
        if missing:
            logger.warning("prices DataFrame missing columns: %s", missing)
            return False

        if len(prices) < 1:
            logger.warning("prices DataFrame is empty")
            return False

        return True

    def _trend_context(
        self,
        close: np.ndarray,
        index: int,
        window: int = 20,
    ) -> str:
        """
        Determine the trend context at a given index using a simple
        linear-regression slope over the preceding ``window`` bars.

        Args:
            close: Array of close prices.
            index: Current bar index.
            window: Look-back window for slope calculation. Default ``20``.

        Returns:
            One of ``'uptrend'``, ``'downtrend'``, or ``'sideways'``.
        """
        start = max(0, index - window + 1)
        segment = close[start : index + 1]
        if len(segment) < 3:
            return "sideways"

        x = np.arange(len(segment), dtype=float)
        slope = np.polyfit(x, segment, 1)[0]

        # Normalise slope by average price to get a percentage-per-bar figure
        avg_price = np.mean(segment)
        if avg_price <= 0:
            return "sideways"

        normalised_slope = slope / avg_price
        threshold = 0.0005  # 0.05 % per bar

        if normalised_slope > threshold:
            return "uptrend"
        if normalised_slope < -threshold:
            return "downtrend"
        return "sideways"

    @staticmethod
    def _to_utc_datetime(ts: Any) -> datetime:
        """
        Convert an arbitrary timestamp value to a UTC-aware datetime.

        Args:
            ts: Timestamp from a pandas DatetimeIndex entry (numpy
                datetime64, pandas Timestamp, or datetime).

        Returns:
            UTC-aware :class:`datetime` object.
        """
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)

        try:
            pd_ts = pd.Timestamp(ts)
            if pd_ts.tzinfo is None:
                pd_ts = pd_ts.tz_localize("UTC")
            return pd_ts.to_pydatetime().astimezone(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)
