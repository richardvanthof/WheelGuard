from flask import Flask, request, jsonify
import MonsterBorg
import time

app = Flask(__name__)

MB = MonsterBorg.MonsterBorg()
MB.Init()

last_command_time = time.time()

# Safety watchdog
def watchdog():
    global last_command_time

    while True:
        if time.time() - last_command_time > 60:
            MB.MotorsOff()

        time.sleep(0.1)

def get_power():
    data = request.get_json(silent=True) or {}

    power = float(data.get("power", 0.4))

    # Clamp power safely
    power = max(-1.0, min(1.0, power))

    return power

def touch_watchdog():
    global last_command_time
    last_command_time = time.time()

@app.route("/forward", methods=["POST"])
def forward():
    touch_watchdog()

    power = get_power()

    MB.SetMotor1(power)
    MB.SetMotor2(power)
    MB.SetMotor3(power)
    MB.SetMotor4(power)

    return jsonify({
        "status": "forward",
        "power": power
    })

@app.route("/backward", methods=["POST"])
def backward():
    touch_watchdog()

    power = get_power()

    MB.SetMotor1(-power)
    MB.SetMotor2(-power)
    MB.SetMotor3(-power)
    MB.SetMotor4(-power)

    return jsonify({
        "status": "backward",
        "power": power
    })

@app.route("/left", methods=["POST"])
def left():
    touch_watchdog()

    power = get_power()

    MB.SetMotor1(-power)
    MB.SetMotor2(power)
    MB.SetMotor3(-power)
    MB.SetMotor4(power)

    return jsonify({
        "status": "left",
        "power": power
    })

@app.route("/right", methods=["POST"])
def right():
    touch_watchdog()

    power = get_power()

    MB.SetMotor1(power)
    MB.SetMotor2(-power)
    MB.SetMotor3(power)
    MB.SetMotor4(-power)

    return jsonify({
        "status": "right",
        "power": power
    })

@app.route("/stop", methods=["POST"])
def stop():
    touch_watchdog()

    MB.MotorsOff()

    return jsonify({
        "status": "stopped"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8443)