import os
import sys
import time
import random
import logging
import requests
from pymongo import MongoClient, UpdateOne

# =========================
# LOGGING & CONFIG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "uma_tracker"
COLLECTION_NAME = "members"
API_URL = "https://uma.moe/api/v4/circles"

# =========================
# CORE ENGINE
# =========================
_mongo_client = None

def get_collection():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URI)
    return _mongo_client[DB_NAME][COLLECTION_NAME]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://uma.moe/leaderboard"
})

def safe_get(url, retries=4):
    """GET with exponential backoff and 404 Fast-Fail."""
    for attempt in range(retries):
        try:
            # Human-like jitter
            time.sleep(random.uniform(2.0, 5.0))
            res = session.get(url, timeout=15)
            
            if res.status_code == 200:
                return res.json()
            
            # CRITICAL FIX: Fast-fail on 404 to avoid Ghost Blocks
            if res.status_code == 404:
                log.warning(f"404 Not Found (Ghost Block?): {url}. Skipping.")
                return None
                
            if res.status_code == 429:
                wait = int(res.headers.get("Retry-After", 60))
                log.warning(f"Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                backoff = 2 ** attempt
                log.warning(f"HTTP {res.status_code}. Retrying in {backoff}s...")
                time.sleep(backoff)
        except Exception as e:
            log.error(f"Request failed: {e}")
    return None

def send_webhook(content):
    """Safe Discord delivery with chunking."""
    if not WEBHOOK_URL or not content: return
    chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
    for chunk in chunks:
        requests.post(WEBHOOK_URL, json={"content": chunk})

# =========================
# TRACKING LOGIC
# =========================
def run_tracker(start_idx, end_idx):
    log.info(f">>> TRACK mode: circles {start_idx} to {end_idx}")
    
    # Discovery: Fetching leaderboard IDs
    all_circles = []
    # Using limit=100 as confirmed by circles.rs
    for p in range(15):
        data = safe_get(f"{API_URL}/list?page={p}&limit=100&sort_by=rank&sort_dir=asc")
        if data: all_circles.extend(data.get("circles", []))
    
    if not all_circles:
        log.error("Failed to fetch leaderboard discovery.")
        return

    collection = get_collection()
    # Load state for transfer alerts
    previous_state = {doc["mid"]: doc for doc in collection.find({}, {"mid": 1, "club": 1, "name": 1})}
    
    target_range = all_circles[start_idx:end_idx]
    current_batch = {}
    transfers = []

    for circle in target_range:
        cid = circle.get("circle_id")
        club_name = circle.get("name")
        detail = safe_get(f"{API_URL}/{cid}")
        
        if detail and "members" in detail:
            for m in (detail["members"] or []):
                mid = str(m.get("id") or m.get("viewer_id"))
                info = {"name": m.get("name"), "club": club_name}
                current_batch[mid] = info
                
                if mid in previous_state and previous_state[mid]["club"] != club_name:
                    transfers.append(f"🔄 **{info['name']}**: {previous_state[mid]['club']} → {club_name} (`{mid}`)")

    if transfers:
        send_webhook(f"📊 **Transfers ({start_idx}-{end_idx})**\n" + "\n".join(transfers))

    # Database Update
    timestamp = time.time()
    ops = [UpdateOne({"mid": mid}, {"$set": {**info, "last_seen": timestamp}}, upsert=True) 
           for mid, info in current_batch.items()]
    if ops:
        result = collection.bulk_write(ops, ordered=False)
        log.info(f"Batch {start_idx}-{end_idx} complete. Updated {len(ops)} members.")

def cleanup():
    """Removes stale players and reports vanished IDs."""
    log.info(">>> Running cleanup...")
    collection = get_collection()
    cutoff = time.time() - 93600 # 26 hours
    vanished = list(collection.find({"last_seen": {"$lt": cutoff}}))
    
    if vanished:
        report = "🔴 **Vanished (Left Top 1500)**\n" + "\n".join(
            [f"- **{m['name']}** (Last: {m['club']}) ID: `{m['mid']}`" for m in vanished[:30]]
        )
        send_webhook(report)
        collection.delete_many({"last_seen": {"$lt": cutoff}})
    log.info(f"Cleanup finished. Removed {len(vanished)} stale records.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
        
    mode = sys.argv[1].upper()
    if mode == "CLEANUP":
        cleanup()
    else:
        run_tracker(int(sys.argv[1]), int(sys.argv[2]))
