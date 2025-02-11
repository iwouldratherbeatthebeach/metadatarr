#!/usr/bin/env python3
"""
Metadatarr Interactive

This script interacts with your Radarr library to either:
  1. Add/Update a custom {edition-...} block to each movie’s folder name (fast mode),
  2. Remove any existing {edition-...} block from the movie folder names,
  3. Add/Update a custom {edition-...} block in slow mode (refreshing each movie’s record),
  4. Change settings via the settings menu,
  5. Exit.

It renames the physical directories on disk and updates the Radarr record’s folderName and path fields.
If no change is needed—or if the candidate edition (built solely from the Radarr record) is incomplete—the movie is skipped.
After an update, the script triggers Radarr’s "RefreshMovie" command and (optionally) the "UpdatePlex" command so that Plex is updated.
A summary of processed, skipped, updated, and error counts is printed at the end.
Note: If Radarr’s auto‑renaming is enabled, it may override external changes.
"""

import os
import re
import sys
import time
import requests
import logging
import shutil
import base64

######################
# DEFAULT SETTINGS (modifiable via settings menu)
######################
VERBOSE = True                  # If False, DEBUG messages will be hidden.
DISPLAY_LOG_MODE = "all"        # Options: "all", "changed", "skipped", "both"
SHOW_RESOLUTION = True
SHOW_CODEC = True
SHOW_LANGUAGE = False
INCLUDE_RATINGS = True
SHOW_CRITIC_RATING = True
SHOW_AUDIENCE_RATING = False
RATING_SOURCE = "tmdb"          # Options: "tmdb", "imdb", "metacritic", "rottenTomatoes"
RATING_DISPLAY_FORMAT = "number"  # "number" or "percentage"

FAST_MODE_SLEEP = 0.5
SLOW_MODE_SLEEP = 3.0
REFRESH_DELAY = 5
CONTINUOUS_MODE_INTERVAL = 60

# New setting: process movies in reverse order.
REVERSE_ORDER = False

# Set to False to skip triggering the UpdatePlex command.
TRIGGER_PLEX_UPDATE = False

# Radarr connection settings
RADARR_URL = "http://localhost:7878"  # Change if necessary
RADARR_API_KEY = "<YOUR_RADARR_API>"  # Replace with your API key
USE_BASIC_AUTH = False

# Quality mapping
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

# Define the order of metadata parts.
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

######################
# END DEFAULT SETTINGS
######################

# Global flag for slow mode is set only for slow mode operations.
SLOW_MODE = False

RADARR_MOVIE_ENDPOINT = f"{RADARR_URL}/api/v3/movie"
REQUEST_TIMEOUT = 20

######################
# Logging Setup
######################
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=(logging.DEBUG if VERBOSE else logging.INFO),
                    format='[%(levelname)s] %(message)s', stream=sys.stdout)

