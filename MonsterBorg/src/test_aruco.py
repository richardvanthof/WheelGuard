import cv2
import numpy as np

aruco_dict = cv2.aruco.getPredefinedDictionary(
    cv2.aruco.DICT_4X4_50
)

marker = cv2.aruco.generateImageMarker(
    aruco_dict,
    0,
    400
)

# Put the marker on a larger white canvas
canvas = np.full((800, 800), 255, dtype=np.uint8)
canvas[200:600, 200:600] = marker

detector = cv2.aruco.ArucoDetector(aruco_dict)

corners, ids, rejected = detector.detectMarkers(canvas)

print("ids =", ids)
print("rejected =", len(rejected))