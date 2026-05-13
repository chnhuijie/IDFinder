import os
import sys
import time
import random
import logging
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

# Set up logging for clear feedback in your PowerShell window
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
BASE_API = "https://uma.moe/api/v4/circles"

def safe_get(url):
    """
    Fetches data using curl_cffi to mimic a real Chrome browser.
    Uses residential-friendly delays to keep your IP safe.
    """
    # Jitter delay: Mimics a human scrolling and clicking (5-10 seconds)
    time.sleep(random.uniform(5.0, 10.0)) 
    
    # URL Normalization: Prevents 404s by adding a clean trailing slash and ref
    current_url = url
    if "/list" not in url: 
        current_url = f"{url}/?ref=web_{int(time.time())}"

    try:
        res = requests.get(
            current_url, 
            impersonate="chrome120", 
            timeout=30,
            headers={
                "Referer": "https://uma.moe/ranking",
                "Origin": "https://uma.moe",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        
        if res.status_code == 200:
            return res.json()
        
        # If 404, the club likely disbanded or ID changed during reset
        if res.status_code == 404:
            log.warning(f"404/Not Found (Club likely disbanded): {current_url}")
            return None
            
        log.warning(f"Status {res.status_code} for {current_url}")
    except Exception as e:
        log.error(f"Error fetching {current_url}: {e}")
    return None

def main(start, end):
    start, end = int(start), int(end)
    
    # 1. Fetch the Top 100 Discovery List
    list_url = f"{BASE_API}/list?page=0&limit=100&sort_by=rank&sort_dir=asc"
    data = safe_get(list_url)
    
    if not data or "circles" not in data:
        log.error("Could not fetch the top 100 list. Site may be updating.")
        return

    all_clubs = data["circles"]
    target = all_clubs[start:end]
    
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    log.info(f"Stealth Syncing Ranks {start+1} to {end} via MyPC")

    for club in target:
        cid = club.get("circle_id")
        name = club.get("name")
        
        # Phase 2: Fetch specific club rosters
        club_url = f"{BASE_API}/{cid}"
        detail = safe_get(club_url)
        
        if detail and "members" in detail:
            ops = [
                UpdateOne(
                    {"mid": str(m.get("id") or m.get("viewer_id"))},
                    {"$set": {"name": m.get("name"), "club": name, "last_seen": time.time()}},
                    upsert=True
                ) for m in (detail["members"] or [])
            ]
            if ops: 
                db.bulk_write(ops, ordered=False)
                log.info(f"Successfully Synced: {name}")
        else:
            log.info(f"Skipping {name} (API returned no roster data)")

    log.info(f"Batch {start+1}-{end} finished. Closing connection.")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
