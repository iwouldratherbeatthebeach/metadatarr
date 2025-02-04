Metadatarr
===========

Metadatarr is a Python script that renames movie directories and updates your Radarr library by to maximize on Plex's {edition-...} feature by appending a custom edition string to each movie’s folder name. The edition string is built using data available directly from the Radarr API (such as quality and ratings) and is formatted as a token in curly braces (e.g. {edition-4.4 - 720p}). Any pre-existing edition block is overwritten.

IMPORTANT:
-----------
Before using this script on your full library, back up your data and test on a small subset of movies. Also, if Radarr’s automatic renaming is enabled, it may override your changes. Consider disabling or adjusting the auto-renaming settings in Radarr’s Media Management → Movie Naming.

# Features
--------
- Custom Edition Token:
  Appends a custom edition token to movie folder names in the format {edition-<data>}.
  
- Data from Radarr:
  Builds the edition string using:
    - Quality information from the movie’s movieFile.quality field (mapped via an expanded quality mapping dictionary that includes keys like "WEBDL-480p" mapped to "480p" and entries for 2160p sources).
    - Rating information from the movie’s ratings object. You can choose which rating source to use (e.g. "tmdb", "imdb", "metacritic", or "rottenTomatoes"). The rating value is rounded to one decimal place.
  
- Directory & Record Update:
  The script renames the physical movie directory on disk and then updates the Radarr record by setting both the folderName and path fields to the new absolute folder path.
  
- Refresh Trigger:
  After updating, the script triggers a refresh command via Radarr’s API so that the changes are re-scanned.
  
- Configurable Rating Inclusion:
  You can choose whether to include rating information in the edition string by setting the INCLUDE_RATINGS flag.

Prerequisites
-------------
- Python 3.x must be installed on your system.
- Required Python Packages:
    Install the required packages with:
      pip install requests

Configuration
-------------
Before running Metadatarr, edit the configuration section at the top of the script (Metadatarr.py):

- RADARR_URL:
    Set to the base URL of your Radarr installation (e.g. http://localhost:7878).

- RADARR_API_KEY:
    Replace <YOUR_RADARR_API_KEY> with your actual Radarr API key.

- RATING_SOURCE:
    Choose which rating to use from the Radarr record. Valid options include "tmdb", "imdb", "metacritic", or "rottenTomatoes" (default is "tmdb").

- INCLUDE_RATINGS:
    Set to True to include rating information in the edition string; set to False to omit ratings.

- QUALITY_MAPPING:
    The QUALITY_MAPPING dictionary maps quality strings (as returned by Radarr) to your preferred shorthand. Adjust this mapping as needed.

- OVERWRITE_EXISTING_EDITION:
    Set to True to remove any pre-existing edition block from the folder name before appending the new one.

- FORCE_RADARR_UPDATE_ON_RENAME_FAILURE:
    Optionally force updating Radarr’s record even if the physical folder rename fails.

Usage
-----
1. Prepare Your Environment:
   - Ensure your Radarr installation is running.
   - If necessary, temporarily disable Radarr’s automatic renaming (in Media Management → Movie Naming) so that your changes are not overwritten.
   - Back up your movie data.

2. Run the Script:
   Execute the script from the command line:
       python Metadatarr.py
   (Replace Metadatarr.py with the actual filename if different.)

3. Review the Output:
   The script logs its progress to the console, including:
     - Fetching movie data from Radarr.
     - Renaming directories on disk.
     - Updating the Radarr record (both the folderName and path fields).
     - Triggering a refresh for each movie.

How It Works
------------
- Data Fetching:
  The script retrieves the complete movie records from the Radarr API using your API key.

- Edition String Construction:
  It builds an edition string by combining:
    - Quality information from the movieFile.quality field (after mapping through QUALITY_MAPPING).
    - (Optionally) Rating information from the movie’s ratings object (using the source specified by RATING_SOURCE), rounded to one decimal place.
  These components are joined using a dash (e.g. "4.4 - 720p").

- Renaming Process:
  The script renames the physical movie directory on disk and then updates the Radarr record by setting both the folderName and path fields to the new absolute folder path.

- Refresh:
  Finally, the script triggers a refresh command via Radarr’s API so that the updated folder name is recognized.

Troubleshooting
---------------
- Auto-Renaming Overwrites:
  If Radarr automatically renames your movies (based on its naming template), it may override your updates. Disable auto-renaming temporarily or adjust the naming template to allow folder names containing your edition token.

- API Update Issues:
  If your updates are not being applied, ensure that you’re sending a complete movie record (not just the modified fields) in your PUT requests. Radarr’s API expects a full object for updates.

- Folder Permissions:
  Verify that the user running the script has permission to rename directories on disk.
