"""
Enhanced Drawing Tools for Charts

Phase 20: Provides professional-grade chart drawing tools including:
- Trendlines and channels
- Fibonacci retracements and extensions
- Pitchfork (Andrews' Pitchfork)
- Elliott wave annotations
- Horizontal bands and vertical lines
- Rectangle and text annotations
- Drawing serialisation (to_dict / from_dict)
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DrawingType:
    """Supported drawing types."""
    TRENDLINE = "trendline"
    HORIZONTAL_LINE = "horizontal_line"
    VERTICAL_LINE = "vertical_line"
    RECTANGLE = "rectangle"
    HORIZONTAL_BAND = "horizontal_band"
    FIBONACCI_RETRACEMENT = "fibonacci_retracement"
    FIBONACCI_EXTENSION = "fibonacci_extension"
    PITCHFORK = "pitchfork"
    CHANNEL = "channel"
    ELLIOTT_WAVE = "elliott_wave"
    TEXT = "text"
    ARROW = "arrow"


class Drawing:
    """
    A single chart drawing object.

    Attributes:
        drawing_id: Unique identifier.
        drawing_type: Type of drawing (see DrawingType).
        properties: Drawing-specific properties dict.
        visible: Whether the drawing is visible.
        color: Drawing colour (hex or CSS name).
        line_width: Line width in pixels.
        created_at: Creation timestamp.
    """

    def __init__(
        self,
        drawing_type: str,
        drawing_id: Optional[str] = None,
        color: str = "#2196F3",
        line_width: int = 1,
    ):
        self.drawing_type = drawing_type
        self.drawing_id = drawing_id or f"{drawing_type}_{datetime.utcnow().timestamp()}"
        self.color = color
        self.line_width = line_width
        self.visible = True
        self.properties: Dict[str, Any] = {}
        self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Serialise drawing to a dictionary."""
        return {
            "drawing_id": self.drawing_id,
            "drawing_type": self.drawing_type,
            "color": self.color,
            "line_width": self.line_width,
            "visible": self.visible,
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Drawing":
        """Deserialise a Drawing from a dictionary."""
        obj = cls(
            drawing_type=data["drawing_type"],
            drawing_id=data.get("drawing_id"),
            color=data.get("color", "#2196F3"),
            line_width=data.get("line_width", 1),
        )
        obj.visible = data.get("visible", True)
        obj.properties = data.get("properties", {})
        return obj

    def __repr__(self) -> str:
        return f"Drawing(type={self.drawing_type!r}, id={self.drawing_id!r})"


class DrawingToolkit:
    """
    Professional chart drawing toolkit.

    Provides methods to add, retrieve, show/hide, update and remove drawings.
    All drawings are stored by their unique drawing_id so they can be
    referenced later.
    """

    def __init__(self):
        self.drawings: Dict[str, Drawing] = {}

    # ------------------------------------------------------------------
    # Trendline
    # ------------------------------------------------------------------

    def draw_trendline(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        color: str = "#2196F3",
        line_width: int = 1,
        extend: bool = False,
    ) -> Drawing:
        """
        Draw a trendline between two price/time coordinates.

        Args:
            start_time: Start timestamp.
            start_price: Price at start.
            end_time: End timestamp.
            end_price: Price at end.
            color: Line colour.
            line_width: Line thickness.
            extend: Whether to extend the line beyond end_time.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.TRENDLINE, color=color, line_width=line_width)
        drawing.properties = {
            "start_time": start_time.isoformat() if isinstance(start_time, datetime) else start_time,
            "start_price": start_price,
            "end_time": end_time.isoformat() if isinstance(end_time, datetime) else end_time,
            "end_price": end_price,
            "extend": extend,
            # slope = price change per second; clamped to minimum 1 second to
            # avoid division-by-zero when start_time == end_time.
            "slope": (end_price - start_price) / max(
                (end_time - start_time).total_seconds(), 1
            ) if isinstance(start_time, datetime) and isinstance(end_time, datetime) else 0,
        }
        self.drawings[drawing.drawing_id] = drawing
        logger.debug("Drew trendline %s", drawing.drawing_id)
        return drawing

    # ------------------------------------------------------------------
    # Horizontal line
    # ------------------------------------------------------------------

    def draw_horizontal_line(
        self,
        price: float,
        color: str = "#FF9800",
        line_width: int = 1,
        label: Optional[str] = None,
        style: str = "solid",
    ) -> Drawing:
        """
        Draw a horizontal price level line.

        Args:
            price: Price level.
            color: Line colour.
            line_width: Line thickness.
            label: Optional text label.
            style: Line style ('solid', 'dashed', 'dotted').

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.HORIZONTAL_LINE, color=color, line_width=line_width)
        drawing.properties = {
            "price": price,
            "label": label or f"{price:.5f}",
            "style": style,
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Vertical line
    # ------------------------------------------------------------------

    def draw_vertical_line(
        self,
        time: datetime,
        color: str = "#9C27B0",
        line_width: int = 1,
        label: Optional[str] = None,
        style: str = "dashed",
    ) -> Drawing:
        """
        Draw a vertical time marker.

        Args:
            time: Timestamp of the vertical line.
            color: Line colour.
            line_width: Line thickness.
            label: Optional text label.
            style: Line style.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.VERTICAL_LINE, color=color, line_width=line_width)
        drawing.properties = {
            "time": time.isoformat() if isinstance(time, datetime) else time,
            "label": label or "",
            "style": style,
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Rectangle
    # ------------------------------------------------------------------

    def draw_rectangle(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        color: str = "#4CAF50",
        fill_opacity: float = 0.1,
    ) -> Drawing:
        """
        Draw a price/time rectangle (supply/demand zone, etc.).

        Args:
            start_time: Top-left timestamp.
            start_price: Top price level.
            end_time: Bottom-right timestamp.
            end_price: Bottom price level.
            color: Border and fill colour.
            fill_opacity: Fill opacity (0–1).

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.RECTANGLE, color=color)
        drawing.properties = {
            "start_time": start_time.isoformat() if isinstance(start_time, datetime) else start_time,
            "start_price": start_price,
            "end_time": end_time.isoformat() if isinstance(end_time, datetime) else end_time,
            "end_price": end_price,
            "fill_opacity": max(0.0, min(1.0, fill_opacity)),
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Horizontal band
    # ------------------------------------------------------------------

    def draw_horizontal_band(
        self,
        upper_price: float,
        lower_price: float,
        color: str = "#FFC107",
        fill_opacity: float = 0.15,
        label: Optional[str] = None,
    ) -> Drawing:
        """
        Draw a horizontal price band (e.g. support/resistance zone).

        Args:
            upper_price: Upper bound of the band.
            lower_price: Lower bound of the band.
            color: Band colour.
            fill_opacity: Fill opacity (0–1).
            label: Optional text label.

        Returns:
            The created Drawing object.
        """
        if upper_price < lower_price:
            upper_price, lower_price = lower_price, upper_price
        drawing = Drawing(DrawingType.HORIZONTAL_BAND, color=color)
        drawing.properties = {
            "upper_price": upper_price,
            "lower_price": lower_price,
            "fill_opacity": max(0.0, min(1.0, fill_opacity)),
            "label": label or f"{lower_price:.5f} – {upper_price:.5f}",
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Fibonacci retracement
    # ------------------------------------------------------------------

    def draw_fibonacci(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        levels: Optional[List[float]] = None,
        color: str = "#FF5722",
    ) -> Drawing:
        """
        Draw Fibonacci retracement levels.

        The levels are computed as::

            price_at_level = end_price - level * (end_price - start_price)

        Args:
            start_time: Swing start timestamp.
            start_price: Swing start price (e.g. swing low).
            end_time: Swing end timestamp.
            end_price: Swing end price (e.g. swing high).
            levels: Fibonacci ratios to draw (default: standard set).
            color: Line colour.

        Returns:
            The created Drawing object.
        """
        if levels is None:
            levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

        price_range = end_price - start_price
        level_prices = {
            f"{int(lvl * 100)}%": end_price - lvl * price_range
            for lvl in levels
        }

        drawing = Drawing(DrawingType.FIBONACCI_RETRACEMENT, color=color)
        drawing.properties = {
            "start_time": start_time.isoformat() if isinstance(start_time, datetime) else start_time,
            "start_price": start_price,
            "end_time": end_time.isoformat() if isinstance(end_time, datetime) else end_time,
            "end_price": end_price,
            "levels": levels,
            "level_prices": level_prices,
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Fibonacci extension
    # ------------------------------------------------------------------

    def draw_fibonacci_extension(
        self,
        point_a_time: datetime,
        point_a_price: float,
        point_b_time: datetime,
        point_b_price: float,
        point_c_time: datetime,
        point_c_price: float,
        levels: Optional[List[float]] = None,
        color: str = "#E91E63",
    ) -> Drawing:
        """
        Draw Fibonacci extension levels (3-point tool).

        Extension prices are calculated as::

            price = point_c_price + level * (point_b_price - point_a_price)

        Args:
            point_a_time: Point A timestamp.
            point_a_price: Point A price.
            point_b_time: Point B timestamp.
            point_b_price: Point B price.
            point_c_time: Point C timestamp.
            point_c_price: Point C price (retracement end).
            levels: Extension ratios (default: 1.272, 1.414, 1.618, 2.0, 2.618).
            color: Line colour.

        Returns:
            The created Drawing object.
        """
        if levels is None:
            levels = [1.272, 1.414, 1.618, 2.0, 2.618]

        swing = point_b_price - point_a_price
        level_prices = {
            f"{lvl:.3f}": point_c_price + lvl * swing
            for lvl in levels
        }

        drawing = Drawing(DrawingType.FIBONACCI_EXTENSION, color=color)
        drawing.properties = {
            "point_a_time": point_a_time.isoformat() if isinstance(point_a_time, datetime) else point_a_time,
            "point_a_price": point_a_price,
            "point_b_time": point_b_time.isoformat() if isinstance(point_b_time, datetime) else point_b_time,
            "point_b_price": point_b_price,
            "point_c_time": point_c_time.isoformat() if isinstance(point_c_time, datetime) else point_c_time,
            "point_c_price": point_c_price,
            "levels": levels,
            "level_prices": level_prices,
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Pitchfork (Andrews' Pitchfork)
    # ------------------------------------------------------------------

    def draw_pitchfork(
        self,
        pivot_time: datetime,
        pivot_price: float,
        high_time: datetime,
        high_price: float,
        low_time: datetime,
        low_price: float,
        color: str = "#00BCD4",
    ) -> Drawing:
        """
        Draw an Andrews' Pitchfork from three pivot points.

        The median line runs from the pivot to the midpoint of the
        high and low handles.

        Args:
            pivot_time: Handle pivot timestamp.
            pivot_price: Handle pivot price.
            high_time: Upper handle timestamp.
            high_price: Upper handle price.
            low_time: Lower handle timestamp.
            low_price: Lower handle price.
            color: Line colour.

        Returns:
            The created Drawing object.
        """
        midpoint_price = (high_price + low_price) / 2.0

        drawing = Drawing(DrawingType.PITCHFORK, color=color)
        drawing.properties = {
            "pivot_time": pivot_time.isoformat() if isinstance(pivot_time, datetime) else pivot_time,
            "pivot_price": pivot_price,
            "high_time": high_time.isoformat() if isinstance(high_time, datetime) else high_time,
            "high_price": high_price,
            "low_time": low_time.isoformat() if isinstance(low_time, datetime) else low_time,
            "low_price": low_price,
            "midpoint_price": midpoint_price,
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Channel (parallel trendlines)
    # ------------------------------------------------------------------

    def draw_channel(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        channel_width: float,
        color: str = "#3F51B5",
    ) -> Drawing:
        """
        Draw a price channel (two parallel trendlines).

        Args:
            start_time: Channel start timestamp.
            start_price: Centre-line start price.
            end_time: Channel end timestamp.
            end_price: Centre-line end price.
            channel_width: Half-width of the channel in price units.
            color: Line colour.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.CHANNEL, color=color)
        drawing.properties = {
            "start_time": start_time.isoformat() if isinstance(start_time, datetime) else start_time,
            "start_price": start_price,
            "end_time": end_time.isoformat() if isinstance(end_time, datetime) else end_time,
            "end_price": end_price,
            "channel_width": channel_width,
            "upper_start": start_price + channel_width,
            "upper_end": end_price + channel_width,
            "lower_start": start_price - channel_width,
            "lower_end": end_price - channel_width,
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Elliott Wave annotation
    # ------------------------------------------------------------------

    def draw_elliott_wave(
        self,
        wave_points: List[Dict[str, Any]],
        wave_type: str = "impulse",
        color: str = "#8BC34A",
    ) -> Drawing:
        """
        Annotate Elliott Wave pivots on the chart.

        Args:
            wave_points: List of dicts with keys ``time``, ``price``,
                         and ``label`` (e.g. '1', '2', …, '5' or 'A', 'B', 'C').
            wave_type: 'impulse' or 'corrective'.
            color: Line colour.

        Returns:
            The created Drawing object.

        Raises:
            ValueError: If fewer than 2 wave points are provided.
        """
        if len(wave_points) < 2:
            raise ValueError("At least 2 wave points are required for an Elliott Wave drawing.")

        drawing = Drawing(DrawingType.ELLIOTT_WAVE, color=color)
        drawing.properties = {
            "wave_points": wave_points,
            "wave_type": wave_type,
            "wave_count": len(wave_points),
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Text annotation
    # ------------------------------------------------------------------

    def draw_text(
        self,
        time: datetime,
        price: float,
        text: str,
        color: str = "#FFFFFF",
        font_size: int = 12,
        background: Optional[str] = None,
    ) -> Drawing:
        """
        Add a text annotation at a specific price/time coordinate.

        Args:
            time: Annotation timestamp.
            price: Price level for the annotation.
            text: Annotation text.
            color: Text colour.
            font_size: Font size in points.
            background: Optional background colour.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.TEXT, color=color)
        drawing.properties = {
            "time": time.isoformat() if isinstance(time, datetime) else time,
            "price": price,
            "text": text,
            "font_size": font_size,
            "background": background,
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Arrow annotation
    # ------------------------------------------------------------------

    def draw_arrow(
        self,
        time: datetime,
        price: float,
        direction: str = "up",
        color: str = "#4CAF50",
        size: int = 12,
        label: Optional[str] = None,
    ) -> Drawing:
        """
        Draw an up/down arrow marker at a price/time coordinate.

        Args:
            time: Arrow timestamp.
            price: Price level.
            direction: 'up' or 'down'.
            color: Arrow colour.
            size: Arrow size in pixels.
            label: Optional text label next to the arrow.

        Returns:
            The created Drawing object.

        Raises:
            ValueError: If direction is not 'up' or 'down'.
        """
        if direction not in ("up", "down"):
            raise ValueError(f"Arrow direction must be 'up' or 'down', got {direction!r}.")

        drawing = Drawing(DrawingType.ARROW, color=color)
        drawing.properties = {
            "time": time.isoformat() if isinstance(time, datetime) else time,
            "price": price,
            "direction": direction,
            "size": size,
            "label": label or "",
        }
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    # ------------------------------------------------------------------
    # Management helpers
    # ------------------------------------------------------------------

    def get_drawings(self, drawing_type: Optional[str] = None) -> List[Drawing]:
        """
        Return all (or filtered) drawings.

        Args:
            drawing_type: If provided, only return drawings of this type.

        Returns:
            List of Drawing objects.
        """
        drawings = list(self.drawings.values())
        if drawing_type:
            drawings = [d for d in drawings if d.drawing_type == drawing_type]
        return drawings

    def get_drawing(self, drawing_id: str) -> Optional[Drawing]:
        """Return a specific drawing by ID, or None if not found."""
        return self.drawings.get(drawing_id)

    def remove_drawing(self, drawing_id: str) -> bool:
        """
        Remove a drawing.

        Args:
            drawing_id: Drawing to remove.

        Returns:
            True if removed, False if not found.
        """
        if drawing_id in self.drawings:
            del self.drawings[drawing_id]
            return True
        return False

    def clear_drawings(self, drawing_type: Optional[str] = None) -> int:
        """
        Remove all (or filtered) drawings.

        Args:
            drawing_type: If provided, only remove drawings of this type.

        Returns:
            Number of drawings removed.
        """
        if drawing_type is None:
            count = len(self.drawings)
            self.drawings.clear()
            return count

        keys_to_remove = [k for k, d in self.drawings.items() if d.drawing_type == drawing_type]
        for k in keys_to_remove:
            del self.drawings[k]
        return len(keys_to_remove)

    def show_drawing(self, drawing_id: str) -> bool:
        """Make a drawing visible. Returns True on success."""
        d = self.drawings.get(drawing_id)
        if d:
            d.visible = True
            return True
        return False

    def hide_drawing(self, drawing_id: str) -> bool:
        """Hide a drawing (keeps it stored but not rendered). Returns True on success."""
        d = self.drawings.get(drawing_id)
        if d:
            d.visible = False
            return True
        return False

    def update_drawing(self, drawing_id: str, **properties) -> bool:
        """
        Update properties of an existing drawing.

        Args:
            drawing_id: Drawing to update.
            **properties: Key/value pairs to merge into drawing.properties.

        Returns:
            True on success, False if drawing not found.
        """
        d = self.drawings.get(drawing_id)
        if not d:
            return False
        for key, value in properties.items():
            if key in ("color", "line_width", "visible"):
                setattr(d, key, value)
            else:
                d.properties[key] = value
        return True

    def export_drawings(self) -> List[Dict[str, Any]]:
        """Serialise all drawings to a list of dicts (for persistence)."""
        return [d.to_dict() for d in self.drawings.values()]

    def import_drawings(self, data: List[Dict[str, Any]]) -> int:
        """
        Load drawings from a list of dicts (inverse of export_drawings).

        Returns:
            Number of drawings imported.
        """
        count = 0
        for item in data:
            try:
                drawing = Drawing.from_dict(item)
                self.drawings[drawing.drawing_id] = drawing
                count += 1
            except (KeyError, TypeError) as exc:
                logger.warning("Skipping invalid drawing data: %s", exc)
        return count

    def get_drawings_count(self) -> int:
        """Return the total number of stored drawings."""
        return len(self.drawings)
