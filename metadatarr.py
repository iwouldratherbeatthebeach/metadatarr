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

LOG_LEVEL = logging.INFO  # Set to logging.DEBUG for more detailed output

# Ensure stdout uses UTF-8 (for Windows Python 3.7+)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(levelname)s] %(message)s',
    stream=sys.stdout
)

def safe_log(message, level=logging.INFO):
    """Log a message safely, avoiding Unicode errors."""
    try:
        logging.log(level, message)
    except UnicodeEncodeError:
        safe_message = message.encode("ascii", "backslashreplace").decode("ascii")
        logging.log(level, safe_message)

# Radarr configuration
RADARR_URL = "http://localhost:7878"  # Update if needed
RADARR_API_KEY = "<YOUR_RADARR_API_KEY>"  # Replace with your actual API key

# For this version, we use only the X-Api-Key header (Basic Auth disabled)
USE_BASIC_AUTH = False

# Choose which rating to use from the Radarr record.
# Options: "tmdb", "imdb", "metacritic", "rottenTomatoes"
RATING_SOURCE = "tmdb"

# Set to True to include rating information in the edition string.
INCLUDE_RATINGS = True

OVERWRITE_EXISTING_EDITION = True
FORCE_RADARR_UPDATE_ON_RENAME_FAILURE = False

# Options for edition string components
SHOW_RESOLUTION = True     # e.g., 720p, 1080p, 4K, etc.
SHOW_CODEC = False
SHOW_LANGUAGE = False

SHOW_CRITIC_RATING = True   # Use one rating value from the record
SHOW_AUDIENCE_RATING = False
CRITIC_LABEL = ""
AUDIENCE_LABEL = "A:"

QUALITY_MAPPING = {
    # DVD Releases
    "DVD-480p": "480p",
    "DVD-576p": "576p",
    "DVD": "DVD",
    # Standard Definition (SD)
    "SDTV": "SDTV",
    "TVRip": "TVRip",
    # High Definition (HD)
    "HDTV-480p": "480p",
    "HDTV-720p": "720p",
    "HDTV-1080p": "1080p",
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
    # Ultra HD / 4K
    "Bluray-4K": "4K",
    "UltraHD-2160p": "4K",
    "WEBRip-4K": "4K",
    "WEBDL-4K": "4K",
    "WEBRip-2160p": "4K",
    "WEBDL-2160p": "4K",
    # Other Formats
    "CAM": "CAM",
    "HDTS": "HDTS",
    "TS": "TS",
    "TC": "TC",
    "Screener": "Screener",
    "VHSRip": "VHS"
}

# Order of metadata parts for the edition string.
METADATA_ORDER = ["rating", "resolution", "codec", "language"]

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

def build_edition_string(movie):
    """
    Build the edition string using data from the Radarr movie record.
    Uses movieFile.quality for resolution and the movie.ratings object for rating.
    """
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
            metadata_parts["codec"] = codec
            safe_log(f"Codec: {codec}", logging.DEBUG)

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
                metadata_parts["rating"] = str(rating_value)
                safe_log(f"Rating (from {RATING_SOURCE}): {metadata_parts['rating']}", logging.DEBUG)
            except Exception as e:
                safe_log(f"Error processing rating value: {e}", logging.ERROR)

    parts_list = [metadata_parts[key] for key in METADATA_ORDER if key in metadata_parts]
    edition_string = " - ".join(parts_list) if parts_list else None
    safe_log(f"Built edition string: {edition_string}", logging.DEBUG)
    return edition_string

