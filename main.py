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

# 1. ADD THIS AT THE VERY TOP (after your imports)
# This creates a "persistent" connection that saves security cookies
session = requests.Session()

def safe_get(url):
    """
    Now uses the 'session' object to mimic a browser that stays open.
    """
    # Human-like delay
    time.sleep(random.uniform(8.0, 15.0)) 
    
    current_url = url
    if "/list" not in url: 
        current_url = f"{url}/?ref=web_{int(time.time())}"

    try:
        # NOTICE: Changed from requests.get to session.get
        res = session.get(
            current_url, 
            impersonate="chrome120", 
            timeout=30,
            headers={
                "Referer": "https://uma.moe/ranking",
                "Origin": "https://uma.moe",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        
        if res.status_code == 200:
            return res.json()
        
        if res.status_code == 404:
            log.warning(f"404/Block Skip: {current_url}")
            return None
            
        log.warning(f"Status {res.status_code} for {current_url}")
    except Exception as e:
        log.error(f"Error fetching {current_url}: {e}")
    return None

def main(start, end):
    start, end = int(start), int(end)
    
    # 2. THE "SECRET KEY": Warming up the session
    # This hits the site to grab the security cookies needed for Eden/TouchGrass
    log.info("Warming up browser session to bypass security checks...")
    session.get("https://uma.moe/ranking", impersonate="chrome120")
    time.sleep(5) 
    
    # 3. Now fetch the list using the session
    list_url = f"{BASE_API}/list?page=0&limit=100&sort_by=rank&sort_dir=asc"
    data = safe_get(list_url)
    
    # ... rest of your code
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
