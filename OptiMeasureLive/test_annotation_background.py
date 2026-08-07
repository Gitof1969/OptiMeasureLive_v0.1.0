import unittest

import numpy as np
from PySide6.QtGui import QColor

from app import (
    LABEL_BACKGROUND_ALPHA,
    Measurement,
    annotate_frame,
    contrasting_label_background,
)


class AnnotationBackgroundTests(unittest.TestCase):
    def test_background_contrasts_with_text_color(self):
        dark_text_background = contrasting_label_background(QColor("#101010"))
        colored_text_background = contrasting_label_background(QColor("#20d6e8"))
        white_text_background = contrasting_label_background(QColor("#ffffff"))

        self.assertEqual(dark_text_background.getRgb(), (255, 255, 255, 170))
        self.assertEqual(colored_text_background.getRgb(), (255, 255, 255, 170))
        self.assertEqual(white_text_background.getRgb(), (16, 16, 16, 170))
        self.assertEqual(dark_text_background.alpha(), LABEL_BACKGROUND_ALPHA)

        custom_background = contrasting_label_background(
            QColor("#ffffff"),
            64,
        )
        self.assertEqual(custom_background.alpha(), 64)

    def test_translucent_background_is_blended_into_capture(self):
        frame = np.full((120, 240, 3), 100, dtype=np.uint8)
        measurement = Measurement(
            number=1,
            kind="distance",
            points=[(20.0, 50.0), (180.0, 50.0)],
            color="#20d6e8",
        )

        plain = annotate_frame(frame, [measurement], None, "mm", False)
        with_background = annotate_frame(
            frame,
            [measurement],
            None,
            "mm",
            False,
            measurement_label_background=True,
        )

        changed = np.any(plain != with_background, axis=2)
        self.assertGreater(np.count_nonzero(changed), 100)
        changed_values = with_background[changed]
        self.assertTrue(np.any((changed_values > 16) & (changed_values < 255)))

    def test_capture_background_opacity_is_adjustable(self):
        frame = np.full((120, 240, 3), 100, dtype=np.uint8)
        measurement = Measurement(
            number=1,
            kind="distance",
            points=[(20.0, 50.0), (180.0, 50.0)],
            color="#20d6e8",
        )
        plain = annotate_frame(frame, [measurement], None, "mm", False)
        invisible_background = annotate_frame(
            frame,
            [measurement],
            None,
            "mm",
            False,
            measurement_label_background=True,
            measurement_label_background_alpha=0,
        )
        low_opacity = annotate_frame(
            frame,
            [measurement],
            None,
            "mm",
            False,
            measurement_label_background=True,
            measurement_label_background_alpha=51,
        )
        high_opacity = annotate_frame(
            frame,
            [measurement],
            None,
            "mm",
            False,
            measurement_label_background=True,
            measurement_label_background_alpha=230,
        )

        np.testing.assert_array_equal(invisible_background, plain)
        low_difference = np.abs(low_opacity.astype(int) - plain.astype(int)).sum()
        high_difference = np.abs(high_opacity.astype(int) - plain.astype(int)).sum()
        self.assertGreater(high_difference, low_difference)

    def test_measurement_label_has_no_dark_shadow(self):
        frame = np.full((120, 240, 3), 100, dtype=np.uint8)
        measurement = Measurement(
            number=1,
            kind="distance",
            points=[(20.0, 50.0), (180.0, 50.0)],
            color="#ffffff",
        )

        annotated = annotate_frame(frame, [measurement], None, "mm", False)

        self.assertGreaterEqual(int(annotated.min()), 100)


if __name__ == "__main__":
    unittest.main()
