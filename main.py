import os
import sys
import time
import random
import requests
import logging
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
API_URL = "https://uma.moe/api/v4/circles"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://uma.moe/leaderboard",
    "Accept-Language": "en-US,en;q=0.9"
})

def safe_get(url, retries=2):
    for attempt in range(retries):
        try:
            # Human-like "reading" delay
            time.sleep(random.uniform(5.0, 12.0)) 
            res = session.get(url, timeout=15)
            
            if res.status_code == 200:
                return res.json()
            
            if res.status_code == 404:
                log.warning(f"Ghost Block on {url}. Skipping.")
                return None
                
            time.sleep(10 * (attempt + 1))
        except Exception as e:
            log.error(f"Network error: {e}")
    return None

def run_layer_one(start, end):
    log.info(f"Ingesting indices {start} to {end}")
    
    # Discovery phase
    all_clubs = []
    for p in range(15):
        data = safe_get(f"{API_URL}/list?page={p}&limit=100&sort_by=rank&sort_dir=asc")
        if data:
            all_clubs.extend(data.get("circles", []))
        else:
            log.error(f"Failed to fetch page {p}. API is likely blocking this IP.")
            return

    # Deep Scrape phase
    target_clubs = all_clubs[start:end]
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    for club in target_clubs:
        cid = club.get("circle_id")
        cname = club.get("name")
        detail = safe_get(f"{API_URL}/{cid}")
        
        if detail and "members" in detail:
            ops = [
                UpdateOne(
                    {"mid": str(m.get("id") or m.get("viewer_id"))},
                    {"$set": {"name": m.get("name"), "club": cname, "last_seen": time.time()}},
                    upsert=True
                ) for m in (detail["members"] or [])
            ]
            if ops:
                db.bulk_write(ops, ordered=False)
            log.info(f"Successfully replicated: {cname}")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        run_layer_one(int(sys.argv[1]), int(sys.argv[2]))
