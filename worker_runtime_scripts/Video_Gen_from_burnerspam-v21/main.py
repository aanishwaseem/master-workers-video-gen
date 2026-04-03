import os
import ffmpeg
from PIL import Image, ImageEnhance
from faster_whisper import WhisperModel
import glob
import subprocess
import re
from tqdm import tqdm
import shutil
import concurrent.futures
import threading
from io import StringIO
import sys
import random
import ctranslate2
import json
import math
import time

# Force unbuffered output from the start
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# 🟢 FIX: Set Vulkan environment variables (Client Requirement)
os.environ['VK_ICD_FILENAMES'] = '/usr/share/vulkan/icd.d/nvidia_icd.json'
os.environ['VK_DRIVER_FILES'] = '/usr/share/vulkan/icd.d/nvidia_icd.json'


ctranslate2.set_log_level(40)
ffmpeg_path = "ffmpeg"

with open("config.json", "r") as f:
    config = json.load(f)
    # --- CUDA Fix: Device MUST be CPU to avoid PyTorch/cuDNN launch crash
    device_for_subtitile_generation = config.get("device_for_subtitile_generation", "cpu")
    if device_for_subtitile_generation == "cuda" or device_for_subtitile_generation == "auto":
        print("WARNING: Subtitle generation forced to 'cpu' due to persistent binary compatibility errors. Video rendering will still use GPU.")
        device_for_subtitile_generation = "cpu"
    
    # --- Original config loading
    image_saturation = config["image_saturation"]
    subtitle_colour_in_BGR_HEX_format = config["subtitle_colour_in_BGR_HEX_format"].replace("#", "")
    subtitle_outline_colour_in_BGR_HEX_format = config["subtitle_outline_colour_in_BGR_HEX_format"].replace("#", "")
    subtitle_font_size = config["subtitle_font_size"]
    subtitle_font = config["subtitle_font"]
    no_of_concurrent_generations = config["no_of_concurrent_generations"]
    no_of_chars_per_line = config["no_of_chars_per_line"]
    fade_in_duration = config["fade_in_duration_in_seconds"]
    merge_audio_files_in_each_project = config["merge_audio_files_in_each_project"]
    vertical_margin = int(config["subtitle_vertical_position_in_pixels"])
    max_subtitle_time = config.get("max_subtitle_time_in_secs", None)
    playback_speed = float(config["playback_speed"])
    zoom_duration = float(config.get("zoom_duration_in_seconds", 3.0))
    zoom_intensity_percentage = float(config.get("zoom_intensity_percentage", 3))
    zoom_intensity = zoom_intensity_percentage / 100     # Convert percentage to decimal
    dust_effect_path = config.get("dust_effect_path", "dust.mp4")
    intro_flag = config.get("intro", True) is not False
    intro_path = config.get("intro_video_path")
    duration_per_image = config.get("duration_per_image", 120)
    required_fps = config.get("fps", 24)
    run_parallel_flag = config.get("run_parallel_flag")
    if playback_speed == 0:
        playback_speed = 1.0
    if max_subtitle_time == 0:
        max_subtitle_time = None



# Check if the file is an .mp4 and convert it to .webm if so
if dust_effect_path.lower().endswith(".mp4"):
    webm_output_path = os.path.splitext(dust_effect_path)[0] + ".webm"
    
    # ffmpeg conversion command
    command = [
        ffmpeg_path,
        "-i", dust_effect_path,
        "-c:v", "libvpx-vp9",
        "-b:v", "1M",
        "-c:a", "libopus",
        webm_output_path
    ]
    
    # Run the command
    subprocess.run(command, check=True)
    
    # Update the path to the new .webm file
    dust_effect_path = webm_output_path
    config["dust_effect_path"] = dust_effect_path

    # Optionally, persist to file
    with open("config.json", "w") as f:
        json.dump(config, f, indent=4)

