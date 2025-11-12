import unittest
from unittest import mock

import numpy as np

from Modules.CamerasStub.utils.frame_convert import frame_to_image


class FrameConvertTests(unittest.TestCase):

    def test_yuv_conversion_strips_stride_padding_before_color_transform(self):
        height = 4
        width = 4
        stride = 8  # simulate padded columns from the ISP
        rows = height * 3 // 2
        frame = np.arange(rows * stride, dtype=np.uint8).reshape(rows, stride)

        mocked_rgb = np.zeros((height, width, 3), dtype=np.uint8)
        with mock.patch("Modules.CamerasStub.utils.frame_convert.cv2.cvtColor", return_value=mocked_rgb) as convert_mock:
            image = frame_to_image(frame, "YUV420", size_hint=(width, height))

        args, _ = convert_mock.call_args
        converted = args[0]
        self.assertEqual(converted.shape, (rows, width))
        self.assertEqual(image.size, (width, height))

    def test_rgb888_frames_respect_bgr_storage_order(self):
        # Picamera2 labels the stream RGB888 but the bytes arrive in BGR order.
        frame = np.array([[[30, 20, 10]]], dtype=np.uint8)  # B, G, R
        image = frame_to_image(frame, "RGB888")
        self.assertEqual(image.size, (1, 1))
        self.assertEqual(image.getpixel((0, 0)), (10, 20, 30))

    def test_xbgr8888_frames_drop_padding_and_preserve_colors(self):
        frame = np.array([[[5, 15, 25, 255]]], dtype=np.uint8)  # R, G, B, X when decoded via raw RGBX
        image = frame_to_image(frame, "XBGR8888")
        self.assertEqual(image.getpixel((0, 0)), (5, 15, 25))


if __name__ == "__main__":
    unittest.main()
