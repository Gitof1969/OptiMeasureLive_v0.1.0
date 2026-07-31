import unittest

from geometry import (
    GeometryError,
    angle_degrees,
    calibration_from_reference,
    circle_from_three_points,
    distance_px,
    parallel_lines_from_three_points,
)


class GeometryTests(unittest.TestCase):
    def test_distance(self):
        self.assertAlmostEqual(distance_px((0, 0), (3, 4)), 5.0)

    def test_right_angle(self):
        self.assertAlmostEqual(angle_degrees((1, 0), (0, 0), (0, 1)), 90.0)

    def test_circle(self):
        circle = circle_from_three_points((1, 0), (0, 1), (-1, 0))
        self.assertAlmostEqual(circle.center[0], 0.0)
        self.assertAlmostEqual(circle.center[1], 0.0)
        self.assertAlmostEqual(circle.radius_px, 1.0)

    def test_circle_rejects_collinear_points(self):
        with self.assertRaises(GeometryError):
            circle_from_three_points((0, 0), (1, 1), (2, 2))

    def test_calibration(self):
        self.assertAlmostEqual(calibration_from_reference((0, 0), (200, 0), 10.0), 0.05)

    def test_parallel_lines_distance(self):
        lines = parallel_lines_from_three_points((0, 0), (10, 0), (3, 4))
        self.assertAlmostEqual(lines.distance_px, 4.0)
        self.assertEqual(lines.first, ((0, 0), (10, 0)))
        self.assertEqual(lines.second, ((0, 4), (10, 4)))
        self.assertEqual(lines.connector, ((3, 0), (3, 4)))

    def test_parallel_lines_extend_to_third_point(self):
        lines = parallel_lines_from_three_points((0, 0), (10, 0), (15, 4))
        self.assertEqual(lines.first, ((0, 0), (15, 0)))
        self.assertEqual(lines.second, ((0, 4), (15, 4)))

    def test_parallel_lines_reject_identical_reference_points(self):
        with self.assertRaises(GeometryError):
            parallel_lines_from_three_points((2, 3), (2, 3), (8, 9))


if __name__ == "__main__":
    unittest.main()
