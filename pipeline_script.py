import cv2
import numpy as np
import sys
import os

if len(sys.argv) < 2:
    print("Usage: python pipeline_script.py <job_folder>")
    sys.exit(1)

job_folder = sys.argv[1]
output_file = os.path.join(job_folder, "result.mp4")

width = 1280
height = 720
fps = 30
seconds = 5
frames = fps * seconds

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
video = cv2.VideoWriter(output_file, fourcc, fps, (width, height))

for i in range(frames):

    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # moving rectangle
    x = int((i / frames) * width)

    cv2.rectangle(
        frame,
        (x, 300),
        (x + 200, 400),
        (0, 255, 0),
        -1
    )

    cv2.putText(
        frame,
        f"Frame {i}",
        (50, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (255,255,255),
        2
    )

    video.write(frame)

video.release()

print("Created video:", output_file)