"""OptiMeasure Live - lightweight calibrated USB microscope viewer.

The application targets UVC/DirectShow cameras and keeps every measurement in
native image coordinates. Resizing or zooming the preview therefore never
changes the calculated dimensions.
"""

from __future__ import annotations

import csv
import json
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSettings,
    QStandardPaths,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QImage,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geometry import (
    Circle,
    GeometryError,
    angle_degrees,
    calibration_from_reference,
    circle_from_three_points,
    distance_px,
    parallel_lines_from_three_points,
    points_to_text,
)

APP_NAME = "OptiMeasure Live"
APP_VERSION = "0.2.0"

Point = tuple[float, float]
ScaleBar = tuple[float, str]

TOOL_POINT_COUNTS = {
    "calibration": 2,
    "distance": 2,
    "angle": 3,
    "circle": 3,
    "parallel": 3,
}

TOOL_COLORS = {
    "calibration": QColor("#ffd54f"),
    "distance": QColor("#20d6e8"),
    "angle": QColor("#ff9f43"),
    "circle": QColor("#3ee68b"),
    "parallel": QColor("#e56bff"),
}

TOOL_NAMES = {
    "calibration": "Étalonnage",
    "distance": "Distance",
    "angle": "Angle",
    "circle": "Cercle",
    "parallel": "Distance entre parallèles",
}

MEASUREMENT_COLOR_CHOICES = [
    ("Par défaut", ""),
    ("Noir", "#101010"),
    ("Cyan", "#20d6e8"),
    ("Orange", "#ff9f43"),
    ("Vert", "#3ee68b"),
    ("Jaune", "#ffd54f"),
    ("Rouge", "#ef5350"),
    ("Bleu", "#42a5f5"),
    ("Magenta", "#e56bff"),
    ("Blanc", "#ffffff"),
]

IMAGE_BACKGROUND_COLOR_CHOICES = [
    ("Sans fond", ""),
    ("Noir", "#101010"),
    ("Gris", "#607d8b"),
    ("Cyan", "#20d6e8"),
    ("Orange", "#ff9f43"),
    ("Vert", "#3ee68b"),
    ("Jaune", "#ffd54f"),
    ("Rouge", "#ef5350"),
    ("Bleu", "#42a5f5"),
    ("Magenta", "#e56bff"),
    ("Blanc", "#ffffff"),
]


@dataclass(slots=True)
class Measurement:
    number: int
    kind: str
    points: list[Point]
    name: str = ""
    color: str = ""
    label_offset: Point = (0.0, 0.0)
    created_at: str = field(
        default_factory=lambda: (
            datetime.now().astimezone().isoformat(timespec="seconds")
        )
    )


def measurement_color(measurement: Measurement) -> QColor:
    custom = QColor(measurement.color)
    if measurement.color and custom.isValid():
        return custom
    return TOOL_COLORS[measurement.kind]


def measurement_label_anchor(measurement: Measurement) -> Point:
    points = measurement.points
    if measurement.kind in {"distance", "calibration"}:
        return (
            (points[0][0] + points[1][0]) / 2 + 8,
            (points[0][1] + points[1][1]) / 2 + 8,
        )
    if measurement.kind == "angle":
        return points[1][0] + 8, points[1][1] + 8
    if measurement.kind == "parallel":
        connector = parallel_lines_from_three_points(*points).connector
        return (
            (connector[0][0] + connector[1][0]) / 2 + 8,
            (connector[0][1] + connector[1][1]) / 2 + 8,
        )
    circle = circle_from_three_points(*points)
    return circle.center[0] + 8, circle.center[1] + 8


def measurement_label_position(measurement: Measurement) -> Point:
    anchor = measurement_label_anchor(measurement)
    return (
        anchor[0] + measurement.label_offset[0],
        anchor[1] + measurement.label_offset[1],
    )


def color_icon(color: QColor) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(color)
    return QIcon(pixmap)


def no_color_icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#9aa4ad"), 1.0))
    painter.drawRect(1, 1, 13, 13)
    painter.setPen(QPen(QColor("#ef5350"), 2.0))
    painter.drawLine(3, 3, 13, 13)
    painter.drawLine(13, 3, 3, 13)
    painter.end()
    return QIcon(pixmap)


def safe_capture_filename_stem(name: str) -> str:
    """Return a Windows-compatible file stem derived from an image name."""

    invalid = '<>:"/\\|?*'
    cleaned = "".join(
        "_" if character in invalid or ord(character) < 32 else character
        for character in name.strip()
    ).strip(" .")
    if not cleaned:
        return ""
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{number}" for number in range(1, 10))
    reserved.update(f"LPT{number}" for number in range(1, 10))
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"
    return cleaned[:80].rstrip(" .")


