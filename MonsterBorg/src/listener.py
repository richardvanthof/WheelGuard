from flask import Flask, request, jsonify
from waitress import serve

import MonsterBorg
import threading
import time
import os

from functools import wraps

# =========================================================
# Configuration
# =========================================================

HOST = "0.0.0.0"
PORT = 8443

# Set this in your shell:
# export ROBOT_API_KEY="supersecret"
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
# MonsterBorg Init
# =========================================================

MB = MonsterBorg.MonsterBorg()
MB.Init()

# Ensure motors start OFF
MB.MotorsOff()

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
        MB.MotorsOff()
    except Exception as e:
        print(f"[ERROR] Failed emergency stop: {e}")

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

            # Fail-safe behavior
            emergency_stop()

            return jsonify({
                "error": "unauthorized"
            }), 401

        return f(*args, **kwargs)

    return decorated

# =========================================================
# Watchdog Thread
# =========================================================

def watchdog():

    print("[INFO] Watchdog thread started")

    while True:

        elapsed = time.time() - last_command_time

        if elapsed > WATCHDOG_TIMEOUT:

            print("[WARNING] Watchdog timeout reached")

            emergency_stop()

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

    touch_watchdog()

    try:

        data = request.get_json()

        if data is None:
            raise ValueError("Missing JSON body")

        left = float(data.get("left", 0))
        right = float(data.get("right", 0))

        # Clamp values safely
        left = clamp(left, MIN_POWER, MAX_POWER)
        right = clamp(right, MIN_POWER, MAX_POWER)

    except Exception as e:

        print(f"[ERROR] Invalid request: {e}")

        emergency_stop()

        return jsonify({
            "error": str(e)
        }), 400

    try:

        # =================================================
        # Differential drive mapping
        # =================================================

        # Left side motors
        MB.SetMotor1(left)
        MB.SetMotor3(left)

        # Right side motors
        MB.SetMotor2(right)
        MB.SetMotor4(right)

    except Exception as e:

        print(f"[ERROR] Motor control failure: {e}")

        emergency_stop()

        return jsonify({
            "error": f"Motor failure: {str(e)}"
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

    print("[INFO] Starting MonsterBorg robot server")

    # Start watchdog
    threading.Thread(
        target=watchdog,
        daemon=True
    ).start()

    print(f"[INFO] Server listening on {HOST}:{PORT}")

    serve(
        app,
        host=HOST,
        port=PORT
    )