def update_movie_folder(movie, new_folder_abs):
    """
    Update the Radarr movie record with the new folder name.
    Both folderName and path fields are updated to the new absolute folder path.
    """
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
    """Trigger a refresh for the movie via Radarr's command API."""
    command_url = f"{RADARR_URL}/api/v3/command"
    payload = {
        "name": "RefreshMovie",
        "movieIds": [movie_id]
    }
    headers = get_headers()
    response = requests.post(command_url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    safe_log(f"Triggered refresh for movie id {movie_id}", logging.INFO)
    return response.json()

def rename_physical_directory(old_full_path, new_full_path):
    """
    Rename the directory on disk using os.rename(), with a fallback to shutil.move() if needed.
    """
    if not os.path.exists(old_full_path):
        safe_log(f"Old folder path does not exist: {old_full_path}", logging.ERROR)
        return False
    if os.path.exists(new_full_path):
        safe_log(f"Destination folder already exists: {new_full_path}", logging.ERROR)
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

def option_add_edition():
    """
    For each movie in Radarr, compute a new folder name that includes an edition block
    based on data from the movie record. The edition block is added (or overwritten) to the folder name.
    """
    safe_log("Starting option: Add/Update edition block...", logging.INFO)
    movies = get_radarr_movies()
    # Regex to detect an existing edition block in curly braces at the end.
    edition_pattern = re.compile(r"\s*\{edition-.*\}$", re.IGNORECASE)
    for movie in movies:
        root = movie.get("rootFolderPath")
        current_folder = movie.get("folderName")
        if not root or not current_folder:
            safe_log(f"Skipping movie '{movie.get('title')}' due to missing rootFolderPath or folderName.", logging.ERROR)
            continue

        # Use only the base name if current_folder is absolute.
        if os.path.isabs(current_folder):
            current_folder = os.path.basename(current_folder)
        current_full_path = os.path.join(root, current_folder)
        if not os.path.exists(current_full_path):
            safe_log(f"Old folder path does not exist: {current_full_path}", logging.ERROR)
            safe_log(f"Skipping movie '{movie.get('title')}'.", logging.ERROR)
            continue

        # Remove any existing edition block.
        if edition_pattern.search(current_folder):
            base_folder = edition_pattern.sub("", current_folder).strip()
            safe_log(f"Removed existing edition block for '{movie.get('title')}'.", logging.DEBUG)
        else:
            base_folder = current_folder.strip()

        edition = build_edition_string(movie)
        if edition:
            new_rel_folder = f"{base_folder} {{edition-{edition}}}"
        else:
            new_rel_folder = base_folder

        if new_rel_folder == current_folder:
            safe_log(f"[SKIP] No folder name change needed for '{movie.get('title')}'", logging.INFO)
            continue

        new_full_path = os.path.join(root, new_rel_folder)
        safe_log(f"[UPDATE] '{movie.get('title')}'", logging.INFO)
        safe_log(f"  Current folder: {current_full_path}", logging.INFO)
        safe_log(f"  New folder:     {new_full_path}", logging.INFO)

        renamed = rename_physical_directory(current_full_path, new_full_path)
        if not renamed and FORCE_RADARR_UPDATE_ON_RENAME_FAILURE:
            safe_log(f"Physical rename failed but forcing Radarr update for '{movie.get('title')}'.", logging.WARNING)
            renamed = True

        if renamed:
            try:
                update_movie_folder(movie, new_full_path)
                trigger_refresh_movie(movie.get("id"))
            except Exception as e:
                safe_log(f"Error updating Radarr record for '{movie.get('title')}': {e}", logging.ERROR)
        else:
            safe_log(f"Skipping Radarr record update for '{movie.get('title')}' due to folder rename failure.", logging.ERROR)
        
        time.sleep(0.5)

def option_remove_edition():
    """
    For each movie in Radarr, if an edition block exists in the folder name,
    remove it and update the movie record and physical folder accordingly.
    """
    safe_log("Starting option: Remove edition block...", logging.INFO)
    movies = get_radarr_movies()
    # Regex to detect an edition block in curly braces at the end.
    edition_pattern = re.compile(r"\s*\{edition-.*\}$", re.IGNORECASE)
    for movie in movies:
        root = movie.get("rootFolderPath")
        current_folder = movie.get("folderName")
        if not root or not current_folder:
            safe_log(f"Skipping movie '{movie.get('title')}' due to missing rootFolderPath or folderName.", logging.ERROR)
            continue

        # Use only the base name if necessary.
        if os.path.isabs(current_folder):
            current_folder = os.path.basename(current_folder)
        current_full_path = os.path.join(root, current_folder)
        if not os.path.exists(current_full_path):
            safe_log(f"Old folder path does not exist: {current_full_path}", logging.ERROR)
            safe_log(f"Skipping movie '{movie.get('title')}'.", logging.ERROR)
            continue

        # Check if an edition block exists.
        if not edition_pattern.search(current_folder):
            safe_log(f"No edition block found for '{movie.get('title')}', skipping.", logging.INFO)
            continue

        # Remove the edition block.
        new_rel_folder = edition_pattern.sub("", current_folder).strip()
        new_full_path = os.path.join(root, new_rel_folder)
        safe_log(f"[UPDATE] '{movie.get('title')}'", logging.INFO)
        safe_log(f"  Current folder: {current_full_path}", logging.INFO)
        safe_log(f"  New folder:     {new_full_path}", logging.INFO)

        renamed = rename_physical_directory(current_full_path, new_full_path)
        if not renamed and FORCE_RADARR_UPDATE_ON_RENAME_FAILURE:
            safe_log(f"Physical rename failed but forcing Radarr update for '{movie.get('title')}'.", logging.WARNING)
            renamed = True

        if renamed:
            try:
                update_movie_folder(movie, new_full_path)
                trigger_refresh_movie(movie.get("id"))
            except Exception as e:
                safe_log(f"Error updating Radarr record for '{movie.get('title')}': {e}", logging.ERROR)
        else:
            safe_log(f"Skipping Radarr record update for '{movie.get('title')}' due to folder rename failure.", logging.ERROR)
        
        time.sleep(0.5)

def main():
    print("Metadatarr Interactive")
    print("-----------------------")
    print("Options:")
    print("1. Add/Update edition block to movie folders")
    print("2. Remove edition block from movie folders")
    choice = input("Enter option (1 or 2): ").strip()
    if choice == "1":
        option_add_edition()
    elif choice == "2":
        option_remove_edition()
    else:
        safe_log("Invalid choice. Exiting.", logging.ERROR)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        safe_log(f"Unhandled error: {e}", logging.ERROR)
