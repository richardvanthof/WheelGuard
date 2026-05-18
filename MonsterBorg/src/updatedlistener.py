import sys
sys.path.append("/home/pi/monsterborg")

from flask import Flask, request, jsonify, send_file, Response
from waitress import serve

from tborg import ThunderBorg

import threading
import time
import os
import subprocess
import cv2

from functools import wraps

# =========================================================
# Configuration
# =========================================================

CURRENT_MODE = 1
DEFAULT_POWER = 0.5

HOST = "0.0.0.0"
PORT = 8443

API_KEY = os.getenv("ROBOT_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "ROBOT_API_KEY environment variable not set"
    )

WATCHDOG_TIMEOUT = 1.0
WATCHDOG_SLEEP = 0.1

MAX_POWER = 1.0
MIN_POWER = -1.0

# =========================================================
# Flask App
# =========================================================

app = Flask(__name__)

# =========================================================
# ThunderBorg Init
# =========================================================

TB = ThunderBorg()

if not TB.find_board():
    raise RuntimeError("ThunderBorg not detected")

TB.halt_motors()

# =========================================================
# Camera Init
# =========================================================

camera = cv2.VideoCapture(0)

camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
camera.set(cv2.CAP_PROP_FPS, 15)

if not camera.isOpened():
    print("[WARNING] Camera failed to open")
else:
    print("[INFO] Camera initialized")


# =========================================================
# Global State
# =========================================================

last_command_time = time.time()

# =========================================================
# Helpers
# =========================================================

def play_sound(filename):

    try:

        subprocess.Popen(
            ["aplay", filename],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    except Exception as e:

        print("[ERROR] Failed to play sound: {}".format(e))

def set_option(option_id):

    global CURRENT_MODE

    CURRENT_MODE = option_id

    print("[INFO] Option selected: {}".format(option_id))

def clamp(value, minimum=-1.0, maximum=1.0):
    return max(minimum, min(maximum, value))

def touch_watchdog():
    global last_command_time
    last_command_time = time.time()

def emergency_stop():

    try:
        TB.halt_motors()

    except Exception as e:
        print("[ERROR] Emergency stop failed: {}".format(e))

def authorize(req):

    key = req.headers.get("X-API-Key")

    return key == API_KEY

# =========================================================
# Authentication Decorator
# =========================================================

def require_api_key(f):

    @wraps(f)
    def decorated(*args, **kwargs):

        if not authorize(request):

            print("[WARNING] Unauthorized request")

            emergency_stop()

            return jsonify({
                "error": "unauthorized"
            }), 401

        return f(*args, **kwargs)

    return decorated

# =========================================================
# Watchdog
# =========================================================

def watchdog():

    print("[INFO] Watchdog thread started")

    stopped = False

    while True:

        elapsed = time.time() - last_command_time

        if elapsed > WATCHDOG_TIMEOUT:

            if not stopped:
                print("[WARNING] Watchdog timeout reached")
                emergency_stop()
                stopped = True

        else:
            stopped = False

        time.sleep(WATCHDOG_SLEEP)

def generate_frames():

    while True:

        success, frame = camera.read()

        if not success:
            continue

        _, buffer = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 60]
        )

        frame_bytes = buffer.tobytes()

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' +
            frame_bytes +
            b'\r\n'
        )

# =========================================================
# Routes
# =========================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "online"
    })

@app.route("/stop", methods=["POST"])
@require_api_key
def stop():

    touch_watchdog()

    emergency_stop()

    print("[INFO] Robot stopped")

    return jsonify({
        "status": "stopped"
    })

@app.route("/bark", methods=["POST"])
@require_api_key
def bark():

    print("[INFO] Bark requested")

    play_sound("/home/pi/MonsterBorg/src/fixed_dog.wav")

    return jsonify({
        "status": "bark"
    })

@app.route("/drive", methods=["POST"])
@require_api_key
def drive():

    print("[INFO] /drive request received")

    touch_watchdog()

    try:

        data = request.get_json()

        print("[INFO] JSON:", data)

        if data is None:
            raise ValueError("Missing JSON body")

        left = float(data.get("left", 0))
        right = float(data.get("right", 0))

        left = clamp(left, MIN_POWER, MAX_POWER)
        right = clamp(right, MIN_POWER, MAX_POWER)

        print("[INFO] Left:", left)
        print("[INFO] Right:", right)

    except Exception as e:

        print("[ERROR] Invalid request: {}".format(e))

        emergency_stop()

        return jsonify({
            "error": str(e)
        }), 400

    try:

        print("[INFO] Setting motors")

        TB.set_motor_one(left)
        TB.set_motor_two(right)

        print("[INFO] Motors updated")

    except Exception as e:

        print("[ERROR] Motor control failure: {}".format(e))

        emergency_stop()

        return jsonify({
            "error": "Motor failure: {}".format(str(e))
        }), 500

    return jsonify({
        "status": "driving",
        "left": left,
        "right": right
    })

@app.route("/video_feed")
def video_feed():

    return Response(

        generate_frames(),

        mimetype=
        "multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/")
def index():

    return send_file("teleop.html")

# =========================================================
# Main
# =========================================================

if __name__ == "__main__":

    print("[INFO] Starting ThunderBorg robot server")

    watchdog_thread = threading.Thread(
        target=watchdog
    )

    watchdog_thread.daemon = True
    watchdog_thread.start()

    print("[INFO] Listening on {}:{}".format(HOST, PORT))

    serve(
        app,
        host=HOST,
        port=PORT
    )