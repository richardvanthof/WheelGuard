#!/usr/bin/env python3

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import time
from dataclasses import dataclass
from collections import deque
from typing import Optional, Tuple, List
from wheelguard_api import MonsterBorgClient
import socket
import threading
import json

import cv2
import numpy as np

# Toggle camera initialization
ENABLE_CAMERA = False
MIN_DRIVE_POWER = 0.7
MAX_DRIVE_POWER = 1.0

# Barking
bark = False
last_bark_time = 0
first_bark_time = 0

API_KEY = "supersecret"

class BarkHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global bark, last_bark_time, first_bark_time

        if self.path != "/bark":
            self.send_response(404)
            self.end_headers()
            return

        if self.headers.get("X-API-Key") != API_KEY:
            self.send_response(403)
            self.end_headers()
            return

        bark = True
        last_bark_time = time.time()
        if first_bark_time == 0:
            first_bark_time = last_bark_time

        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress default logging


def start_bark_server():
    server = HTTPServer(("0.0.0.0", 8221), BarkHandler)
    print("[BARK] Listening on :8221")
    server.serve_forever()

robot = MonsterBorgClient(
    host="192.168.4.1",
    api_key="supersecret"
)

@dataclass
class Detection:
    """Store one vision update and the debug images derived from it."""

    debug: np.ndarray
    mask: np.ndarray
    detected: bool
    error_x: float
    error_y: float
    area_ratio: float
    confidence: float
    status: str
    bbox: Optional[Tuple[int, int, int, int]] = None


def fill_holes(binary_mask: np.ndarray) -> np.ndarray:
    """Fill enclosed black holes inside a binary foreground mask."""
    h, w = binary_mask.shape[:2]
    flood = binary_mask.copy()
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, flood_mask, (0, 0), 255)
    flood_inv = cv2.bitwise_not(flood)
    return cv2.bitwise_or(binary_mask, flood_inv)


