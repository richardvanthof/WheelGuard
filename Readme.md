# WheelGuard
Robot that deters people from touching someone elses wheelchair.

## Development requirements
- VS Code with Remote Development Extension
- Docker
- [Gazebo Harmonic](https://gazebosim.org/docs/harmonic/install/)

## Development setup guide
1. Open Docker and VS code. In VS Code command palette (cmd/ctrl + p) run `Dev Containers: Rebuild and open in Container.`
2. Run the simulator using the command `gz sim /src/simulator/building_robot.sdf`
[Rest TBD]

<!-- ## ROS tutorials
https://www.youtube.com/watch?v=HJAE5Pk8Nyw -->

## Robot

Service autostarted based on listener.py

After updating listener.py on the robot, must be rebooted with sudo systemctl restart monsterborg.service
Watch logs with journalctl -u monsterborg.service -f

Connect with the wifi first
SSID= WheelGuard, password is wheelguard
ssh to pi@192.168.4.1 to interact with robot internally

Webpage autostart after minute of booting is: http://192.168.4.1:8443

