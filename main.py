import os, sys, time, random, logging, datetime
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def safe_get(url):
    time.sleep(random.uniform(5.0, 10.0)) 
    try:
        res = session.get(url.rstrip('/'), impersonate="chrome120", timeout=30)
        if res.status_code == 200: return res.json()
    except Exception as e:
        log.error(f"Request error: {e}")
    return None

def main(start, end):
    start, end = int(start), int(end)
    now_dt = datetime.datetime.now()
    curr_year, curr_month = now_dt.year, now_dt.month
    
    log.info(f"--- Starting Sync: Range {start} to {end} ---")
    session.get("https://uma.moe/ranking", impersonate="chrome120")
    
    api_page = 0 if start < 100 else 1
    api_start = start if api_page == 0 else (start - 100)
    api_end = end if api_page == 0 else (end - 100)
    
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
        absolute_club_rank = start + index 
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
                # Drop entries lacking valid IDs
                if not p_id or p_id.lower() == "none":
                    continue
                
                # Drop entries explicitly tagged as left/inactive by the system
                if m.get("left") is True or m.get("active") is False:
                    continue
                    
                # Drop members showing 0 cumulative point updates for the tracked month
                if m.get("fans") == 0 or m.get("point") == 0:
                    continue
                
                # If the item clears all validation checks, it is an active roster spot
                valid_members.append((p_id, m))
            
            # Now this slice will capture only true active users!
            target_members = valid_members[:30]
            ops = []
            for p_id, m in target_members:
                p_name = m.get("name") or m.get("nickname") or "Unknown"

                ops.append(UpdateOne(
                    {"mid": p_id},
                    {"$set": {
                        "name": p_name, 
                        "club": club_name,
                        "club_tier": "Top 100" if absolute_club_rank < 100 else "Top 200",
                        "last_seen": time.time()
                    }},
                    upsert=True
                ))
            
            if ops: 
                db.bulk_write(ops, ordered=False)
                log.info(f"Successfully Synced: {club_name} (Rank {absolute_club_rank + 1}) | Active Members: {len(target_members)}")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
