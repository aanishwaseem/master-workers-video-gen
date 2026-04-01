import cv2
import numpy as np
import os

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_ROOT = os.path.join(BASE_DIR, "input_files")
OUTPUT_ROOT = os.path.join(BASE_DIR, "output_files")

# Video Settings
WIDTH, HEIGHT = 1280, 720
FPS = 30
SECONDS = 30  # Updated to 10 seconds
TOTAL_FRAMES = FPS * SECONDS
FOURCC = cv2.VideoWriter_fourcc(*"mp4v")

# Ensure input directory exists to avoid errors
if not os.path.exists(INPUT_ROOT):
    print(f"Error: {INPUT_ROOT} not found. Please create it and add subfolders.")
    exit()

# --- Processing Loop ---
# Iterate through every folder inside input_files
for folder_name in os.listdir(INPUT_ROOT):
    input_folder_path = os.path.join(INPUT_ROOT, folder_name)

    # Only process if it's actually a directory
    if os.path.isdir(input_folder_path):
        print(f"Processing: {folder_name}...")

        # 1. Create matching directory in output_files
        target_output_dir = os.path.join(OUTPUT_ROOT, folder_name)
        os.makedirs(target_output_dir, exist_ok=True)

        # 2. Define final output file path
        output_file_path = os.path.join(target_output_dir, "result.mp4")

        # 3. Initialize Video Writer
        video = cv2.VideoWriter(output_file_path, FOURCC, FPS, (WIDTH, HEIGHT))

        # 4. Generate Frames
        for i in range(TOTAL_FRAMES):
            frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

            # Moving rectangle logic
            x = int((i / TOTAL_FRAMES) * WIDTH)
            cv2.rectangle(frame, (x, 300), (x + 200, 400), (0, 255, 0), -1)

            # Overlay text
            cv2.putText(
                frame, f"Folder: {folder_name} | Frame {i}", (50, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2
            )

            video.write(frame)

        video.release()
        print(f"Done! Saved to: {output_file_path}")

print("\nAll tasks completed.")