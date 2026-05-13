import os
import sys
import time
import random
import requests
from pymongo import MongoClient, UpdateOne

# =========================
# CONFIG & AUTHENTICATION
# =========================
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "uma_tracker"
COLLECTION_NAME = "members"
API_URL = "https://uma.moe/api/v4/circles"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
})

def get_collection():
    client = MongoClient(MONGO_URI)
    return client[DB_NAME][COLLECTION_NAME]

def load_previous_state():
    collection = get_collection()
    state = {}
    # Fetch existing members to compare for club transfers
    for doc in collection.find({}, {"mid": 1, "name": 1, "club": 1}):
        state[doc["mid"]] = {"name": doc["name"], "club": doc["club"]}
    return state

def safe_get(url):
    try:
        time.sleep(random.uniform(1.0, 2.0)) # Prevent rapid-fire requests
        res = session.get(url, timeout=15)
        if res.status_code == 429:
            wait = int(res.headers.get("Retry-After", 60))
            print(f"Throttled. Waiting {wait} seconds...")
            time.sleep(wait)
            return safe_get(url)
        return res.json() if res.status_code == 200 else None
    except Exception as e:
        print(f"Request failed: {e}")
        return None

def fetch_roster(circle):
    cid = circle.get("circle_id")
    name = circle.get("name")
    detail = safe_get(f"{API_URL}/{cid}")
    players = {}
    if detail and "members" in detail:
        for m in (detail["members"] or []):
            mid = str(m.get("id") or m.get("viewer_id"))
            players[mid] = {"name": m.get("name"), "club": name}
    return players

def report_vanished():
    """Identifies and reports IDs not updated in the current 24h cycle."""
    collection = get_collection()
    # 26-hour cutoff to account for runner variations
    cutoff = time.time() - 93600 
    
    vanished = list(collection.find({"last_seen": {"$lt": cutoff}}))
    if vanished and WEBHOOK_URL:
        report = "🔴 **Vanished / Now Clubless (Left Top 1500)**\n"
        report += "\n".join([f"- **{m['name']}** (Last seen in: {m['club']}) [ID: {m['mid']}]" for m in vanished[:25]])
        requests.post(WEBHOOK_URL, json={"content": report})
        # Remove stale data to stay within free tier storage limits
        collection.delete_many({"last_seen": {"$lt": cutoff}})

def main():
    if len(sys.argv) < 3: return
    arg = sys.argv[1]
    
    # Mode: CLEANUP (Runs after all scraping jobs)
    if arg == "CLEANUP":
        print(">>> Analyzing missing players...")
        report_vanished()
        return

    # Mode: SCRAPE (Regular matrix job)
    start_idx, end_idx = int(arg), int(sys.argv[2])
    all_circles = []
    for p in range(15): # Fetch 1500 IDs
        data = safe_get(f"{API_URL}/list?page={p}&limit=100&sort_by=rank&sort_dir=asc")
        if data: all_circles.extend(data.get("circles", []))
    
    target_range = all_circles[start_idx:end_idx]
    previous_state = load_previous_state()
    current_batch = {}
    transfers = []
    
    for circle in target_range:
        roster = fetch_roster(circle)
        for mid, info in roster.items():
            current_batch[mid] = info
            # Detect movement between tracked clubs
            if mid in previous_state and previous_state[mid]["club"] != info["club"]:
                transfers.append(f"🔄 **{info['name']}** [ID: {mid}]: {previous_state[mid]['club']} → {info['club']}")

    if transfers and WEBHOOK_URL:
        msg = f"📊 **Transfer Activity (Rank {start_idx}-{end_idx})**\n" + "\n".join(transfers[:20])
        requests.post(WEBHOOK_URL, json={"content": msg})

    # Perform Upsert to update existing members or insert new ones
    collection = get_collection()
    timestamp = time.time()
    ops = [UpdateOne({"mid": mid}, {"$set": {"mid": mid, **info, "last_seen": timestamp}}, upsert=True) 
           for mid, info in current_batch.items()]
    if ops: collection.bulk_write(ops, ordered=False)

if __name__ == "__main__":
    main()
