import os
import json
import time
import shutil
import subprocess
import random
import re
from pathlib import Path
from datetime import datetime
import glob

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_FILE = "render_watcher_log.txt"

def log(message, pc_name, section=False, file_only=False):
    """Print timestamped log message to both console and log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    if section:
        log_line = f"[{timestamp}] [{pc_name}] {'━' * 45}"
    else:
        log_line = f"[{timestamp}] [{pc_name}] {message}"

    if not file_only:
        print(log_line)

    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + "\n")
            f.flush()
    except Exception as e:
        print(f"WARNING: Failed to write to log file: {e}")

SLIM_LOG_FILE = "render_watcher_slim.txt"

def log_slim(message, pc_name):
    """Write a concise, critical-only log line."""
    if not message or not message.strip():
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] [{pc_name}] {message}"
    try:
        with open(SLIM_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass

# ============================================================================
# CONFIGURATION AND UTILITY FUNCTIONS
# ============================================================================

def load_config(config_path="render_watcher_config.json"):
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        print(f"Error: Config file '{config_path}' not found!")
        print("Creating default config file...")

        default_config = {
            "my_pc_name": "PC1",
            "scan_interval_seconds": 45,
            "approval_wait_seconds": 60,
            "post_render_delay_seconds": 180,
            "random_jitter_min": 0.5,
            "random_jitter_max": 2.0,
            "max_retries": 5,
            "mats_output_path": "C:\\Users\\Shadow\\Desktop\\Compiled Binaries\\Shared Folder\\! Mats Output",
            "synced_video_output_path": "C:\\Users\\Shadow\\Desktop\\Compiled Binaries\\Shared Folder\\! Video Output",
            "videogen_script": "C:\\Users\\Shadow\\Desktop\\Compiled Binaries\\Mats Farmer Pipeline\\Programs\\Video_Gen\\video_render_gen.py"
        }

        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=2)

        print(f"Default config created at '{config_path}'. Please edit it and restart.")
        exit(1)

    with open(config_path, 'r') as f:
        return json.load(f)


def get_videogen_concurrency(videogen_script_path):
    """Load videogen's config.json and read no_of_concurrent_generations."""
    videogen_dir = os.path.dirname(videogen_script_path)
    videogen_config_path = os.path.join(videogen_dir, "config.json")

    try:
        with open(videogen_config_path, 'r') as f:
            videogen_config = json.load(f)
        return videogen_config.get("no_of_concurrent_generations", 3)
    except FileNotFoundError:
        print(f"⚠️ Videogen config.json not found, defaulting to 3")
        return 3
    except json.JSONDecodeError as e:
        print(f"⚠️ Error parsing videogen config.json: {e}, defaulting to 3")
        return 3


def get_retry_count(folder_name):
    """Extract retry count from folder name."""
    match = re.search(r'\[R(\d+)\]', folder_name)
    if match:
        return int(match.group(1))
    return 0


def strip_retry_tag(folder_name):
    """Remove [RN] tag from folder name."""
    return re.sub(r'\s*\[R\d+\]', '', folder_name)


def random_jitter(min_sec, max_sec):
    """Return random jitter in seconds."""
    return random.uniform(min_sec, max_sec)


def get_video_short_name(video_path):
    """Extract short name from video path for display."""
    parts = video_path.split('/')
    if len(parts) >= 2:
        config_name = parts[0]
        video_name = parts[1]
        tokens = video_name.split()
        if len(tokens) >= 2:
            video_num = tokens[1]
            identifier = ""
            for token in reversed(tokens[2:]):
                if token not in ['-', 'Script', 'For'] and not re.match(r'\d{1,2}-\d{1,2}', token):
                    identifier = token
                    break
            video_short = f"Video {video_num} {identifier}".strip()
            return (config_name, video_short)
    return (video_path, "")


# ============================================================================
# VIDEO DISCOVERY & CLAIMING
# ============================================================================

