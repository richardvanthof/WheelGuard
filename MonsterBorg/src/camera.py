import cv2

USE_LAPTOP_CAMERA: bool = True

CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240

def get_camera():
    if USE_LAPTOP_CAMERA:
        video_capture = cv2.VideoCapture(0)

        if not video_capture.isOpened():
            print("Could not open PI camera.")
            sys.exit(1)

        return video_capture
    else:
        from picamera2 import Picamera2
        import time

        picam2 = Picamera2()
        config = picam2.create_preview_configuration(
            main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
        )

        picam2.configure(config)
        picam2.start()

        time.sleep(0.5)

        return picam2

def get_frame(video_capture):
    frame = None
    if USE_LAPTOP_CAMERA:
        _ret, frame = video_capture.read()
    else:
        frame = video_capture.capture_array()

    return frame