# WheelGuard
Robot that deters people from touching someone elses wheelchair.

<!-- ## Development requirements
- VS Code with Remote Development Extension
- Docker
- [Gazebo Harmonic](https://gazebosim.org/docs/harmonic/install/) -->

# Monsterbord steering + AR tag detection
## Get started

1. Create and activate virtual environment
```
python3 -m venv venv
source venv/bin/activate
```
2. install dependencies using `pip install -r requirements.txt`
3. set environmental variables in your terminal
```sh
export ROBOT_HOST="your_host_here" # optional, otherwise 0.0.0.0
export ROBOT_API_KEY="your_api_key_here"
```
4. start listener by running `python3 MonsterBorg/src/listener.py`
5. start april tag location detector by running `python3 MonsterBorg/src/pos_detector.py`


## Robot

Service autostarted based on listener.py

After updating listener.py on the robot, must be rebooted with sudo systemctl restart monsterborg.service
Watch logs with journalctl -u monsterborg.service -f

Connect with the wifi first
SSID= WheelGuard, password is wheelguard
ssh to pi@192.168.4.1 to interact with robot internally

Webpage autostart after minute of booting is: http://192.168.4.1:8443

Order of operation: Turn the robot on, turn the speaker on, connect to the network
ssh into it
first do alsamixer and then up the volume 

Stopping the robot service: sudo systemctl stop monsterborg.service

# Other Pi

same commands but the service is called vision.service
journalctl -u vision.service -f

## Jetson
Then when plugged into the router:
sudo nmcli connection up "Router DHCP"
And when plugged into the Pi:
sudo nmcli connection up "Wired connection 1"

PS C:\Users\Meowstermind> ssh jetson@10.7.65.32 , password jetson
scp "D:\SchoolProjects\WheelGuard\MonsterBorg\src\human_detection_ucp.py" jetson@10.7.65.32:~/Downloads/human_detection-main/

service is called yolo.service