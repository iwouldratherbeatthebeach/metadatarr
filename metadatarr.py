#!/usr/bin/env python3
import os
import re
import sys
import time
import requests
import logging
import shutil
import base64

######################
# CONFIGURATION
######################

LOG_LEVEL = logging.INFO  # Change to logging.DEBUG for more detailed output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(levelname)s] %(message)s',
    stream=sys.stdout
)

# DISPLAY_LOG_MODE controls which update/skip messages are shown.
# Allowed values: "all", "changed", "skipped", "both"
DISPLAY_LOG_MODE = "all"  # Default setting

def safe_log(message, level=logging.INFO):
    try:
        logging.log(level, message)
    except UnicodeEncodeError:
        safe_message = message.encode("ascii", "backslashreplace").decode("ascii")
        logging.log(level, safe_message)

def filtered_log(message, category, level=logging.INFO):
    mode = DISPLAY_LOG_MODE.lower()
    if mode == "all":
        safe_log(message, level)
    elif mode == "changed" and category == "update":
        safe_log(message, level)
    elif mode == "skipped" and category == "skip":
        safe_log(message, level)
    elif mode == "both" and category in ("update", "skip"):
        safe_log(message, level)

# Radarr configuration
RADARR_URL = "http://localhost:7878"  # Update if needed
RADARR_API_KEY = "<YOUR_RADARR_API_KEY>"  # Replace with your actual API key
USE_BASIC_AUTH = False  # Use only the X-Api-Key header

RATING_SOURCE = "tmdb"  # Options: "tmdb", "imdb", "metacritic", "rottenTomatoes"
RATING_DISPLAY_FORMAT = "number"  # "number" or "percentage"
INCLUDE_RATINGS = True

OVERWRITE_EXISTING_EDITION = True
FORCE_RADARR_UPDATE_ON_RENAME_FAILURE = False

# Options for edition string components
SHOW_RESOLUTION = True
SHOW_CODEC = True
SHOW_LANGUAGE = False

SHOW_CRITIC_RATING = True
SHOW_AUDIENCE_RATING = False
CRITIC_LABEL = ""
AUDIENCE_LABEL = "A:"

QUALITY_MAPPING = {
    "DVD-480p": "480p",
    "DVD-576p": "576p",
    "DVD": "DVD",
    "SDTV": "480p",
    "TVRip": "TVRip",
    "HDTV-480p": "480p",
    "HDTV-720p": "720p",
    "HDTV-1080p": "1080p",
    "Bluray-480p": "480p",
    "Bluray-576p": "576p",
    "Bluray-720p": "720p",
    "Bluray-1080p": "1080p",
    "WEBRip-480p": "480p",
    "WEBRip-720p": "720p",
    "WEBRip-1080p": "1080p",
    "WEBDL-480p": "480p",
    "WEBDL-720p": "720p",
    "WEBDL-1080p": "1080p",
    "DVDRip": "DVDRip",
    "HDRip": "HDRip",
    "BDRip": "BDRip",
    "Bluray-4K": "4K",
    "UltraHD-2160p": "4K",
    "WEBRip-4K": "4K",
    "WEBDL-4K": "4K",
    "WEBRip-2160p": "4K",
    "WEBDL-2160p": "4K",
    "REMUX": "REMUX",
    "BD REMUX": "REMUX",
    "Bluray-REMUX": "REMUX",
    "BR REMUX": "REMUX",
    "CAM": "CAM",
    "HDTS": "HDTS",
    "TS": "TS",
    "TC": "TC",
    "Screener": "Screener",
    "VHSRip": "VHS"
}

METADATA_ORDER = ["rating", "resolution", "codec", "language"]

def get_enabled_fields():
    fields = []
    if INCLUDE_RATINGS and (SHOW_CRITIC_RATING or SHOW_AUDIENCE_RATING):
        fields.append("rating")
    if SHOW_RESOLUTION:
        fields.append("resolution")
    if SHOW_CODEC:
        fields.append("codec")
    if SHOW_LANGUAGE:
        fields.append("language")
    return fields

ENABLED_FIELDS = get_enabled_fields()
EXPECTED_PARTS_COUNT = len(ENABLED_FIELDS)

FAST_MODE_SLEEP = 0.5
SLOW_MODE_SLEEP = 1.0
REFRESH_DELAY = 5

######################
# END CONFIGURATION
######################

RADARR_MOVIE_ENDPOINT = f"{RADARR_URL}/api/v3/movie"
REQUEST_TIMEOUT = 10

