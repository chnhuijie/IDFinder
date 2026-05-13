import os
import sys
import time
import random
import logging
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
# Base URL without the trailing slash
BASE_API = "https://uma.moe/api/v4/circles"

def safe_get(url):
    # Jitter to mimic human reading time
    time.sleep(random.uniform(10.0, 18.0)) 
    
    # URL TRICK: Randomly choose between a trailing slash or a timestamp parameter
    # This turns ".../12345" into ".../12345/" or ".../12345?cache=1715600000"
    if "/list" not in url: # Only apply to specific club IDs
        if random.choice([True, False]):
            url = f"{url}/"
        else:
            url = f"{url}?ref=web_{int(time.time())}"

    try:
        res = requests.get(
            url, 
            impersonate="chrome120", 
            timeout=30,
            headers={
                "Referer": "https://uma.moe/leaderboard",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
        
        if res.status_code == 200:
            return res.json()
        
        if res.status_code == 404:
            log.warning(f"404/Block Skip: {url}")
            return None
            
        log.warning(f"Status {res.status_code} for {url}")
    except Exception as e:
        log.error(f"Error fetching {url}: {e}")
    return None

def main(start, end):
    start, end = int(start), int(end)
    
    # 1. Fetch Discovery List
    data = safe_get(f"{BASE_API}/list?page=0&limit=100&sort_by=rank&sort_dir=asc")
    
    if not data or "circles" not in data:
        log.error("Could not fetch the top 100 list.")
        return

    all_clubs = data["circles"]
    target = all_clubs[start:end]
    
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    log.info(f"Stealth Syncing Ranks {start+1} to {end}")

    for club in target:
        cid = club.get("circle_id")
        name = club.get("name")
        # Construct specific club URL
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
                log.info(f"Synced: {name}")

    # Cooldown for the next matrix batch
    log.info("Batch complete. Cooling down 120s...")
    time.sleep(120)

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
