#!/usr/bin/env python3
"""
human_detect_udp.py  —  Python 3.6 compatible
───────────────────────────────────────────────
Detects whether a human is present in the camera frame and broadcasts a
UDP packet on state change:
    b'\x01'  → human detected
    b'\x00'  → no human

Two detector backends, both use only opencv-python (no ultralytics / torch):

  DETECTOR = "hog"     — OpenCV built-in HOG+SVM person detector.
                         Zero extra setup.  Fast, good enough for close range.

  DETECTOR = "yolov4"  — YOLOv4-tiny via OpenCV DNN.  More accurate.
                         Needs a one-time download (see instructions below).

YOLOv4-tiny download (run once):
    wget https://raw.githubusercontent.com/AlexeyAB/darknet/master/cfg/yolov4-tiny.cfg
    wget https://github.com/AlexeyAB/darknet/releases/download/darknet_yolo_v4_pre/yolov4-tiny.weights

Usage:
    python3 human_detect_udp.py
    python3 human_detect_udp.py --every-frame
    python3 human_detect_udp.py --receiver 192.168.1.50 --port 8221
"""

import argparse
import os
import socket
import sys
import time

import cv2

# ──────────────────────────────────────────────────── CONFIG
DEFAULT_RECEIVER = "192.168.50.2"
DEFAULT_UDP_PORT = 8221
DEFAULT_CAMERA   = 0
CONF_THRESHOLD   = 0.40   # used by yolov4 backend

# "hog" or "yolov4"
DETECTOR = "hog"

# Paths for yolov4 backend (only needed if DETECTOR = "yolov4")
YOLO_CFG     = "yolov4-tiny.cfg"
YOLO_WEIGHTS = "yolov4-tiny.weights"


# ──────────────────────────────────────────────────── DETECTORS

class HogDetector:
    def __init__(self):
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        print("Detector: OpenCV HOG (no download needed)")

    def detect(self, frame):
        # Resize to speed up; HOG is stride-sensitive to large images
        small = cv2.resize(frame, (320, 240))
        rects, _ = self.hog.detectMultiScale(
            small,
            winStride=(8, 8),
            padding=(4, 4),
            scale=1.05,
        )
        return len(rects) > 0, small


class Yolov4Detector:
    PERSON_CLASS = 0   # COCO class index for "person"

    def __init__(self, cfg, weights, conf):
        if not os.path.exists(cfg):
            sys.exit(f"YOLOv4 config not found: {cfg}\n"
                     "Download with:\n"
                     "  wget https://raw.githubusercontent.com/AlexeyAB/"
                     "darknet/master/cfg/yolov4-tiny.cfg")
        if not os.path.exists(weights):
            sys.exit(f"YOLOv4 weights not found: {weights}\n"
                     "Download with:\n"
                     "  wget https://github.com/AlexeyAB/darknet/releases/"
                     "download/darknet_yolo_v4_pre/yolov4-tiny.weights")
        self.conf  = conf
        self.net   = cv2.dnn.readNetFromDarknet(cfg, weights)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        layer_names    = self.net.getLayerNames()
        unconnected    = self.net.getUnconnectedOutLayers()
        # getUnconnectedOutLayers() returns shape (N,1) in older OpenCV
        self.out_layers = [layer_names[i[0] - 1]
                           if hasattr(i, '__len__') else layer_names[i - 1]
                           for i in unconnected]
        print("Detector: YOLOv4-tiny (OpenCV DNN)")

    def detect(self, frame):
        blob = cv2.dnn.blobFromImage(
            frame, 1 / 255.0, (416, 416), swapRB=True, crop=False
        )
        self.net.setInput(blob)
        outs = self.net.forward(self.out_layers)

        h, w = frame.shape[:2]
        for out in outs:
            for detection in out:
                scores  = detection[5:]
                cls_id  = int(scores.argmax())
                conf    = float(scores[cls_id])
                if cls_id == self.PERSON_CLASS and conf >= self.conf:
                    return True, frame
        return False, frame


# ──────────────────────────────────────────────────── CAMERA OPEN

