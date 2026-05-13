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
API_URL = "https://uma.moe/api/v4/circles"

def safe_get(url):
    # Base delay between individual club requests
    time.sleep(random.uniform(10.0, 15.0)) 
    try:
        res = requests.get(url, impersonate="chrome120", timeout=30)
        if res.status_code == 200: return res.json()
        if res.status_code == 404: log.warning(f"404/Block Skip: {url}")
    except Exception as e:
        log.error(f"Error: {e}")
    return None

def main(start, end):
    start, end = int(start), int(end)
    # Fetch the first page of rankings (contains Top 100)
    data = safe_get(f"{API_URL}/list?page=0&limit=100&sort_by=rank&sort_dir=asc")
    
    if not data or "circles" not in data:
        log.error("Could not fetch the top 100 list.")
        return

    all_clubs = data["circles"]
    target = all_clubs[start:end]
    
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    log.info(f"Processing Ranks {start+1} to {end}")

    for club in target:
        cid = club.get("circle_id")
        name = club.get("name")
        detail = safe_get(f"{API_URL}/{cid}")
        
        if detail and "members" in detail:
            ops = [
                UpdateOne(
                    {"mid": str(m.get("id") or m.get("viewer_id"))},
                    {"$set": {"name": m.get("name"), "club": name, "last_seen": time.time()}},
                    upsert=True
                ) for m in (detail["members"] or [])
            ]
            if ops: db.bulk_write(ops, ordered=False)
            log.info(f"Synced Club: {name}")

    # 3-Minute Interval Cooldown
    log.info("Batch finished. Sleeping for 3 minutes to maintain stealth...")
    time.sleep(180) 

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
