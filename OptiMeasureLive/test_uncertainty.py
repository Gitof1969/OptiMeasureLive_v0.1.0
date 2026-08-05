import unittest

from app import Measurement, assess_distance_uncertainty


class DistanceUncertaintyTests(unittest.TestCase):
    def test_two_pixel_uncertainty_and_one_percent_requirement(self):
        measurement = Measurement(
            number=1,
            kind="distance",
            points=[(0, 0), (100, 0)],
        )

        assessment = assess_distance_uncertainty(measurement, 0.005)

        self.assertAlmostEqual(assessment.measured_mm, 0.5)
        self.assertAlmostEqual(assessment.uncertainty_mm, 0.01)
        self.assertAlmostEqual(assessment.relative_percent, 2.0)
        self.assertAlmostEqual(assessment.required_mm_per_pixel, 0.0025)

    def test_non_distance_measurement_is_rejected(self):
        measurement = Measurement(
            number=1,
            kind="angle",
            points=[(1, 0), (0, 0), (0, 1)],
        )

        with self.assertRaises(ValueError):
            assess_distance_uncertainty(measurement, 0.005)

    def test_invalid_calibration_is_rejected(self):
        measurement = Measurement(
            number=1,
            kind="distance",
            points=[(0, 0), (100, 0)],
        )

        with self.assertRaises(ValueError):
            assess_distance_uncertainty(measurement, 0.0)


if __name__ == "__main__":
    unittest.main()
