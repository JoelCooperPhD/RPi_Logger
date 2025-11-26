"""
Picamera2 color format handling for IMX296 global shutter cameras.

!! IMPORTANT - READ THIS BEFORE CHANGING ANYTHING !!

The IMX296 global shutter camera has a KERNEL BUG that causes R and B channels
to be swapped. This has been "fixed" multiple times but keeps regressing.

THE BUG:
--------
- The IMX296 sensor reports Bayer pattern SBGGR (Blue-Green-Green-Red)
- But the actual sensor is SRGGB (Red-Green-Green-Blue)
- The ISP debayers using the wrong pattern
- Result: When you request RGB888 format, you actually get BGR888

THE FIX:
--------
We do NOT swap the pixels. We simply label the output correctly as "bgr"
so downstream code (OpenCV, display pipeline) handles it properly.

WHY NOT SWAP PIXELS?
--------------------
Swapping pixels is expensive (memory copy) and error-prone (easy to double-swap).
The correct fix is to be truthful about what format the data actually is.

WHEN THIS BUG IS FIXED IN THE KERNEL:
-------------------------------------
If/when the kernel properly fixes the Bayer pattern, frames will come out as
actual RGB. At that point, change PICAM_OUTPUT_FORMAT to "rgb".

You can test by capturing a frame of something with a known red color and
checking if the red channel (index 0 for RGB, index 2 for BGR) has the
highest value.

Test command:
    python3 -c "
    from picamera2 import Picamera2
    cam = Picamera2(0)
    cam.configure(cam.create_video_configuration(main={'format': 'RGB888'}))
    cam.start()
    frame = cam.capture_array('main')
    print('Pixel [0,0]:', frame[0,0,:3])
    print('If red object: R should be highest')
    print('Index 0 =', frame[0,0,0], '  Index 2 =', frame[0,0,2])
    cam.close()
    "
"""

# The ACTUAL color format output by Picamera2 RGB888 on IMX296.
# Due to kernel Bayer pattern bug, RGB888 outputs BGR.
PICAM_OUTPUT_FORMAT = "bgr"


def get_picam_color_format() -> str:
    """
    Returns the actual color format of Picamera2 RGB888 output.

    Currently returns "bgr" due to IMX296 Bayer pattern kernel bug.
    See module docstring for full explanation.
    """
    return PICAM_OUTPUT_FORMAT


def is_bgr_due_to_kernel_bug() -> bool:
    """Returns True if we're working around the IMX296 color bug."""
    return PICAM_OUTPUT_FORMAT == "bgr"