def get_headers():
    headers = {
        "X-Api-Key": RADARR_API_KEY,
        "Content-Type": "application/json"
    }
    if USE_BASIC_AUTH:
        auth_value = base64.b64encode(f"admin:{RADARR_API_KEY}".encode()).decode()
        headers["Authorization"] = f"Basic {auth_value}"
    return headers

def get_radarr_movies():
    headers = get_headers()
    response = requests.get(RADARR_MOVIE_ENDPOINT, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    safe_log("Retrieved movies from Radarr.", logging.DEBUG)
    return response.json()

def refresh_and_get_movie(movie_id):
    trigger_refresh_movie(movie_id)
    safe_log(f"Waiting for refresh to complete for movie id {movie_id}...", logging.DEBUG)
    time.sleep(REFRESH_DELAY)
    headers = get_headers()
    response = requests.get(f"{RADARR_MOVIE_ENDPOINT}/{movie_id}", headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    safe_log(f"Retrieved updated record for movie id {movie_id}.", logging.DEBUG)
    return response.json()

def normalize_codec(codec_str):
    cs = codec_str.lower().strip()
    if cs in ["x264", "h264"]:
        return "h264"
    if cs in ["x265", "h265"]:
        return "h265"
    return cs

def build_edition_string(movie):
    metadata_parts = {}
    movie_file = movie.get("movieFile", {})
    if SHOW_RESOLUTION:
        quality_info = movie_file.get("quality", {})
        quality_data = quality_info.get("quality")
        quality_name = quality_data.get("name") if isinstance(quality_data, dict) else quality_data
        if quality_name:
            resolution = QUALITY_MAPPING.get(quality_name, quality_name)
            metadata_parts["resolution"] = resolution
            safe_log(f"Resolution: {resolution}", logging.DEBUG)
    if SHOW_CODEC:
        codec = movie_file.get("mediaInfo", {}).get("videoCodec")
        if codec:
            normalized = normalize_codec(codec)
            metadata_parts["codec"] = normalized
            safe_log(f"Codec: {normalized}", logging.DEBUG)
    if SHOW_LANGUAGE:
        language = movie_file.get("language")
        if language:
            lang = language.upper()
            metadata_parts["language"] = lang
            safe_log(f"Language: {lang}", logging.DEBUG)
    if INCLUDE_RATINGS and (SHOW_CRITIC_RATING or SHOW_AUDIENCE_RATING):
        ratings_obj = movie.get("ratings", {})
        rating_value = None
        if RATING_SOURCE in ratings_obj and "value" in ratings_obj[RATING_SOURCE]:
            rating_value = ratings_obj[RATING_SOURCE]["value"]
        if rating_value is None and "imdb" in ratings_obj and "value" in ratings_obj["imdb"]:
            rating_value = ratings_obj["imdb"]["value"]
        if rating_value is not None:
            try:
                rating_value = round(float(rating_value), 1)
                if RATING_DISPLAY_FORMAT.lower() == "percentage":
                    rating_percentage = round(rating_value * 10)
                    metadata_parts["rating"] = f"{rating_percentage}%"
                else:
                    metadata_parts["rating"] = str(rating_value)
                safe_log(f"Rating (from {RATING_SOURCE}): {metadata_parts['rating']}", logging.DEBUG)
            except Exception as e:
                safe_log(f"Error processing rating value: {e}", logging.ERROR)
    parts_list = [metadata_parts[key] for key in METADATA_ORDER if key in metadata_parts]
    edition_string = " - ".join(parts_list) if parts_list else None
    safe_log(f"Built edition string: {edition_string}", logging.DEBUG)
    return edition_string

def update_movie_folder(movie, new_folder_abs):
    movie_id = movie.get("id")
    update_url = f"{RADARR_MOVIE_ENDPOINT}/{movie_id}"
    movie["folderName"] = new_folder_abs
    movie["path"] = new_folder_abs
    headers = get_headers()
    response = requests.put(update_url, json=movie, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    safe_log(f"Updated Radarr record for '{movie.get('title')}' to folder '{new_folder_abs}'", logging.INFO)
    return response.json()

def trigger_refresh_movie(movie_id):
    command_url = f"{RADARR_URL}/api/v3/command"
    payload = {"name": "RefreshMovie", "movieIds": [movie_id]}
    headers = get_headers()
    response = requests.post(command_url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    safe_log(f"Triggered refresh for movie id {movie_id}", logging.INFO)
    return response.json()

def rename_physical_directory(old_full_path, new_full_path):
    if not os.path.exists(old_full_path):
        safe_log(f"Old folder path does not exist: {old_full_path}", logging.ERROR)
        return False
    if os.path.exists(new_full_path):
        safe_log(f"[SKIP] New folder already exists: {new_full_path}", logging.INFO)
        return False
    try:
        os.rename(old_full_path, new_full_path)
        safe_log(f"Successfully renamed directory from '{old_full_path}' to '{new_full_path}'", logging.INFO)
        return True
    except Exception as e:
        safe_log(f"Error renaming directory from '{old_full_path}' to '{new_full_path}': {e}", logging.ERROR)
        try:
            shutil.move(old_full_path, new_full_path)
            safe_log(f"Fallback: successfully moved directory from '{old_full_path}' to '{new_full_path}'", logging.INFO)
            return True
        except Exception as e2:
            safe_log(f"Fallback failed: {e2}", logging.ERROR)
            return False

# Global counters
processed_count = 0
empty_count = 0

def print_summary():
    safe_log(f"Total movies processed: {processed_count}", logging.INFO)
    safe_log(f"Total movies skipped due to missing physical folder: {empty_count}", logging.INFO)

def option_add_edition():
    global processed_count, empty_count
    safe_log("Starting option: Add/Update edition block (fast mode)...", logging.INFO)
    movies = get_radarr_movies()
    total = len(movies)
    edition_pattern = re.compile(r"\{edition-(.*)\}$", re.IGNORECASE)
    
    for index, movie in enumerate(movies, start=1):
        title = movie.get("title")
        safe_log(f"Processing movie {index}/{total}: {title}", logging.INFO)
        processed_count += 1
        movie_id = movie.get("id")
        
        root = movie.get("rootFolderPath")
        current_folder = movie.get("folderName")
        if not root or not current_folder:
            safe_log(f"Skipping movie '{title}' due to missing rootFolderPath or folderName.", logging.ERROR)
            continue

        if os.path.isabs(current_folder):
            current_folder = os.path.basename(current_folder)
        current_full_path = os.path.join(root, current_folder)
        if not os.path.exists(current_full_path):
            safe_log(f"Physical folder missing: {current_full_path}. Skipping movie '{title}'.", logging.ERROR)
            empty_count += 1
            continue

        current_parts = []
        if edition_pattern.search(current_folder):
            current_edition = edition_pattern.search(current_folder).group(1).strip()
            current_parts = [p.strip() for p in current_edition.split(" - ")]
            base_folder = edition_pattern.sub("", current_folder).strip()
            safe_log(f"Removed existing edition block for '{title}'.", logging.DEBUG)
        else:
            base_folder = current_folder.strip()

        candidate_edition = build_edition_string(movie)
        if candidate_edition:
            candidate_parts = [p.strip() for p in candidate_edition.split(" - ")]
            candidate_folder = f"{base_folder} {{edition-{candidate_edition}}}"
        else:
            candidate_folder = base_folder
            candidate_parts = []

        # Compare non-codec fields by checking only the last 3 characters for codec.
        if current_parts and candidate_parts:
            non_codec_same = True
            enabled = get_enabled_fields()
            for field, cur, cand in zip(enabled, current_parts, candidate_parts):
                if field == "codec":
                    # Compare only the last three characters.
                    if cur[-3:] != cand[-3:]:
                        non_codec_same = False
                        break
                else:
                    if cur.lower() != cand.lower():
                        non_codec_same = False
                        break
            if non_codec_same:
                filtered_log(f"[SKIP] For '{title}': Candidate edition (ignoring codec) equals current. Skipping update.", "skip")
                continue

        if candidate_folder == current_folder:
            filtered_log(f"[SKIP] No folder name change needed for '{title}'", "skip")
            continue

        new_full_path = os.path.join(root, candidate_folder)
        if os.path.exists(new_full_path):
            filtered_log(f"[SKIP] New folder already exists for '{title}': {new_full_path}", "skip")
            continue

        filtered_log(f"[UPDATE] '{title}'", "update")
        safe_log(f"  Current folder: {current_full_path}", logging.INFO)
        safe_log(f"  New folder:     {new_full_path}", logging.INFO)

        renamed = rename_physical_directory(current_full_path, new_full_path)
        if not renamed and FORCE_RADARR_UPDATE_ON_RENAME_FAILURE:
            safe_log(f"Physical rename failed but forcing update for '{title}'.", logging.WARNING)
            renamed = True

        if renamed:
            try:
                update_movie_folder(movie, new_full_path)
                trigger_refresh_movie(movie_id)
                filtered_log(f"[UPDATE] '{title}' processed.", "update")
            except Exception as e:
                safe_log(f"Error updating record for '{title}': {e}", logging.ERROR)
        else:
            filtered_log(f"[SKIP] Skipping update for '{title}' due to folder rename failure.", "skip")
        
        time.sleep(FAST_MODE_SLEEP)

def option_remove_edition():
    safe_log("Starting option: Remove edition block...", logging.INFO)
    movies = get_radarr_movies()
    total = len(movies)
    edition_pattern = re.compile(r"\s*\{edition-.*\}$", re.IGNORECASE)
    for index, movie in enumerate(movies, start=1):
        title = movie.get("title")
        safe_log(f"Processing movie {index}/{total}: {title}", logging.INFO)
        movie_id = movie.get("id")
        try:
            movie = refresh_and_get_movie(movie_id)
        except Exception as e:
            safe_log(f"Failed to refresh movie '{title}': {e}", logging.ERROR)
            continue
        
        root = movie.get("rootFolderPath")
        current_folder = movie.get("folderName")
        if not root or not current_folder:
            safe_log(f"Skipping movie '{title}' due to missing rootFolderPath or folderName.", logging.ERROR)
            continue
        
        if os.path.isabs(current_folder):
            current_folder = os.path.basename(current_folder)
        current_full_path = os.path.join(root, current_folder)
        if not os.path.exists(current_full_path):
            safe_log(f"Old folder path does not exist: {current_full_path}", logging.ERROR)
            safe_log(f"Skipping movie '{title}'", logging.ERROR)
            continue
        
        if not edition_pattern.search(current_folder):
            safe_log(f"No edition block found for '{title}', skipping.", logging.INFO)
            continue
        
        new_rel_folder = edition_pattern.sub("", current_folder).strip()
        new_full_path = os.path.join(root, new_rel_folder)
        safe_log(f"[UPDATE] '{title}'", logging.INFO)
        safe_log(f"  Current folder: {current_full_path}", logging.INFO)
        safe_log(f"  New folder:     {new_full_path}", logging.INFO)
        
        renamed = rename_physical_directory(current_full_path, new_full_path)
        if not renamed and FORCE_RADARR_UPDATE_ON_RENAME_FAILURE:
            safe_log(f"Physical rename failed but forcing update for '{title}'.", logging.WARNING)
            renamed = True
        
        if renamed:
            try:
                update_movie_folder(movie, new_full_path)
                trigger_refresh_movie(movie_id)
            except Exception as e:
                safe_log(f"Error updating record for '{title}': {e}", logging.ERROR)
        else:
            safe_log(f"Skipping update for '{title}' due to folder rename failure.", logging.ERROR)
        
        time.sleep(FAST_MODE_SLEEP)

def print_summary():
    safe_log(f"Total movies processed: {processed_count}", logging.INFO)
    safe_log(f"Total movies skipped due to missing physical folder: {empty_count}", logging.INFO)

def main_menu():
    while True:
        print("\nMetadatarr Interactive")
        print("-----------------------")
        print("Options:")
        print("1. Add/Update edition block to movie folders (fast)")
        print("2. Remove edition block from movie folders")
        print("3. Add/Update edition block to movie folders (slow mode)")
        print("4. Set display log mode")
        print("5. Exit")
        choice = input("Enter option (1, 2, 3, 4, or 5): ").strip()
        if choice == "1":
            global FAST_MODE_SLEEP
            FAST_MODE_SLEEP = 0.5
            option_add_edition()
        elif choice == "2":
            FAST_MODE_SLEEP = 0.5
            option_remove_edition()
        elif choice == "3":
            FAST_MODE_SLEEP = 1.0
            option_add_edition()
        elif choice == "4":
            new_mode = input("Enter new display log mode (all, changed, skipped, both): ").strip().lower()
            if new_mode in ("all", "changed", "skipped", "both"):
                global DISPLAY_LOG_MODE
                DISPLAY_LOG_MODE = new_mode
                safe_log(f"Display log mode set to '{DISPLAY_LOG_MODE}'", logging.INFO)
            else:
                safe_log("Invalid log mode option.", logging.ERROR)
            continue  # Return to main menu after setting
        elif choice == "5":
            break
        else:
            safe_log("Invalid choice. Please try again.", logging.ERROR)
    print_summary()

if __name__ == "__main__":
    try:
        main_menu()
    except Exception as e:
        safe_log(f"Unhandled error: {e}", logging.ERROR)
