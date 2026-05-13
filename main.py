import os
import sys
import time
import random
import logging
import datetime
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
BASE_API = "https://uma.moe/api/v4/circles"

# Persistent session to carry Cloudflare/Security cookies
session = requests.Session()

def safe_get(url):
    """
    Mimics a real Chrome browser. 
    Uses jittered delays to keep your home IP safe from detection.
    """
    time.sleep(random.uniform(5.0, 10.0)) 
    current_url = url.rstrip('/')

    try:
        res = session.get(
            current_url, 
            impersonate="chrome120", 
            timeout=30,
            headers={
                "Host": "uma.moe",
                "Connection": "keep-alive",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "Referer": "https://uma.moe/ranking",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        
        if res.status_code == 200:
            return res.json()
        
        if res.status_code == 404:
            log.warning(f"404 Skip: {current_url}")
            return None
            
        log.warning(f"Status {res.status_code} for {current_url}")
    except Exception as e:
        log.error(f"Error fetching {current_url}: {e}")
    return None

def main(start, end):
    start, end = int(start), int(end)
    
    # --- AUTOMATED DATE LOGIC ---
    now = datetime.datetime.now()
    curr_year = now.year
    curr_month = now.month
    log.info(f"Syncing for Date: {curr_year}-{curr_month:02d}")
    
    # --- SESSION WARM-UP ---
    log.info("Warming up browser session...")
    session.get("https://uma.moe/ranking", impersonate="chrome120")
    time.sleep(3) 
    
    # 1. Fetch Discovery List
    list_url = f"{BASE_API}/list?page=0&limit=100&sort_by=rank&sort_dir=asc"
    data = safe_get(list_url)
    
    if not data or "circles" not in data:
        log.error("Could not fetch the top 100 list.")
        return

    all_clubs = data["circles"]
    target = all_clubs[start:end]
    
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    log.info(f"Stealth Syncing Ranks {start+1} to {end} via MyPC")

    for club in target:
        cid = club.get("circle_id")
        name = club.get("name")
        
        # Using the updated query format you discovered
        club_url = f"{BASE_API}?circle_id={cid}&year={curr_year}&month={curr_month}"
        detail = safe_get(club_url)
        
        if detail and "members" in detail:
            # FIX: Prioritize viewer_id (the 12-digit public ID) over internal id
            ops = []
            for m in (detail.get("members") or []):
                # We try viewer_id first; if missing, we use id. 
                public_id = str(m.get("viewer_id") or m.get("id"))
                
                ops.append(UpdateOne(
                    {"mid": public_id},
                    {"$set": {
                        "name": m.get("name"), 
                        "club": name, 
                        "last_seen": time.time()
                    }},
                    upsert=True
                ))
            
            if ops: 
                db.bulk_write(ops, ordered=False)
                log.info(f"Synced: {name}")
        else:
            log.info(f"Skipping {name} (No roster data)")

    log.info(f"Batch {start+1}-{end} finished.")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
