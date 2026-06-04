# todo: do not send a continuous stream of command

import cv2
import os
import numpy as np
from pupil_apriltags import Detector
import wheelguard_api as WP

robot = WP.MonsterBorgClient(
    host=os.getenv("ROBOT_HOST", "localhost"),
    api_key=os.getenv("ROBOT_API_KEY")
)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))

def forward():
    try:
        print("Moving forward")
        robot.forward(
            0.5,
            0.5,
            1.0
        )
    except Exception as e:
        print(f"Failed to move forward: {e}")

def backward():
    try:
        print("Moving backward")
        robot.backward(
            0.5,
            0.5,
            1.0
        )
    except Exception as e:
        print(f"Failed to move backward: {e}")

def left():
    try:
        print("Turning left")
        robot.left(
            0.5,
            0.5,
            1.0
        )
    except Exception as e:
        print(f"Failed to turn left: {e}")

def right():
    try:
        print("Turning right")
        robot.right(
            0.5,
            0.5,
            1.0
        )
    except Exception as e:
        print(f"Failed to turn right: {e}")


def steer_toward_tag(tag_center_x, frame_center_x, max_turn=0.5):
    """Compute a proportional turn value from horizontal pixel error."""
    error = tag_center_x - frame_center_x
    normalized_error = error / frame_center_x
    turn = clamp(normalized_error * max_turn, -max_turn, max_turn)

    try:
        print(f"Steering with turn power: {turn:.2f}")
        robot.arcade(
            0.4,
            turn,
            0.2
        )
    except Exception as e:
        print(f"Failed to steer toward tag: {e}")



def follow_apriltag():
    """Main function to follow an AprilTag with the robot."""
    
    # Initialize camera
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    # Initialize AprilTag detector
    detector = Detector(families='tagStandard41h12', nthreads=1, quad_decimate=1.0, quad_sigma=0.0, 
                        refine_edges=1, decode_sharpening=0.25, debug=0)
    
    # Target parameters
    target_area = 5000  # Desired tag area in pixels
    frame_center_x = 320  # Image width / 2
    frame_center_y = 240  # Image height / 2
    area_threshold = 500
    position_threshold = 30
    
    print("Starting AprilTag follower...")
    print(os.getenv("ROBOT_API_KEY"))
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            tags = detector.detect(
                gray,
                estimate_tag_pose=True,
                camera_params=[1440, 1440, 960, 540],
                tag_size=0.05
            )
            
            if len(tags) > 0:
                # Get the largest tag (closest to camera)
                tag = max(tags, key=lambda t: t.decision_margin)
                
                # Calculate tag center
                tag_center_x = int((tag.corners[0][0] + tag.corners[1][0] + 
                                   tag.corners[2][0] + tag.corners[3][0]) / 4)
                tag_center_y = int((tag.corners[0][1] + tag.corners[1][1] + 
                                   tag.corners[2][1] + tag.corners[3][1]) / 4)
                
                # Calculate tag area
                tag_width = np.linalg.norm(tag.corners[1] - tag.corners[0])
                tag_height = np.linalg.norm(tag.corners[3] - tag.corners[0])
                tag_area = tag_width * tag_height
                
                # Horizontal movement scales with distance from the frame center.
                if abs(tag_center_x - frame_center_x) > position_threshold:
                    steer_toward_tag(tag_center_x, frame_center_x)
                
                # Vertical movement (forward/backward) based on area
                if tag_area < target_area - area_threshold:
                    forward()
                elif tag_area > target_area + area_threshold:
                    backward()
                
                # Draw tag for visualization
                cv2.polylines(frame, [tag.corners.astype(int)], True, (0, 255, 0), 2)
                cv2.circle(frame, (tag_center_x, tag_center_y), 5, (0, 0, 255), -1)
                cv2.putText(frame, f"ID: {tag.tag_id} Area: {tag_area:.0f}", 
                           (tag_center_x, tag_center_y - 20), cv2.FONT_HERSHEY_SIMPLEX, 
                           0.5, (0, 255, 0), 2)
            else:
                print("No AprilTag detected")
            
            # Display frame
            cv2.imshow("AprilTag Follower", frame)
            
            # Exit on 'q' key
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    follow_apriltag()