def draw_lines(img, lines, x=10, y=25, color=(0, 255, 255)):
    """Draw a vertical stack of status text lines onto an image."""
    for line in lines:
        cv2.putText(img, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        y += 22


def safe_clip_bbox(x, y, w, h, W, H):
    """Clip a bounding box so it stays valid inside the image frame."""
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    return x, y, w, h


def find_laptop_camera(max_index=10):
    """Find the first available camera"""
    # try different camera indices
    for i in range(10):  # check up to 10 possible camera devices
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                print(f"Found camera at index {i}")
                cap.release()
                return i
        cap.release()
    
    # if no camera found by index, try using -1 or other defaults
    for i in [-1, 0, 1]:  # common fallback values
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                print(f"Found camera at index {i}")
                cap.release()
                return i
        cap.release()
    
    return None

def read_frame(camera):
    ret, frame = camera.read()
    if not ret:
        return None
    return frame


class Challenge2Vision:
    """Detect, lock, and track a moving target using motion and color cues.

    The class works as a small state machine:
    SCAN learns the static background, LOCK finds a stable moving object,
    and FOLLOW tracks the locked object by its learned HSV color.
    """

    def __init__(
        self,
        scan_duration=8.0,
        min_area=250,
        min_area_ratio=0.004,
        max_area_ratio=0.35,
        required_lock_count=5,
        lock_center_dist_thresh=35.0,
        hue_margin=18,
        sat_margin=65,
        val_margin=75,
        min_saturation=50,
        min_value=50,
        smooth_window=10,
        lost_tolerance_frames=5,
        is_car_camera=True,
    ):
        """Initialize thresholds, state-machine values, and smoothing buffers.

        Parameters tune three parts of the pipeline: motion/background
        detection, stable target locking, and smoothed target measurements.
        """
        # State-machine setup. The robot should remain still during SCAN
        self.status = "FOLLOW"
        self.scan_duration = scan_duration
        self.scan_start = time.perf_counter()

        # Background model used later to detect newly moving objects
        self.background_acc = None
        self.background_gray = None

        # Basic geometric filters for rejecting noise and huge false positives
        self.min_area = min_area
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.max_bbox_width_ratio = 0.85
        self.max_bbox_height_ratio = 0.85

        # Locking requires the candidate center to stay stable for several frames
        self.required_lock_count = required_lock_count
        self.lock_center_dist_thresh = lock_center_dist_thresh
        self.lock_candidate = None
        self.lock_count = 0

        # HSV margins are applied around the learned dominant target color
        self.hue_margin = hue_margin
        self.sat_margin = sat_margin
        self.val_margin = val_margin
        self.min_saturation = min_saturation
        self.min_value = min_value

        # Car camera frames tend to vibrate more, so they use stricter motion detection
        self.motion_threshold = 52 if is_car_camera else 35
        self.bg_alpha = 0.008 if is_car_camera else 0.03

        # Learned target color and its corresponding lower/upper HSV bounds
        self.target_hsv = None
        self.lower = None
        self.upper = None

        # Last accepted target box, used to choose candidates and coast over misses
        self.last_bbox = None
        self.lock_area_ratio = 0.0

        # Loss handling prevents one bad frame from immediately declaring LOST
        self.lost_frames = 0
        self.lost_tolerance_frames = lost_tolerance_frames

        # Smoothed output values reduce unstable control commands
        self.smooth_error_x = 0.0
        self.alpha_x = 0.3
        self.area_history = deque(maxlen=smooth_window)
        self.error_x_history = deque(maxlen=smooth_window)
        self.error_y_history = deque(maxlen=smooth_window)

        # ArUco setup
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(
            cv2.aruco.DICT_4X4_50
        )

        self.aruco_detector = cv2.aruco.ArucoDetector(
            self.aruco_dict
        )

        # Marker ID to follow
        self.target_id = 0

    def process(self, frame):
        return self._follow_aruco(frame)

    def _gray(self, frame):
        """Convert a BGR frame to blurred grayscale for stable motion matching.

        Blurring suppresses small image noise before background subtraction.
        """
        return cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)

    def _scan(self, frame):
        """Build the static background model while the robot is stopped.

        During this state no target is reported. The function only updates the
        running background average and draws countdown/debug information.
        """
        debug = frame.copy()
        gray = self._gray(frame)

        elapsed = time.perf_counter() - self.scan_start

        # Update the running background image during the scan window
        if self.background_acc is None:
            self.background_acc = gray.astype("float")
        else:
            cv2.accumulateWeighted(gray, self.background_acc, self.bg_alpha)

        remaining = max(0, int(self.scan_duration - elapsed))
        draw_lines(
            debug,
            [
                "STATUS: SCAN",
                "Robot must stay STOPPED",
                f"Remaining: {remaining}s",
            ],
        )

        # Freeze the learned background and advance to target locking
        if elapsed >= self.scan_duration:
            self.background_gray = cv2.convertScaleAbs(self.background_acc)
            self.status = "LOCK"
            print("[VISION] Background ready. Now place/move the target object.")

        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        return Detection(debug, mask, False, 0.0, 0.0, 0.0, 0.0, "SCAN")

    def _motion_mask(self, frame):
        """Create a cleaned mask of pixels that differ from the background.

        The mask is used only during LOCK, when the user places or moves the
        unknown target after the background has already been learned.
        """
        if self.background_gray is None:
            return np.zeros(frame.shape[:2], dtype=np.uint8)

        gray = self._gray(frame)
        diff = cv2.absdiff(self.background_gray, gray)

        _, mask = cv2.threshold(diff, self.motion_threshold, 255, cv2.THRESH_BINARY)

        # Opening removes tiny speckles; closing and dilation merge object parts
        kernel_open = np.ones((3, 3), np.uint8)
        kernel_close = np.ones((7, 7), np.uint8)

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
        mask = cv2.dilate(mask, kernel_close, iterations=1)

        return mask

    def _bbox_candidates_from_mask(self, frame, mask, max_area_ratio=None):
        """Extract plausible target bounding boxes from a binary mask.

        Each connected component is filtered by pixel area, relative size,
        border position, aspect ratio, and bounding-box area.
        """
        H, W = frame.shape[:2]
        max_area_ratio = self.max_area_ratio if max_area_ratio is None else max_area_ratio

        candidates = []

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

        for label in range(1, num_labels):
            # Label 0 is the background; labels from 1 onward are foreground blobs
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            w = int(stats[label, cv2.CC_STAT_WIDTH])
            h = int(stats[label, cv2.CC_STAT_HEIGHT])
            pixel_area = float(stats[label, cv2.CC_STAT_AREA])

            area_ratio = pixel_area / float(W * H)

            # Reject blobs that are too small, too large, or likely caused by edges
            if pixel_area < self.min_area:
                continue
            if area_ratio < self.min_area_ratio:
                continue
            if area_ratio > max_area_ratio:
                continue
            if w > self.max_bbox_width_ratio * W:
                continue
            if h > self.max_bbox_height_ratio * H:
                continue

            cx = x + w / 2
            cy = y + h / 2

            # Ignore detections too close to the image border
            if cx < 0.05 * W or cx > 0.95 * W:
                continue
            if cy < 0.05 * H or cy > 0.95 * H:
                continue

            # Extremely thin blobs are usually shadows, arms, or background artifacts
            aspect = w / max(h, 1)
            if aspect > 4.5 or aspect < 1 / 4.5:
                continue

            # Use bounding-box area as an additional guard against wide masks
            bbox_area_ratio = (w * h) / float(W * H)
            if bbox_area_ratio > max_area_ratio:
                continue

            candidates.append((x, y, w, h, pixel_area))

        return candidates

    def _lock(self, frame):
        """Lock onto a stable moving object and learn its target color.

        The largest valid motion blob is accepted only after its center remains
        close to the previous candidate for several consecutive frames.
        """
        debug = frame.copy()
        H, W = frame.shape[:2]

        # Find moving regions after the background scan has completed
        mask = self._motion_mask(frame)
        candidates = self._bbox_candidates_from_mask(frame, mask)

        draw_lines(
            debug,
            [
                "STATUS: LOCK",
                "Move/place unknown target",
                "Robot must stay STOPPED",
            ],
        )

        if not candidates:
            # No stable motion candidate in this frame, so restart the lock counter
            self.lock_candidate = None
            self.lock_count = 0
            return Detection(debug, mask, False, 0.0, 0.0, 0.0, 0.0, "LOCK")

        # Use the largest valid moving region as the current lock candidate
        x, y, w, h, area = max(candidates, key=lambda item: item[4])

        cx = x + w // 2
        cy = y + h // 2

        cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 255), 2)
        cv2.circle(debug, (cx, cy), 5, (0, 0, 255), -1)

        # Require several consistent frames before accepting the target
        if self.lock_candidate is None:
            self.lock_candidate = (cx, cy, x, y, w, h, area)
            self.lock_count = 1
        else:
            prev_cx, prev_cy, *_ = self.lock_candidate
            dist = np.hypot(cx - prev_cx, cy - prev_cy)

            # Nearby centers indicate the same object; a jump starts a new lock
            if dist < self.lock_center_dist_thresh:
                self.lock_count += 1
            else:
                self.lock_count = 1

            self.lock_candidate = (cx, cy, x, y, w, h, area)

        cv2.putText(
            debug,
            f"candidate {self.lock_count}/{self.required_lock_count}",
            (x, max(45, y - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2,
        )

        if self.lock_count < self.required_lock_count:
            return Detection(debug, mask, False, 0.0, 0.0, 0.0, 0.0, "LOCK")

        # Learn HSV bounds from the locked region and switch to color tracking
        roi = frame[y:y + h, x:x + w]
        roi_mask = mask[y:y + h, x:x + w]

        if roi.size == 0:
            # Defensive guard in case the candidate box became invalid
            self.lock_candidate = None
            self.lock_count = 0
            return Detection(debug, mask, False, 0.0, 0.0, 0.0, 0.0, "LOCK")

        self._learn_target_color(roi, roi_mask)

        self.last_bbox = (x, y, w, h)
        self.lock_area_ratio = (w * h) / float(W * H)

        # Clear old smoothing state so FOLLOW starts from the newly locked box
        self.area_history.clear()
        self.error_x_history.clear()
        self.error_y_history.clear()

        self.lost_frames = 0
        self.status = "FOLLOW"

        print(f"[VISION] Target locked. HSV={self.target_hsv}, lock_area={self.lock_area_ratio:.4f}")

        return self._output_from_bbox(
            debug,
            mask,
            frame.shape,
            x,
            y,
            w,
            h,
            confidence=1.0,
            status="FOLLOW",
        )

    def _learn_target_color(self, roi, roi_mask):
        """Estimate the dominant HSV color from the locked target region.

        The motion mask selects target pixels inside the ROI. If too few masked
        pixels exist, the whole ROI is used as a fallback.
        """
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        mask = cv2.threshold(roi_mask, 1, 255, cv2.THRESH_BINARY)[1]

        # If the motion mask is unreliable, learn from the full locked box
        if cv2.countNonZero(mask) < 30:
            mask = np.full(roi.shape[:2], 255, dtype=np.uint8)

        pixels = hsv[mask > 0]
        # Prefer colorful and bright pixels because gray/dark pixels are unstable in hue
        color_pixels = pixels[
            (pixels[:, 1] > self.min_saturation)
            & (pixels[:, 2] > self.min_value)
        ]

        # Fall back to all selected pixels if the target is not very saturated
        if len(color_pixels) == 0:
            color_pixels = pixels

        # Find the dominant hue bin first to avoid averaging different colors together
        hue_hist = cv2.calcHist([color_pixels[:, 0]], [0], None, [18], [0, 180]).ravel()
        hue_bin = int(np.argmax(hue_hist))
        hue_center = hue_bin * 10 + 5

        # Keep pixels near the dominant hue before taking the median HSV value
        hue_dist = np.abs(((color_pixels[:, 0].astype(int) - hue_center + 90) % 180) - 90)
        dominant_pixels = color_pixels[hue_dist <= 10]

        if len(dominant_pixels) == 0:
            dominant_pixels = color_pixels

        # Median is robust against small highlights, shadows, and mixed background pixels
        h, s, v = np.median(dominant_pixels, axis=0)

        self.target_hsv = (int(h), int(s), int(v))
        self.lower, self.upper = self._color_range(self.target_hsv)

    def _color_range(self, hsv_color):
        """Build lower and upper HSV thresholds around a learned color.

        Hue wraps around at 180 in OpenCV, while saturation and value are
        clamped to valid 0-255 ranges and minimum quality thresholds.
        """
        h, s, v = hsv_color

        lower = np.array(
            [
                (h - self.hue_margin) % 180,
                max(self.min_saturation, s - self.sat_margin),
                max(self.min_value, v - self.val_margin),
            ],
            dtype=np.uint8,
        )

        upper = np.array(
            [
                (h + self.hue_margin) % 180,
                min(255, s + self.sat_margin),
                min(255, v + self.val_margin),
            ],
            dtype=np.uint8,
        )

        return lower, upper

    def _target_color_mask(self, frame):
        """Segment the current frame using the learned target HSV range.

        This is the main detection source during FOLLOW. It returns a binary
        mask where white pixels are likely to belong to the locked target.
        """
        if self.target_hsv is None or self.lower is None or self.upper is None:
            return np.zeros(frame.shape[:2], dtype=np.uint8)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower, upper = self.lower, self.upper

        # Hue is circular in OpenCV HSV, so ranges crossing 0 need two masks
        if lower[0] <= upper[0]:
            mask = cv2.inRange(hsv, lower, upper)
        else:
            low_a = np.array([0, lower[1], lower[2]], dtype=np.uint8)
            high_a = np.array([upper[0], upper[1], upper[2]], dtype=np.uint8)
            low_b = np.array([lower[0], lower[1], lower[2]], dtype=np.uint8)
            high_b = np.array([179, upper[1], upper[2]], dtype=np.uint8)

            mask = cv2.bitwise_or(
                cv2.inRange(hsv, low_a, high_a),
                cv2.inRange(hsv, low_b, high_b),
            )

        # Reject low-saturation or too-dark pixels even if their hue matches
        sv_gate = cv2.inRange(
            hsv,
            np.array([0, self.min_saturation, self.min_value], dtype=np.uint8),
            np.array([179, 255, 255], dtype=np.uint8),
        )

        mask = cv2.bitwise_and(mask, sv_gate)

        # Remove isolated noise, merge nearby target pixels, and fill gaps
        kernel_open = np.ones((3, 3), np.uint8)
        kernel_close = np.ones((7, 7), np.uint8)

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=2)
        mask = cv2.dilate(mask, kernel_open, iterations=1)
        mask = fill_holes(mask)

        return mask

    def _follow_aruco(self, frame):
        debug = frame.copy()
        H, W = frame.shape[:2]

        corners, ids, rejected = self.aruco_detector.detectMarkers(frame)

        print(
            "ids:",
            None if ids is None else ids.flatten(),
            "rejected:",
            len(rejected)
        )

        if ids is None:
            self.lost_frames += 1

            return self._lost_output(
                debug,
                np.zeros((H, W), dtype=np.uint8)
            )

        target = None

        for marker_corners, marker_id in zip(
            corners,
            ids.flatten()
        ):
            if marker_id != self.target_id:
                continue

            target = marker_corners[0]
            break

        if target is None:
            self.lost_frames += 1

            return self._lost_output(
                debug,
                np.zeros((H, W), dtype=np.uint8)
            )

        pts = target.astype(np.int32)

        cv2.polylines(
            debug,
            [pts],
            True,
            (0, 255, 0),
            2
        )

        cx = int(np.mean(pts[:, 0]))
        cy = int(np.mean(pts[:, 1]))

        x, y, w, h = cv2.boundingRect(pts)

        cv2.circle(debug, (cx, cy), 5, (0, 0, 255), -1)

        self.lost_frames = 0

        return self._output_from_bbox(
            debug,
            np.zeros((H, W), dtype=np.uint8),
            frame.shape,
            x,
            y,
            w,
            h,
            confidence=1.0,
            status=f"ARUCO {self.target_id}",
        )

    def _follow(self, frame):
        """Track the locked target using its learned color mask.

        If the target disappears briefly, the function coasts using the last
        known box for a few frames before reporting LOST.
        """
        debug = frame.copy()
        mask = self._target_color_mask(frame)

        H, W = frame.shape[:2]

        # Convert color blobs into candidate boxes and choose the best match
        candidates = self._bbox_candidates_from_mask(frame, mask, max_area_ratio=0.85)
        best = self._choose_follow_candidate(candidates, W, H)

        if best is None:
            self.lost_frames += 1

            # Briefly reuse the last known box to avoid flickering on missed frames
            if self.last_bbox is not None and self.lost_frames <= self.lost_tolerance_frames:
                x, y, w, h = self.last_bbox

                cv2.putText(
                    debug,
                    f"FOLLOW coast {self.lost_frames}/{self.lost_tolerance_frames}",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                )

                return self._output_from_bbox(
                    debug,
                    mask,
                    frame.shape,
                    x,
                    y,
                    w,
                    h,
                    confidence=0.25,
                    status="FOLLOW_COAST",
                )

            return self._lost_output(debug, mask)

        x, y, w, h, area = best

        # Refresh tracking memory once a valid candidate is found
        self.last_bbox = (x, y, w, h)
        self.lost_frames = 0

        return self._output_from_bbox(
            debug,
            mask,
            frame.shape,
            x,
            y,
            w,
            h,
            confidence=0.8,
            status="FOLLOW",
        )

    def _choose_follow_candidate(self, candidates, W, H):
        """Choose the candidate closest to the previous target location and size.

        The score prefers boxes near the previous center and with similar area,
        which helps reject other objects with the same color.
        """
        if not candidates:
            return None

        if self.last_bbox is None:
            # Without history, the largest color blob is the best initial guess
            return max(candidates, key=lambda item: item[4])

        lx, ly, lw, lh = self.last_bbox
        last_cx = lx + lw / 2
        last_cy = ly + lh / 2
        last_area_ratio = (lw * lh) / float(W * H)

        best = None
        best_score = float("inf")

        for x, y, w, h, area in candidates:
            cx = x + w / 2
            cy = y + h / 2

            # Normalize distance by image size so the score is resolution-independent
            area_ratio = (w * h) / float(W * H)
            dist_score = min(1.0, np.hypot(cx - last_cx, cy - last_cy) / max(W, H))

            area_scale = area_ratio / max(last_area_ratio, 1e-6)

            # Large area jumps usually indicate a wrong blob or partial occlusion
            if area_scale < 0.25 or area_scale > 4.0:
                continue

            # Log area ratio treats 2x larger and 2x smaller as equally different
            area_score = abs(np.log(max(area_scale, 1e-6)))
            score = 0.75 * dist_score + 0.25 * area_score

            if score < best_score:
                best_score = score
                best = (x, y, w, h, area)

        return best

    def _output_from_bbox(self, debug, mask, frame_shape, x, y, w, h, confidence, status):
        """Convert a target box into normalized control errors and debug output.

        error_x and error_y are normalized to roughly [-1, 1], and area_ratio
        estimates target distance for the controller.
        """
        H, W = frame_shape[:2]
        x, y, w, h = safe_clip_bbox(x, y, w, h, W, H)

        # Convert pixel center position into normalized image-center errors
        cx = x + w // 2
        cy = y + h // 2

        error_x = (cx - W / 2) / (W / 2)
        error_y = (cy - H / 2) / (H / 2)

        area_ratio = (w * h) / float(W * H)
        
        # Smooth control signals to reduce jitter in the robot response
        self.smooth_error_x = (
            self.alpha_x * error_x +
            (1 - self.alpha_x) * self.smooth_error_x
        )
        self.error_y_history.append(error_y)
        self.area_history.append(area_ratio)

        # smooth_error_x = sum(self.error_x_history) / len(self.error_x_history)
        # X uses exponential smoothing for responsive turning; Y and area use windows
        smooth_error_x = self.smooth_error_x
        smooth_error_y = sum(self.error_y_history) / len(self.error_y_history)
        smooth_area = sum(self.area_history) / len(self.area_history)

        # Draw the accepted box, target center, and image center for display
        cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.circle(debug, (cx, cy), 5, (0, 0, 255), -1)
        cv2.circle(debug, (W // 2, H // 2), 4, (255, 255, 0), -1)

        draw_lines(
            debug,
            [
                f"STATUS: {status}",
                f"Detected: True Conf: {confidence:.2f}",
                f"Center: ({cx}, {cy})",
                f"Error_x: {smooth_error_x:.2f}",
                f"Area_ratio: {area_ratio:.4f}",
                f"Smooth_area: {smooth_area:.4f}",
                f"Lock_area: {self.lock_area_ratio:.4f}",
                f"HSV: {self.target_hsv}",
            ],
            color=(0, 255, 0),
        )

        return Detection(
            debug=debug,
            mask=mask,
            detected=True,
            error_x=smooth_error_x,
            error_y=smooth_error_y,
            area_ratio=smooth_area,
            confidence=confidence,
            status=status,
            bbox=(x, y, w, h),
        )

    def _lost_output(self, debug, mask):
        """Return a no-target detection result and clear tracking smoothers.

        Clearing the histories prevents stale target measurements from
        influencing the controller after the object has been lost.
        """
        self.error_x_history.clear()
        self.error_y_history.clear()
        self.area_history.clear()

        draw_lines(
            debug,
            [
                f"STATUS: LOST {self.lost_frames}",
                "Detected: False",
            ],
            color=(0, 0, 255),
        )

        return Detection(debug, mask, False, 0.0, 0.0, 0.0, 0.0, "LOST")


class RobotController:
    """Translate vision detections into PiCar-4WD movement commands."""

    def __init__(
        self,
        control_enabled,
        target_area_ratio=0.05,
        area_tolerance=0.02,
        area_move_count=3,
        required_area_count=5,
        center_tolerance=0.25,
        max_speed=22,
        min_speed=3,
        k_linear=450.0,
        turn_power=7,
        search_power=7,
        search_turn_duration=0.25,
        search_wait_duration=0.65,
    ):
        """Initialize control gains, movement limits, and search behavior."""
        self.control_enabled = control_enabled

        self.fc = None

        self.target_area_ratio = target_area_ratio
        self.area_tolerance = area_tolerance
        self.center_tolerance = center_tolerance

        self.area_move_count = area_move_count
        self.required_area_count = required_area_count

        self.max_speed = max_speed
        self.min_speed = min_speed
        self.k_linear = k_linear

        self.turn_power = turn_power
        self.search_power = search_power

        self.search_turn_duration = search_turn_duration
        self.search_wait_duration = search_wait_duration

        self.search_phase = "TURN"
        self.search_phase_start = time.perf_counter()

        self.last_seen_left = True
        self.last_seen_x = 0.0
        self.last_seen_y = 0.0

    def stop(self):
        robot.stop()

    def _turn_left(self, power=None):
        p = power if power is not None else self.turn_power

        speed = min(1.0, p / 10.0)

        robot.drive(
            -speed,
            speed
        )

    def _turn_right(self, power=None):
        p = power if power is not None else self.turn_power

        speed = min(1.0, p / 10.0)

        robot.drive(
            speed,
            -speed
        )

    def _forward(self, power):

        speed = power / self.max_speed

        speed = (
            MIN_DRIVE_POWER +
            speed * (MAX_DRIVE_POWER - MIN_DRIVE_POWER)
        )

        speed = min(MAX_DRIVE_POWER, speed)

        robot.drive(speed, speed)

    def _backward(self, power):

        speed = power / self.max_speed

        speed = (
            MIN_DRIVE_POWER +
            speed * (MAX_DRIVE_POWER - MIN_DRIVE_POWER)
        )

        speed = min(MAX_DRIVE_POWER, speed)

        robot.drive(-speed, -speed)

    def update(self, det):
        """Update the robot command from the latest vision detection."""
        # Keep the robot stationary while the target model is being prepared
        if det.status in ("SCAN", "LOCK"):
            self.stop()
            return

        if det.detected:
            # Save the latest target direction for later search recovery
            self.last_seen_x = det.error_x
            self.last_seen_y = det.error_y
            self.last_seen_left = det.error_x < 0

            self.search_phase = "TURN"
            self.search_phase_start = time.perf_counter()

            self._follow(det)
            return

        self._search_step()

    def _follow(self, det):
        """Center the target first, then adjust distance from target area."""
        # Turn in place until the target is close enough to the image center
        if det.error_x < -self.center_tolerance:
            self._turn_left(self.turn_power)
            return

        if det.error_x > self.center_tolerance:
            self._turn_right(self.turn_power)
            return

        # Use apparent target size as a distance estimate
        area_error = self.target_area_ratio - det.area_ratio
        print(
            f"[CONTROL] target={self.target_area_ratio:.4f}, "
            f"smooth_area={det.area_ratio:.4f}, "
            f"area_error={area_error:.4f}"
        )

        if abs(area_error) <= self.area_tolerance:
            self.area_move_count = 0
            self.stop()
            return

        # Require repeated distance errors before moving to suppress jitter
        self.area_move_count += 1

        if self.area_move_count < self.required_area_count:
            self.stop()
            return

        raw_speed = abs(self.k_linear * area_error)
        speed = int(max(self.min_speed, min(self.max_speed, raw_speed)))

        if area_error > 0:
            print("[CONTROL] too far -> forward")
            self._forward(speed)
        else:
            print("[CONTROL] too close -> backward")
            self._backward(speed)

    def _search_step(self):
        """Run a turn-and-wait search pattern after the target is lost."""
        now = time.perf_counter()

        if self.search_phase == "TURN":
            if self.last_seen_left:
                self._turn_left(self.search_power)
            else:
                self._turn_right(self.search_power)

            if now - self.search_phase_start >= self.search_turn_duration:
                self.stop()
                self.search_phase = "WAIT"
                self.search_phase_start = now

            return

        self.stop()

        if now - self.search_phase_start >= self.search_wait_duration:
            self.search_phase = "TURN"
            self.search_phase_start = now


def is_barking():
    global bark, first_bark_time
    are_we_barking = time.time() - first_bark_time < 1.0
    bark = are_we_barking
    if bark == False:
        first_bark_time = 0
    return are_we_barking

def main():
    threading.Thread(
        target=start_bark_server,
        daemon=True
    ).start()
    """Parse options, start camera/control modules, and run the vision loop."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", action="store_true")
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--scan", type=float, default=12.0)
    parser.add_argument("--target-area", type=float, default=0.045)

    args = parser.parse_args()

    idx = find_laptop_camera()
    # Open the selected camera source
    camera = cv2.VideoCapture(idx, cv2.CAP_V4L2) #For Linux
    #camera = cv2.VideoCapture(0, cv2.CAP_DSHOW) # For Windows

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    #camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
    #camera.set(cv2.CAP_PROP_EXPOSURE, -6)

    #camera.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    #camera.set(cv2.CAP_PROP_FOCUS, 30)

    if not camera.isOpened():
        raise RuntimeError("Failed to open camera")

    # Build the vision state machine and movement controller
    vision = Challenge2Vision(
        scan_duration=args.scan,
        is_car_camera=True,
    )

    controller = RobotController(
        control_enabled=args.control,
        target_area_ratio=args.target_area,
        center_tolerance=0.30,
        area_tolerance=0.05,
        turn_power=7,
        search_power=7,
        min_speed=5,
        max_speed=20,
        k_linear=600,
    )

    print("[MAIN] Challenge 2 started.")
    print("[MAIN] Robot stays stopped during SCAN and LOCK.")
    print("[MAIN] Press q or ESC to quit if display is enabled.")

    try:
        while True:
            # Read, process, and apply one frame at a time
            frame = read_frame(camera)

            if frame is None:
                continue

            det = vision.process(frame)
            controller.update(det)

            if args.display:
                cv2.imshow("DEBUG", det.debug)
                # cv2.imshow("MASK", det.mask)

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
            if is_barking():
                print("[MAIN] Bark command received from sp32") #TODO: Implement barking logic by receiving YOLO state here

    except KeyboardInterrupt:
        print("\n[MAIN] Ctrl+C detected.")

    finally:
        # Always stop hardware and close camera/display resources
        controller.stop()


        camera.release()

        if args.display:
            cv2.destroyAllWindows()

        print("[MAIN] Program terminated.")


if __name__ == "__main__":
    main()