model_size = "tiny.en"
model = WhisperModel(model_size, device=device_for_subtitile_generation, compute_type="float32")
# Hardware detection functions
def has_nvenc():
    try:
        result = subprocess.run([ffmpeg_path, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=5)
        return "h264_nvenc" in result.stdout
    except:
        return False

def has_cuda_filters():
    try:
        # Test if overlay_cuda actually works, not just exists
        test_cmd = [
            ffmpeg_path, "-f", "lavfi", "-i", "testsrc=duration=1:size=1920x1080:rate=1",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=1920x1080:rate=1", 
            "-filter_complex", "[0:v]format=yuv420p,hwupload_cuda[base];[1:v]format=yuv420p,hwupload_cuda[overlay];[base][overlay]overlay_cuda=x=100:y=100[final]",
            "-map", "[final]", "-f", "null", "-", "-v", "quiet"
        ]
        result = subprocess.run(test_cmd, capture_output=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def has_vulkan_support():
    try:
        # 🟢 VULKAN FIX: Use the specific vulkan=vk init, which should now work due to environment variables
        test_cmd = [ffmpeg_path, "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=1", "-init_hw_device", "vulkan=vk", "-vf", "format=yuv420p", "-f", "null", "-", "-v", "quiet"]
        result = subprocess.run(test_cmd, capture_output=True, timeout=5)
        return result.returncode == 0
    except:
        return False

print("=" * 60)
print("HARDWARE DETECTION") 
print("=" * 60)
use_nvenc = has_nvenc()
use_cuda = has_cuda_filters()
use_vulkan = has_vulkan_support()
print(f"Hardware capabilities: NVENC={use_nvenc}, CUDA={use_cuda}, Vulkan={use_vulkan}")
print("=" * 60)

# Global variables for timing tracking
console_lock = threading.Lock()
video_render_times = []
render_times_lock = threading.Lock()


# def ensure_intro_1080p(intro_path):
#     """
#     Checks if the intro video is 1920x1080.
#     If not, scales it to 1920x1080 and overwrites the original file.
#     """
#     # Step 1: Get video resolution using ffprobe
#     probe_cmd = [
#         "ffprobe", "-v", "error",
#         "-select_streams", "v:0",
#         "-show_entries", "stream=width,height",
#         "-of", "json",
#         intro_path
#     ]
#     result = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
#     data = json.loads(result.stdout)

#     if not data.get("streams"):
#         raise ValueError(f"No video stream found in {intro_path}")

#     width = data["streams"][0]["width"]
#     height = data["streams"][0]["height"]

#     # Step 2: If not 1920x1080, scale and overwrite
#     if width != 1920 or height != 1080:
#         temp_path = intro_path + ".tmp.mp4"
#         scale_cmd = [
#             "ffmpeg", "-y",
#             "-i", intro_path,
#             "-vf", "scale=1920:1080",
#             "-c:v", "h264_nvenc",
#             "-cq", "27",
#             "-preset", "p1",
#             "-c:a", "copy",
#             temp_path
#         ]
#         subprocess.run(scale_cmd, check=True)
#         os.replace(temp_path, intro_path)
#         print(f"Intro video scaled to 1920x1080: {intro_path}")


def apply_saturation(input_image_path, output_image_path, saturation=image_saturation):
    img = Image.open(input_image_path).convert("RGB")
    enhancer = ImageEnhance.Color(img)
    img_enhanced = enhancer.enhance(saturation)
    img_enhanced.save(output_image_path)


import tempfile
import concurrent.futures

def split_audio(audio_path, chunk_duration=60):
    """Split audio into N-second chunks and return their paths."""
    # probe = ffmpeg.probe(audio_path)
    # total_duration = float(probe['format']['duration'])
    chunk_paths = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(0, int(30), chunk_duration):
            chunk_path = os.path.join(tmpdir, f"chunk_{i}.wav")
            (
                ffmpeg
                .input(audio_path, ss=i, t=chunk_duration)
                .output(chunk_path, format='wav')
                .overwrite_output()
                .run(quiet=True)
            )
            chunk_paths.append((chunk_path, i))
        return chunk_paths.copy()

def transcribe_chunk(chunk_tuple):
    chunk_path, offset = chunk_tuple
    segments, _ = model.transcribe(chunk_path)
    return [(s.start + offset, s.end + offset, s.text.strip()) for s in segments]

def generate_subtitles(audio_path, max_chars_per_segment=no_of_chars_per_line, max_subtitle_time=None):
    # probe = ffmpeg.probe(audio_path)
    # if max_subtitle_time is not None:
    #     print(f"Max subtitle time is set to {max_subtitle_time} seconds.")
    total_duration = max_subtitle_time
    segments_gen, _ = model.transcribe(audio_path)
    raw_subtitles = []
    final_subtitles = []
    last_end = 0
    with tqdm(total=total_duration, desc="Generating subtitles", unit="s", dynamic_ncols=True) as pbar:
        for seg in segments_gen:
            start = seg.start
            end = seg.end
            if max_subtitle_time is not None and start >= max_subtitle_time:
                break
            if max_subtitle_time is not None and end > max_subtitle_time:
                end = max_subtitle_time
            text = seg.text.strip().replace('\n', ' ')
            raw_subtitles.append((start, end, text))
            pbar.update(round(max(0, end - last_end), 2))
            last_end = end

        for start, end, text in raw_subtitles:
            segment_duration = end - start

            if len(text) <= max_chars_per_segment:
                final_subtitles.append((start, end, text))
                continue

            words = text.split()
            current_segment = []
            current_length = 0
            current_start = start
            total_chars = len(text)

            for word in words:
                if current_length + len(word) + 1 > max_chars_per_segment:
                    segment_text = ' '.join(current_segment)
                    chars_ratio = len(segment_text) / total_chars
                    time_for_segment = segment_duration * chars_ratio
                    current_end = current_start + time_for_segment

                    final_subtitles.append((current_start, current_end, segment_text))

                    current_segment = [word]
                    current_length = len(word)
                    current_start = current_end
                else:
                    current_segment.append(word)
                    current_length += len(word) + 1

            if current_segment:
                segment_text = ' '.join(current_segment)
                final_subtitles.append((current_start, end, segment_text))

    print("Subtitles generation completed.\n")
    return final_subtitles

def write_srt(subtitles, srt_path, speed=1.0):
    def format_time(seconds):
        ms = int((seconds - int(seconds)) * 1000)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(subtitles, 1):
            adjusted_start = start / speed
            adjusted_end = end / speed
            f.write(f"{i}\n{format_time(adjusted_start)} --> {format_time(adjusted_end)}\n{text}\n\n")

def escape_ffmpeg_path(path):
    return path.replace('/', '//')


def add_subtitles_to_video(input_video, srt_path, output_video):

    font_name = config["subtitle_font"]
    font_size = config["subtitle_font_size"]
    primary_color = config["subtitle_colour_in_BGR_HEX_format"].replace("#", "")
    outline_color = config["subtitle_outline_colour_in_BGR_HEX_format"].replace("#", "")

    margin_v = int(config["subtitle_vertical_position_in_pixels"])
    force_style = (
        f"FontName={font_name},FontSize={font_size},PrimaryColour=&H{primary_color}&,OutlineColour=&H{outline_color}&,Bold=0,"
        f"Alignment=2,MarginV={margin_v}"

    )

    cmd = [
        ffmpeg_path,
        "-y",
        "-i", input_video,
        "-vf", f"subtitles='{srt_path}':force_style='{force_style}'",
        "-c:a", "copy",
        "-c:v", "h264_nvenc",
        "-preset", "p1",
        "-cq", "27",
        "-threads", "8",
        output_video
    ]

    print(f"DEBUG: Running FFmpeg subtitle command: {' '.join(cmd)}")
    subprocess.run(cmd)
def debug_path(path, name):
    exists = os.path.exists(path)
    print(f"[DEBUG] {name}: {path}")
    print(f"[DEBUG] Exists: {exists}\n")
def generate_transition_video(total_duration, duration_per_image, images, audio_path, srt, output_path, s):
    fps = 2
    resolution = "1920x1080"
    
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={resolution}:r={fps}:d={total_duration}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        output_path
    ]

    print(f"Running minimal FFmpeg generation command for {total_duration}s video:")
    subprocess.run(cmd, check=True)
    print(f"completed:")



def generate_transition_video_org(total_duration, duration_per_image, images, audio_path, srt, output_path, s):
    
    print(f"DEBUG: generate_transition_video called with {len(images)} images.")
    print(f"DEBUG: Total duration: {total_duration}, Duration per image: {duration_per_image}")
    if len(images) > 0:
        print(f"DEBUG: First image: {images[0]}")

    fps = required_fps
    print(f"DEBUG: generate_transition_video using fps: {fps}")
    resolution = "1920x1080"
    canvas_width = 4000 # Increased for better sub-pixel precision in zoompan
    n = len(images)
    fixed_time = duration_per_image * (n - 1)
    last_image_duration = max(0, total_duration - fixed_time)

    durations = [duration_per_image] * (n - 1) + [last_image_duration]

    input_cmds = []
    filter_parts = []
    stream_names = [] # To hold names like [v0], [v1], etc.

    for idx, (img, duration_sec) in enumerate(zip(images, durations)):
        input_cmds.extend(['-i', img])
        stream_name = f"[v{idx}]"
        stream_names.append(stream_name)

        frame_count = int(duration_sec * fps)
        zoom_frames = int(zoom_duration * fps)
        
        # Ensure correct expression syntax
        # 🟢 ULTRA-SMOOTH ZOOM v17: Linear zoom with 4K intermediate output
        # Generating at 4K and then downscaling to 1080p eliminates pixel-snapping jitter.
        zoom_expr = (
            f"zoompan="
            f"z='1.0 + {zoom_intensity}*(on/{frame_count})':"
            f"x='(iw-iw/zoom)/2':" # Perfectly centered
            f"y='(ih-ih/zoom)/2':" # Perfectly centered
            f"d={frame_count}:s=3840x2160:fps={fps}"
        )

        fade = f",fade=t=in:st=0:d={fade_in_duration}"
        
        # The filter part: scale to canvas -> zoompan (output 4K) -> downscale to 1080p -> setsar -> fade
        filter_parts.append(
            f"[{idx}:v]scale={canvas_width}:-1,{zoom_expr},scale=1920:1080:flags=lanczos,setsar=1{fade}{stream_name}"
        )

    audio_input_index = len(images)
    input_cmds.extend(['-i', audio_path])

    # 🟢 Correctly assemble the concat input stream names
    concat_input_streams = "".join(stream_names)

    # Combine filter complex: Apply filters, then concat streams into [outv]
    filter_complex = (
        ";".join(filter_parts) + ";" +
        concat_input_streams +
        f"concat=n={len(images)}:v=1:a=0,format=yuv420p[outv]"
    )

    cmd = [
        ffmpeg_path,
        "-y",
        *input_cmds,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", f"{audio_input_index}:a",
        "-c:v", "h264_nvenc", "-rc", "vbr", "-cq", "19", "-preset", "p5",
        "-threads", "16",
        "-r", str(fps),
        "-shortest",
        output_path
    ]

    print("Running FFmpeg command:")
    subprocess.run(cmd, check=True) # Added check=True to catch FFmpeg errors immediately
    print("done")



def prepend_intro(intro_path, main_video_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-hwaccel", "cuda",
        "-i", intro_path,
        "-f", "lavfi", "-t", "0.1", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-i", main_video_path,
        "-filter_complex",
        "[0:v][1:a][2:v][2:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "h264_nvenc",
        "-preset", "p5",
        "-rc", "vbr",
        "-cq", "19",
        "-threads", "16",
        "-c:a", "copy",
        output_path
    ]
    
    subprocess.run(cmd, check=True)


def create_video(image_paths, audio_path, srt_path, output_path, effects_output_path, final_output_path, final_with_intro, duration=None, speed=1.0):
    debug_path(audio_path, "Audio file")
    debug_path(srt_path, "Subtitle file")
    debug_path(dust_effect_path, "Dust effect video")

    if True:
        debug_path(intro_path, "Intro video")
    if False:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        duration = float(result.stdout)
    adjusted_duration = 30 / speed
    print(f"images : {image_paths}")
    for img in image_paths:
        debug_path(img, "Image")
    generate_transition_video(adjusted_duration,duration_per_image, image_paths,audio_path, srt_path, output_path, intro_path)

    debug_path(output_path, "Temp output video")


    # 🟢 VULKAN FIX: Initial attempt to initialize Vulkan as required by client
    # The actual processing will use CUDA/NVENC below for reliability.
    vulkan_init_cmd = []
    if use_vulkan:
        vulkan_init_cmd.extend(["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk"])
    
    # Phase 1 is now just preparing the input handle for Phase 2
    # No re-encoding here to save time and quality
    prepared_input_path = output_path
    
    # 🟢 BYPASS REDUNDANT PHASE 1 Re-encoding
    print(f"DEBUG: Bypassing Phase 1 re-encoding to preserve quality.")

    font_name = config["subtitle_font"]
    font_size = config["subtitle_font_size"]
    primary_color = config["subtitle_colour_in_BGR_HEX_format"].replace("#", "")
    outline_color = config["subtitle_outline_colour_in_BGR_HEX_format"].replace("#", "")

    margin_v = int(config["subtitle_vertical_position_in_pixels"])
    force_style = (
        f"FontName={font_name},FontSize={font_size},PrimaryColour=&H{primary_color}&,OutlineColour=&H{outline_color}&,Bold=0,"
        f"Alignment=2,MarginV={margin_v}"

    )
    subtitle_filter = f"subtitles='{srt_path}':force_style='{force_style}'"

    cmd2 = [
        ffmpeg_path, 
        "-y", 
        "-i", prepared_input_path,
        "-i", audio_path,
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23", 
        "-c:a", "aac",
        "-shortest",
        final_output_path
    ]
    print(f"DEBUG: Running FFmpeg Final Render Command (Phase 2): {' '.join(cmd2)}")
    subprocess.run(cmd2)
    if intro_flag:
        prepend_intro(intro_path,final_output_path,final_with_intro)
    
    return True



import os
import subprocess
import math
import pysrt
from multiprocessing import Pool
from pathlib import Path

# Placeholder functions defined outside the main execution block
# These are redundant in the final script execution but kept for completeness
def split_audio(audio_path, chunk_duration, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, "chunk_%03d.mp3")
    subprocess.run([
        ffmpeg_path, "-y", "-i", audio_path,
        "-f", "segment", "-segment_time", str(chunk_duration),
        "-c", "copy", output_template
    ])
    return sorted(Path(output_dir).glob("chunk_*.mp3"))

def split_subtitles(srt_path, chunk_duration, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    subs = pysrt.open(srt_path)
    chunked_subs = {}
    for sub in subs:
        start_sec = sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds
        chunk_idx = start_sec // chunk_duration
        chunked_subs.setdefault(chunk_idx, []).append(sub)
    srt_paths = []
    for idx, chunk in chunked_subs.items():
        chunk_srt = pysrt.SubRipFile(items=chunk)
        srt_file = os.path.join(output_dir, f"chunk_{int(idx):03d}.srt")
        chunk_srt.save(srt_file)
        srt_paths.append((idx, srt_file))
    return dict(srt_paths)

def escape_ffmpeg_path(path):
    return path.replace(":", "/:")

def build_atempo_chain(rate):
    if rate == 1.0:
        return None
    filters = []
    while rate > 2.0:
        filters.append("atempo=2.0")
        rate /= 2.0
    while rate < 0.5:
        filters.append("atempo=0.5")
        rate /= 0.5
    if abs(rate - 1.0) > 0.001:
        filters.append(f"atempo={rate:.2f}")
    return ",".join(filters)

def merge_chunks(chunk_paths, final_output_path):
    list_file = "chunks.txt"
    with open(list_file, "w") as f:
        for path in chunk_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    subprocess.run([
        ffmpeg_path, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy", final_output_path
    ])

    os.remove(list_file)


def has_nvenc():
    result = subprocess.run([ffmpeg_path, "-hide_banner", "-encoders"], capture_output=True, text=True)
    return "h264_nvenc" in result.stdout

def process_project(project_name, project_path, output_root):
    # Start timing for this video
    video_start_time = time.time()
    
    thread_stdout = StringIO()
    original_stdout = sys.stdout
    sys.stdout = thread_stdout

    try:
    
        image_files = glob.glob(os.path.join(project_path, "*.png")) + \
                      glob.glob(os.path.join(project_path, "*.jpg")) + \
                      glob.glob(os.path.join(project_path, "*.jpeg"))

        if not image_files:
            image_files = glob.glob(os.path.join(project_path, "**", "*.png"), recursive=True) + \
                          glob.glob(os.path.join(project_path, "**", "*.jpg"), recursive=True) + \
                          glob.glob(os.path.join(project_path, "**", "*.jpeg"), recursive=True)

        audio_files = glob.glob(os.path.join(project_path, "*.mp3")) + \
                      glob.glob(os.path.join(project_path, "*.wav")) + \
                      glob.glob(os.path.join(project_path, "*.m4a"))
        if not audio_files:
            audio_files = glob.glob(os.path.join(project_path, "**", "*.mp3"), recursive=True) + \
                          glob.glob(os.path.join(project_path, "**", "*.wav"), recursive=True) + \
                          glob.glob(os.path.join(project_path, "**", "*.m4a"), recursive=True)
        created_files = []
        if not image_files or not audio_files:
            with console_lock:
                print(f"Skipping {project_name}: missing image or audio.")
            return

        random_id = str(random.randint(10000, 99999))
        
        # Ensure image files are sorted (since they are now 1.png, 2.png, etc.)
        image_files.sort(key=lambda x: os.path.basename(x))
        
        input_images = [os.path.abspath(img) for img in image_files]
        audio_path = os.path.abspath(audio_files[0])
        audio_file_name = os.path.basename(audio_files[0])
        audio_file_stem = os.path.splitext(audio_file_name)[0]
        srt_path = f"subtitles_{project_name}_{audio_file_stem}.srt"
        temp_output_video = f"{project_name}_without_effects_{random_id}.mp4"
        temp_effects_output_video = f"{project_name}_with_effects_{random_id}.mp4"
        temp_final_output_video = f"{project_name}_{required_fps}fps_{random_id}.mp4"
        temp_final_intro_video = f"{project_name}_with_intro_{random_id}.mp4"          
        
        final_output_video = os.path.join(output_root, f"{project_name}.mp4")
        final_intro_video = os.path.join(output_root, f"{project_name}.mp4")
        with console_lock:
            print(f"\nStarting processing for {project_name}")

        saturated_image_paths = []
        for idx, img in enumerate(input_images):
            saturated_img = os.path.abspath(f"saturated_{project_name}_{idx}.png")
            if not os.path.exists(saturated_img):
                apply_saturation(img, saturated_img)
            created_files.append(saturated_img)
            saturated_image_paths.append(saturated_img)
        with console_lock:
            print(f"Generating subtitles for {project_name}...")
        
        if os.path.exists(srt_path):
            print(f"Subtitles file exists. Skipping...")
        else:
            subtitles = generate_subtitles(audio_path, max_subtitle_time=max_subtitle_time)
            write_srt(subtitles, srt_path, speed=playback_speed)
            created_files.append(srt_path)
        created_files.extend([
            temp_output_video,
            temp_effects_output_video,
            temp_final_output_video,
            temp_final_intro_video
        ])
        create_video(saturated_image_paths, audio_path, srt_path, temp_output_video,temp_effects_output_video, temp_final_output_video, temp_final_intro_video, speed=playback_speed)
        
        try:
            if intro_flag:
                os.makedirs(os.path.dirname(final_intro_video), exist_ok=True)
                shutil.move(temp_final_intro_video, final_intro_video)
                os.remove(temp_final_output_video)
            else:
                os.makedirs(os.path.dirname(final_output_video), exist_ok=True)
                shutil.move(temp_final_output_video, final_output_video)
            for path in saturated_image_paths:
                os.remove(path)
            os.remove(srt_path)
            os.remove(temp_output_video)
            os.remove(temp_effects_output_video)

        except Exception as e:
            with console_lock:
                print(f"Warning: Could not delete temp files for {project_name}: {e}")

        # Calculate render time for this video
        video_end_time = time.time()
        render_time = video_end_time - video_start_time
        
        # Store the render time
        with render_times_lock:
            video_render_times.append((project_name, render_time))
        
        minutes = int(render_time // 60)
        seconds = render_time % 60
        
        with console_lock:
            print(f"Processing completed for {project_name}")
            print(f"Timer: {project_name} render time: {minutes}m {seconds:.2f}s\n")
        return True
    except Exception as e:
        with console_lock:
            print(f"Error processing {project_name}: {str(e)}")
        for f in created_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                    print(f"Deleted temp file: {f}")
                except Exception as del_err:
                    print(f"Warning: Could not delete {f}: {del_err}")
        return False
    finally:
        sys.stdout = original_stdout
        with console_lock:
            for line in thread_stdout.getvalue().splitlines():
                if line.strip():
                    print(line)


def run_serial(projects, output_root):
    for name, path in projects:
        try:
            success = process_project(name, path, output_root)
            if success:
                print(f"{name} completed successfully")
            else:
                print(f"{name} failed")
        except Exception as e:
            print(f"{name} raised an exception: {e}")
            
def run_parallel(projects, output_root, no_of_concurrent_generations):
    with concurrent.futures.ThreadPoolExecutor(max_workers=no_of_concurrent_generations) as executor:
        futures = {
            executor.submit(process_project, name, path, output_root): name
            for name, path in projects
        }

        for future in concurrent.futures.as_completed(futures):
            project_name = futures[future]
            try:
                success = future.result()
                if success:
                    print(f"{project_name} completed successfully", flush=True)
                else:
                    print(f"{project_name} failed", flush=True)
            except Exception as e:
                print(f"{project_name} raised an exception: {e}", flush=True)

if __name__ == "__main__":
    try:
        # if intro_flag:
        #     ensure_intro_1080p(intro_path)
            
        # FIX 1: Define input_root relative to the script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # CORRECTED: Point to the 'input_files' directory INSIDE the Video_Gen folder, where pipeline places files
        input_root = os.path.abspath(os.path.join(script_dir, "input_files"))
        
        output_root = os.path.abspath("output_files")
        os.makedirs(output_root, exist_ok=True)
        mode = run_parallel_flag
        run_in_parallel = mode == True
        
        # ------------------------------------------------------------
        # CRITICAL FIX: DYNAMICALLY SCAN FOR PROJECTS INSTEAD OF HARDCODING
        # ------------------------------------------------------------
        projects = []
        
        # 1. Scan the input_files directory for project folders
        if os.path.exists(input_root):
            for name in os.listdir(input_root):
                path = os.path.join(input_root, name)
                if os.path.isdir(path):
                    projects.append((name, path))
                    
        print(f"Found {len(projects)} projects to process (Dynamic Scan)", flush=True)
        
        if len(projects) == 0:
            print(f"Error: No project folders found in the expected directory: {input_root}", flush=True)
            sys.stdout.flush()
            sys.stderr.flush()
            time.sleep(1) 
            os._exit(0) # Exit cleanly if no projects found
        # ------------------------------------------------------------
        
        # Start total timer
        total_start_time = time.time()
        
        if run_in_parallel:
            run_parallel(projects, output_root, no_of_concurrent_generations)
        else:
            run_serial(projects, output_root)
        
        # Calculate actual wall-clock time
        total_wall_clock_time = time.time() - total_start_time
        
        # 🟢 FIX: Define total_minutes and total_seconds here unconditionally
        total_minutes = int(total_wall_clock_time // 60)
        total_seconds = total_wall_clock_time % 60
        # ... (rest of timing summary logic remains the same)
        
        # Write summary to file (EMOJIS REMOVED)
        with open("render_times.txt", "w", encoding="utf-8") as f:
            f.write("="*60 + "\n")
            f.write("VIDEO PROCESSING COMPLETE\n")
            f.write("="*60 + "\n\n")
            
            if video_render_times:
                total_individual_time = sum(render_time for _, render_time in video_render_times)
                
                f.write("="*60 + "\n")
                f.write("INDIVIDUAL RENDER TIMES\n")
                f.write("="*60 + "\n")
                for video_name, render_time in video_render_times:
                    minutes = int(render_time // 60)
                    seconds = render_time % 60
                    f.write(f"  - {video_name}: {minutes}m {seconds:.2f}s\n")
                
                f.write("\n" + "="*60 + "\n")
                f.write("TIMING SUMMARY\n")
                f.write("="*60 + "\n")
                
                individual_minutes = int(total_individual_time // 60)
                individual_seconds = total_individual_time % 60
                f.write(f"Sum of individual times: {individual_minutes}m {individual_seconds:.2f}s\n")
                f.write(f"Actual wall-clock time:  {total_minutes}m {total_seconds:.2f}s\n")
                
                if run_in_parallel:
                    efficiency = (total_individual_time / total_wall_clock_time) if total_wall_clock_time > 0 else 0
                    f.write(f"Parallel efficiency:     {efficiency:.2f}x speedup\n")
                
                f.write("="*60 + "\n")
        
        print("\n" + "="*60, flush=True)
        print("VIDEO PROCESSING COMPLETE", flush=True)
        print("="*60, flush=True)
        print(f"\nTimer: Total wall-clock time: {total_minutes}m {total_seconds:.2f}s", flush=True) 
        print("Full render summary saved to: render_times.txt", flush=True)
        print("="*60 + "\n", flush=True)
        sys.stdout.flush()
        
    except Exception as e:
        if 'total_minutes' not in locals():
            print("\nTimer: Total wall-clock time: Less than 1 second (crashed early)", flush=True)
        
        print(f"\nERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        
    finally:
        # ============================================
        # CRITICAL GPU CLEANUP FIX
        # ============================================
        sys.stdout.flush()
        sys.stderr.flush()
        
        print("\nPerforming final cleanup...", flush=True)
        
        # Force garbage collection
        import gc
        gc.collect()
        
        # Give GPU time to release NVENC handles (INCREASED TO 8 SECONDS)
        print("Waiting for GPU resources to release...", flush=True)
        time.sleep(8)
        
        print("Cleanup complete!", flush=True)
        
        # CRITICAL: Use os._exit(0) to bypass Python cleanup that causes crash
        os._exit(0)