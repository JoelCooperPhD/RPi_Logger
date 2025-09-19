#!/usr/bin/env python3
"""
Raspberry Pi Camera with Timestamp Overlay
- OpenCV preview with timestamp overlay
- Snapshots with 's'
- Quit with 'q'
- Overlay drawn in both preview loop and callback so it works for video too
"""

import time
import cv2
from picamera2 import Picamera2


def draw_overlay(request):
    """Draw overlay into frames before encoding/recording."""
    frame = request.make_array("main")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(frame, timestamp, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)


def main():
    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": (1280, 720), "format": "XRGB8888"}
    )
    picam2.configure(config)

    # Attach callback (applies to video recording, not to capture_array)
    picam2.pre_callback = draw_overlay

    picam2.start()
    time.sleep(0.5)

    cv2.startWindowThread()
    snapshot_count = 0

    try:
        while True:
            frame = picam2.capture_array("main")

            # Draw overlay again for live preview and snapshots
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, timestamp, (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3)
            cv2.putText(frame, timestamp, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            cv2.imshow("Camera Feed", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            elif key == ord("s"):
                ts = time.strftime("%Y-%m-%d_%H-%M-%S")
                filename = f"snapshot_{ts}.jpg"
                cv2.imwrite(filename, frame)
                print(f"Saved: {filename}")
                snapshot_count += 1
    finally:
        picam2.stop()
        cv2.destroyAllWindows()
        print(f"Done! Saved {snapshot_count} snapshot(s)")


if __name__ == "__main__":
    main()
