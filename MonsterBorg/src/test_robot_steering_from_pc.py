from wheelguard_api import MonsterBorgClient

import time

robot = MonsterBorgClient(
    host="192.168.137.215",
    api_key="supersecret"
)

print("Forward")
robot.forward(
    0.5,
    0.5,
    1.0
)

time.sleep(1)

print("Backward")
robot.backward(
    0.5,
    0.5,
    1.0
)

time.sleep(1)

print("Left")
robot.left(
    0.5,
    0.5,
    1.0
)

time.sleep(1)

print("Right")
robot.right(
    0.5,
    0.5,
    1.0
)

time.sleep(1)

print("Curve")
robot.drive_for(
    0.2,
    0.7,
    2.0
)

print("Done")