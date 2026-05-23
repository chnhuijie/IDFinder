import os, sys, time, random, logging, datetime
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def send_discord_log(message):
    """Sends active loop live-stream status signals directly to your log channel."""
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        except Exception as e:
            log.error(f"Failed to send Discord log: {e}")

def safe_get(url):
    time.sleep(random.uniform(3.0, 6.0)) 
    try:
        res = session.get(url.rstrip('/'), impersonate="chrome120", timeout=30)
        if res.status_code == 200: return res.json()
    except Exception as e:
        log.error(f"Request error: {e}")
    return None

def process_club_sub_batch(batch_start, batch_end, curr_year, curr_month):
    """Processes your assigned range in micro-batches of 20 clubs to maintain a safe footprint."""
    api_page = batch_start // 100
    api_start = batch_start % 100
    api_end = batch_end % 100
    if api_end == 0 and batch_end > batch_start:
        api_end = 100
        
    url = f"{BASE_API}/list?page={api_page}&limit=100&sort_by=rank&sort_dir=asc"
    data = safe_get(url)
    
    if not data or "circles" not in data: 
        log.error(f"Failed to fetch leaderboard list for page {api_page}.")
        return

    target_clubs = data["circles"][api_start:api_end]
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    club_rank_collection = client["uma_tracker"]["clubs"]
    
    for index, club in enumerate(target_clubs):
        absolute_club_rank = batch_start + index 
        cid, club_name = club.get("circle_id"), club.get("name")
        
        # Unique Circle ID serves as your immutable anchor for rank monitoring
        club_rank_collection.update_one(
            {"circle_id": cid},
            {"$set": {"name": club_name, "last_known_rank": absolute_club_rank, "last_updated": time.time()}},
            upsert=True
        )

        club_url = f"{BASE_API}?circle_id={cid}&year={curr_year}&month={curr_month}"
        detail = safe_get(club_url)
        
        if detail and "members" in detail:
            raw_members = detail.get("members") or []
            valid_members = []
            
            for m in raw_members:
                if not m:
                    continue
                
                p_id = str(m.get("viewer_id") or m.get("id") or "").strip()
                
                # 🛡️ GHOST FILTER LAYER
                if not p_id or p_id.lower() == "none":
                    continue
                if m.get("left") is True or m.get("active") is False:
                    continue
                if m.get("fans") == 0 or m.get("point") == 0:
                    continue
                
                valid_members.append((p_id, m))
            
            target_members = valid_members[:30]
            ops = []
            for p_id, m in target_members:
                p_name = m.get("name") or m.get("nickname") or "Unknown"

                if absolute_club_rank < 100:
                    tier_label = "Top 100"
                elif absolute_club_rank < 200:
                    tier_label = "Top 200"
                else:
                    tier_label = "Top 500"

                ops.append(UpdateOne(
                    {"mid": p_id},
                    {"$set": {
                        "name": p_name, 
                        "club": club_name,
                        "club_id": cid,  # 🆔 Hard-linked to protect against shared club names
                        "club_tier": tier_label,
                        "last_seen": time.time()
                    }},
                    upsert=True
                ))
            
            if ops: 
                db.bulk_write(ops, ordered=False)
                log.info(f"Successfully Synced: {club_name} (Rank {absolute_club_rank + 1}) | Active Members: {len(target_members)}")
                send_discord_log(f"✅ **Synced:** `{club_name}` (Rank {absolute_club_rank + 1}) | Active: {len(target_members)}/30")
                
    client.close()

def main(start, end):
    start, end = int(start), int(end)
    now_dt = datetime.datetime.now()
    curr_year, curr_month = now_dt.year, now_dt.month
    
    log.info(f"--- Starting Sync Stream: Range {start} to {end} ---")
    send_discord_log(f"🛰️ **Tracker Stream Activated:** Syncing ranks {start} to {end}...")
    
    session.get("https://uma.moe/ranking", impersonate="chrome120")
    
    current_step = start
    while current_step < end:
        next_step = min(current_step + 20, end)
        process_club_sub_batch(current_step, next_step, curr_year, curr_month)
        current_step = next_step
        if current_step < end:
            time.sleep(random.uniform(15.0, 30.0))
            
    send_discord_log(f"🏁 **Stream Completed:** Ranks {start} to {end} are fully committed.")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