def open_camera(index):
    """
    Open the camera on Jetson Nano (CSI or USB) or Mac.

    Tried in order:
      1. nvarguscamerasrc  — Jetson CSI camera (IMX219 / IMX477 etc.)
                             Uses NVIDIA's ISP directly, most reliable on Jetson.
      2. v4l2src           — USB camera on Linux via GStreamer.
      3. Plain VideoCapture— fallback for Mac and non-GStreamer builds.
    """

    # ── Option 1: Jetson CSI camera ───────────────────────────────────────
    gst_csi = (
        "nvarguscamerasrc sensor-id={} ! "
        "video/x-raw(memory:NVMM),width=320,height=240,framerate=15/1 ! "
        "nvvidconv ! "
        "video/x-raw,format=BGRx ! "
        "videoconvert ! "
        "video/x-raw,format=BGR ! "
        "appsink drop=true sync=false"
    ).format(index)

    cap = cv2.VideoCapture(gst_csi, cv2.CAP_GSTREAMER)
    if cap.isOpened():
        for _ in range(5):
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                print("Camera opened via nvarguscamerasrc (CSI)")
                return cap
        cap.release()

    # ── Option 2: USB camera via GStreamer V4L2 ───────────────────────────
    gst_usb = (
        "v4l2src device=/dev/video{} ! "
        "video/x-raw,width=320,height=240,framerate=15/1 ! "
        "videoconvert ! "
        "video/x-raw,format=BGR ! "
        "appsink drop=true sync=false"
    ).format(index)

    cap = cv2.VideoCapture(gst_usb, cv2.CAP_GSTREAMER)
    if cap.isOpened():
        for _ in range(5):
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                print("Camera opened via v4l2src (USB)")
                return cap
        cap.release()

    # ── Option 3: plain open (Mac / no GStreamer) ─────────────────────────
    print("GStreamer pipelines failed, trying direct open (Mac / fallback)...")
    cap = cv2.VideoCapture(index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        for _ in range(10):
            ret, frame = cap.read()
            time.sleep(0.05)
            if ret and frame is not None and frame.size > 0:
                print("Camera opened via direct VideoCapture")
                return cap
        cap.release()

    return None


# ──────────────────────────────────────────────────── MAIN

def main():
    parser = argparse.ArgumentParser(description="Human detection → UDP flag")
    parser.add_argument("--receiver",    default=DEFAULT_RECEIVER)
    parser.add_argument("--port",        default=DEFAULT_UDP_PORT, type=int)
    parser.add_argument("--camera",      default=DEFAULT_CAMERA,   type=int)
    parser.add_argument("--conf",        default=CONF_THRESHOLD,   type=float)
    parser.add_argument("--every-frame", action="store_true",
                        help="Send a packet every frame, not just on change")
    args = parser.parse_args()

    # ── Detector ──────────────────────────────────────────────────────────
    if DETECTOR == "yolov4":
        detector = Yolov4Detector(YOLO_CFG, YOLO_WEIGHTS, args.conf)
    else:
        detector = HogDetector()

    # ── UDP socket ────────────────────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    print("UDP → {}:{}".format(args.receiver, args.port))

    # ── Camera ────────────────────────────────────────────────────────────
    cap = open_camera(args.camera)
    if cap is None or not cap.isOpened():
        sys.exit("Cannot open camera {}".format(args.camera))
    print("Camera {} ready. Press q or ESC to quit.\n".format(args.camera))

    prev_flag  = None
    t0, frames = time.time(), 0

    while True:
        ret, frame = cap.read()
        if not ret or frame is None or frame.size == 0:
            time.sleep(0.05)
            continue

        human_present, vis = detector.detect(frame)
        flag = 1 if human_present else 0

        # ── UDP send ──────────────────────────────────────────────────────
        if args.every_frame or flag != prev_flag:
            sock.sendto(bytes([flag]), (args.receiver, args.port))
            prev_flag = flag
            print("→ {}  ({})".format(flag, "HUMAN" if flag else "none "))

        # ── Display ───────────────────────────────────────────────────────
        frames += 1
        fps = frames / max(0.001, time.time() - t0)
        label = "{:.1f} fps  {}".format(fps, "HUMAN" if flag else "---")
        colour = (0, 255, 0) if flag else (0, 80, 80)
        cv2.putText(vis, label, (8, 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, colour, 2)
        cv2.imshow("human_detect", vis)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break

    cap.release()
    cv2.destroyAllWindows()
    sock.close()


if __name__ == "__main__":
    main()