def get_available_videos(mats_output_path, max_retries=5):
    """Get list of video folders that are available (not claimed, not rendered)."""
    if not os.path.exists(mats_output_path):
        return []

    config_folders = []
    for config_folder in os.listdir(mats_output_path):
        config_path = os.path.join(mats_output_path, config_folder)
        if not os.path.isdir(config_path):
            continue
        if config_folder.startswith("request_") or config_folder.startswith("_"):
            continue
        config_folders.append(config_folder)

    config_folders.sort()

    all_available = []

    for config_folder in config_folders:
        config_path = os.path.join(mats_output_path, config_folder)
        available_in_config = []

        for video_folder in os.listdir(config_path):
            video_path = os.path.join(config_path, video_folder)

            if not os.path.isdir(video_path):
                continue

            if not video_folder.startswith("Video"):
                continue

            # Skip if already claimed
            if " - PC" in video_folder:
                continue

            # Skip if already rendered
            if " - Rendered" in video_folder:
                continue

            # Skip if retry count has reached max
            if get_retry_count(video_folder) >= max_retries:
                continue

            # Verify the folder actually has materials (audio + images)
            has_audio = any(f.lower().endswith(".mp3") for f in os.listdir(video_path) if os.path.isfile(os.path.join(video_path, f)))
            has_images = any(f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for f in os.listdir(video_path) if os.path.isfile(os.path.join(video_path, f)))

            if not has_audio or not has_images:
                continue

            available_in_config.append(f"{config_folder}/{video_folder}")

        def get_video_number(path):
            try:
                video_part = path.split('/')[1]
                num_str = video_part.split()[1]
                return int(num_str)
            except:
                return 0

        available_in_config.sort(key=get_video_number)
        all_available.extend(available_in_config)

    return all_available


def cleanup_stale_requests(mats_output_path, max_age_seconds=300):
    """Delete request files older than max_age_seconds."""
    cleaned = 0
    for filepath in glob.glob(os.path.join(mats_output_path, "request_*.txt")):
        try:
            age = time.time() - os.path.getmtime(filepath)
            if age > max_age_seconds:
                os.remove(filepath)
                cleaned += 1
        except:
            pass
    return cleaned


def cleanup_stale_claims(mats_output_path, synced_video_output_path, pc_name):
    """On startup, unclaim any videos still claimed by this PC from a previous crash."""
    unclaimed_count = 0
    skipped_count = 0

    if not os.path.exists(mats_output_path):
        return unclaimed_count, skipped_count

    pc_suffix = f" - {pc_name}"

    for config_folder in os.listdir(mats_output_path):
        config_path = os.path.join(mats_output_path, config_folder)

        if not os.path.isdir(config_path):
            continue

        if config_folder.startswith("request_") or config_folder.startswith("_"):
            continue

        for video_folder in os.listdir(config_path):
            video_path = os.path.join(config_path, video_folder)

            if not os.path.isdir(video_path):
                continue

            if not video_folder.endswith(pc_suffix):
                continue

            if " - Rendered" in video_folder:
                skipped_count += 1
                continue

            # Check if .mp4 exists in synced output
            mp4_exists = False
            if synced_video_output_path:
                mp4_path = os.path.join(synced_video_output_path, config_folder, f"{video_folder}.mp4")
                mp4_exists = os.path.exists(mp4_path)

            if mp4_exists:
                skipped_count += 1
                continue

            # Stale claim - unclaim without retry increment
            base_name = video_folder[:-len(pc_suffix)]
            new_path = os.path.join(config_path, base_name)

            if os.path.exists(new_path):
                continue

            try:
                os.rename(video_path, new_path)
                unclaimed_count += 1
            except Exception:
                pass

    return unclaimed_count, skipped_count


