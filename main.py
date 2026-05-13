import os
import sys
import time
import random
import requests
import logging
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Config
MONGO_URI = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
API_URL = "https://uma.moe/api/v4/circles"

# Session setup with "Human" fingerprint
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://uma.moe/leaderboard",
    "Accept-Language": "en-US,en;q=0.9"
})

def safe_get(url, retries=3):
    for attempt in range(retries):
        try:
            # Human-like delay
            time.sleep(random.uniform(3.0, 7.0))
            res = session.get(url, timeout=15)
            
            if res.status_code == 200:
                return res.json()
            
            # GHOST BLOCK DETECTION
            if res.status_code == 404:
                log.warning(f"404 Not Found: {url}. Likely a Ghost Block.")
                return None # Skip immediately
                
            log.warning(f"HTTP {res.status_code} on attempt {attempt+1}")
            time.sleep(5 * (attempt + 1))
        except Exception as e:
            log.error(f"Error: {e}")
    return None

def run_batch(start, end):
    # Discovery step
    log.info(f"Starting Layer 1: Index {start} to {end}")
    circles = []
    for p in range(15):
        data = safe_get(f"{API_URL}/list?page={p}&limit=100&sort_by=rank&sort_dir=asc")
        if data: circles.extend(data.get("circles", []))
    
    if not circles:
        log.error("Failed to fetch club list. Blocked?")
        return

    # Process range
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    target = circles[start:end]
    
    for c in target:
        cid = c.get("circle_id")
        name = c.get("name")
        detail = safe_get(f"{API_URL}/{cid}")
        
        if detail and "members" in detail:
            # Logic to upsert into MongoDB
            ops = [
                UpdateOne(
                    {"mid": str(m.get("id") or m.get("viewer_id"))},
                    {"$set": {"name": m.get("name"), "club": name, "last_seen": time.time()}},
                    upsert=True
                ) for m in (detail["members"] or [])
            ]
            if ops: db.bulk_write(ops)
            log.info(f"Synced {name} ({cid})")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        run_batch(int(sys.argv[1]), int(sys.argv[2]))