class CalibrationStore:
    """Small JSON store for reusable microscope/objective calibrations."""

    def __init__(self) -> None:
        config_root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        self.path = Path(config_root) / "calibrations.json"
        self.profiles: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.profiles = {
                        str(name): profile
                        for name, profile in data.items()
                        if isinstance(profile, dict)
                        and float(profile.get("mm_per_pixel", 0)) > 0
                    }
        except (OSError, ValueError, TypeError):
            self.profiles = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.profiles, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def set_profile(
        self,
        name: str,
        mm_per_pixel: float,
        resolution: tuple[int, int] | None,
    ) -> None:
        clean_name = name.strip() or "Calibration"
        self.profiles[clean_name] = {
            "mm_per_pixel": mm_per_pixel,
            "resolution": list(resolution) if resolution else None,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.save()

    def delete_profile(self, name: str) -> None:
        if name in self.profiles:
            del self.profiles[name]
            self.save()


class CollapsibleSection(QWidget):
    """Panel section with a clickable disclosure arrow."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.toggle_button.setStyleSheet(
            "QToolButton { text-align: left; font-weight: bold; padding: 4px; }"
        )
        self.toggle_button.setToolTip(f"Replier la section {title}")

        self.content = QFrame()
        self.content.setFrameShape(QFrame.Shape.StyledPanel)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(2)
        root_layout.addWidget(self.toggle_button)
        root_layout.addWidget(self.content)

        self.toggle_button.toggled.connect(self._on_toggled)

    def set_content_layout(self, layout: QLayout) -> None:
        self.content.setLayout(layout)

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(expanded)
        self._on_toggled(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        self.content.setVisible(expanded)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        action = "Replier" if expanded else "Déplier"
        self.toggle_button.setToolTip(
            f"{action} la section {self.toggle_button.text()}"
        )


class ImageCanvas(QGraphicsView):
    """Zoomable camera canvas whose scene coordinates match image pixels."""

    tool_completed = Signal(str, object)
    point_selected = Signal(int)
    point_moved = Signal(int, int, object)
    point_move_finished = Signal(int, int)
    measurement_moved = Signal(int, object)
    measurement_move_finished = Signal(int)
    label_moved = Signal(int, object)
    label_move_finished = Signal(int)
    image_size_changed = Signal()
    cursor_position = Signal(float, float)
    hint = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene().addItem(self.pixmap_item)
        self.pixmap_item.setZValue(0)

        self._image_size: tuple[int, int] | None = None
        self._active_tool: str | None = None
        self._pending_points: list[Point] = []
        self._temporary_items: list[QGraphicsItem] = []
        self._overlay_items: list[QGraphicsItem] = []
        self._editable_points: list[
            tuple[int, int, Point, QGraphicsEllipseItem, QColor]
        ] = []
        self._editable_measurements: list[tuple[int, str, tuple[Point, ...]]] = []
        self._editable_labels: list[
            tuple[int, QGraphicsSimpleTextItem]
        ] = []
        self._selected_point: tuple[int, int] | None = None
        self._dragged_point: tuple[int, int] | None = None
        self._dragged_measurement: int | None = None
        self._measurement_drag_origin: Point | None = None
        self._measurement_drag_points: tuple[Point, ...] = ()
        self._dragged_label: int | None = None
        self._label_drag_origin: Point | None = None
        self._label_drag_position: Point | None = None
        self._scale_bar_label: (
            tuple[QGraphicsSimpleTextItem, float, float] | None
        ) = None
        self._crosshair_visible = True
        self._auto_fit = True

        self.setBackgroundBrush(QBrush(QColor("#101419")))
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

    @property
    def has_image(self) -> bool:
        return self._image_size is not None

    def set_frame(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        if frame.ndim == 2:
            image = QImage(
                frame.data,
                width,
                height,
                frame.strides[0],
                QImage.Format.Format_Grayscale8,
            ).copy()
        else:
            image = QImage(
                frame.data,
                width,
                height,
                frame.strides[0],
                QImage.Format.Format_BGR888,
            ).copy()

        size_changed = self._image_size != (width, height)
        self._image_size = (width, height)
        self.pixmap_item.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(QRectF(0, 0, width, height))
        if size_changed or self._auto_fit:
            self.fit_image()
        if size_changed:
            self.image_size_changed.emit()

    def fit_image(self) -> None:
        if self.has_image:
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self._auto_fit = True
            self._center_scale_bar_label()

    def set_crosshair_visible(self, visible: bool) -> None:
        self._crosshair_visible = visible
        self.viewport().update()

    def set_tool(self, tool: str | None) -> None:
        self.cancel_pending()
        self._dragged_point = None
        self._dragged_measurement = None
        self._measurement_drag_origin = None
        self._measurement_drag_points = ()
        self._dragged_label = None
        self._label_drag_origin = None
        self._label_drag_position = None
        self._set_selected_point(None)
        self._active_tool = tool
        if tool:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            count = TOOL_POINT_COUNTS[tool]
            self.hint.emit(
                f"{TOOL_NAMES[tool]} : cliquer {count} point(s), clic droit pour annuler."
            )
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def cancel_pending(self) -> None:
        self._pending_points.clear()
        self._remove_items(self._temporary_items)
        self._temporary_items.clear()

    def clear_overlays(self) -> None:
        self._remove_items(self._overlay_items)
        self._overlay_items.clear()
        self._editable_points.clear()
        self._editable_measurements.clear()
        self._editable_labels.clear()
        self._scale_bar_label = None

    def _remove_items(self, items: Iterable[QGraphicsItem]) -> None:
        for item in list(items):
            if item.scene() is self.scene():
                self.scene().removeItem(item)

    def _inside_image(self, point: QPointF) -> bool:
        if not self._image_size:
            return False
        width, height = self._image_size
        return 0 <= point.x() < width and 0 <= point.y() < height

    def _add_point_marker(
        self,
        point: Point,
        color: QColor,
        collection: list[QGraphicsItem],
        z_value: float = 20,
        selected: bool = False,
    ) -> QGraphicsEllipseItem:
        marker = QGraphicsEllipseItem(-4, -4, 8, 8)
        marker.setPos(*point)
        marker.setPen(
            QPen(
                QColor("#ffffff") if selected else color,
                2.5 if selected else 1.5,
            )
        )
        marker.setBrush(QBrush(QColor(20, 20, 20, 180)))
        marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        marker.setZValue(z_value)
        self.scene().addItem(marker)
        collection.append(marker)
        if selected:
            marker.setRect(-6, -6, 12, 12)
        return marker

    def _set_selected_point(self, selected: tuple[int, int] | None) -> None:
        self._selected_point = selected
        for number, point_index, _point, marker, color in self._editable_points:
            is_selected = selected == (number, point_index)
            if is_selected:
                marker.setRect(-6, -6, 12, 12)
            else:
                marker.setRect(-4, -4, 8, 8)
            marker.setPen(
                QPen(
                    QColor("#ffffff") if is_selected else color,
                    2.5 if is_selected else 1.5,
                )
            )

    def _point_at_view_position(self, position: QPointF) -> tuple[int, int] | None:
        """Return the closest editable point within a screen-sized hit area."""

        closest: tuple[int, int] | None = None
        closest_distance_squared = 12.0**2
        for number, point_index, point, _marker, _color in self._editable_points:
            view_point = self.mapFromScene(QPointF(*point))
            delta_x = view_point.x() - position.x()
            delta_y = view_point.y() - position.y()
            distance_squared = delta_x * delta_x + delta_y * delta_y
            if distance_squared <= closest_distance_squared:
                closest = (number, point_index)
                closest_distance_squared = distance_squared
        return closest

    def _clamp_to_image(self, point: QPointF) -> Point:
        if not self._image_size:
            return point.x(), point.y()
        width, height = self._image_size
        return (
            max(0.0, min(width - 1.0, point.x())),
            max(0.0, min(height - 1.0, point.y())),
        )

    @staticmethod
    def _distance_to_segment(
        point: Point, first: Point, second: Point
    ) -> float:
        delta_x = second[0] - first[0]
        delta_y = second[1] - first[1]
        length_squared = delta_x * delta_x + delta_y * delta_y
        if length_squared <= 1e-12:
            return distance_px(point, first)
        projection = (
            (point[0] - first[0]) * delta_x
            + (point[1] - first[1]) * delta_y
        ) / length_squared
        projection = max(0.0, min(1.0, projection))
        closest = (
            first[0] + projection * delta_x,
            first[1] + projection * delta_y,
        )
        return distance_px(point, closest)

    def _measurement_at_view_position(self, position: QPointF) -> int | None:
        """Find a measurement line or circumference near the mouse pointer."""

        cursor = (position.x(), position.y())
        hit_distance = 8.0
        closest_number: int | None = None
        closest_distance = hit_distance

        for number, kind, points in self._editable_measurements:
            view_points = [
                self.mapFromScene(QPointF(*point))
                for point in points
            ]
            converted = [
                (float(point.x()), float(point.y()))
                for point in view_points
            ]

            distances: list[float]
            if kind in {"distance", "calibration"}:
                distances = [
                    self._distance_to_segment(cursor, converted[0], converted[1])
                ]
            elif kind == "angle":
                distances = [
                    self._distance_to_segment(cursor, converted[1], converted[0]),
                    self._distance_to_segment(cursor, converted[1], converted[2]),
                ]
            elif kind == "parallel":
                try:
                    lines = parallel_lines_from_three_points(*points)
                except GeometryError:
                    continue
                view_segments: list[tuple[Point, Point]] = []
                for first, second in (
                    lines.first,
                    lines.second,
                    lines.connector,
                ):
                    first_view = self.mapFromScene(QPointF(*first))
                    second_view = self.mapFromScene(QPointF(*second))
                    view_segments.append(
                        (
                            (float(first_view.x()), float(first_view.y())),
                            (float(second_view.x()), float(second_view.y())),
                        )
                    )
                distances = [
                    self._distance_to_segment(cursor, first, second)
                    for first, second in view_segments
                ]
            else:
                try:
                    circle = circle_from_three_points(*points)
                except GeometryError:
                    continue
                center_view = self.mapFromScene(QPointF(*circle.center))
                center = (float(center_view.x()), float(center_view.y()))
                radius = distance_px(center, converted[0])
                distances = [abs(distance_px(cursor, center) - radius)]

            distance = min(distances)
            if distance <= closest_distance:
                closest_number = number
                closest_distance = distance

        return closest_number

    def _label_at_view_position(
        self, position: QPointF
    ) -> tuple[int, QGraphicsSimpleTextItem] | None:
        items_at_position = self.items(position.toPoint())
        for hit_item in items_at_position:
            for number, label_item in self._editable_labels:
                if hit_item is label_item or hit_item == label_item:
                    return number, label_item
        return None

    def _translated_measurement_points(self, current: QPointF) -> list[Point]:
        if (
            self._measurement_drag_origin is None
            or not self._measurement_drag_points
        ):
            return []

        delta_x = current.x() - self._measurement_drag_origin[0]
        delta_y = current.y() - self._measurement_drag_origin[1]
        if self._image_size:
            width, height = self._image_size
            minimum_x = min(point[0] for point in self._measurement_drag_points)
            maximum_x = max(point[0] for point in self._measurement_drag_points)
            minimum_y = min(point[1] for point in self._measurement_drag_points)
            maximum_y = max(point[1] for point in self._measurement_drag_points)
            delta_x = max(-minimum_x, min(width - 1.0 - maximum_x, delta_x))
            delta_y = max(-minimum_y, min(height - 1.0 - maximum_y, delta_y))

        return [
            (point[0] + delta_x, point[1] + delta_y)
            for point in self._measurement_drag_points
        ]

    def _add_line(
        self,
        first: Point,
        second: Point,
        color: QColor,
        collection: list[QGraphicsItem],
        width: float = 2.0,
        style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> None:
        pen = QPen(color, width, style)
        pen.setCosmetic(True)
        item = QGraphicsLineItem(first[0], first[1], second[0], second[1])
        item.setPen(pen)
        item.setZValue(10)
        self.scene().addItem(item)
        collection.append(item)

    def _add_text(
        self,
        position: Point,
        text: str,
        color: QColor,
        collection: list[QGraphicsItem],
    ) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(text)
        item.setBrush(QBrush(color))
        # Use the measurement color for both the glyph fill and its fine edge.
        # A black pen at this size can visually cover the colored glyph.
        item.setPen(QPen(color, 0.5))
        item.setPos(*position)
        item.setRotation(0.0)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(30)
        self.scene().addItem(item)
        collection.append(item)
        return item

    def _render_scale_bar(
        self,
        mm_per_pixel: float | None,
        scale_bar: ScaleBar | None,
    ) -> None:
        if not self._image_size or not mm_per_pixel or not scale_bar:
            return
        length_px = scale_bar_pixels(scale_bar, mm_per_pixel)
        width, height = self._image_size
        margin = max(16.0, min(width, height) * 0.03)
        if length_px <= 0 or length_px > width - 2 * margin:
            return

        end_x = width - margin
        start_x = end_x - length_px
        bar_y = height - margin
        tick_height = max(8.0, min(width, height) * 0.012)
        shadow = QColor("#101010")
        foreground = QColor("#ffffff")

        for color, line_width in [(shadow, 7.0), (foreground, 3.0)]:
            self._add_line(
                (start_x, bar_y),
                (end_x, bar_y),
                color,
                self._overlay_items,
                width=line_width,
            )
            self._add_line(
                (start_x, bar_y - tick_height / 2),
                (start_x, bar_y + tick_height / 2),
                color,
                self._overlay_items,
                width=line_width,
            )
            self._add_line(
                (end_x, bar_y - tick_height / 2),
                (end_x, bar_y + tick_height / 2),
                color,
                self._overlay_items,
                width=line_width,
            )

        label_y = bar_y - tick_height - 22
        label_item = self._add_text(
            ((start_x + end_x) / 2, label_y),
            scale_bar_label(scale_bar),
            foreground,
            self._overlay_items,
        )
        self._scale_bar_label = (
            label_item,
            (start_x + end_x) / 2,
            label_y,
        )
        self._center_scale_bar_label()

    def _center_scale_bar_label(self) -> None:
        if self._scale_bar_label is None:
            return
        item, center_x, position_y = self._scale_bar_label
        if item.scene() is not self.scene():
            return
        view_scale = abs(self.transform().m11())
        if view_scale <= 1e-12:
            return
        label_width_scene = item.boundingRect().width() / view_scale
        item.setPos(center_x - label_width_scene / 2, position_y)

    def _render_image_name(
        self,
        name: str,
        text_color_value: str,
        background_color_value: str,
    ) -> None:
        if not self._image_size or not name.strip():
            return

        text_color = QColor(text_color_value)
        if not text_color.isValid():
            text_color = QColor("#ffffff")
        width, height = self._image_size
        margin = max(12.0, min(width, height) * 0.025)
        text_item = self._add_text(
            (margin, margin),
            name.strip(),
            text_color,
            self._overlay_items,
        )
        background_color = QColor(background_color_value)
        if not background_color_value or not background_color.isValid():
            return

        padding_x = 6.0
        padding_y = 4.0
        text_bounds = text_item.boundingRect()
        background_item = QGraphicsRectItem(
            text_bounds.left() - padding_x,
            text_bounds.top() - padding_y,
            text_bounds.width() + padding_x * 2,
            text_bounds.height() + padding_y * 2,
        )
        background_item.setBrush(QBrush(background_color))
        background_item.setPen(QPen(Qt.PenStyle.NoPen))
        background_item.setPos(margin, margin)
        background_item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
            True,
        )
        background_item.setZValue(29)
        self.scene().addItem(background_item)
        self._overlay_items.append(background_item)

    def render_measurements(
        self,
        measurements: list[Measurement],
        mm_per_pixel: float | None,
        display_unit: str,
        scale_bar: ScaleBar | None = None,
        image_name: str = "",
        image_name_color: str = "#ffffff",
        image_name_background: str = "",
    ) -> None:
        self.clear_overlays()
        for measurement in measurements:
            points = measurement.points
            color = measurement_color(measurement)
            self._editable_measurements.append(
                (measurement.number, measurement.kind, tuple(points))
            )
            for point_index, point in enumerate(points):
                key = (measurement.number, point_index)
                marker = self._add_point_marker(
                    point,
                    color,
                    self._overlay_items,
                    selected=self._selected_point == key,
                )
                self._editable_points.append(
                    (measurement.number, point_index, point, marker, color)
                )

            if measurement.kind in {"distance", "calibration"}:
                self._add_line(points[0], points[1], color, self._overlay_items)
            elif measurement.kind == "angle":
                self._add_line(points[1], points[0], color, self._overlay_items)
                self._add_line(points[1], points[2], color, self._overlay_items)
            elif measurement.kind == "parallel":
                try:
                    lines = parallel_lines_from_three_points(*points)
                except GeometryError:
                    continue
                self._add_line(*lines.first, color, self._overlay_items)
                self._add_line(*lines.second, color, self._overlay_items)
                self._add_line(
                    *lines.connector,
                    color,
                    self._overlay_items,
                    width=1.5,
                    style=Qt.PenStyle.DashLine,
                )
            elif measurement.kind == "circle":
                try:
                    circle = circle_from_three_points(*points)
                except GeometryError:
                    continue
                pen = QPen(color, 2.0)
                pen.setCosmetic(True)
                ellipse = QGraphicsEllipseItem(
                    circle.center[0] - circle.radius_px,
                    circle.center[1] - circle.radius_px,
                    circle.radius_px * 2,
                    circle.radius_px * 2,
                )
                ellipse.setPen(pen)
                ellipse.setZValue(10)
                self.scene().addItem(ellipse)
                self._overlay_items.append(ellipse)
                self._add_point_marker(circle.center, color, self._overlay_items)
            label_item = self._add_text(
                measurement_label_position(measurement),
                measurement_label(measurement, mm_per_pixel, display_unit),
                color,
                self._overlay_items,
            )
            self._editable_labels.append((measurement.number, label_item))
        self._render_scale_bar(mm_per_pixel, scale_bar)
        self._render_image_name(
            image_name,
            image_name_color,
            image_name_background,
        )

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.RightButton
            and self._active_tool is not None
        ):
            self.cancel_pending()
            self.hint.emit("Mesure en cours annulée.")
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            cursor_point = self.mapToScene(event.position().toPoint())
            if self._inside_image(cursor_point):
                self.cursor_position.emit(cursor_point.x(), cursor_point.y())

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._active_tool is not None
        ):
            scene_point = self.mapToScene(event.position().toPoint())
            if not self._inside_image(scene_point):
                return
            point = (scene_point.x(), scene_point.y())
            self._pending_points.append(point)
            color = TOOL_COLORS[self._active_tool]
            self._add_point_marker(point, color, self._temporary_items, z_value=40)
            if len(self._pending_points) > 1:
                if (
                    self._active_tool == "parallel"
                    and len(self._pending_points) == 3
                ):
                    try:
                        lines = parallel_lines_from_three_points(
                            *self._pending_points
                        )
                    except GeometryError:
                        pass
                    else:
                        self._add_line(
                            *lines.second,
                            color,
                            self._temporary_items,
                            width=1.5,
                            style=Qt.PenStyle.DashLine,
                        )
                        self._add_line(
                            *lines.connector,
                            color,
                            self._temporary_items,
                            width=1.5,
                            style=Qt.PenStyle.DashLine,
                        )
                else:
                    self._add_line(
                        self._pending_points[-2],
                        self._pending_points[-1],
                        color,
                        self._temporary_items,
                        width=1.5,
                        style=Qt.PenStyle.DashLine,
                    )

            expected = TOOL_POINT_COUNTS[self._active_tool]
            if len(self._pending_points) == expected:
                tool = self._active_tool
                points = list(self._pending_points)
                self.cancel_pending()
                self.tool_completed.emit(tool, points)
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._active_tool is None
        ):
            selected = self._point_at_view_position(event.position())
            if selected is not None:
                self._dragged_point = selected
                self._dragged_measurement = None
                self._dragged_label = None
                self._set_selected_point(selected)
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                self.point_selected.emit(selected[0])
                self.hint.emit(
                    "Point sélectionné : maintenir le clic et déplacer pour ajuster "
                    "la mesure."
                )
                event.accept()
                return

            selected_label = self._label_at_view_position(event.position())
            if selected_label is not None:
                number, label_item = selected_label
                scene_position = self.mapToScene(event.position().toPoint())
                self._dragged_label = number
                self._label_drag_origin = (
                    scene_position.x(),
                    scene_position.y(),
                )
                self._label_drag_position = (
                    label_item.pos().x(),
                    label_item.pos().y(),
                )
                self._dragged_measurement = None
                self._set_selected_point(None)
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                self.point_selected.emit(number)
                self.hint.emit(
                    "Étiquette sélectionnée : maintenir le clic et déplacer "
                    "pour la repositionner."
                )
                event.accept()
                return

            selected_measurement = self._measurement_at_view_position(
                event.position()
            )
            if selected_measurement is not None:
                measurement = next(
                    (
                        points
                        for number, _kind, points in self._editable_measurements
                        if number == selected_measurement
                    ),
                    (),
                )
                scene_position = self.mapToScene(event.position().toPoint())
                self._dragged_measurement = selected_measurement
                self._measurement_drag_origin = (
                    scene_position.x(),
                    scene_position.y(),
                )
                self._measurement_drag_points = measurement
                self._set_selected_point(None)
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                self.point_selected.emit(selected_measurement)
                self.hint.emit(
                    "Mesure sélectionnée : maintenir le clic et déplacer "
                    "pour la repositionner."
                )
                event.accept()
                return
            self._set_selected_point(None)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        point = self.mapToScene(event.position().toPoint())
        if self._inside_image(point):
            self.cursor_position.emit(point.x(), point.y())

        if self._dragged_point is not None:
            number, point_index = self._dragged_point
            self.point_moved.emit(
                number, point_index, self._clamp_to_image(point)
            )
            event.accept()
            return

        if (
            self._dragged_label is not None
            and self._label_drag_origin is not None
            and self._label_drag_position is not None
        ):
            label_position = QPointF(
                self._label_drag_position[0]
                + point.x()
                - self._label_drag_origin[0],
                self._label_drag_position[1]
                + point.y()
                - self._label_drag_origin[1],
            )
            self.label_moved.emit(
                self._dragged_label,
                self._clamp_to_image(label_position),
            )
            event.accept()
            return

        if self._dragged_measurement is not None:
            translated_points = self._translated_measurement_points(point)
            if translated_points:
                self.measurement_moved.emit(
                    self._dragged_measurement, translated_points
                )
            event.accept()
            return

        if self._active_tool is None:
            if self._point_at_view_position(event.position()) is not None:
                cursor = Qt.CursorShape.PointingHandCursor
            elif self._label_at_view_position(event.position()) is not None:
                cursor = Qt.CursorShape.SizeAllCursor
            elif self._measurement_at_view_position(event.position()) is not None:
                cursor = Qt.CursorShape.SizeAllCursor
            else:
                cursor = Qt.CursorShape.OpenHandCursor
            self.viewport().setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._dragged_point is not None
        ):
            number, point_index = self._dragged_point
            self._dragged_point = None
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            self.point_move_finished.emit(number, point_index)
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._dragged_label is not None
        ):
            number = self._dragged_label
            self._dragged_label = None
            self._label_drag_origin = None
            self._label_drag_position = None
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            self.label_move_finished.emit(number)
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._dragged_measurement is not None
        ):
            number = self._dragged_measurement
            self._dragged_measurement = None
            self._measurement_drag_origin = None
            self._measurement_drag_points = ()
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            self.measurement_move_finished.emit(number)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if not self.has_image:
            return
        self._auto_fit = False
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        current = self.transform().m11()
        if (factor > 1 and current < 25) or (factor < 1 and current > 0.02):
            self.scale(factor, factor)
            self._center_scale_bar_label()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.fit_image()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_image()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        if not (self._crosshair_visible and self._image_size):
            return
        width, height = self._image_size
        pen = QPen(QColor(255, 70, 70, 175), 1.0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(QPointF(width / 2, 0), QPointF(width / 2, height))
        painter.drawLine(QPointF(0, height / 2), QPointF(width, height / 2))


def converted_length(value_mm: float, unit: str) -> tuple[float, str]:
    if unit == "µm":
        return value_mm * 1000.0, "µm"
    return value_mm, "mm"


def format_number(value: float) -> str:
    return f"{value:.3f}"


def scale_bar_length_mm(scale_bar: ScaleBar) -> float:
    value, unit = scale_bar
    return value / 1000.0 if unit == "µm" else value


def scale_bar_pixels(scale_bar: ScaleBar, mm_per_pixel: float) -> float:
    if mm_per_pixel <= 0:
        return 0.0
    return scale_bar_length_mm(scale_bar) / mm_per_pixel


def scale_bar_label(scale_bar: ScaleBar, ascii_only: bool = False) -> str:
    value, unit = scale_bar
    if ascii_only and unit == "µm":
        unit = "um"
    return f"{value:.6g} {unit}"


def measurement_value(
    measurement: Measurement,
    mm_per_pixel: float | None,
    display_unit: str,
) -> tuple[float, str]:
    if measurement.kind == "angle":
        return angle_degrees(*measurement.points), "°"

    if measurement.kind == "circle":
        pixels = circle_from_three_points(*measurement.points).radius_px * 2
    elif measurement.kind == "parallel":
        pixels = parallel_lines_from_three_points(
            *measurement.points
        ).distance_px
    else:
        pixels = distance_px(*measurement.points[:2])

    if mm_per_pixel and mm_per_pixel > 0:
        return converted_length(pixels * mm_per_pixel, display_unit)
    return pixels, "px"


def measurement_label(
    measurement: Measurement,
    mm_per_pixel: float | None,
    display_unit: str,
    ascii_only: bool = False,
) -> str:
    value, unit = measurement_value(measurement, mm_per_pixel, display_unit)
    if ascii_only:
        unit = {"µm": "um", "°": "deg"}.get(unit, unit)
    prefix = {
        "distance": "L",
        "angle": "A",
        "circle": "D",
        "parallel": "P",
        "calibration": "CAL",
    }[measurement.kind]
    name = measurement.name.strip()
    if ascii_only and name:
        name = (
            unicodedata.normalize("NFKD", name)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    identifier = f"{prefix}{measurement.number}"
    if name:
        identifier += f" {name}"
    return f"{identifier}: {format_number(value)} {unit}"


def cv_color(measurement: Measurement) -> tuple[int, int, int]:
    color = measurement_color(measurement)
    return color.blue(), color.green(), color.red()


def put_cv_label(
    image: np.ndarray,
    position: Point,
    text: str,
    color: tuple[int, int, int],
    scale: float,
    thickness: int,
) -> None:
    x, y = round(position[0]), round(position[1])
    x = max(4, min(image.shape[1] - 4, x))
    y = max(18, min(image.shape[0] - 4, y))
    shadow_offset = max(1, thickness // 2)
    cv2.putText(
        image,
        text,
        (x + shadow_offset, y + shadow_offset),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (10, 10, 10),
        thickness,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        text,
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def draw_cv_image_name(
    image: np.ndarray,
    name: str,
    color_value: str,
    background_color_value: str = "",
) -> None:
    text = (
        unicodedata.normalize("NFKD", name.strip())
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    if not text:
        return

    color = QColor(color_value)
    if not color.isValid():
        color = QColor("#ffffff")
    bgr_color = (color.blue(), color.green(), color.red())
    height, width = image.shape[:2]
    margin = max(12, round(min(width, height) * 0.025))
    scale = max(0.65, min(1.6, width / 1400.0))
    thickness = max(1, round(scale))
    text_size, baseline = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        thickness,
    )
    text_x = margin
    text_y = margin + text_size[1]
    background_color = QColor(background_color_value)
    if background_color_value and background_color.isValid():
        padding = max(4, round(scale * 6))
        text_x += padding
        text_y += padding
        cv2.rectangle(
            image,
            (margin, margin),
            (
                margin + text_size[0] + padding * 2,
                margin + text_size[1] + baseline + padding * 2,
            ),
            (
                background_color.blue(),
                background_color.green(),
                background_color.red(),
            ),
            -1,
            cv2.LINE_AA,
        )
    put_cv_label(
        image,
        (text_x, text_y),
        text,
        bgr_color,
        scale,
        thickness,
    )


def draw_cv_scale_bar(
    image: np.ndarray,
    mm_per_pixel: float | None,
    scale_bar: ScaleBar | None,
) -> None:
    if not mm_per_pixel or not scale_bar:
        return

    height, width = image.shape[:2]
    length_px = scale_bar_pixels(scale_bar, mm_per_pixel)
    margin = max(16, round(min(width, height) * 0.03))
    if length_px <= 0 or length_px > width - 2 * margin:
        return

    end_x = width - margin
    start_x = round(end_x - length_px)
    bar_y = height - margin
    tick_height = max(8, round(min(width, height) * 0.012))
    line_width = max(2, round(width / 800))
    shadow_width = line_width + max(3, round(width / 500))
    label_scale = max(0.55, min(1.5, width / 1400.0))
    label_thickness = max(1, round(label_scale))

    segments = [
        ((start_x, bar_y), (end_x, bar_y)),
        (
            (start_x, bar_y - tick_height // 2),
            (start_x, bar_y + tick_height // 2),
        ),
        (
            (end_x, bar_y - tick_height // 2),
            (end_x, bar_y + tick_height // 2),
        ),
    ]
    for first, second in segments:
        cv2.line(image, first, second, (10, 10, 10), shadow_width, cv2.LINE_AA)
        cv2.line(image, first, second, (255, 255, 255), line_width, cv2.LINE_AA)

    label = scale_bar_label(scale_bar, ascii_only=True)
    label_size, _baseline = cv2.getTextSize(
        label,
        cv2.FONT_HERSHEY_SIMPLEX,
        label_scale,
        label_thickness,
    )
    label_x = round((start_x + end_x - label_size[0]) / 2)
    label_x = max(4, min(width - label_size[0] - 4, label_x))
    label_y = max(18, bar_y - tick_height - 8)
    put_cv_label(
        image,
        (label_x, label_y),
        label,
        (255, 255, 255),
        label_scale,
        label_thickness,
    )


def magnified_region(
    frame: np.ndarray,
    center: Point,
    zoom_factor: float,
    output_size: tuple[int, int],
) -> np.ndarray:
    """Return a pixel-accurate magnified crop with a central aiming cross."""

    output_width, output_height = output_size
    output_width = max(32, output_width)
    output_height = max(32, output_height)
    zoom_factor = max(1.0, zoom_factor)
    crop_width = max(3, round(output_width / zoom_factor))
    crop_height = max(3, round(output_height / zoom_factor))
    source = frame
    if frame.ndim == 2:
        source = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

    crop = cv2.getRectSubPix(
        source,
        (crop_width, crop_height),
        (float(center[0]), float(center[1])),
    )
    magnified = cv2.resize(
        crop,
        (output_width, output_height),
        interpolation=cv2.INTER_NEAREST,
    )

    center_x = output_width // 2
    center_y = output_height // 2
    arm = max(18, min(output_width, output_height) // 5)
    cross_color = (0, 255, 255)
    for thickness, color in [(3, (10, 10, 10)), (1, cross_color)]:
        cv2.line(
            magnified,
            (center_x - arm, center_y),
            (center_x + arm, center_y),
            color,
            thickness,
            cv2.LINE_AA,
        )
        cv2.line(
            magnified,
            (center_x, center_y - arm),
            (center_x, center_y + arm),
            color,
            thickness,
            cv2.LINE_AA,
        )
    cv2.circle(
        magnified,
        (center_x, center_y),
        3,
        cross_color,
        1,
        cv2.LINE_AA,
    )
    return magnified


def annotate_frame(
    frame: np.ndarray,
    measurements: list[Measurement],
    mm_per_pixel: float | None,
    display_unit: str,
    crosshair: bool,
    scale_bar: ScaleBar | None = None,
    image_name: str = "",
    image_name_color: str = "#ffffff",
    image_name_background: str = "",
) -> np.ndarray:
    image = frame.copy()
    height, width = image.shape[:2]
    factor = max(0.65, min(2.0, width / 1600.0))
    thickness = max(1, round(factor * 2))
    text_thickness = max(1, round(factor))

    if crosshair:
        color = (70, 70, 255)
        cv2.line(
            image,
            (width // 2, 0),
            (width // 2, height - 1),
            color,
            1,
            cv2.LINE_AA,
        )
        cv2.line(
            image,
            (0, height // 2),
            (width - 1, height // 2),
            color,
            1,
            cv2.LINE_AA,
        )

    for measurement in measurements:
        points = measurement.points
        integer_points = [(round(point[0]), round(point[1])) for point in points]
        color = cv_color(measurement)

        label = measurement_label(
            measurement, mm_per_pixel, display_unit, ascii_only=True
        )
        if measurement.kind in {"distance", "calibration"}:
            cv2.line(
                image,
                integer_points[0],
                integer_points[1],
                color,
                thickness,
                cv2.LINE_AA,
            )
        elif measurement.kind == "angle":
            cv2.line(
                image,
                integer_points[1],
                integer_points[0],
                color,
                thickness,
                cv2.LINE_AA,
            )
            cv2.line(
                image,
                integer_points[1],
                integer_points[2],
                color,
                thickness,
                cv2.LINE_AA,
            )
        elif measurement.kind == "parallel":
            lines = parallel_lines_from_three_points(*points)
            for first, second in (lines.first, lines.second):
                cv2.line(
                    image,
                    (round(first[0]), round(first[1])),
                    (round(second[0]), round(second[1])),
                    color,
                    thickness,
                    cv2.LINE_AA,
                )
            cv2.line(
                image,
                (
                    round(lines.connector[0][0]),
                    round(lines.connector[0][1]),
                ),
                (
                    round(lines.connector[1][0]),
                    round(lines.connector[1][1]),
                ),
                color,
                max(1, thickness - 1),
                cv2.LINE_AA,
            )
        else:
            circle: Circle = circle_from_three_points(*points)
            center = (
                round(circle.center[0]),
                round(circle.center[1]),
            )
            radius = round(circle.radius_px)
            cv2.circle(image, center, radius, color, thickness, cv2.LINE_AA)

        position = measurement_label_position(measurement)
        put_cv_label(
            image,
            position,
            label,
            color,
            factor * 0.55,
            text_thickness,
        )

    draw_cv_scale_bar(image, mm_per_pixel, scale_bar)
    draw_cv_image_name(
        image,
        image_name,
        image_name_color,
        image_name_background,
    )
    return image


def write_png(path: Path, image: np.ndarray) -> bool:
    """Write a PNG reliably even when the Windows path contains Unicode."""

    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        return False
    try:
        encoded.tofile(str(path))
    except OSError:
        return False
    return True


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1380, 850)
        self.setStatusBar(QStatusBar(self))

        self.settings = QSettings("OpenSourceTools", "OptiMeasureLive")
        self.calibration_store = CalibrationStore()
        self.camera = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read_camera)
        self.last_frame: np.ndarray | None = None
        self.consecutive_read_errors = 0
        self.mm_per_pixel: float | None = None
        self.measurements: list[Measurement] = []
        self.next_measurement_number = 1
        self.current_resolution: tuple[int, int] | None = None
        self.magnifier_position: Point | None = None

        self.canvas = ImageCanvas()
        self.canvas.tool_completed.connect(self.on_tool_completed)
        self.canvas.point_selected.connect(self.select_measurement)
        self.canvas.point_moved.connect(self.move_measurement_point)
        self.canvas.point_move_finished.connect(self.finish_measurement_point_move)
        self.canvas.measurement_moved.connect(self.move_measurement)
        self.canvas.measurement_move_finished.connect(
            self.finish_measurement_move
        )
        self.canvas.label_moved.connect(self.move_measurement_label)
        self.canvas.label_move_finished.connect(
            self.finish_measurement_label_move
        )
        self.canvas.image_size_changed.connect(self.refresh_measurements)
        self.canvas.cursor_position.connect(self.show_cursor_position)
        self.canvas.hint.connect(self.statusBar().showMessage)

        self._build_ui()
        self._build_menus()
        self._restore_settings()
        saved_profile = str(self.settings.value("calibration/profile", ""))
        self._refresh_profiles(saved_profile)
        self.load_selected_profile()
        self._update_scale_label()
        self._update_measurement_table()

        self.shortcuts: list[QShortcut] = []
        for sequence, callback in [
            ("Ctrl+Z", self.undo_measurement),
            ("Delete", self.delete_selected),
            ("Escape", self.cancel_current_tool),
        ]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

        self.statusBar().showMessage(
            "Prêt. Choisir la caméra puis cliquer sur Démarrer."
        )

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self._build_side_panel())
        splitter.setSizes([1050, 330])
        splitter.setStretchFactor(0, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.setCentralWidget(splitter)

    def _build_side_panel(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.sections: dict[str, CollapsibleSection] = {
            "camera": self._build_camera_group(),
            "objective": self._build_objective_group(),
            "calibration": self._build_calibration_group(),
            "measurements": self._build_measurement_group(),
            "results": self._build_results_group(),
        }
        for section in self.sections.values():
            layout.addWidget(section)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(325)
        scroll.setWidget(content)
        return scroll

    def _build_camera_group(self) -> CollapsibleSection:
        group = CollapsibleSection("Caméra")
        grid = QGridLayout()
        group.set_content_layout(grid)

        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 20)
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Automatique", cv2.CAP_ANY)
        self.backend_combo.addItem("DirectShow", cv2.CAP_DSHOW)
        self.backend_combo.addItem("Media Foundation", cv2.CAP_MSMF)

        self.resolution_combo = QComboBox()
        for label, size in [
            ("640 × 480", (640, 480)),
            ("1280 × 720", (1280, 720)),
            ("1920 × 1080", (1920, 1080)),
            ("2560 × 1440", (2560, 1440)),
            ("3840 × 2160", (3840, 2160)),
        ]:
            self.resolution_combo.addItem(label, size)
        self.resolution_combo.setCurrentIndex(2)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(30)
        self.fps_spin.setSuffix(" i/s")

        grid.addWidget(QLabel("Index"), 0, 0)
        grid.addWidget(self.camera_index, 0, 1)
        grid.addWidget(QLabel("Interface"), 1, 0)
        grid.addWidget(self.backend_combo, 1, 1)
        grid.addWidget(QLabel("Résolution"), 2, 0)
        grid.addWidget(self.resolution_combo, 2, 1)
        grid.addWidget(QLabel("Cadence"), 3, 0)
        grid.addWidget(self.fps_spin, 3, 1)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Démarrer")
        self.start_button.clicked.connect(self.toggle_camera)
        self.freeze_button = QPushButton("Figer")
        self.freeze_button.setCheckable(True)
        self.freeze_button.setEnabled(False)
        self.freeze_button.toggled.connect(self.on_freeze_changed)
        self.capture_button = QPushButton("Capture")
        self.capture_button.setEnabled(False)
        self.capture_button.clicked.connect(self.capture_image)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.freeze_button)
        button_row.addWidget(self.capture_button)
        grid.addLayout(button_row, 4, 0, 1, 2)

        image_name_row = QHBoxLayout()
        self.image_name_check = QCheckBox("Nom")
        self.image_name_check.setToolTip(
            "Incruster le nom en haut à gauche de la capture"
        )
        self.image_name_edit = QLineEdit()
        self.image_name_edit.setPlaceholderText("Nom de l’image")
        self.image_name_color = QComboBox()
        self.image_name_color.setToolTip("Couleur du texte")
        for label, color_value in MEASUREMENT_COLOR_CHOICES:
            color = QColor(color_value or "#ffffff")
            self.image_name_color.addItem(
                color_icon(color),
                label,
                color_value,
            )
        self.image_name_background = QComboBox()
        self.image_name_background.setToolTip("Couleur de fond du nom")
        for label, color_value in IMAGE_BACKGROUND_COLOR_CHOICES:
            icon = (
                no_color_icon()
                if not color_value
                else color_icon(QColor(color_value))
            )
            self.image_name_background.addItem(icon, label, color_value)
        self.image_name_check.toggled.connect(self.image_name_edit.setEnabled)
        self.image_name_check.toggled.connect(self.image_name_color.setEnabled)
        self.image_name_check.toggled.connect(
            self.image_name_background.setEnabled
        )
        self.image_name_check.toggled.connect(self.on_image_name_changed)
        self.image_name_edit.textChanged.connect(self.on_image_name_changed)
        self.image_name_color.currentIndexChanged.connect(
            self.on_image_name_changed
        )
        self.image_name_background.currentIndexChanged.connect(
            self.on_image_name_changed
        )
        self.image_name_edit.setEnabled(False)
        self.image_name_color.setEnabled(False)
        self.image_name_background.setEnabled(False)
        image_name_row.addWidget(self.image_name_check)
        image_name_row.addWidget(self.image_name_edit, 1)
        image_name_row.addWidget(self.image_name_color)
        grid.addLayout(image_name_row, 5, 0, 1, 2)

        grid.addWidget(QLabel("Fond du nom"), 6, 0)
        grid.addWidget(self.image_name_background, 6, 1)

        self.keep_raw_check = QCheckBox("Conserver aussi l’image brute")
        self.keep_raw_check.setChecked(True)
        grid.addWidget(self.keep_raw_check, 7, 0, 1, 2)

        self.camera_status = QLabel("Arrêtée")
        self.camera_status.setStyleSheet("color: #9aa4ad;")
        grid.addWidget(self.camera_status, 8, 0, 1, 2)
        return group

    def _build_objective_group(self) -> CollapsibleSection:
        group = CollapsibleSection("Objectif")
        layout = QFormLayout()
        group.set_content_layout(layout)

        self.objective_combo = QComboBox()
        self.objective_combo.setPlaceholderText("Aucun profil enregistré")
        self.objective_combo.setEnabled(False)
        self.objective_combo.activated.connect(self.load_objective_profile)
        self.objective_combo.setToolTip(
            "Charger rapidement un profil d’étalonnage enregistré"
        )
        layout.addRow("Profil", self.objective_combo)
        return group

    def _build_calibration_group(self) -> CollapsibleSection:
        group = CollapsibleSection("Étalonnage")
        layout = QFormLayout()
        group.set_content_layout(layout)

        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.profile_combo.activated.connect(self.load_selected_profile)
        self.delete_profile_button = QPushButton("×")
        self.delete_profile_button.setToolTip("Supprimer le profil")
        self.delete_profile_button.setFixedWidth(30)
        self.delete_profile_button.clicked.connect(self.delete_selected_profile)
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(self.delete_profile_button)
        layout.addRow("Profil", profile_row)

        reference_row = QHBoxLayout()
        self.reference_length = QDoubleSpinBox()
        self.reference_length.setDecimals(5)
        self.reference_length.setRange(0.00001, 1_000_000)
        self.reference_length.setValue(1.0)
        self.reference_length.setKeyboardTracking(False)
        self.reference_unit = QComboBox()
        self.reference_unit.addItems(["mm", "µm"])
        reference_row.addWidget(self.reference_length, 1)
        reference_row.addWidget(self.reference_unit)
        layout.addRow("Longueur connue", reference_row)

        self.calibrate_button = QPushButton("Étalonner avec 2 points")
        self.calibrate_button.clicked.connect(self.begin_calibration)
        layout.addRow(self.calibrate_button)

        self.scale_label = QLabel("Non calibrée")
        self.scale_label.setWordWrap(True)
        layout.addRow("Échelle", self.scale_label)

        self.display_unit = QComboBox()
        self.display_unit.addItems(["mm", "µm"])
        self.display_unit.currentTextChanged.connect(self.refresh_measurements)
        layout.addRow("Unité affichée", self.display_unit)
        return group

    def _build_measurement_group(self) -> CollapsibleSection:
        group = CollapsibleSection("Mesures")
        layout = QGridLayout()
        group.set_content_layout(layout)
        self.tool_group = QButtonGroup(self)
        # The buttons behave like independent toggles so the active measurement
        # tool can be disabled by clicking it a second time.
        self.tool_group.setExclusive(False)
        self.tool_buttons: dict[str, QPushButton] = {}

        for row, (kind, label) in enumerate(
            [
                ("distance", "Distance · 2 points"),
                ("angle", "Angle · 3 points"),
                ("circle", "Cercle · 3 points"),
                ("parallel", "Lignes parallèles · 3 points"),
            ]
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.toggled.connect(
                lambda checked, selected=kind: self.on_tool_toggled(selected, checked)
            )
            self.tool_group.addButton(button)
            self.tool_buttons[kind] = button
            layout.addWidget(button, row, 0, 1, 2)

        self.crosshair_check = QCheckBox("Réticule central")
        self.crosshair_check.setChecked(True)
        self.crosshair_check.toggled.connect(self.canvas.set_crosshair_visible)
        layout.addWidget(self.crosshair_check, 4, 0, 1, 2)

        scale_bar_row = QHBoxLayout()
        self.scale_bar_check = QCheckBox("Échelle")
        self.scale_bar_check.setToolTip(
            "Afficher une barre d’échelle en bas à droite de l’image"
        )
        self.scale_bar_length = QDoubleSpinBox()
        self.scale_bar_length.setDecimals(5)
        self.scale_bar_length.setRange(0.00001, 1_000_000)
        self.scale_bar_length.setValue(1.0)
        self.scale_bar_length.setKeyboardTracking(False)
        self.scale_bar_unit = QComboBox()
        self.scale_bar_unit.addItems(["mm", "µm"])
        scale_bar_row.addWidget(self.scale_bar_check)
        scale_bar_row.addWidget(self.scale_bar_length, 1)
        scale_bar_row.addWidget(self.scale_bar_unit)
        layout.addLayout(scale_bar_row, 5, 0, 1, 2)

        self.scale_bar_check.toggled.connect(self.on_scale_bar_changed)
        self.scale_bar_length.valueChanged.connect(self.on_scale_bar_changed)
        self.scale_bar_unit.currentTextChanged.connect(self.on_scale_bar_changed)
        self.scale_bar_length.setEnabled(False)
        self.scale_bar_unit.setEnabled(False)

        magnifier_row = QHBoxLayout()
        magnifier_title = QLabel("Loupe de pointage")
        self.magnifier_zoom_combo = QComboBox()
        for percentage in [200, 400, 800, 1200, 1600]:
            self.magnifier_zoom_combo.addItem(
                f"{percentage} %",
                percentage / 100.0,
            )
        self.magnifier_zoom_combo.setCurrentText("800 %")
        self.magnifier_zoom_combo.currentIndexChanged.connect(
            self.update_magnifier
        )
        self.magnifier_coordinates = QLabel("x=— · y=—")
        self.magnifier_coordinates.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        magnifier_row.addWidget(magnifier_title)
        magnifier_row.addWidget(self.magnifier_zoom_combo)
        magnifier_row.addWidget(self.magnifier_coordinates, 1)
        layout.addLayout(magnifier_row, 6, 0, 1, 2)

        self.magnifier_label = QLabel("Survoler l’image pour activer la loupe")
        self.magnifier_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.magnifier_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.magnifier_label.setMinimumSize(260, 150)
        self.magnifier_label.setFixedHeight(170)
        self.magnifier_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.magnifier_label.setStyleSheet(
            "QLabel { background-color: #101419; color: #7f8a94; }"
        )
        layout.addWidget(self.magnifier_label, 7, 0, 1, 2)

        edit_help = QLabel(
            "Recliquer sur l’outil actif pour le désactiver, puis "
            "cliquer-glisser un point pour le corriger ou une ligne "
            "pour déplacer toute la mesure."
        )
        edit_help.setWordWrap(True)
        edit_help.setStyleSheet("color: #7f8a94;")
        layout.addWidget(edit_help, 8, 0, 1, 2)

        self.undo_button = QPushButton("Annuler dernière")
        self.undo_button.clicked.connect(self.undo_measurement)
        self.clear_button = QPushButton("Tout effacer")
        self.clear_button.clicked.connect(self.clear_measurements)
        layout.addWidget(self.undo_button, 9, 0)
        layout.addWidget(self.clear_button, 9, 1)
        return group

    def _build_results_group(self) -> CollapsibleSection:
        group = CollapsibleSection("Résultats")
        layout = QVBoxLayout()
        group.set_content_layout(layout)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ["N°", "Nom", "Type", "Valeur", "Couleur"]
        )
        self.results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.results_table.itemChanged.connect(self.on_measurement_name_changed)
        self.results_table.verticalHeader().setVisible(False)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.setMinimumHeight(170)
        layout.addWidget(self.results_table)

        self.export_button = QPushButton("Exporter les mesures en CSV")
        self.export_button.clicked.connect(self.export_csv)
        layout.addWidget(self.export_button)

        help_label = QLabel(
            "Molette : zoom · glisser : déplacer · double-clic : ajuster "
            "l’image · point/mesure/étiquette : cliquer-glisser pour modifier · "
            "double-clic sur « Nom » : renommer · "
            "clic droit/Échap : annuler l’outil."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #7f8a94;")
        layout.addWidget(help_label)
        return group

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&Fichier")
        capture_action = QAction("Capturer l’image", self)
        capture_action.setShortcut(QKeySequence("Ctrl+S"))
        capture_action.triggered.connect(self.capture_image)
        file_menu.addAction(capture_action)

        output_action = QAction("Choisir le dossier des captures…", self)
        output_action.triggered.connect(self.choose_output_directory)
        file_menu.addAction(output_action)
        file_menu.addSeparator()

        quit_action = QAction("Quitter", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&Affichage")
        fit_action = QAction("Ajuster l’image", self)
        fit_action.setShortcut(QKeySequence("F"))
        fit_action.triggered.connect(self.canvas.fit_image)
        view_menu.addAction(fit_action)

        help_menu = self.menuBar().addMenu("&Aide")
        about_action = QAction("À propos", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _restore_settings(self) -> None:
        self.camera_index.setValue(int(self.settings.value("camera/index", 0)))
        self.backend_combo.setCurrentIndex(
            int(self.settings.value("camera/backend_index", 1))
        )
        self.resolution_combo.setCurrentIndex(
            int(self.settings.value("camera/resolution_index", 2))
        )
        self.fps_spin.setValue(int(self.settings.value("camera/fps", 30)))
        self.keep_raw_check.setChecked(
            self.settings.value("capture/keep_raw", True, type=bool)
        )
        self.image_name_edit.setText(
            str(self.settings.value("capture/image_name", ""))
        )
        image_name_color = str(
            self.settings.value("capture/image_name_color", "")
        )
        image_name_color_index = self.image_name_color.findData(image_name_color)
        self.image_name_color.setCurrentIndex(max(0, image_name_color_index))
        image_name_background = str(
            self.settings.value("capture/image_name_background", "")
        )
        image_name_background_index = self.image_name_background.findData(
            image_name_background
        )
        self.image_name_background.setCurrentIndex(
            max(0, image_name_background_index)
        )
        self.image_name_check.setChecked(
            self.settings.value(
                "capture/image_name_enabled", False, type=bool
            )
        )
        self.display_unit.setCurrentText(
            str(self.settings.value("measurement/unit", "mm"))
        )
        self.scale_bar_length.setValue(
            float(self.settings.value("measurement/scale_bar_length", 1.0))
        )
        self.scale_bar_unit.setCurrentText(
            str(self.settings.value("measurement/scale_bar_unit", "mm"))
        )
        self.scale_bar_check.setChecked(
            self.settings.value(
                "measurement/scale_bar_enabled", False, type=bool
            )
        )
        self.magnifier_zoom_combo.setCurrentText(
            str(self.settings.value("measurement/magnifier_zoom", "800 %"))
        )
        for key, section in self.sections.items():
            section.set_expanded(
                self.settings.value(
                    f"sections/{key}_expanded", True, type=bool
                )
            )
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _save_settings(self) -> None:
        self.settings.setValue("camera/index", self.camera_index.value())
        self.settings.setValue(
            "camera/backend_index", self.backend_combo.currentIndex()
        )
        self.settings.setValue(
            "camera/resolution_index", self.resolution_combo.currentIndex()
        )
        self.settings.setValue("camera/fps", self.fps_spin.value())
        self.settings.setValue("capture/keep_raw", self.keep_raw_check.isChecked())
        self.settings.setValue(
            "capture/image_name_enabled", self.image_name_check.isChecked()
        )
        self.settings.setValue(
            "capture/image_name", self.image_name_edit.text().strip()
        )
        self.settings.setValue(
            "capture/image_name_color", self.image_name_color.currentData() or ""
        )
        self.settings.setValue(
            "capture/image_name_background",
            self.image_name_background.currentData() or "",
        )
        self.settings.setValue("measurement/unit", self.display_unit.currentText())
        self.settings.setValue(
            "measurement/scale_bar_enabled", self.scale_bar_check.isChecked()
        )
        self.settings.setValue(
            "measurement/scale_bar_length", self.scale_bar_length.value()
        )
        self.settings.setValue(
            "measurement/scale_bar_unit", self.scale_bar_unit.currentText()
        )
        self.settings.setValue(
            "measurement/magnifier_zoom",
            self.magnifier_zoom_combo.currentText(),
        )
        for key, section in self.sections.items():
            self.settings.setValue(
                f"sections/{key}_expanded", section.is_expanded()
            )
        self.settings.setValue(
            "calibration/profile", self.profile_combo.currentText().strip()
        )
        self.settings.setValue("window/geometry", self.saveGeometry())

    def _refresh_profiles(self, selected: str | None = None) -> None:
        current = selected or self.profile_combo.currentText().strip()
        profile_names = sorted(self.calibration_store.profiles)

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(profile_names)
        if current:
            self.profile_combo.setCurrentText(current)
        elif self.profile_combo.count() == 0:
            self.profile_combo.setEditText("Objectif 1")
        self.profile_combo.blockSignals(False)

        self.objective_combo.blockSignals(True)
        self.objective_combo.clear()
        self.objective_combo.addItems(profile_names)
        objective_index = self.objective_combo.findText(current)
        self.objective_combo.setCurrentIndex(objective_index)
        self.objective_combo.setPlaceholderText(
            "Sélectionner un profil"
            if profile_names
            else "Aucun profil enregistré"
        )
        self.objective_combo.setEnabled(bool(profile_names))
        self.objective_combo.blockSignals(False)

        self.delete_profile_button.setEnabled(bool(self.calibration_store.profiles))

    def load_objective_profile(self, *_args) -> None:
        name = self.objective_combo.currentText().strip()
        if name not in self.calibration_store.profiles:
            return
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentText(name)
        self.profile_combo.blockSignals(False)
        self.load_selected_profile()

    def toggle_camera(self) -> None:
        if self.camera is not None:
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self) -> None:
        index = self.camera_index.value()
        backend = int(self.backend_combo.currentData())
        requested_width, requested_height = self.resolution_combo.currentData()

        camera = cv2.VideoCapture(index, backend)
        if not camera.isOpened():
            camera.release()
            QMessageBox.critical(
                self,
                "Caméra inaccessible",
                "Impossible d’ouvrir la caméra.\n\n"
                "Vérifie l’index, ferme les autres logiciels utilisant la caméra "
                "et essaie une autre interface (DirectShow ou Media Foundation).",
            )
            return

        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, requested_width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, requested_height)
        camera.set(cv2.CAP_PROP_FPS, self.fps_spin.value())
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.camera = camera
        self.consecutive_read_errors = 0
        interval = max(1, round(1000 / self.fps_spin.value()))
        self.timer.start(interval)
        self.start_button.setText("Arrêter")
        self.freeze_button.setEnabled(True)
        self.capture_button.setEnabled(True)
        self.camera_index.setEnabled(False)
        self.backend_combo.setEnabled(False)
        self.resolution_combo.setEnabled(False)
        self.fps_spin.setEnabled(False)
        self.camera_status.setText("Ouverture…")
        self.statusBar().showMessage("Caméra démarrée.")

    def stop_camera(self) -> None:
        self.timer.stop()
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        self.start_button.setText("Démarrer")
        self.freeze_button.setChecked(False)
        self.freeze_button.setEnabled(False)
        self.capture_button.setEnabled(self.last_frame is not None)
        self.camera_index.setEnabled(True)
        self.backend_combo.setEnabled(True)
        self.resolution_combo.setEnabled(True)
        self.fps_spin.setEnabled(True)
        self.camera_status.setText("Arrêtée")
        self.statusBar().showMessage("Caméra arrêtée.")

    def read_camera(self) -> None:
        if self.camera is None:
            return
        ok, frame = self.camera.read()
        if not ok or frame is None:
            self.consecutive_read_errors += 1
            if self.consecutive_read_errors >= 20:
                self.stop_camera()
                QMessageBox.warning(
                    self,
                    "Flux interrompu",
                    "Le flux de la caméra a été interrompu.",
                )
            return

        self.consecutive_read_errors = 0
        height, width = frame.shape[:2]
        self.current_resolution = (width, height)
        actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
        fps_text = f" · {actual_fps:.1f} i/s" if actual_fps > 0 else ""
        self.camera_status.setText(f"{width} × {height}{fps_text}")

        if not self.freeze_button.isChecked():
            self.last_frame = frame.copy()
            self.canvas.set_frame(frame)
            self.update_magnifier()

    def on_freeze_changed(self, frozen: bool) -> None:
        self.freeze_button.setText("Reprendre" if frozen else "Figer")
        self.statusBar().showMessage(
            "Image figée pour mesurer." if frozen else "Acquisition en direct."
        )

    def begin_calibration(self) -> None:
        if not self.canvas.has_image:
            QMessageBox.information(
                self,
                "Aucune image",
                "Démarre la caméra avant de réaliser l’étalonnage.",
            )
            return
        self._uncheck_tool_buttons()
        self.canvas.set_tool("calibration")

    def on_tool_toggled(self, kind: str, checked: bool) -> None:
        if checked:
            if not self.canvas.has_image:
                self.tool_buttons[kind].setChecked(False)
                QMessageBox.information(
                    self,
                    "Aucune image",
                    "Démarre la caméra avant de réaliser une mesure.",
                )
                return
            for other_kind, button in self.tool_buttons.items():
                if other_kind != kind and button.isChecked():
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
            self.canvas.set_tool(kind)
        elif not any(button.isChecked() for button in self.tool_buttons.values()):
            self.canvas.set_tool(None)
            self.statusBar().showMessage(
                "Outil désactivé. Cliquer-glisser un point pour modifier une mesure."
            )

    def _uncheck_tool_buttons(self) -> None:
        for button in self.tool_buttons.values():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)

    def cancel_current_tool(self) -> None:
        self._uncheck_tool_buttons()
        self.canvas.set_tool(None)
        self.statusBar().showMessage("Outil annulé.")

    def on_tool_completed(self, kind: str, raw_points: object) -> None:
        points = [(float(x), float(y)) for x, y in raw_points]
        if kind == "calibration":
            known_mm = self.reference_length.value()
            if self.reference_unit.currentText() == "µm":
                known_mm /= 1000.0
            try:
                self.mm_per_pixel = calibration_from_reference(
                    points[0], points[1], known_mm
                )
            except GeometryError as error:
                QMessageBox.warning(self, "Étalonnage impossible", str(error))
                return

            profile_name = self.profile_combo.currentText().strip() or "Objectif 1"
            try:
                self.calibration_store.set_profile(
                    profile_name, self.mm_per_pixel, self.current_resolution
                )
            except OSError as error:
                QMessageBox.warning(
                    self,
                    "Profil non enregistré",
                    "L’étalonnage est actif, mais le profil n’a pas pu être "
                    f"enregistré :\n{error}",
                )
            self._refresh_profiles(profile_name)
            self._update_scale_label()
            self.refresh_measurements()
            self.canvas.set_tool(None)
            self.statusBar().showMessage(
                f"Profil « {profile_name} » étalonné et enregistré."
            )
            return

        measurement = Measurement(
            number=self.next_measurement_number,
            kind=kind,
            points=points,
        )
        try:
            measurement_value(
                measurement, self.mm_per_pixel, self.display_unit.currentText()
            )
        except GeometryError as error:
            QMessageBox.warning(self, "Mesure impossible", str(error))
            return
        self.next_measurement_number += 1
        self.measurements.append(measurement)
        self.refresh_measurements()
        self.statusBar().showMessage(
            f"{TOOL_NAMES[kind]} ajoutée. L’outil reste actif."
        )

    def refresh_measurements(self) -> None:
        if not hasattr(self, "results_table"):
            return
        self._render_measurement_overlays()
        self._update_measurement_table()

    def _render_measurement_overlays(self) -> None:
        unit = self.display_unit.currentText()
        image_name = (
            self.image_name_edit.text().strip()
            if self.image_name_check.isChecked()
            else ""
        )
        self.canvas.render_measurements(
            self.measurements,
            self.mm_per_pixel,
            unit,
            self.selected_scale_bar(),
            image_name,
            str(self.image_name_color.currentData() or "#ffffff"),
            str(self.image_name_background.currentData() or ""),
        )

    def on_image_name_changed(self, *_args) -> None:
        self.refresh_measurements()

    def selected_scale_bar(self) -> ScaleBar | None:
        if not self.scale_bar_check.isChecked():
            return None
        return self.scale_bar_length.value(), self.scale_bar_unit.currentText()

    def on_scale_bar_changed(self, *_args) -> None:
        enabled = self.scale_bar_check.isChecked()
        self.scale_bar_length.setEnabled(enabled)
        self.scale_bar_unit.setEnabled(enabled)
        self.refresh_measurements()
        if enabled and not self.mm_per_pixel:
            self.statusBar().showMessage(
                "La barre d’échelle nécessite un profil d’étalonnage actif."
            )

    def select_measurement(self, number: int) -> None:
        for row, measurement in enumerate(self.measurements):
            if measurement.number == number:
                self.results_table.selectRow(row)
                return

    def move_measurement_point(
        self, number: int, point_index: int, raw_point: object
    ) -> None:
        measurement = next(
            (
                item
                for item in self.measurements
                if item.number == number
            ),
            None,
        )
        if measurement is None or not 0 <= point_index < len(measurement.points):
            return

        x, y = raw_point
        candidate = (float(x), float(y))
        previous = measurement.points[point_index]
        measurement.points[point_index] = candidate
        try:
            measurement_value(
                measurement, self.mm_per_pixel, self.display_unit.currentText()
            )
        except GeometryError:
            # Keep the last valid geometry if two points coincide or the three
            # points of a circle become collinear during the drag.
            measurement.points[point_index] = previous
            return

        self.refresh_measurements()
        self.select_measurement(number)

    def finish_measurement_point_move(self, number: int, _point_index: int) -> None:
        self._show_adjusted_measurement(number)

    def move_measurement(self, number: int, raw_points: object) -> None:
        measurement = next(
            (item for item in self.measurements if item.number == number),
            None,
        )
        if measurement is None:
            return
        measurement.points = [
            (float(x), float(y))
            for x, y in raw_points
        ]
        self.refresh_measurements()
        self.select_measurement(number)

    def finish_measurement_move(self, number: int) -> None:
        self._show_adjusted_measurement(number)

    def move_measurement_label(self, number: int, raw_position: object) -> None:
        measurement = next(
            (item for item in self.measurements if item.number == number),
            None,
        )
        if measurement is None:
            return
        x, y = raw_position
        anchor = measurement_label_anchor(measurement)
        measurement.label_offset = (
            float(x) - anchor[0],
            float(y) - anchor[1],
        )
        self._render_measurement_overlays()
        self.select_measurement(number)

    def finish_measurement_label_move(self, number: int) -> None:
        self.statusBar().showMessage(
            f"Étiquette de la mesure {number} repositionnée."
        )

    def _show_adjusted_measurement(self, number: int) -> None:
        measurement = next(
            (item for item in self.measurements if item.number == number),
            None,
        )
        if measurement is None:
            return
        value, unit = measurement_value(
            measurement, self.mm_per_pixel, self.display_unit.currentText()
        )
        self.statusBar().showMessage(
            f"Mesure {measurement.number} ajustée : {format_number(value)} {unit}."
        )

    def _update_measurement_table(self) -> None:
        if not hasattr(self, "results_table"):
            return
        self.results_table.blockSignals(True)
        try:
            self.results_table.setRowCount(len(self.measurements))
            unit = self.display_unit.currentText()
            for row, measurement in enumerate(self.measurements):
                number_item = QTableWidgetItem(str(measurement.number))
                number_item.setFlags(
                    number_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                name_item = QTableWidgetItem(measurement.name)
                type_item = QTableWidgetItem(TOOL_NAMES[measurement.kind])
                type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                value, value_unit = measurement_value(
                    measurement, self.mm_per_pixel, unit
                )
                value_item = QTableWidgetItem(
                    f"{format_number(value)} {value_unit}"
                )
                value_item.setFlags(
                    value_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                self.results_table.setItem(row, 0, number_item)
                self.results_table.setItem(row, 1, name_item)
                self.results_table.setItem(row, 2, type_item)
                self.results_table.setItem(row, 3, value_item)
                color_combo = QComboBox()
                for label, color_value in MEASUREMENT_COLOR_CHOICES:
                    color = (
                        measurement_color(measurement)
                        if not color_value
                        else QColor(color_value)
                    )
                    color_combo.addItem(
                        color_icon(color),
                        label,
                        color_value,
                    )
                selected_color = color_combo.findData(measurement.color)
                color_combo.setCurrentIndex(max(0, selected_color))
                color_combo.currentIndexChanged.connect(
                    lambda _index,
                    number=measurement.number,
                    combo=color_combo: self.on_measurement_color_changed(number, combo)
                )
                self.results_table.setCellWidget(row, 4, color_combo)
        finally:
            self.results_table.blockSignals(False)
        self.results_table.resizeColumnToContents(0)
        self.results_table.setColumnWidth(1, max(100, self.results_table.columnWidth(1)))
        self.results_table.resizeColumnToContents(2)
        self.undo_button.setEnabled(bool(self.measurements))
        self.clear_button.setEnabled(bool(self.measurements))
        self.export_button.setEnabled(bool(self.measurements))

    def on_measurement_name_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        row = item.row()
        if not 0 <= row < len(self.measurements):
            return
        measurement = self.measurements[row]
        measurement.name = item.text().strip()
        self.refresh_measurements()
        self.select_measurement(measurement.number)
        self.statusBar().showMessage(
            f"Nom de la mesure {measurement.number} mis à jour."
        )

    def on_measurement_color_changed(
        self, number: int, combo: QComboBox
    ) -> None:
        measurement = next(
            (item for item in self.measurements if item.number == number),
            None,
        )
        if measurement is None:
            return
        measurement.color = str(combo.currentData() or "")
        self._render_measurement_overlays()
        self.select_measurement(number)
        self.statusBar().showMessage(
            f"Couleur de la mesure {number} mise à jour."
        )

    def _update_scale_label(self) -> None:
        if not self.mm_per_pixel:
            self.scale_label.setText("Non calibrée — les longueurs seront en pixels.")
            return
        microns = self.mm_per_pixel * 1000
        text = f"1 px = {format_number(microns)} µm"
        if self.current_resolution:
            text += (
                f"\nRésolution active : {self.current_resolution[0]} × "
                f"{self.current_resolution[1]}"
            )
        self.scale_label.setText(text)

    def load_selected_profile(self, *_args) -> None:
        name = self.profile_combo.currentText().strip()
        profile = self.calibration_store.profiles.get(name)
        if not profile:
            return
        self.objective_combo.blockSignals(True)
        self.objective_combo.setCurrentText(name)
        self.objective_combo.blockSignals(False)
        self.mm_per_pixel = float(profile["mm_per_pixel"])
        self._update_scale_label()
        self.refresh_measurements()

        saved_resolution = profile.get("resolution")
        if (
            saved_resolution
            and self.current_resolution
            and tuple(saved_resolution) != self.current_resolution
        ):
            self.statusBar().showMessage(
                "Attention : ce profil a été créé avec une autre résolution."
            )
        else:
            self.statusBar().showMessage(f"Profil « {name} » chargé.")

    def delete_selected_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if name not in self.calibration_store.profiles:
            return
        answer = QMessageBox.question(
            self,
            "Supprimer le profil",
            f"Supprimer le profil d’étalonnage « {name} » ?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.calibration_store.delete_profile(name)
            self.mm_per_pixel = None
            self._refresh_profiles()
            self._update_scale_label()
            self.refresh_measurements()

    def undo_measurement(self) -> None:
        if self.measurements:
            self.measurements.pop()
            self.refresh_measurements()
            self.statusBar().showMessage("Dernière mesure supprimée.")

    def delete_selected(self) -> None:
        row = self.results_table.currentRow()
        if 0 <= row < len(self.measurements):
            del self.measurements[row]
            self.refresh_measurements()
            self.statusBar().showMessage("Mesure sélectionnée supprimée.")

    def clear_measurements(self) -> None:
        if not self.measurements:
            return
        answer = QMessageBox.question(
            self,
            "Effacer les mesures",
            "Effacer toutes les mesures affichées ?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.measurements.clear()
            self.refresh_measurements()
            self.statusBar().showMessage("Toutes les mesures ont été effacées.")

    def default_output_directory(self) -> Path:
        stored = self.settings.value("capture/output_directory")
        if stored:
            return Path(str(stored))
        pictures = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        return Path(pictures) / "OptiMeasureLive"

    def choose_output_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Dossier des captures",
            str(self.default_output_directory()),
        )
        if selected:
            self.settings.setValue("capture/output_directory", selected)
            self.statusBar().showMessage(f"Captures enregistrées dans : {selected}")

    def capture_image(self) -> None:
        if self.last_frame is None:
            QMessageBox.information(
                self, "Aucune image", "Aucune image n’est disponible."
            )
            return
        output = self.default_output_directory()
        try:
            output.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            image_name = (
                self.image_name_edit.text().strip()
                if self.image_name_check.isChecked()
                else ""
            )
            filename_stem = safe_capture_filename_stem(image_name) or "mesure"
            base_name = f"{filename_stem}_{timestamp}"
            annotated = annotate_frame(
                self.last_frame,
                self.measurements,
                self.mm_per_pixel,
                self.display_unit.currentText(),
                False,
                self.selected_scale_bar(),
                image_name,
                str(self.image_name_color.currentData() or "#ffffff"),
                str(self.image_name_background.currentData() or ""),
            )
            annotated_path = output / f"{base_name}.png"
            if not write_png(annotated_path, annotated):
                raise OSError("OpenCV n’a pas pu écrire l’image.")
            if self.keep_raw_check.isChecked():
                raw_path = output / f"{base_name}_brute.png"
                if not write_png(raw_path, self.last_frame):
                    raise OSError("OpenCV n’a pas pu écrire l’image brute.")
        except OSError as error:
            QMessageBox.critical(
                self, "Capture impossible", f"Échec de l’enregistrement :\n{error}"
            )
            return
        self.statusBar().showMessage(f"Capture enregistrée : {annotated_path}")

    def export_csv(self) -> None:
        if not self.measurements:
            QMessageBox.information(
                self, "Aucune mesure", "Il n’y a aucune mesure à exporter."
            )
            return
        default_path = self.default_output_directory() / (
            "mesures_" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S") + ".csv"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter les mesures",
            str(default_path),
            "Fichier CSV (*.csv)",
        )
        if not filename:
            return

        unit = self.display_unit.currentText()
        profile = self.profile_combo.currentText().strip()
        try:
            destination = Path(filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(
                    [
                        "numero",
                        "nom",
                        "couleur",
                        "type",
                        "valeur",
                        "unite",
                        "points_image_px",
                        "mm_par_pixel",
                        "profil",
                        "resolution",
                        "horodatage",
                    ]
                )
                for measurement in self.measurements:
                    value, value_unit = measurement_value(
                        measurement, self.mm_per_pixel, unit
                    )
                    resolution = (
                        f"{self.current_resolution[0]}x{self.current_resolution[1]}"
                        if self.current_resolution
                        else ""
                    )
                    writer.writerow(
                        [
                            measurement.number,
                            measurement.name,
                            measurement_color(measurement).name(),
                            TOOL_NAMES[measurement.kind],
                            format_number(value),
                            value_unit,
                            points_to_text(measurement.points),
                            (f"{self.mm_per_pixel:.12g}" if self.mm_per_pixel else ""),
                            profile,
                            resolution,
                            measurement.created_at,
                        ]
                    )
        except OSError as error:
            QMessageBox.critical(
                self, "Export impossible", f"Échec de l’export CSV :\n{error}"
            )
            return
        self.statusBar().showMessage(f"CSV enregistré : {filename}")

    def show_cursor_position(self, x: float, y: float) -> None:
        self.magnifier_position = (x, y)
        self.magnifier_coordinates.setText(f"x={x:.2f} · y={y:.2f}")
        self.update_magnifier()
        self.statusBar().showMessage(f"Position image : x={x:.1f} px · y={y:.1f} px")

    def update_magnifier(self, *_args) -> None:
        if self.last_frame is None or self.magnifier_position is None:
            self.magnifier_label.setPixmap(QPixmap())
            self.magnifier_label.setText(
                "Survoler l’image pour activer la loupe"
            )
            return

        available_width = max(
            32,
            self.magnifier_label.contentsRect().width(),
        )
        available_height = max(
            32,
            self.magnifier_label.contentsRect().height(),
        )
        zoom_factor = float(self.magnifier_zoom_combo.currentData())
        image_data = magnified_region(
            self.last_frame,
            self.magnifier_position,
            zoom_factor,
            (available_width, available_height),
        )
        height, width = image_data.shape[:2]
        image = QImage(
            image_data.data,
            width,
            height,
            image_data.strides[0],
            QImage.Format.Format_BGR888,
        ).copy()
        self.magnifier_label.setText("")
        self.magnifier_label.setPixmap(QPixmap.fromImage(image))

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"À propos de {APP_NAME}",
            f"<b>{APP_NAME} {APP_VERSION}</b><br><br>"
            "Acquisition et mesure dimensionnelle pour caméras USB.<br>"
            "OpenCV + PySide6 · licence MIT.<br><br>"
            "Les mesures sont conservées dans les coordonnées natives "
            "de l’image.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_settings()
        self.stop_camera()
        event.accept()


def main() -> int:
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationVersion(APP_VERSION)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
