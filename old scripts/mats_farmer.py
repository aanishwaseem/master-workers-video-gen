import os
import shutil
import json
import subprocess
import sys
import io
import threading
import time
from datetime import datetime

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
NICHES_DIR = os.path.join(BASE_DIR, "niches")

# ============================================================================
# LOGGING
# ============================================================================

LOG_FILE = os.path.join(BASE_DIR, "mats_farmer_log.txt")
SLIM_LOG_FILE = os.path.join(BASE_DIR, "mats_farmer_slim.txt")

_log_lock = threading.Lock()

def log(message, section=False, file_only=False):
    """Print timestamped log message to both console and log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if section:
        log_line = f"[{timestamp}] {'━' * 50}"
    else:
        log_line = f"[{timestamp}] {message}"

    if not file_only:
        print(log_line)

    with _log_lock:
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(log_line + "\n")
                f.flush()
        except Exception:
            pass

def log_slim(message):
    """Write a concise, critical-only log line."""
    if not message or not message.strip():
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    with _log_lock:
        try:
            with open(SLIM_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + "\n")
                f.flush()
        except Exception:
            pass

# Load config.json
try:
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"❌ config.json not found at {CONFIG_PATH}")
    exit(1)
except json.JSONDecodeError as e:
    print(f"❌ Error parsing config.json: {e}")
    exit(1)


# ==============================================
# NICHE DETECTION SYSTEM
# ==============================================

def get_niche_config(niche_name):
    """Load niche config from niches/ folder."""
    niche_file = os.path.join(NICHES_DIR, f"{niche_name}.json")
    if os.path.exists(niche_file):
        try:
            with open(niche_file, 'r') as f:
                niche_config = json.load(f)
                print(f"📂 Loaded niche config: {niche_name}")
                return niche_config
        except json.JSONDecodeError as e:
            print(f"⚠️ Error parsing niche config {niche_name}.json: {e}")
    return None


def detect_niche_from_input(input_folder):
    """Scan input folder and detect niche from config folder name."""
    if not os.path.isdir(input_folder):
        return None, None

    available_niches = []
    if os.path.isdir(NICHES_DIR):
        for niche_file in os.listdir(NICHES_DIR):
            if niche_file.endswith(".json"):
                niche_name = niche_file[:-5]
                available_niches.append(niche_name)

    available_niches.sort(key=len, reverse=True)

    for item in os.listdir(input_folder):
        item_path = os.path.join(input_folder, item)
        if os.path.isdir(item_path):
            item_lower = item.lower()

            niche_config = get_niche_config(item)
            if niche_config:
                return item, niche_config

            for niche_name in available_niches:
                if niche_name.lower() in item_lower:
                    niche_config = get_niche_config(niche_name)
                    if niche_config:
                        print(f"📂 Matched folder '{item}' to niche '{niche_name}'")
                        return niche_name, niche_config

    return None, None


def get_config_number_by_name(configs_dir, config_name):
    """Given a config folder name, return its number (1-based index)."""
    if not os.path.exists(configs_dir):
        return "1"

    config_folders = sorted([
        d for d in os.listdir(configs_dir)
        if os.path.isdir(os.path.join(configs_dir, d))
    ])

    for idx, folder in enumerate(config_folders):
        if folder == config_name:
            return str(idx + 1)

    print(f"⚠️ Config '{config_name}' not found in {configs_dir}, using default")
    return "1"


# ==============================================
# UTILITY FUNCTIONS
# ==============================================

def clear_folder(folder_path, folder_name):
    """Clear all contents of a folder without deleting the folder itself."""
    if os.path.exists(folder_path):
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception as e:
                print(f"⚠️ Failed to delete {item_path}: {e}")
        print(f"🧹 Cleared: {folder_name}")
    else:
        print(f"⚠️ Folder not found (skipping): {folder_name}")


def copy_story_folders(src_root, dest_root):
    """Copy story folders from src_root to dest_root, preserving nested config/video structure."""
    if not os.path.isdir(src_root):
        print(f"❌ Input folder not found: {src_root}")
        return []

    copied_folders = []

    for item in os.listdir(src_root):
        item_path = os.path.join(src_root, item)
        if not os.path.isdir(item_path):
            continue

        subitems = os.listdir(item_path)
        has_video_subfolders = any(
            os.path.isdir(os.path.join(item_path, sub)) and sub.startswith("Video")
            for sub in subitems
        )

        if has_video_subfolders:
            config_name = item
            for video_name in subitems:
                video_path = os.path.join(item_path, video_name)
                if os.path.isdir(video_path):
                    dest_config = os.path.join(dest_root, config_name)
                    os.makedirs(dest_config, exist_ok=True)
                    dest_path = os.path.join(dest_config, video_name)
                    if os.path.exists(dest_path):
                        shutil.rmtree(dest_path)
                    shutil.copytree(video_path, dest_path)
                    copied_folders.append(f"{config_name}/{video_name}")
                    print(f"📂 Copied story folder: {config_name}/{video_name}")
        else:
            dest_path = os.path.join(dest_root, item)
            if os.path.exists(dest_path):
                shutil.rmtree(dest_path)
            shutil.copytree(item_path, dest_path)
            copied_folders.append(item)
            print(f"📂 Copied story folder: {item}")

    return copied_folders


def remove_copied_folders(dest_root, story_names):
    """Delete the folders we copied to component."""
    for story_name in story_names:
        if "/" in story_name:
            dest_path = os.path.join(dest_root, story_name)
        else:
            dest_path = os.path.join(dest_root, story_name)

        if os.path.exists(dest_path):
            shutil.rmtree(dest_path)
            print(f"🗑️ Removed copied folder: {story_name}")


def enumerate_all_videos(input_folder):
    """Scan input folder and return list of all video story names."""
    video_list = []

    if not os.path.isdir(input_folder):
        print(f"❌ Input folder not found: {input_folder}")
        return video_list

    for item in os.listdir(input_folder):
        item_path = os.path.join(input_folder, item)
        if not os.path.isdir(item_path):
            continue

        subitems = os.listdir(item_path)
        has_video_subfolders = any(
            os.path.isdir(os.path.join(item_path, sub)) and sub.startswith("Video")
            for sub in subitems
        )

        if has_video_subfolders:
            config_name = item
            for video_name in subitems:
                video_path = os.path.join(item_path, video_name)
                if os.path.isdir(video_path):
                    video_list.append(f"{config_name}/{video_name}")
        else:
            video_list.append(item)

    return video_list


def get_video_name_from_story(story_name):
    """Extract the video folder name from a story name."""
    if "/" in story_name:
        return story_name.split("/", 1)[1]
    return story_name


def find_video_in_temp(temp_folder, video_name):
    """Find the actual path for a video in temp folder (handles flat and nested)."""
    video_path = os.path.join(temp_folder, video_name)
    if os.path.exists(video_path):
        return video_path

    if os.path.exists(temp_folder):
        for item in os.listdir(temp_folder):
            item_path = os.path.join(temp_folder, item)
            if os.path.isdir(item_path):
                nested_path = os.path.join(item_path, video_name)
                if os.path.exists(nested_path):
                    return nested_path
    return None


def count_materials(folder_path):
    """Count audio and image files in a folder. Returns (audio_count, image_count)."""
    if not folder_path or not os.path.exists(folder_path):
        return 0, 0

    audio_count = 0
    image_count = 0
    for item in os.listdir(folder_path):
        lower = item.lower()
        if lower.endswith(".mp3"):
            audio_count += 1
        elif lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
            image_count += 1

    return audio_count, image_count


def get_expected_image_count_from_config(imagegen_dir, img_project_name):
    """
    Read expected images per video from the image gen config.
    Returns no_of_chapters * no_of_chunks_per_chapter, or 0 if unavailable.
    """
    if not imagegen_dir or not img_project_name:
        return 0
    config_path = os.path.join(imagegen_dir, "configs", img_project_name, "config.json")
    if not os.path.exists(config_path):
        return 0
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        focal = cfg.get("focal_point_settings", {})
        chapters = focal.get("no_of_chapters", 1)
        chunks = focal.get("no_of_chunks_per_chapter", 1)
        return chapters * chunks
    except Exception:
        return 0


def get_expected_image_count(video_name, img_manifest_path):
    """
    Get the expected number of images for a video from the IMG manifest.
    Returns the count, or 0 if manifest unavailable.
    """
    if not img_manifest_path or not os.path.exists(img_manifest_path):
        return 0

    try:
        with open(img_manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        prompts = manifest.get("prompts", {})
        count = 0
        for prompt_key, prompt_data in prompts.items():
            if prompt_data.get("story_folder") == video_name:
                count += 1

        return count
    except (json.JSONDecodeError, Exception):
        return 0


def check_video_ready(temp_folder, video_name, expected_images=None, require_audio=True):
    """
    Check if a video has required materials in temp folder.
    If require_audio is True, needs audio. Always needs images.
    If expected_images is set, requires exact match. Otherwise requires at least 1.
    """
    video_path = find_video_in_temp(temp_folder, video_name)
    if not video_path:
        return False

    audio_count, image_count = count_materials(video_path)

    if require_audio and audio_count == 0:
        return False

    if expected_images and expected_images > 0:
        return image_count >= expected_images
    else:
        return image_count > 0


# ==============================================
# WORKER SUBPROCESS FUNCTIONS
# ==============================================

def run_worker_subprocess(name, script_path, script_dir, first_input=None, second_input=None):
    """Run a worker subprocess. Returns the Popen object."""
    cmd = ["py", "-3.11", "-u", script_path]

    process_input = None
    if first_input is not None:
        process_input = f"{first_input}\n"
        if second_input is not None:
            process_input += f"{second_input}\n"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    process = subprocess.Popen(
        cmd,
        cwd=script_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        encoding='utf-8'
    )

    if process_input:
        process.stdin.write(process_input)
        process.stdin.flush()
    process.stdin.close()

    return process


def stream_process_output(process, name, print_lock):
    """Stream output from a subprocess with a prefix, filtering noisy lines from console."""
    import re as _re_stream

    # Console filter state
    _last_vo_poll_key = None

    try:
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line_stripped = line.rstrip()
                s = line_stripped

                # Log everything to verbose log (file only)
                log(f"[{name}] {s}", file_only=True)

                # === CONSOLE FILTER: suppress noisy patterns ===
                show_on_console = True

                # Suppress: DEBUG check_video_ready (fires every poll cycle)
                if "DEBUG check_video_ready" in s:
                    show_on_console = False

                # Suppress: VO/IMG fuzzy match spam
                elif "fuzzy match" in s:
                    show_on_console = False

                # Suppress: "Checking X items, Y active tasks" — condense to summary on change
                elif "Checking" in s and "active tasks" in s:
                    show_on_console = False
                    try:
                        m = _re_stream.search(r'Checking (\d+) items?, (\d+) active', s)
                        if m:
                            poll_key = f"{m.group(1)}_{m.group(2)}"
                            if poll_key != _last_vo_poll_key:
                                _last_vo_poll_key = poll_key
                                with print_lock:
                                    print(f"[{name}] ⏳ Polling: {m.group(2)} active tasks, {m.group(1)} items", flush=True)
                    except:
                        pass

                # Suppress: "Item N: Processing/Status" per-item dumps
                elif _re_stream.match(r'.*Item \d+:', s):
                    show_on_console = False

                # Suppress: "Workers done but" repeated waiting messages
                elif "Workers done but" in s:
                    show_on_console = False

                # Suppress: "VO moved: X/Y, IMG moved: X/Y" repeated status
                elif "VO moved:" in s and "IMG moved:" in s:
                    show_on_console = False

                # Suppress: "Still waiting for N tabs" repeated poll messages
                elif "Still waiting for" in s and "tabs" in s:
                    show_on_console = False

                # Print to console if not suppressed
                if show_on_console:
                    with print_lock:
                        print(f"[{name}] {s}", flush=True)

                # === SLIM LOG: critical events only ===

                # VO events
                if name == "VO":
                    if "Queued:" in s:
                        log_slim(f"[VO] Queued: {s.split('Queued:', 1)[1].strip()}")
                    elif "Saved:" in s and ".mp3" in s:
                        log_slim(f"[VO] Downloaded: {s.split('Saved:', 1)[1].strip()}")
                    elif "Merged:" in s and ".mp3" in s:
                        log_slim(f"[VO] Merged: {s.split('Merged:', 1)[1].strip()}")
                    elif "All stories completed" in s:
                        log_slim(f"[VO] All stories completed")
                    elif "failed" in s.lower() or "error" in s.lower() or "❌" in s:
                        log_slim(f"[VO] {s}")

                # IMG events
                elif name == "IMG":
                    if "COMPLETE:" in s or "TOTAL PROMPTS GENERATED:" in s:
                        log_slim(f"[IMG] {s}")
                    elif "Inline saved:" in s:
                        log_slim(f"[IMG] {s}")
                    elif "RETRY ROUND" in s:
                        log_slim(f"[IMG] {s}")
                    elif "Skipping" in s or "Rate limit" in s:
                        log_slim(f"[IMG] {s}")
                    elif "failed" in s.lower() or "error" in s.lower() or "❌" in s:
                        log_slim(f"[IMG] {s}")
                    elif "Worker completed" in s or "✅ Worker" in s:
                        log_slim(f"[IMG] {s}")

                # Moved to temp
                elif "Moved VO:" in s:
                    log_slim(f"[VO] {s}")
                elif "Moved IMG:" in s:
                    log_slim(f"[IMG] {s}")

                # Errors (catch-all)
                elif "❌" in s or "ERROR" in s:
                    log_slim(f"[{name}] {s}")

    except Exception as e:
        with print_lock:
            print(f"[{name}] Stream error: {e}")
        log_slim(f"[{name}] Stream error: {e}")
    finally:
        process.stdout.close()


# ==============================================
# PROJECT NAME RESOLUTION
# ==============================================

def get_project_name(component_dir, config_key_project, config_key_input, cfg):
    """Get project name from config or derive from input number."""
    project_name = cfg.get(config_key_project)
    if project_name:
        return project_name

    configs_dir = os.path.join(component_dir, "configs")
    if not os.path.exists(configs_dir):
        return None

    try:
        config_folders = sorted([
            d for d in os.listdir(configs_dir)
            if os.path.isdir(os.path.join(configs_dir, d))
        ])

        if not config_folders:
            return None

        input_val = cfg.get(config_key_input, "1")
        input_num = int(input_val.split(",")[0].strip())
        input_idx = input_num - 1

        if 0 <= input_idx < len(config_folders):
            return config_folders[input_idx]
        else:
            return config_folders[0]
    except Exception as e:
        print(f"⚠️ Error getting project name: {e}")
        return None


# ==============================================
# OUTPUT MOVEMENT TO TEMP
# ==============================================

def move_vo_output_to_temp(video_name, voiceover_output, temp_folder, story_name_map, print_lock):
    """Move a completed VO .mp3 file to the temp folder."""
    try:
        story_name = story_name_map.get(video_name, video_name)

        # Check nested path first (config_name/video_name.mp3), then flat
        if "/" in story_name:
            config_name, vid_name = story_name.split("/", 1)
            mp3_path = os.path.join(voiceover_output, config_name, vid_name + ".mp3")
            if not os.path.exists(mp3_path):
                mp3_path = os.path.join(voiceover_output, video_name + ".mp3")
        else:
            mp3_path = os.path.join(voiceover_output, video_name + ".mp3")

        if not os.path.exists(mp3_path):
            return False

        dest_video_folder = os.path.join(temp_folder, video_name)

        os.makedirs(dest_video_folder, exist_ok=True)
        dest_path = os.path.join(dest_video_folder, video_name + ".mp3")

        if os.path.exists(dest_path):
            os.remove(dest_path)

        shutil.move(mp3_path, dest_path)

        with print_lock:
            print(f"📦 Moved VO: {video_name}.mp3 → temp")
        log_slim(f"[VO] Moved: {video_name}.mp3 → temp")

        return True
    except Exception as e:
        with print_lock:
            print(f"⚠️ Error moving VO output: {e}")
        log_slim(f"[VO] ⚠️ Error moving {video_name}: {e}")
        return False


def move_img_output_to_temp(story_folder_name, imagegen_output, temp_folder, story_name_map, print_lock):
    """Move a completed IMG folder to the temp folder."""
    try:
        # Check nested path first (config_name/video_name/), then flat
        story_name = story_name_map.get(story_folder_name, story_folder_name)
        if "/" in story_name:
            src_path = os.path.join(imagegen_output, story_name)
            if not os.path.exists(src_path):
                src_path = os.path.join(imagegen_output, story_folder_name)
        else:
            src_path = os.path.join(imagegen_output, story_folder_name)

        if not os.path.exists(src_path):
            return False

        has_images = any(f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) for f in os.listdir(src_path))
        if not has_images:
            return False

        dest_video_folder = os.path.join(temp_folder, story_folder_name)
        os.makedirs(dest_video_folder, exist_ok=True)

        for item in os.listdir(src_path):
            src_file = os.path.join(src_path, item)
            dest_file = os.path.join(dest_video_folder, item)

            if os.path.exists(dest_file):
                if os.path.isfile(dest_file):
                    os.remove(dest_file)
                else:
                    shutil.rmtree(dest_file)

            shutil.move(src_file, dest_file)

        shutil.rmtree(src_path, ignore_errors=True)

        with print_lock:
            print(f"📦 Moved IMG: {story_folder_name}/ → temp")
        log_slim(f"[IMG] Moved: {story_folder_name}/ → temp")

        return True
    except Exception as e:
        with print_lock:
            print(f"⚠️ Error moving IMG output: {e}")
        log_slim(f"[IMG] ⚠️ Error moving {story_folder_name}: {e}")
        return False


# ==============================================
# MANIFEST POLLING
# ==============================================

def poll_vo_manifest(vo_manifest_path, voiceover_output, temp_folder, story_name_map,
                     vo_moved_set, all_video_names, print_lock):
    """Poll VO manifest for completed stories and move them to temp."""
    newly_moved = []

    if not os.path.exists(vo_manifest_path):
        return newly_moved

    try:
        with open(vo_manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        stories = manifest.get("stories", {})

        for story_name, story_data in stories.items():
            if story_data.get("status") == "completed":
                video_name = story_name
                if video_name in all_video_names and video_name not in vo_moved_set:
                    if move_vo_output_to_temp(video_name, voiceover_output, temp_folder, story_name_map, print_lock):
                        vo_moved_set.add(video_name)
                        newly_moved.append(video_name)
    except json.JSONDecodeError:
        pass
    except Exception as e:
        with print_lock:
            print(f"⚠️ Error polling VO manifest: {e}")

    return newly_moved


def poll_img_manifest(img_manifest_path, imagegen_output, temp_folder, story_name_map,
                      img_moved_set, all_video_names, print_lock, expected_image_counts=None):
    """Poll IMG manifest for stories with all images completed and move them to temp."""
    newly_moved = []

    if not os.path.exists(img_manifest_path):
        return newly_moved

    try:
        with open(img_manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        prompts = manifest.get("prompts", {})

        stories = {}
        for prompt_key, prompt_data in prompts.items():
            story_folder = prompt_data.get("story_folder")
            if story_folder:
                if story_folder not in stories:
                    stories[story_folder] = {"total": 0, "completed": 0}
                stories[story_folder]["total"] += 1
                if prompt_data.get("status") == "completed":
                    stories[story_folder]["completed"] += 1

        for story_folder, counts in stories.items():
            if counts["total"] > 0 and counts["completed"] == counts["total"]:
                if story_folder in all_video_names and story_folder not in img_moved_set:
                    if move_img_output_to_temp(story_folder, imagegen_output, temp_folder, story_name_map, print_lock):
                        img_moved_set.add(story_folder)
                        newly_moved.append(story_folder)
                        # Track expected image count
                        if expected_image_counts is not None:
                            expected_image_counts[story_folder] = counts["total"]
    except json.JSONDecodeError:
        pass
    except Exception as e:
        with print_lock:
            print(f"⚠️ Error polling IMG manifest: {e}")

    return newly_moved


def find_latest_manifest(configs_dir, manifest_name="manifest.json"):
    """Find the most recently modified manifest.json across all config folders."""
    latest_path = None
    latest_mtime = 0

    if not os.path.exists(configs_dir):
        return None

    for config_folder in os.listdir(configs_dir):
        manifest_path = os.path.join(configs_dir, config_folder, manifest_name)
        if os.path.exists(manifest_path):
            mtime = os.path.getmtime(manifest_path)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = manifest_path

    return latest_path


# ==============================================
# MOVE READY VIDEO TO MATS OUTPUT
# ==============================================

def move_to_mats_output(video_name, story_name, temp_folder, mats_output_path, print_lock,
                        expected_images=0, require_audio=True):
    """
    Move a ready video from temp to the shared mats output folder.
    STRICT VALIDATION: Will NOT move unless required materials are present.
    """
    try:
        # Find source folder
        src_path = find_video_in_temp(temp_folder, video_name)
        if not src_path:
            if "/" in story_name:
                config_name, vid_name = story_name.split("/", 1)
                src_path = os.path.join(temp_folder, config_name, vid_name)
            if not src_path or not os.path.exists(src_path):
                with print_lock:
                    print(f"⚠️ Temp folder not found for: {video_name}")
                return False

        # STRICT VALIDATION: count actual materials
        audio_count, image_count = count_materials(src_path)

        if require_audio and audio_count == 0:
            with print_lock:
                print(f"❌ BLOCKED export for {video_name}: NO AUDIO (.mp3)")
            log_slim(f"❌ BLOCKED: {video_name} - no audio")
            return False

        if image_count == 0:
            with print_lock:
                print(f"❌ BLOCKED export for {video_name}: NO IMAGES")
            log_slim(f"❌ BLOCKED: {video_name} - no images")
            return False

        if expected_images > 0 and image_count < expected_images:
            with print_lock:
                print(f"❌ BLOCKED export for {video_name}: only {image_count}/{expected_images} images")
            log_slim(f"❌ BLOCKED: {video_name} - {image_count}/{expected_images} images")
            return False

        # Destination restores config/video nesting
        if "/" in story_name:
            config_name, vid_name = story_name.split("/", 1)
            dest_config = os.path.join(mats_output_path, config_name)
            os.makedirs(dest_config, exist_ok=True)
            dest_path = os.path.join(dest_config, vid_name)
        else:
            dest_path = os.path.join(mats_output_path, video_name)

        os.makedirs(mats_output_path, exist_ok=True)

        # Skip if already exported (prevents duplicates on crash-restart)
        if os.path.exists(dest_path):
            with print_lock:
                print(f"⏭️ Already exported, skipping: {story_name}")
            log_slim(f"⏭️ Skipped (already exported): {story_name}")
            return True

        shutil.move(src_path, dest_path)

        with print_lock:
            print(f"✅ Exported to mats output: {story_name} (audio: {audio_count}, images: {image_count})")
        log(f"✅ Exported to mats output: {story_name} (audio: {audio_count}, images: {image_count})", file_only=True)
        log_slim(f"✅ Exported: {story_name} ({image_count} images)")

        return True
    except Exception as e:
        with print_lock:
            print(f"⚠️ Error moving to mats output: {e}")
        log_slim(f"⚠️ Export failed: {story_name} - {e}")
        return False


def remove_from_processing(story_name, batch_input_folder):
    """Remove a successfully exported video from the processing folder."""
    try:
        if "/" in story_name:
            config_name, vid_name = story_name.split("/", 1)
            video_path = os.path.join(batch_input_folder, config_name, vid_name)
        else:
            video_path = os.path.join(batch_input_folder, story_name)
        if os.path.exists(video_path):
            shutil.rmtree(video_path)
    except Exception:
        pass


# ==============================================
# FARM A SINGLE BATCH
# ==============================================

def farm_batch(batch_input_folder, config, tts_input_num, img_input_num, niche_config, mats_output_path):
    """
    Farm a single batch of videos from batch_input_folder.
    Returns (exported_count, total_count, incomplete_list).
    """
    skip_voiceover = config.get("skip_voiceover", False)

    voiceover_dir = os.path.dirname(config["voiceover_path"])
    voiceover_input = os.path.join(voiceover_dir, "inputFiles")
    voiceover_output = os.path.join(voiceover_dir, "audioOutput")

    imagegen_dir = os.path.dirname(config["imagegen_path"])
    imagegen_input = os.path.join(imagegen_dir, "inputFiles")
    imagegen_output = os.path.join(imagegen_dir, "outputFiles")

    temp_folder = os.path.join(BASE_DIR, "temp_mats_staging")

    # CLEANUP PHASE
    print("\n" + "="*60)
    print("🧹 CLEANUP PHASE: Clearing component folders...")
    print("="*60)

    if not skip_voiceover:
        clear_folder(voiceover_input, "Voiceover Input")
        clear_folder(voiceover_output, "Voiceover Output")
    else:
        print("⏭️ Skipping voiceover (disabled in config)")
    clear_folder(imagegen_input, "Image Gen Input")
    clear_folder(imagegen_output, "Image Gen Output")
    clear_folder(temp_folder, "Temp Staging")

    print("✅ Cleanup complete!\n")

    # Enumerate all videos in this batch
    all_videos = enumerate_all_videos(batch_input_folder)

    if not all_videos:
        print("❌ No videos found in batch folder!")
        return 0, 0, []

    print(f"\n📋 Found {len(all_videos)} videos in this batch")

    # Create temp folder
    os.makedirs(temp_folder, exist_ok=True)
    os.makedirs(mats_output_path, exist_ok=True)

    # Tracking
    videos_exported = set()
    all_video_names = [get_video_name_from_story(v) for v in all_videos]
    story_name_map = {get_video_name_from_story(v): v for v in all_videos}

    vo_moved_set = set()
    img_moved_set = set()
    expected_image_counts = {}

    # When skipping voiceover, mark all videos as VO-complete
    if skip_voiceover:
        vo_moved_set.update(all_video_names)

    # Get project names for manifest paths
    if niche_config and niche_config.get("tts_config"):
        vo_project_name = niche_config.get("tts_config")
    else:
        vo_project_name = get_project_name(voiceover_dir, "voiceover_project", "voiceover_default_input", config)

    if niche_config and niche_config.get("imagegen_config"):
        img_project_name = niche_config.get("imagegen_config")
    else:
        img_project_name = get_project_name(imagegen_dir, "imagegen_project", "imagegen_default_input", config)

    print(f"📁 VO Project: {vo_project_name}")
    print(f"📁 IMG Project: {img_project_name}")

    # Manifest paths
    vo_manifest_path = os.path.join(voiceover_dir, "configs", vo_project_name, "manifest.json") if vo_project_name else None
    img_manifest_path = os.path.join(imagegen_dir, "configs", img_project_name, "manifest.json") if img_project_name else None

    print(f"📄 VO Manifest: {vo_manifest_path}")
    print(f"📄 IMG Manifest: {img_manifest_path}")

    # Minimum expected images from config (fallback when manifest count is 0)
    min_expected_images = get_expected_image_count_from_config(imagegen_dir, img_project_name)
    if min_expected_images > 0:
        print(f"📊 Min expected images per video (from config): {min_expected_images}")

    # Threading
    worker_errors = []
    error_lock = threading.Lock()
    print_lock = threading.Lock()

    vo_complete = threading.Event()
    img_complete = threading.Event()
    manifest_poller_stop = threading.Event()

    print(f"\n{'='*60}")
    print("📤 COPYING BATCH VIDEOS TO WORKERS...")
    print(f"{'='*60}\n")

    if not skip_voiceover:
        print("📤 Copying to Voiceover input...")
        copy_story_folders(batch_input_folder, voiceover_input)

    print("📤 Copying to Image Gen input...")
    copy_story_folders(batch_input_folder, imagegen_input)

    # ==============================================
    # WORKER THREADS
    # ==============================================

    def voiceover_worker():
        try:
            script_path = config.get("voiceover_path")
            if not script_path or not os.path.isfile(script_path):
                with error_lock:
                    worker_errors.append(("Voiceover", f"Script not found: {script_path}"))
                return

            with print_lock:
                print(f"\n🎙️ Starting Voiceover worker...")
            log_slim(f"[VO] Worker started")

            inputs = tts_input_num.split(",")
            first_input = inputs[0].strip() if len(inputs) > 0 else "1"
            second_input = inputs[1].strip() if len(inputs) > 1 else ""

            process = run_worker_subprocess(
                "Voiceover",
                script_path,
                voiceover_dir,
                first_input=first_input,
                second_input=second_input
            )

            stream_process_output(process, "VO", print_lock)
            process.wait()

            if process.returncode != 0:
                with error_lock:
                    worker_errors.append(("Voiceover", f"Process exited with code {process.returncode}"))
                log_slim(f"[VO] ❌ Worker failed (exit code {process.returncode})")
            else:
                with print_lock:
                    print(f"✅ Voiceover worker completed.")
                log_slim(f"[VO] ✅ Worker completed")
                remove_copied_folders(voiceover_input, all_videos)

        except Exception as e:
            with error_lock:
                worker_errors.append(("Voiceover", str(e)))
            log_slim(f"[VO] ❌ Worker error: {e}")
        finally:
            vo_complete.set()

    def imagegen_worker():
        try:
            script_path = config.get("imagegen_path")
            if not script_path or not os.path.isfile(script_path):
                with error_lock:
                    worker_errors.append(("Image Gen", f"Script not found: {script_path}"))
                return

            with print_lock:
                print(f"\n🖼️ Starting Image Gen worker...")
            log_slim(f"[IMG] Worker started")

            inputs = img_input_num.split(",")
            first_input = inputs[0].strip() if len(inputs) > 0 else "1"
            second_input = inputs[1].strip() if len(inputs) > 1 else None

            process = run_worker_subprocess(
                "Image Gen",
                script_path,
                imagegen_dir,
                first_input=first_input,
                second_input=second_input
            )

            stream_process_output(process, "IMG", print_lock)
            process.wait()

            if process.returncode != 0:
                with error_lock:
                    worker_errors.append(("Image Gen", f"Process exited with code {process.returncode}"))
                log_slim(f"[IMG] ❌ Worker failed (exit code {process.returncode})")
            else:
                with print_lock:
                    print(f"✅ Image Gen worker completed.")
                log_slim(f"[IMG] ✅ Worker completed")
                remove_copied_folders(imagegen_input, all_videos)

        except Exception as e:
            with error_lock:
                worker_errors.append(("Image Gen", str(e)))
            log_slim(f"[IMG] ❌ Worker error: {e}")
        finally:
            img_complete.set()

    def _scan_vo_dir(scan_dir):
        """Scan a directory for .mp3 files and move to temp."""
        for item in os.listdir(scan_dir):
            item_path = os.path.join(scan_dir, item)
            # Recurse into config subfolders
            if os.path.isdir(item_path):
                _scan_vo_dir(item_path)
                continue
            if not item.lower().endswith(".mp3"):
                continue
            if "_chunk" in item:
                continue
            video_name = item[:-4]
            if video_name in all_video_names and video_name not in vo_moved_set:
                if move_vo_output_to_temp(video_name, voiceover_output, temp_folder, story_name_map, print_lock):
                    vo_moved_set.add(video_name)
            elif video_name not in vo_moved_set:
                for known_name in all_video_names:
                    if known_name not in vo_moved_set and known_name in video_name:
                        with print_lock:
                            print(f"🔍 VO fuzzy match: '{video_name}' -> '{known_name}'")
                        old_path = os.path.join(scan_dir, item)
                        new_path = os.path.join(scan_dir, known_name + ".mp3")
                        if old_path != new_path:
                            if os.path.exists(new_path):
                                os.remove(new_path)
                            os.rename(old_path, new_path)
                        if move_vo_output_to_temp(known_name, voiceover_output, temp_folder, story_name_map, print_lock):
                            vo_moved_set.add(known_name)
                        break

    def scan_vo_output_direct():
        if not os.path.exists(voiceover_output):
            return
        try:
            _scan_vo_dir(voiceover_output)
        except Exception as e:
            with print_lock:
                print(f"⚠️ Error in VO direct scan: {e}")

    def _scan_img_dir(scan_dir):
        """Scan a directory for image folders and move to temp."""
        img_configs_dir = os.path.join(imagegen_dir, "configs")
        active_manifest = find_latest_manifest(img_configs_dir)

        for item in os.listdir(scan_dir):
            item_path = os.path.join(scan_dir, item)
            if not os.path.isdir(item_path):
                continue

            # Check if this folder has images (video folder) or subfolders (config folder)
            has_images = any(f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
                           for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f)))

            if not has_images:
                # Could be a config folder — recurse
                _scan_img_dir(item_path)
                continue

            target_name = item
            if item not in all_video_names:
                matched = False
                for known_name in all_video_names:
                    if known_name not in img_moved_set and known_name in item:
                        with print_lock:
                            print(f"🔍 IMG fuzzy match: '{item}' -> '{known_name}'")
                        old_path = item_path
                        new_path = os.path.join(scan_dir, known_name)
                        if old_path != new_path:
                            if os.path.exists(new_path):
                                shutil.rmtree(new_path)
                            os.rename(old_path, new_path)
                            item_path = new_path
                        target_name = known_name
                        matched = True
                        break
                if not matched:
                    continue

            if target_name in img_moved_set:
                continue

            actual_images = sum(1 for f in os.listdir(item_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')))
            if actual_images == 0:
                continue

            expected = get_expected_image_count(target_name, active_manifest) or min_expected_images

            if expected > 0 and actual_images < expected:
                continue

            if move_img_output_to_temp(target_name, imagegen_output, temp_folder, story_name_map, print_lock):
                img_moved_set.add(target_name)
                expected_image_counts[target_name] = expected if expected > 0 else actual_images

    def scan_img_output_direct():
        if not os.path.exists(imagegen_output):
            return
        try:
            _scan_img_dir(imagegen_output)
        except Exception as e:
            with print_lock:
                print(f"⚠️ Error in IMG direct scan: {e}")

    def manifest_poller():
        MANIFEST_POLL_INTERVAL = 3
        vo_configs_dir = os.path.join(voiceover_dir, "configs")
        img_configs_dir = os.path.join(imagegen_dir, "configs")
        logged_vo_manifest = None
        logged_img_manifest = None

        while not manifest_poller_stop.is_set():
            active_vo_manifest = find_latest_manifest(vo_configs_dir)
            if active_vo_manifest:
                if active_vo_manifest != logged_vo_manifest:
                    with print_lock:
                        print(f"📄 VO manifest found: {active_vo_manifest}")
                    logged_vo_manifest = active_vo_manifest
                poll_vo_manifest(
                    active_vo_manifest, voiceover_output, temp_folder,
                    story_name_map, vo_moved_set, all_video_names, print_lock
                )
            scan_vo_output_direct()

            active_img_manifest = find_latest_manifest(img_configs_dir)
            if active_img_manifest:
                if active_img_manifest != logged_img_manifest:
                    with print_lock:
                        print(f"📄 IMG manifest found: {active_img_manifest}")
                    logged_img_manifest = active_img_manifest
                poll_img_manifest(
                    active_img_manifest, imagegen_output, temp_folder,
                    story_name_map, img_moved_set, all_video_names, print_lock,
                    expected_image_counts
                )
            scan_img_output_direct()

            time.sleep(MANIFEST_POLL_INTERVAL)

        # Final poll after workers complete
        active_vo_manifest = find_latest_manifest(vo_configs_dir)
        if active_vo_manifest:
            poll_vo_manifest(
                active_vo_manifest, voiceover_output, temp_folder,
                story_name_map, vo_moved_set, all_video_names, print_lock
            )
        scan_vo_output_direct()

        active_img_manifest = find_latest_manifest(img_configs_dir)
        if active_img_manifest:
            poll_img_manifest(
                active_img_manifest, imagegen_output, temp_folder,
                story_name_map, img_moved_set, all_video_names, print_lock
            )
        scan_img_output_direct()

    # Start worker threads
    print(f"\n{'='*60}")
    print("🚀 STARTING WORKERS...")
    print(f"{'='*60}\n")

    img_thread = threading.Thread(target=imagegen_worker, daemon=True)
    manifest_thread = threading.Thread(target=manifest_poller, daemon=True)

    if not skip_voiceover:
        vo_thread = threading.Thread(target=voiceover_worker, daemon=True)
        vo_thread.start()
    else:
        vo_complete.set()  # Mark VO as done immediately
        vo_thread = None

    img_thread.start()
    manifest_thread.start()

    # ==============================================
    # MAIN POLLING LOOP - check for ready videos and export
    # ==============================================
    POLL_INTERVAL = 5

    print(f"\n{'='*60}")
    print("🔍 POLLING FOR READY VIDEOS...")
    print(f"{'='*60}\n")

    while True:
        newly_ready = []
        for video_name in all_video_names:
            if video_name not in videos_exported:
                expected = max(expected_image_counts.get(video_name, 0), min_expected_images)
                if check_video_ready(temp_folder, video_name, expected_images=expected, require_audio=not skip_voiceover):
                    newly_ready.append(video_name)

        for video_name in newly_ready:
            story_name = story_name_map.get(video_name, video_name)
            expected = max(expected_image_counts.get(video_name, 0), min_expected_images)
            if move_to_mats_output(video_name, story_name, temp_folder, mats_output_path, print_lock,
                                   expected_images=expected, require_audio=not skip_voiceover):
                videos_exported.add(video_name)
                remove_from_processing(story_name, batch_input_folder)

        workers_done = vo_complete.is_set() and img_complete.is_set()

        if workers_done:
            remaining = [v for v in all_video_names if v not in videos_exported]
            if remaining:
                with print_lock:
                    print(f"⏳ Workers done but {len(remaining)} videos not ready yet. Waiting...")
                    print(f"   VO moved: {len(vo_moved_set)}/{len(all_video_names)}, IMG moved: {len(img_moved_set)}/{len(all_video_names)}")

                for _wait_i in range(6):
                    time.sleep(5)
                    for video_name in list(remaining):
                        if video_name not in videos_exported:
                            expected = max(expected_image_counts.get(video_name, 0), min_expected_images)
                            if check_video_ready(temp_folder, video_name, expected_images=expected, require_audio=not skip_voiceover):
                                story_name = story_name_map.get(video_name, video_name)
                                if move_to_mats_output(video_name, story_name, temp_folder, mats_output_path, print_lock,
                                                       expected_images=expected, require_audio=not skip_voiceover):
                                    videos_exported.add(video_name)
                                    remove_from_processing(story_name, batch_input_folder)
                    remaining = [v for v in all_video_names if v not in videos_exported]
                    if not remaining:
                        break

            # Final scan
            for video_name in all_video_names:
                if video_name not in videos_exported:
                    expected = max(expected_image_counts.get(video_name, 0), min_expected_images)
                    if check_video_ready(temp_folder, video_name, expected_images=expected, require_audio=not skip_voiceover):
                        story_name = story_name_map.get(video_name, video_name)
                        if move_to_mats_output(video_name, story_name, temp_folder, mats_output_path, print_lock,
                                               expected_images=expected, require_audio=not skip_voiceover):
                            videos_exported.add(video_name)
                            remove_from_processing(story_name, batch_input_folder)

            # Report what's missing for incomplete videos
            still_incomplete = [v for v in all_video_names if v not in videos_exported]
            if still_incomplete:
                print(f"\n{'='*60}")
                print(f"🔍 INCOMPLETE VIDEO DETAILS:")
                print(f"{'='*60}")
                for video_name in still_incomplete:
                    video_path = find_video_in_temp(temp_folder, video_name)
                    audio_count, image_count = count_materials(video_path)
                    expected = expected_image_counts.get(video_name, "?")
                    missing = []
                    if audio_count == 0:
                        missing.append("AUDIO")
                    if image_count == 0:
                        missing.append("ALL IMAGES")
                    elif expected != "?" and image_count < expected:
                        missing.append(f"IMAGES ({image_count}/{expected})")
                    print(f"  ❌ {video_name}: audio={audio_count}, images={image_count}/{expected} - Missing: {', '.join(missing) if missing else 'unknown'}")
                    log_slim(f"❌ {video_name}: audio={audio_count}, images={image_count}/{expected}")
                print(f"{'='*60}\n")

            break

        time.sleep(POLL_INTERVAL)

    # Stop manifest poller
    manifest_poller_stop.set()

    # Wait for threads
    if vo_thread:
        vo_thread.join(timeout=1)
    img_thread.join(timeout=1)
    manifest_thread.join(timeout=1)

    # Check for errors
    if worker_errors:
        print(f"\n{'='*60}")
        print("❌ BATCH FARMING COMPLETED WITH ERRORS:")
        print(f"{'='*60}")
        for name, error in worker_errors:
            print(f"  - {name}: {error}")
            log_slim(f"❌ {name}: {error}")

    # Clean up temp staging
    if os.path.exists(temp_folder):
        shutil.rmtree(temp_folder)
        print("🧹 Cleaned up temp staging folder.")

    incomplete = [v for v in all_video_names if v not in videos_exported]
    return len(videos_exported), len(all_videos), incomplete


# ==============================================
# MAIN — BATCH LOOP
# ==============================================

if __name__ == "__main__":
    # Paths
    input_files_dir = os.path.join(BASE_DIR, "input_files")
    processing_dir = os.path.join(BASE_DIR, "processing")
    mats_output_path = config["mats_output_path"]
    batch_size = config.get("batch_size", 20)

    voiceover_dir = os.path.dirname(config["voiceover_path"])
    imagegen_dir = os.path.dirname(config["imagegen_path"])

    # Create directories
    os.makedirs(input_files_dir, exist_ok=True)
    os.makedirs(processing_dir, exist_ok=True)

    # ==============================================
    # NICHE DETECTION
    # ==============================================
    print("\n" + "="*60)
    print("🔍 NICHE DETECTION PHASE")
    print("="*60)

    niche_name, niche_config = detect_niche_from_input(input_files_dir)

    if niche_config:
        print(f"✅ Detected niche: {niche_config.get('niche_name', niche_name)}")

        tts_configs_dir = os.path.join(voiceover_dir, "configs")
        img_configs_dir = os.path.join(imagegen_dir, "configs")

        tts_config_name = niche_config.get("tts_config")
        img_config_name = niche_config.get("imagegen_config")

        if tts_config_name:
            tts_input_num = get_config_number_by_name(tts_configs_dir, tts_config_name)
            print(f"   TTS Config: {tts_config_name} (#{tts_input_num})")
        else:
            tts_input_num = config.get("voiceover_default_input", "1")
            print(f"   TTS Config: Using default (#{tts_input_num})")

        if img_config_name:
            img_input_num = get_config_number_by_name(img_configs_dir, img_config_name) + ",1"
            print(f"   ImageGen Config: {img_config_name} (#{img_input_num})")
        else:
            img_input_num = config.get("imagegen_default_input", "1")
            print(f"   ImageGen Config: Using default (#{img_input_num})")
    else:
        print(f"ℹ️ No niche config found, using defaults from config.json")
        tts_input_num = config.get("voiceover_default_input", "1")
        img_input_num = config.get("imagegen_default_input", "1")
        print(f"   TTS Config: #{tts_input_num}")
        print(f"   ImageGen Config: #{img_input_num}")

    print("="*60 + "\n")

    # ==============================================
    # PRE-FLIGHT VALIDATION
    # ==============================================
    print("="*60)
    print("🔍 PRE-FLIGHT VALIDATION")
    print("="*60)

    preflight_errors = []
    skip_voiceover = config.get("skip_voiceover", False)

    if not skip_voiceover:
        vo_path = config.get("voiceover_path")
        if not vo_path or not os.path.isfile(vo_path):
            preflight_errors.append(f"Voiceover script not found: {vo_path}")

    img_path = config.get("imagegen_path")
    if not img_path or not os.path.isfile(img_path):
        preflight_errors.append(f"Image Gen script not found: {img_path}")

    if not mats_output_path:
        preflight_errors.append("mats_output_path not set in config.json")

    if preflight_errors:
        print("❌ PRE-FLIGHT FAILED:")
        for err in preflight_errors:
            print(f"  - {err}")
        print("="*60 + "\n")
        sys.exit(1)
    else:
        print("✅ All paths validated")
        print(f"📁 Mats output: {mats_output_path}")
        print(f"📦 Batch size: {batch_size}")
        print("="*60 + "\n")

    # ==============================================
    # BATCH LOOP (24/7 — resumes processing/, then input_files/, waits for more)
    # ==============================================

    WAIT_POLL_INTERVAL = 30  # seconds between checks when waiting for new videos

    total_exported = 0
    total_incomplete = []
    batch_num = 0

    while True:
        # Step 1: Check if processing/ has leftover videos from a previous crash
        processing_videos = enumerate_all_videos(processing_dir)
        if processing_videos:
            batch_num += 1
            print(f"\n{'='*60}")
            print(f"📦 BATCH {batch_num}: RESUMING {len(processing_videos)} videos from processing/")
            print(f"{'='*60}\n")
            log_slim(f"Batch {batch_num}: Resuming {len(processing_videos)} videos from processing/")

            exported, total, incomplete = farm_batch(
                processing_dir, config, tts_input_num, img_input_num, niche_config, mats_output_path
            )

            total_exported += exported
            total_incomplete.extend(incomplete)

            clear_folder(processing_dir, "Processing")

            print(f"\n📊 Batch {batch_num} result: {exported}/{total} exported")
            if incomplete:
                print(f"   ⚠️ Incomplete: {incomplete}")
                log_slim(f"Batch {batch_num}: {exported}/{total} exported. Incomplete: {', '.join(incomplete)}")
            else:
                log_slim(f"Batch {batch_num}: {exported}/{total} exported - ALL COMPLETE")
            continue  # Check for more in processing/ or input_files/

        # Step 2: Check input_files/ for new videos
        all_remaining = enumerate_all_videos(input_files_dir)

        if not all_remaining:
            if batch_num == 0:
                print(f"⏳ No videos found yet. Waiting for videos in input_files/...")
                log_slim(f"Waiting for videos in input_files/...")
            else:
                print(f"\n{'='*60}")
                print(f"✅ All batches complete: {total_exported} exported, {len(total_incomplete)} incomplete")
                print(f"{'='*60}")
                print(f"⏳ Waiting for new videos in input_files/...")
                log_slim(f"All caught up ({total_exported} exported). Waiting for new videos...")
            time.sleep(WAIT_POLL_INTERVAL)
            continue

        batch_num += 1
        batch_videos = all_remaining[:batch_size]

        print(f"\n{'='*60}")
        print(f"📦 BATCH {batch_num}: Processing {len(batch_videos)}/{len(all_remaining)} remaining videos")
        print(f"{'='*60}\n")

        # Clear processing/ and move batch in
        clear_folder(processing_dir, "Processing")

        for story_name in batch_videos:
            if "/" in story_name:
                config_name, video_name = story_name.split("/", 1)
                src = os.path.join(input_files_dir, config_name, video_name)
                dest_config = os.path.join(processing_dir, config_name)
                os.makedirs(dest_config, exist_ok=True)
                dest = os.path.join(dest_config, video_name)
            else:
                src = os.path.join(input_files_dir, story_name)
                dest = os.path.join(processing_dir, story_name)

            if os.path.exists(src):
                shutil.move(src, dest)
                print(f"  📂 Moved to processing: {story_name}")

        # Clean up empty config folders left in input_files/
        if os.path.isdir(input_files_dir):
            for item in os.listdir(input_files_dir):
                item_path = os.path.join(input_files_dir, item)
                if os.path.isdir(item_path) and not os.listdir(item_path):
                    os.rmdir(item_path)

        # Farm the batch
        exported, total, incomplete = farm_batch(
            processing_dir, config, tts_input_num, img_input_num, niche_config, mats_output_path
        )

        total_exported += exported
        total_incomplete.extend(incomplete)

        # Clean up processing/
        clear_folder(processing_dir, "Processing")

        print(f"\n📊 Batch {batch_num} result: {exported}/{total} exported")
        if incomplete:
            print(f"   ⚠️ Incomplete: {incomplete}")
            log_slim(f"Batch {batch_num}: {exported}/{total} exported. Incomplete: {', '.join(incomplete)}")
        else:
            log_slim(f"Batch {batch_num}: {exported}/{total} exported - ALL COMPLETE")