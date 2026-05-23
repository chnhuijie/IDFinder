import os, sys, time, random, logging, datetime
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def safe_get(url):
    # Safe humanized time interval between profile scraping loops
    time.sleep(random.uniform(3.0, 6.0)) 
    try:
        res = session.get(url.rstrip('/'), impersonate="chrome120", timeout=30)
        if res.status_code == 200: return res.json()
    except Exception as e:
        log.error(f"Request error: {e}")
    return None

def process_club_sub_batch(batch_start, batch_end, curr_year, curr_month):
    """Processes a micro-chunk of 20 clubs sequentially to optimize server footprint."""
    # 📈 DYNAMIC CLOUD PAGE RESOLUTION
    # Automatically tracks any assignment segment cleanly into the API's 100-row page blocks
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
                
                # 🛡️ GHOST FILTER EXTRACTION LAYER
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

                # Calculate the accurate tier mapping boundary for the Top 500 spectrum
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
                        "club_tier": tier_label,
                        "last_seen": time.time()
                    }},
                    upsert=True
                ))
            
            if ops: 
                db.bulk_write(ops, ordered=False)
                log.info(f"Successfully Synced: {club_name} (Rank {absolute_club_rank + 1}) | Active Members: {len(target_members)}")
                
    client.close()

def main(start, end):
    start, end = int(start), int(end)
    now_dt = datetime.datetime.now()
    curr_year, curr_month = now_dt.year, now_dt.month
    
    log.info(f"--- Starting Sync Stream: Range {start} to {end} ---")
    session.get("https://uma.moe/ranking", impersonate="chrome120")
    
    # 📦 THE INTERNAL 0-20 CHUNKER RULE
    # Breaks your assigned 100-club matrix run into sequential micro-blocks of 20
    current_step = start
    while current_step < end:
        next_step = min(current_step + 20, end)
        log.info(f"📦 Streaming Sub-Batch: Ranks {current_step} through {next_step}")
        
        process_club_sub_batch(current_step, next_step, curr_year, curr_month)
        
        current_step = next_step
        if current_step < end:
            # Let the endpoint breathe between your 20-club segments
            time.sleep(random.uniform(15.0, 30.0))
            
    log.info(f"🏁 Stream Sequence Completed for Range {start}-{end}.")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
