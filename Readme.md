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