def safe_log(message, level=logging.INFO):
    if level == logging.DEBUG and not VERBOSE:
        return
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
    try:
        trigger_refresh_movie(movie_id)
        safe_log(f"Slow mode: Refreshing record for movie id {movie_id}...", logging.INFO)
        time.sleep(REFRESH_DELAY)
        headers = get_headers()
        response = requests.get(f"{RADARR_MOVIE_ENDPOINT}/{movie_id}", headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        safe_log(f"Slow mode: Retrieved updated record for movie id {movie_id}.", logging.INFO)
        return response.json()
    except Exception as e:
        safe_log(f"Error refreshing movie id {movie_id} in slow mode: {e}", logging.ERROR)
        return None

def normalize_codec(codec_str):
    cs = codec_str.lower().strip()
    if cs in ["x264", "h264"]:
        return "h264"
    if cs in ["x265", "h265"]:
        return "h265"
    return cs

def build_edition_string(movie):
    """Build candidate edition string solely from the Radarr record.
       If the resulting candidate does not have all enabled fields, return None."""
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
    if len(parts_list) < EXPECTED_PARTS_COUNT:
        safe_log("Candidate edition is incomplete.", logging.DEBUG)
        return None
    edition_string = " - ".join(parts_list)
    safe_log(f"Built candidate edition string: {edition_string}", logging.DEBUG)
    return edition_string

def editions_equal(existing, candidate):
    """Return True if the two edition strings are equal (ignoring codec differences of x264 vs h264 and x265 vs h265)."""
    existing_parts = [p.strip() for p in existing.split(" - ")]
    candidate_parts = [p.strip() for p in candidate.split(" - ")]
    if len(existing_parts) != len(candidate_parts):
        return False
    for field, ex_val, cand_val in zip(ENABLED_FIELDS, existing_parts, candidate_parts):
        if field == "codec":
            if normalize_codec(ex_val) != normalize_codec(cand_val):
                return False
        else:
            if ex_val.lower() != cand_val.lower():
                return False
    return True

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

def post_command_with_retry(command_name, movie_id, retries=3):
    command_url = f"{RADARR_URL}/api/v3/command"
    payload = {"name": command_name, "movieIds": [movie_id]}
    headers = get_headers()
    for attempt in range(1, retries+1):
        try:
            response = requests.post(command_url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            safe_log(f"Triggered {command_name} for movie id {movie_id}", logging.INFO)
            return response.json()
        except Exception as e:
            safe_log(f"Error triggering {command_name} for movie id {movie_id} (attempt {attempt}): {e}", logging.ERROR)
            if attempt < retries:
                time.sleep(2)
            else:
                safe_log(f"Failed to trigger {command_name} for movie id {movie_id} after {retries} attempts", logging.ERROR)
                return None

def trigger_refresh_movie(movie_id):
    return post_command_with_retry("RefreshMovie", movie_id)

def trigger_plex_update(movie_id):
    if not TRIGGER_PLEX_UPDATE:
        safe_log(f"Skipping Plex update for movie id {movie_id} (disabled in settings).", logging.DEBUG)
        return None
    return post_command_with_retry("UpdatePlex", movie_id)

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

# Global counters for summary
processed_count = 0
skipped_count = 0
updated_count = 0
error_count = 0
empty_count = 0

def option_add_edition(reverse_order=False, slow_mode=False):
    global processed_count, skipped_count, updated_count, error_count, empty_count
    mode_text = "slow mode (refreshing each record)" if slow_mode else "fast mode"
    safe_log(f"Starting option: Add/Update edition block ({mode_text})...", logging.INFO)
    movies = get_radarr_movies()
    if reverse_order:
        movies = list(reversed(movies))
        safe_log("Processing movies in reverse order.", logging.INFO)
    total = len(movies)
    
    for index, movie in enumerate(movies, start=1):
        processed_count += 1
        title = movie.get("title")
        safe_log(f"Processing movie {index}/{total}: {title}", logging.INFO)
        movie_id = movie.get("id")
        
        if slow_mode:
            safe_log(f"Slow mode: Refreshing record for '{title}'...", logging.INFO)
            refreshed = refresh_and_get_movie(movie_id)
            if refreshed:
                movie = refreshed
            else:
                safe_log(f"Skipping '{title}' due to refresh failure.", logging.ERROR)
                skipped_count += 1
                continue

        root = movie.get("rootFolderPath")
        current_folder = movie.get("folderName")
        if not root or not current_folder:
            safe_log(f"Skipping movie '{title}' due to missing rootFolderPath or folderName.", logging.ERROR)
            skipped_count += 1
            continue

        if os.path.isabs(current_folder):
            current_folder = os.path.basename(current_folder)
        current_full_path = os.path.join(root, current_folder)
        if not os.path.exists(current_full_path):
            safe_log(f"Physical folder missing: {current_full_path}. Skipping movie '{title}'.", logging.ERROR)
            empty_count += 1
            continue

        # Get base folder by removing any existing edition block (if present)
        existing_match = re.search(r"\{edition-(.*)\}$", current_folder)
        if existing_match:
            existing_edition = existing_match.group(1).strip()
            base_folder = current_folder[:existing_match.start()].strip()
        else:
            existing_edition = None
            base_folder = current_folder.strip()

        candidate_edition = build_edition_string(movie)
        if candidate_edition is None or len(candidate_edition.split(" - ")) < EXPECTED_PARTS_COUNT:
            filtered_log(f"[SKIP] For '{title}': Candidate edition is incomplete. Skipping update.", "skip")
            skipped_count += 1
            continue

        # If there is an existing edition block, compare it with candidate.
        if existing_edition is not None and editions_equal(existing_edition, candidate_edition):
            filtered_log(f"[SKIP] For '{title}': Existing edition equals candidate. Skipping update.", "skip")
            skipped_count += 1
            continue

        candidate_folder = f"{base_folder} {{edition-{candidate_edition}}}"
        if candidate_folder == current_folder:
            filtered_log(f"[SKIP] No folder name change needed for '{title}'", "skip")
            skipped_count += 1
            continue

        new_full_path = os.path.join(root, candidate_folder)
        if os.path.exists(new_full_path):
            filtered_log(f"[SKIP] New folder already exists for '{title}': {new_full_path}", "skip")
            skipped_count += 1
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
                trigger_plex_update(movie_id)
                filtered_log(f"[UPDATE] '{title}' processed.", "update")
                updated_count += 1
            except Exception as e:
                safe_log(f"Error updating record for '{title}': {e}", logging.ERROR)
                error_count += 1
        else:
            filtered_log(f"[SKIP] Skipping update for '{title}' due to folder rename failure.", "skip")
            skipped_count += 1
        
        if slow_mode:
            time.sleep(SLOW_MODE_SLEEP)
        else:
            time.sleep(FAST_MODE_SLEEP)

def option_remove_edition():
    global processed_count, skipped_count, updated_count, error_count
    safe_log("Starting option: Remove edition block...", logging.INFO)
    movies = get_radarr_movies()
    total = len(movies)
    for index, movie in enumerate(movies, start=1):
        processed_count += 1
        title = movie.get("title")
        safe_log(f"Processing movie {index}/{total}: {title}", logging.INFO)
        movie_id = movie.get("id")
        try:
            movie = refresh_and_get_movie(movie_id)
            if movie is None:
                safe_log(f"Skipping '{title}' due to refresh failure.", logging.ERROR)
                skipped_count += 1
                continue
        except Exception as e:
            safe_log(f"Failed to refresh movie '{title}': {e}", logging.ERROR)
            error_count += 1
            continue
        
        root = movie.get("rootFolderPath")
        current_folder = movie.get("folderName")
        if not root or not current_folder:
            safe_log(f"Skipping movie '{title}' due to missing rootFolderPath or folderName.", logging.ERROR)
            skipped_count += 1
            continue
        
        if os.path.isabs(current_folder):
            current_folder = os.path.basename(current_folder)
        current_full_path = os.path.join(root, current_folder)
        if not os.path.exists(current_full_path):
            safe_log(f"Old folder path does not exist: {current_full_path}", logging.ERROR)
            safe_log(f"Skipping movie '{title}'", logging.ERROR)
            skipped_count += 1
            continue
        
        new_rel_folder = re.sub(r"\{edition-[^}]*\}", "", current_folder).strip()
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
                trigger_plex_update(movie_id)
                filtered_log(f"[UPDATE] '{title}' processed.", "update")
                updated_count += 1
            except Exception as e:
                safe_log(f"Error updating record for '{title}': {e}", logging.ERROR)
                error_count += 1
        else:
            safe_log(f"Skipping update for '{title}' due to folder rename failure.", logging.ERROR)
            skipped_count += 1
        
        time.sleep(FAST_MODE_SLEEP)

def print_summary():
    safe_log("\n--- Summary ---", logging.INFO)
    safe_log(f"Total movies processed: {processed_count}", logging.INFO)
    safe_log(f"Total movies skipped (including missing folders): {skipped_count + empty_count}", logging.INFO)
    safe_log(f"Total movies updated: {updated_count}", logging.INFO)
    safe_log(f"Total errors: {error_count}", logging.INFO)

def settings_menu():
    global VERBOSE, DISPLAY_LOG_MODE, SHOW_RESOLUTION, SHOW_CODEC, SHOW_LANGUAGE
    global INCLUDE_RATINGS, FAST_MODE_SLEEP, SLOW_MODE_SLEEP, REFRESH_DELAY, CONTINUOUS_MODE_INTERVAL, REVERSE_ORDER, TRIGGER_PLEX_UPDATE
    print("\n--- Settings Menu ---")
    try:
        v = input("Verbose logging? (Y/n) [default Y]: ").strip().lower() or "y"
        VERBOSE = (v == "y")
        dlm = input("Display log mode? (all/changed/skipped/both) [default all]: ").strip().lower() or "all"
        if dlm in ("all", "changed", "skipped", "both"):
            DISPLAY_LOG_MODE = dlm
        else:
            safe_log("Invalid display log mode. Keeping current.", logging.ERROR)
        sr = input("Include Resolution? (Y/n) [default Y]: ").strip().lower() or "y"
        SHOW_RESOLUTION = (sr == "y")
        sc = input("Include Codec? (Y/n) [default Y]: ").strip().lower() or "y"
        SHOW_CODEC = (sc == "y")
        sl = input("Include Language? (Y/n) [default n]: ").strip().lower() or "n"
        SHOW_LANGUAGE = (sl == "y")
        ir = input("Include Ratings? (Y/n) [default Y]: ").strip().lower() or "y"
        INCLUDE_RATINGS = (ir == "y")
        try:
            FAST_MODE_SLEEP = float(input("Fast mode sleep time (sec, default 0.5): ") or "0.5")
            SLOW_MODE_SLEEP = float(input("Slow mode sleep time (sec, default 3.0): ") or "3.0")
            REFRESH_DELAY = float(input("Refresh delay (sec, default 5): ") or "5")
            CONTINUOUS_MODE_INTERVAL = float(input("Continuous mode interval (sec, default 60): ") or "60")
        except Exception as e:
            safe_log(f"Invalid input for sleep times. Using defaults. Error: {e}", logging.ERROR)
        rev = input("Process movies in reverse order? (Y/n) [default n]: ").strip().lower() or "n"
        REVERSE_ORDER = (rev == "y")
        plex = input("Trigger Plex update after Radarr update? (Y/n) [default Y]: ").strip().lower() or "y"
        TRIGGER_PLEX_UPDATE = (plex == "y")
        safe_log(f"Reverse order processing set to: {REVERSE_ORDER}", logging.INFO)
        safe_log(f"Trigger Plex update set to: {TRIGGER_PLEX_UPDATE}", logging.INFO)
    except Exception as e:
        safe_log(f"Error in settings menu: {e}", logging.ERROR)

def continuous_mode():
    safe_log("Entering continuous mode. Press Ctrl+C to exit.", logging.INFO)
    try:
        while True:
            option_add_edition(reverse_order=REVERSE_ORDER, slow_mode=False)
            safe_log(f"Sleeping for {CONTINUOUS_MODE_INTERVAL} seconds before next check...", logging.INFO)
            time.sleep(CONTINUOUS_MODE_INTERVAL)
    except KeyboardInterrupt:
        safe_log("Continuous mode interrupted by user.", logging.INFO)

def main_menu():
    print("\nMetadatarr Interactive")
    print("-----------------------")
    print("Options:")
    print("1. Add/Update edition block to movie folders (fast)")
    print("2. Remove edition block from movie folders")
    print("3. Add/Update edition block to movie folders (slow mode - refresh each record)")
    print("4. Settings")
    print("5. Exit")
    return input("Enter option (1-5): ").strip()

# Global counters for summary
processed_count = 0
skipped_count = 0
updated_count = 0
error_count = 0
empty_count = 0

def main():
    global processed_count, skipped_count, updated_count, error_count
    while True:
        choice = main_menu()
        if choice == "1":
            processed_count = skipped_count = updated_count = error_count = empty_count = 0
            option_add_edition(reverse_order=REVERSE_ORDER, slow_mode=False)
            print_summary()
        elif choice == "2":
            processed_count = skipped_count = updated_count = error_count = 0
            option_remove_edition()
            print_summary()
        elif choice == "3":
            processed_count = skipped_count = updated_count = error_count = 0
            safe_log("Running in slow mode: Refreshing each movie record before update.", logging.INFO)
            option_add_edition(reverse_order=REVERSE_ORDER, slow_mode=True)
            print_summary()
        elif choice == "4":
            settings_menu()
        elif choice == "5":
            break
        else:
            safe_log("Invalid choice. Please try again.", logging.ERROR)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        safe_log(f"Unhandled error: {e}", logging.ERROR)
