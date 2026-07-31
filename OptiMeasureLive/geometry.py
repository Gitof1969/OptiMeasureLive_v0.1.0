"""Pure geometry helpers used by OptiMeasure Live.

The module intentionally has no OpenCV or Qt dependency so its calculations can
be tested independently from the camera and user interface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import acos, degrees, hypot

Point = tuple[float, float]


class GeometryError(ValueError):
    """Raised when a geometric construction cannot be computed."""


def distance_px(first: Point, second: Point) -> float:
    """Return the Euclidean distance between two image points in pixels."""

    return hypot(second[0] - first[0], second[1] - first[1])


def calibrated_distance(first: Point, second: Point, mm_per_pixel: float) -> float:
    """Return the distance in millimetres for a valid image calibration."""

    if mm_per_pixel <= 0:
        raise GeometryError("La calibration doit être strictement positive.")
    return distance_px(first, second) * mm_per_pixel


def angle_degrees(first: Point, vertex: Point, third: Point) -> float:
    """Return the smaller A-B-C angle in degrees."""

    vector_a = (first[0] - vertex[0], first[1] - vertex[1])
    vector_b = (third[0] - vertex[0], third[1] - vertex[1])
    norm_a = hypot(*vector_a)
    norm_b = hypot(*vector_b)
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        raise GeometryError("Les points définissant l'angle sont confondus.")

    cosine = (vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]) / (norm_a * norm_b)
    # Numerical rounding may otherwise put cosine infinitesimally outside [-1, 1].
    cosine = max(-1.0, min(1.0, cosine))
    return degrees(acos(cosine))


@dataclass(frozen=True, slots=True)
class Circle:
    center: Point
    radius_px: float


@dataclass(frozen=True, slots=True)
class ParallelLines:
    first: tuple[Point, Point]
    second: tuple[Point, Point]
    connector: tuple[Point, Point]
    distance_px: float


def circle_from_three_points(first: Point, second: Point, third: Point) -> Circle:
    """Return the circumcircle through three non-collinear image points."""

    ax, ay = first
    bx, by = second
    cx, cy = third
    determinant = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(determinant) <= 1e-9:
        raise GeometryError("Les trois points du cercle sont alignés.")

    a_squared = ax * ax + ay * ay
    b_squared = bx * bx + by * by
    c_squared = cx * cx + cy * cy

    center_x = (
        a_squared * (by - cy) + b_squared * (cy - ay) + c_squared * (ay - by)
    ) / determinant
    center_y = (
        a_squared * (cx - bx) + b_squared * (ax - cx) + c_squared * (bx - ax)
    ) / determinant

    center = (center_x, center_y)
    return Circle(center=center, radius_px=distance_px(center, first))


def parallel_lines_from_three_points(
    first: Point,
    second: Point,
    third: Point,
) -> ParallelLines:
    """Build two parallel lines and their perpendicular separation.

    ``first`` and ``second`` define the reference direction. The other line
    passes through ``third``. Display segments are extended when necessary so
    that all three construction points remain visible on their line.
    """

    delta_x = second[0] - first[0]
    delta_y = second[1] - first[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared <= 1e-12:
        raise GeometryError(
            "Les deux premiers points définissant les parallèles sont confondus."
        )

    projection_factor = (
        (third[0] - first[0]) * delta_x
        + (third[1] - first[1]) * delta_y
    ) / length_squared
    projection = (
        first[0] + projection_factor * delta_x,
        first[1] + projection_factor * delta_y,
    )
    offset = (
        third[0] - projection[0],
        third[1] - projection[1],
    )

    start_factor = min(0.0, projection_factor)
    end_factor = max(1.0, projection_factor)
    first_start = (
        first[0] + start_factor * delta_x,
        first[1] + start_factor * delta_y,
    )
    first_end = (
        first[0] + end_factor * delta_x,
        first[1] + end_factor * delta_y,
    )
    second_start = (
        first_start[0] + offset[0],
        first_start[1] + offset[1],
    )
    second_end = (
        first_end[0] + offset[0],
        first_end[1] + offset[1],
    )

    return ParallelLines(
        first=(first_start, first_end),
        second=(second_start, second_end),
        connector=(projection, third),
        distance_px=hypot(*offset),
    )


def calibration_from_reference(
    first: Point, second: Point, known_length_mm: float
) -> float:
    """Calculate millimetres per pixel from a known reference length."""

    if known_length_mm <= 0:
        raise GeometryError("La longueur étalon doit être strictement positive.")
    pixels = distance_px(first, second)
    if pixels <= 1e-9:
        raise GeometryError("Les deux points de calibration sont confondus.")
    return known_length_mm / pixels


def points_to_text(points: Sequence[Point], decimals: int = 2) -> str:
    """Serialize points into a compact human-readable string."""

    return " ; ".join(f"({x:.{decimals}f}, {y:.{decimals}f})" for x, y in points)