def create_request_file(video_folder, pc_name, mats_output_path):
    """Create a request file for claiming a video."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]

    config_name, video_name = video_folder.split('/', 1)
    clean_config = config_name.replace(" ", "_").replace("/", "_")
    clean_video = video_name.replace(" ", "_").replace("/", "_")

    request_filename = f"request_{clean_config}__{clean_video}_{pc_name}_{timestamp}.txt"
    request_path = os.path.join(mats_output_path, request_filename)

    Path(request_path).touch()
    return request_filename


def parse_request_filename(filename):
    """Parse request filename to extract video path, PC name, and timestamp."""
    try:
        parts = filename.replace(".txt", "").split("__", 1)

        if len(parts) < 2:
            return None

        config_part = parts[0].replace("request_", "")
        config_name = config_part.replace("_", " ")

        remaining = parts[1].split("_")
        pc_name = remaining[-2]
        timestamp_str = remaining[-1]

        video_name_parts = remaining[:-2]
        video_name = " ".join(video_name_parts)

        full_video_path = f"{config_name}/{video_name}"

        return {
            "video": full_video_path,
            "pc": pc_name,
            "timestamp": timestamp_str,
            "filename": filename
        }
    except Exception:
        return None


def get_all_requests(mats_output_path):
    """Read all request files."""
    request_files = glob.glob(os.path.join(mats_output_path, "request_*.txt"))

    requests = []
    for filepath in request_files:
        filename = os.path.basename(filepath)
        parsed = parse_request_filename(filename)
        if parsed:
            requests.append(parsed)

    return requests


def run_approval_algorithm(requests, pc_name):
    """Deterministic approval: earliest timestamp wins."""
    by_video = {}
    for req in requests:
        video = req["video"]
        if video not in by_video:
            by_video[video] = []
        by_video[video].append(req)

    approvals = {}
    for video, reqs in by_video.items():
        reqs.sort(key=lambda r: r["timestamp"])
        winner = reqs[0]
        competitors = [r["pc"] for r in reqs]
        approvals[video] = (winner["pc"], competitors)

    return approvals


def delete_my_requests(video_folder, pc_name, mats_output_path):
    """Delete all my request files for a specific video."""
    config_name, video_name = video_folder.split('/', 1)
    clean_config = config_name.replace(" ", "_").replace("/", "_")
    clean_video = video_name.replace(" ", "_").replace("/", "_")

    pattern = os.path.join(mats_output_path, f"request_{clean_config}__{clean_video}_{pc_name}_*.txt")

    for filepath in glob.glob(pattern):
        try:
            os.remove(filepath)
        except Exception:
            pass


def rename_folder(old_name, pc_name, mats_output_path):
    """Rename folder to claim it with PC suffix."""
    config_name, video_name = old_name.split('/', 1)
    new_video_name = f"{video_name} - {pc_name}"

    old_path = os.path.join(mats_output_path, config_name, video_name)
    new_path = os.path.join(mats_output_path, config_name, new_video_name)

    if not os.path.exists(old_path):
        return False, None

    if os.path.exists(new_path):
        return False, None

    try:
        os.rename(old_path, new_path)
        return True, f"{config_name}/{new_video_name}"
    except Exception:
        return False, None


def unclaim_video(claimed_name, mats_output_path, pc_name):
    """Unclaim a video by removing PC suffix and incrementing retry tag."""
    config_name, video_name = claimed_name.split('/', 1)

    pc_suffix = f" - {pc_name}"
    if video_name.endswith(pc_suffix):
        base_name = video_name[:-len(pc_suffix)]
    else:
        match = re.search(r' - PC\d+$', video_name)
        if match:
            base_name = video_name[:match.start()]
        else:
            base_name = video_name

    current_retries = get_retry_count(base_name)
    new_retries = current_retries + 1

    clean_name = strip_retry_tag(base_name)
    new_name = f"{clean_name} [R{new_retries}]"

    old_path = os.path.join(mats_output_path, config_name, video_name)
    new_path = os.path.join(mats_output_path, config_name, new_name)

    if not os.path.exists(old_path):
        return False

    if os.path.exists(new_path):
        return False

    try:
        os.rename(old_path, new_path)
        return True
    except Exception:
        return False


# ============================================================================
# RENDERING
# ============================================================================

def clear_videogen_folders(videogen_script_path, pc_name):
    """Clear Video_Gen input and output folders, and temp .mp4 files in root."""
    videogen_dir = os.path.dirname(videogen_script_path)
    input_dir = os.path.join(videogen_dir, "input_files")
    output_dir = os.path.join(videogen_dir, "output_files")

    for folder_path, name in [(input_dir, "VideoGen Input"), (output_dir, "VideoGen Output")]:
        if os.path.exists(folder_path):
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except Exception as e:
                    log(f"⚠️ Failed to clear {item_path}: {e}", pc_name)
            log(f"🧹 Cleared: {name}", pc_name)

    # Clean up temp render artifacts in Video_Gen root (e.g. _24fps_, _with_effects_, _without_effects_)
    temp_count = 0
    for item in os.listdir(videogen_dir):
        if item.endswith(".mp4") and any(tag in item for tag in ["_24fps_", "_with_effects_", "_without_effects_"]):
            try:
                os.unlink(os.path.join(videogen_dir, item))
                temp_count += 1
            except Exception:
                pass
    if temp_count > 0:
        log(f"🧹 Cleared {temp_count} temp render file(s) from VideoGen root", pc_name)


def copy_materials_to_videogen(video_names, mats_output_path, videogen_script_path, pc_name):
    """
    Copy claimed video materials from mats output to Video_Gen input_files.
    Preserves config/video nesting.
    """
    videogen_dir = os.path.dirname(videogen_script_path)
    videogen_input = os.path.join(videogen_dir, "input_files")
    os.makedirs(videogen_input, exist_ok=True)

    copied = []
    for video_name in video_names:
        config_name, video_folder = video_name.split('/', 1)
        source = os.path.join(mats_output_path, config_name, video_folder)

        # Preserve nesting: copy to videogen input_files/{config_name}/{video_folder}/
        dest_config = os.path.join(videogen_input, config_name)
        os.makedirs(dest_config, exist_ok=True)
        dest = os.path.join(dest_config, video_folder)

        if not os.path.exists(source):
            log(f"⚠️ Source not found: {source}", pc_name)
            continue

        if os.path.exists(dest):
            shutil.rmtree(dest)

        try:
            shutil.copytree(source, dest)
            copied.append(video_name)
            log(f"📂 Copied to VideoGen: {video_folder}", pc_name)
        except Exception as e:
            log(f"⚠️ Failed to copy {video_folder}: {e}", pc_name)

    return copied


def run_videogen(videogen_script_path, pc_name, video_names=None):
    """Run video_render_gen.py directly with real-time output streaming."""
    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        videogen_dir = os.path.dirname(videogen_script_path)

        if video_names:
            video_labels = []
            for v in video_names:
                _, short = get_video_short_name(v)
                video_labels.append(short)
            log_slim(f"Rendering: {', '.join(video_labels)}", pc_name)

        log(f"Starting Video_Gen...", pc_name)

        process = subprocess.Popen(
            ["py", "-3.11", videogen_script_path],
            cwd=videogen_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            universal_newlines=True
        )

        # Stream output in real-time
        for line in process.stdout:
            stripped = line.strip()
            if not stripped:
                continue

            # Skip ffmpeg progress lines from verbose log
            if stripped.startswith("frame=") or "fps=" in stripped[:30]:
                continue
            if stripped.startswith("size=") or stripped.startswith("bitrate="):
                continue

            # Verbose log
            log(stripped, pc_name, file_only=True)

            # Print to console
            print(line, end='')

            # Slim log: key events
            if "❌" in stripped or "ERROR" in stripped or "error:" in stripped.lower():
                log_slim(stripped, pc_name)
            elif "Completed" in stripped or "completed" in stripped:
                log_slim(stripped, pc_name)
            elif "Skipping" in stripped:
                log_slim(stripped, pc_name)

        process.wait()

        if process.returncode == 0:
            log(f"✓ Video_Gen completed successfully", pc_name)
            log_slim(f"Video_Gen completed successfully", pc_name)
            return True
        else:
            log(f"✗ Video_Gen failed with exit code {process.returncode}", pc_name)
            log_slim(f"Video_Gen failed (exit code {process.returncode})", pc_name)
            return False

    except Exception as e:
        log(f"✗ Video_Gen error: {e}", pc_name)
        log_slim(f"Video_Gen error: {e}", pc_name)
        return False


def move_videos_to_synced_output(video_names, videogen_script_path, synced_video_output_path, pc_name):
    """
    Move rendered .mp4 files from Video_Gen output to synced output folder.
    Returns (moved_count, failed_video_names).
    """
    videogen_dir = os.path.dirname(videogen_script_path)
    videogen_output = os.path.join(videogen_dir, "output_files")

    if not os.path.exists(videogen_output):
        log(f"⚠️ Video_Gen output_files not found!", pc_name)
        return 0, list(video_names)

    os.makedirs(synced_video_output_path, exist_ok=True)

    moved_count = 0
    failed_videos = []
    MIN_FILE_SIZE_KB = 100

    for video_name in video_names:
        config_name, video_folder = video_name.split('/', 1)

        # Video_Gen outputs nested: output_files/{config_name}/{video_folder}.mp4
        source_mp4 = os.path.join(videogen_output, config_name, f"{video_folder}.mp4")
        # Fallback to flat output for backward compatibility
        if not os.path.exists(source_mp4):
            source_mp4 = os.path.join(videogen_output, f"{video_folder}.mp4")

        if not os.path.exists(source_mp4):
            log(f"⚠️ No .mp4 found for: {video_folder}", pc_name)
            failed_videos.append(video_name)
            continue

        file_size_kb = os.path.getsize(source_mp4) / 1024
        if file_size_kb < MIN_FILE_SIZE_KB:
            log(f"✗ {video_folder}.mp4 too small ({file_size_kb:.1f} KB)", pc_name)
            log_slim(f"✗ {video_folder} too small ({file_size_kb:.1f} KB)", pc_name)
            failed_videos.append(video_name)
            continue

        # Destination: synced output preserves config nesting
        dest_config_folder = os.path.join(synced_video_output_path, config_name)
        os.makedirs(dest_config_folder, exist_ok=True)
        dest_mp4 = os.path.join(dest_config_folder, f"{video_folder}.mp4")

        try:
            if os.path.exists(dest_mp4):
                os.remove(dest_mp4)
            shutil.move(source_mp4, dest_mp4)

            file_size = os.path.getsize(dest_mp4) / (1024 * 1024)
            _, video_short = get_video_short_name(video_name)
            log(f"✓ {config_name}", pc_name)
            log(f"  {video_short} - Completed by {pc_name} ({file_size:.2f} MB)", pc_name)
            log_slim(f"✓ {video_short} → output ({file_size:.1f} MB)", pc_name)
            moved_count += 1
        except Exception as e:
            log(f"✗ Failed to move {video_folder}.mp4: {e}", pc_name)
            log_slim(f"✗ Failed to move {video_folder}", pc_name)
            failed_videos.append(video_name)

    return moved_count, failed_videos


# ============================================================================
# MANIFEST FUNCTIONS
# ============================================================================

def reset_manifest(mats_output_path, pc_name):
    """Reset the PC's manifest file on startup."""
    manifest_dir = os.path.join(mats_output_path, "_manifests")
    os.makedirs(manifest_dir, exist_ok=True)

    filename = f"{pc_name}_manifest.json"
    manifest_path = os.path.join(manifest_dir, filename)

    manifest = {
        "pc_name": pc_name,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_updated": "",
        "summary": {"total": 0, "success": 0, "failed": 0},
        "failed": [],
        "succeeded": [],
    }

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def write_manifest(mats_output_path, pc_name, successfully_prepared,
                   failed_videos, synced_video_output_path, max_retries):
    """Append results from this batch run to the PC's manifest."""
    manifest_dir = os.path.join(mats_output_path, "_manifests")
    filename = f"{pc_name}_manifest.json"
    manifest_path = os.path.join(manifest_dir, filename)

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        reset_manifest(mats_output_path, pc_name)
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    manifest["last_updated"] = now_str

    failed_set = set(failed_videos)

    for video_name in successfully_prepared:
        config_name, video_short = get_video_short_name(video_name)
        video_folder = video_name.split('/', 1)[1]

        if video_name in failed_set:
            pc_suffix = f" - {pc_name}"
            base = video_folder[:-len(pc_suffix)] if video_folder.endswith(pc_suffix) else video_folder
            current_retries = get_retry_count(base)
            new_retry = current_retries + 1

            manifest["failed"].append({
                "short_name": f"{config_name} / {video_short}",
                "video_path": video_name,
                "failed_at": now_str,
                "retry_count": new_retry,
                "will_retry": new_retry < max_retries,
            })
            manifest["summary"]["failed"] += 1
        else:
            entry = {
                "short_name": f"{config_name} / {video_short}",
                "video_path": video_name,
                "completed_at": now_str,
            }
            if synced_video_output_path:
                mp4_path = os.path.join(synced_video_output_path, config_name, f"{video_folder}.mp4")
                if os.path.exists(mp4_path):
                    entry["file_size_mb"] = round(os.path.getsize(mp4_path) / (1024 * 1024), 2)

            manifest["succeeded"].append(entry)
            manifest["summary"]["success"] += 1

        manifest["summary"]["total"] += 1

    try:
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        log(f"📋 Manifest updated: {manifest['summary']['success']}✓ {manifest['summary']['failed']}✗ (total: {manifest['summary']['total']})", pc_name)
        log_slim(f"Manifest: {manifest['summary']['success']}✓ {manifest['summary']['failed']}✗ (session total: {manifest['summary']['total']})", pc_name)
    except Exception as e:
        log(f"⚠️ Failed to write manifest: {e}", pc_name)


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    """Main render watcher loop."""
    config = load_config()

    pc_name = config["my_pc_name"]
    scan_interval = config["scan_interval_seconds"]
    approval_wait = config["approval_wait_seconds"]
    post_render_delay = config["post_render_delay_seconds"]
    jitter_min = config["random_jitter_min"]
    jitter_max = config["random_jitter_max"]
    max_retries = config.get("max_retries", 5)
    mats_output_path = config["mats_output_path"]
    synced_video_output_path = config.get("synced_video_output_path")
    videogen_script_path = config["videogen_script"]

    # Get batch size from videogen config
    batch_size = get_videogen_concurrency(videogen_script_path)

    log(f"=== Mats Render Watcher Started ===", pc_name)
    log(f"Scan interval: {scan_interval}s | Approval wait: {approval_wait}s | Batch size: {batch_size} | Max retries: {max_retries}", pc_name)
    log(f"Mats source: {mats_output_path}", pc_name)
    log(f"Video output: {synced_video_output_path}", pc_name)
    log(f"VideoGen: {videogen_script_path}", pc_name)
    log(f"", pc_name)

    log_slim(f"Render watcher started (batch: {batch_size}, retries: {max_retries})", pc_name)

    # Validate videogen script exists
    if not os.path.isfile(videogen_script_path):
        log(f"❌ VideoGen script not found: {videogen_script_path}", pc_name)
        exit(1)

    # Reset manifest on startup
    os.makedirs(mats_output_path, exist_ok=True)
    reset_manifest(mats_output_path, pc_name)
    log(f"📋 Manifest reset", pc_name)

    # Cleanup stale claims from previous crash
    unclaimed, skipped = cleanup_stale_claims(mats_output_path, synced_video_output_path, pc_name)
    if unclaimed > 0 or skipped > 0:
        log(f"🧹 Stale claim cleanup: {unclaimed} unclaimed, {skipped} already completed", pc_name)
        log_slim(f"Stale claim cleanup: {unclaimed} unclaimed, {skipped} completed", pc_name)

    # Clear leftover Video_Gen files from previous crash
    clear_videogen_folders(videogen_script_path, pc_name)

    while True:
        try:
            # Sleep with random jitter
            sleep_time = scan_interval + random_jitter(jitter_min, jitter_max)
            log(f"Sleeping {sleep_time:.2f}s before next scan...", pc_name)
            time.sleep(sleep_time)

            # === STEP 0: CLEANUP STALE REQUESTS ===
            cleaned = cleanup_stale_requests(mats_output_path)
            if cleaned > 0:
                log(f"🧹 Cleaned {cleaned} stale request file(s)", pc_name)

            # === STEP 1: SCAN ===
            log("", pc_name, section=True)
            available_videos = get_available_videos(mats_output_path, max_retries)

            if not available_videos:
                log(f"SCAN: Found 0 available videos", pc_name)
                log("", pc_name, section=True)
                continue

            log(f"SCAN: Found {len(available_videos)} available videos", pc_name)
            log("", pc_name, section=True)

            # Take up to batch_size videos
            videos_to_request = available_videos[:batch_size]
            log(f"REQUESTING (Batch of {len(videos_to_request)}):", pc_name)
            for video in videos_to_request:
                config_name, video_short = get_video_short_name(video)
                log(f"  ✓ {config_name} / {video_short}", pc_name)

            log_slim(f"Scan: {len(available_videos)} available. Requesting: {', '.join(get_video_short_name(v)[1] for v in videos_to_request)}", pc_name)

            # === STEP 2: CREATE REQUESTS ===
            created_requests = []
            for video in videos_to_request:
                request_file = create_request_file(video, pc_name, mats_output_path)
                created_requests.append((video, request_file))

            # === STEP 3: WAIT FOR APPROVAL ===
            wait_time = approval_wait + random_jitter(jitter_min, jitter_max)
            log(f"Waiting {wait_time:.2f}s for approval window...", pc_name)
            time.sleep(wait_time)

            # === STEP 4: RUN APPROVAL ALGORITHM ===
            log("", pc_name, section=True)
            log(f"APPROVAL RESULTS", pc_name)
            log("", pc_name, section=True)

            all_requests = get_all_requests(mats_output_path)
            approvals = run_approval_algorithm(all_requests, pc_name)

            my_wins = 0
            won_labels = []
            lost_labels = []
            for video, request_file in created_requests:
                config_name, video_short = get_video_short_name(video)
                if video in approvals:
                    winner, competitors = approvals[video]
                    result_symbol = "✓" if winner == pc_name else "✗"

                    if len(competitors) > 1:
                        competitors_str = " vs ".join(competitors)
                        log(f"  {result_symbol} {config_name} / {video_short} - {competitors_str} → Winner: {winner}", pc_name)
                    else:
                        log(f"  {result_symbol} {config_name} / {video_short} - Winner: {winner}", pc_name)

                    if winner == pc_name:
                        my_wins += 1
                        won_labels.append(video_short)
                    else:
                        lost_labels.append(f"{video_short} to {winner}")

                delete_my_requests(video, pc_name, mats_output_path)

            log(f"MY RESULTS: Won {my_wins}/{len(created_requests)} videos", pc_name)

            slim_parts = [f"Won {my_wins}/{len(created_requests)}"]
            if won_labels:
                slim_parts.append(f": {', '.join(won_labels)}")
            if lost_labels:
                slim_parts.append(f" (lost {', '.join(lost_labels)})")
            log_slim("".join(slim_parts), pc_name)

            # === STEP 5: CLAIM AND RENDER ===
            my_approved_videos = [v for v, _ in created_requests if v in approvals and approvals[v][0] == pc_name]

            if not my_approved_videos:
                continue

            log("", pc_name, section=True)
            log(f"CLAIMING & RENDERING", pc_name)
            log("", pc_name, section=True)

            # Step 1: Rename to claim
            successfully_prepared = []
            claimed_labels = []
            for video in my_approved_videos:
                success, new_name = rename_folder(video, pc_name, mats_output_path)
                if not success:
                    continue

                _, video_short = get_video_short_name(video)
                log(f"  ✓ Claimed: {video_short}", pc_name)

                successfully_prepared.append(new_name)
                claimed_labels.append(video_short)

            if not successfully_prepared:
                continue

            log_slim(f"Claimed: {', '.join(claimed_labels)}", pc_name)

            # Step 2: Clear Video_Gen folders
            clear_videogen_folders(videogen_script_path, pc_name)

            # Step 3: Copy materials to Video_Gen input
            copied = copy_materials_to_videogen(successfully_prepared, mats_output_path, videogen_script_path, pc_name)

            if not copied:
                log(f"⚠️ No materials could be copied, skipping render", pc_name)
                # Unclaim all
                for video_name in successfully_prepared:
                    unclaim_video(video_name, mats_output_path, pc_name)
                continue

            # Step 4: Run Video_Gen
            log("", pc_name, section=True)
            log(f"RENDERING ({len(copied)} videos)", pc_name)
            log("", pc_name, section=True)

            render_success = run_videogen(videogen_script_path, pc_name, copied)

            if render_success:
                log(f"✓ Render complete", pc_name)
            else:
                log(f"✗ Render reported failure", pc_name)

            # Step 5: Move .mp4s to synced output
            failed_videos = []
            if synced_video_output_path:
                log("", pc_name, section=True)
                log(f"MOVING TO OUTPUT", pc_name)
                log("", pc_name, section=True)

                moved_count, failed_videos = move_videos_to_synced_output(
                    successfully_prepared, videogen_script_path, synced_video_output_path, pc_name
                )

                if moved_count > 0:
                    log(f"Successfully moved {moved_count} videos to synced output", pc_name)
            else:
                if not render_success:
                    failed_videos = list(successfully_prepared)

            # Step 6: Unclaim failed videos
            if failed_videos:
                log("", pc_name, section=True)
                log(f"UNCLAIMING FAILED VIDEOS ({len(failed_videos)})", pc_name)
                log("", pc_name, section=True)

                for failed_video in failed_videos:
                    _, video_short = get_video_short_name(failed_video)
                    if unclaim_video(failed_video, mats_output_path, pc_name):
                        video_folder = failed_video.split('/', 1)[1]
                        pc_suffix = f" - {pc_name}"
                        base_name = video_folder[:-len(pc_suffix)] if video_folder.endswith(pc_suffix) else video_folder
                        new_retry = get_retry_count(base_name) + 1

                        log(f"  ↩️ {video_short} - Unclaimed (retry {new_retry}/{max_retries})", pc_name)
                        log_slim(f"✗ {video_short} → unclaimed (retry {new_retry}/{max_retries})", pc_name)
                    else:
                        log(f"  ✗ {video_short} - Failed to unclaim!", pc_name)

            # Step 7: Mark successful renders
            failed_set = set(failed_videos)
            for video_name in successfully_prepared:
                if video_name not in failed_set:
                    config_name, video_folder = video_name.split('/', 1)
                    mats_folder = os.path.join(mats_output_path, config_name, video_folder)
                    rendered_folder = os.path.join(mats_output_path, config_name, f"{video_folder} - Rendered")
                    if os.path.exists(mats_folder) and not os.path.exists(rendered_folder):
                        try:
                            os.rename(mats_folder, rendered_folder)
                        except Exception:
                            pass

            # Step 8: Update manifest
            write_manifest(
                mats_output_path, pc_name, successfully_prepared,
                failed_videos, synced_video_output_path, max_retries
            )

            # Step 9: Clear Video_Gen folders after render
            clear_videogen_folders(videogen_script_path, pc_name)

            # === STEP 6: POST-RENDER COOLDOWN ===
            cooldown_time = post_render_delay + random_jitter(jitter_min, jitter_max)
            log(f"Post-render cooldown: {cooldown_time:.2f}s", pc_name)
            time.sleep(cooldown_time)

        except KeyboardInterrupt:
            log(f"Watcher stopped by user", pc_name)
            log_slim(f"Watcher stopped by user", pc_name)
            break
        except Exception as e:
            log(f"ERROR: {e}", pc_name)
            log_slim(f"ERROR: {e}", pc_name)
            import traceback
            traceback.print_exc()
            time.sleep(30)


if __name__ == "__main__":
    main()