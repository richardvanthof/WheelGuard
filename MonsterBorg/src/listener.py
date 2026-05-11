import sys
sys.path.append("/home/pi/monsterborg")

from flask import Flask, request, jsonify
from waitress import serve

import ThunderBorg

import threading
import time
import os

from functools import wraps

# =========================================================
# Configuration
# =========================================================

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

TB = ThunderBorg.ThunderBorg()
TB.Init()

if not TB.foundChip:
    raise RuntimeError("ThunderBorg not detected")

TB.MotorsOff()

# =========================================================
# Global State
# =========================================================

last_command_time = time.time()

# =========================================================
# Helpers
# =========================================================

def clamp(value, minimum=-1.0, maximum=1.0):
    return max(minimum, min(maximum, value))

def touch_watchdog():
    global last_command_time
    last_command_time = time.time()

def emergency_stop():

    try:
        TB.MotorsOff()

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

        TB.SetMotor1(left)
        TB.SetMotor2(right)

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