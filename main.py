import os, sys, time, random, logging, datetime
import requests as discord_req
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def send_summary(new_count, shift_count, new_clubs_dict, shift_clubs_dict):
    """Sends a breakdown of exactly which clubs experienced player movements."""
    if not DISCORD_WEBHOOK_URL: return
    messages = []
    
    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered the tracking pool.")
        for club, count in new_clubs_dict.items():
            messages.append(f"  • **{club}**: +{count} new player(s)")
            
    if shift_count > 0:
        messages.append(f"\n🔄 **{shift_count}** players moved between tracked clubs.")
        for club, count in shift_clubs_dict.items():
            messages.append(f"  • **{club}**: +{count} transferred player(s)")
    
    if messages:
        try:
            discord_req.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(messages)})
        except Exception as e:
            log.error(f"Discord error: {e}")

def send_movement_alert(message):
    if not DISCORD_WEBHOOK_URL or not message: return
    try:
        discord_req.post(DISCORD_WEBHOOK_URL, json={"content": message})
    except Exception as e:
        log.error(f"Discord notification error: {e}")

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
    
    # 🟢 DYNAMIC PAGE RESOLUTION
    # Ranks 0-99 map to page=0. Ranks 100-199 map to page=1.
    api_page = 0 if start < 100 else 1
    
    # Normalize our matrix slices to match a 0-100 index scale per page array
    api_start = start if api_page == 0 else (start - 100)
    api_end = end if api_page == 0 else (end - 100)
    
    # Request the target page with the standard 100 limit the API expects natively
    url = f"{BASE_API}/list?page={api_page}&limit=100&sort_by=rank&sort_dir=asc"
    data = safe_get(url)
    
    if not data or "circles" not in data: 
        log.error(f"Failed to fetch leaderboard list for page {api_page}.")
        return

    target_clubs = data["circles"][api_start:api_end]
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    club_rank_collection = client["uma_tracker"]["clubs"]
    
    new_count = 0
    shift_count = 0
    new_clubs_dict = {}
    shift_clubs_dict = {}
    
    for index, club in enumerate(target_clubs):
        absolute_club_rank = start + index 
        cid, club_name = club.get("circle_id"), club.get("name")
        
        prev_club_state = club_rank_collection.find_one({"circle_id": cid})
        if prev_club_state:
            prev_rank = prev_club_state.get("last_known_rank", 999)
            if prev_rank >= 100 and absolute_club_rank < 100:
                send_movement_alert(f"🚀 **{club_name}** has entered the **Top 100**! (Rank {absolute_club_rank + 1})")
            elif prev_rank < 100 and absolute_club_rank >= 100:
                send_movement_alert(f"📉 **{club_name}** has dropped out of the **Top 100** into the Top 200. (Rank {absolute_club_rank + 1})")
        
        club_rank_collection.update_one(
            {"circle_id": cid},
            {"$set": {"name": club_name, "last_known_rank": absolute_club_rank, "last_updated": time.time()}},
            upsert=True
        )

        club_url = f"{BASE_API}?circle_id={cid}&year={curr_year}&month={curr_month}"
        detail = safe_get(club_url)
        
        if detail and "members" in detail:
            ops = []
            for m in (detail.get("members") or []):
                p_id = str(m.get("viewer_id") or m.get("id"))
                p_name = m.get("name") or m.get("nickname") or "Unknown"

                prev_record = db.find_one({"mid": p_id})
                
                if not prev_record:
                    new_count += 1
                    new_clubs_dict[club_name] = new_clubs_dict.get(club_name, 0) + 1
                elif prev_record.get("club") != club_name:
                    shift_count += 1
                    shift_clubs_dict[club_name] = shift_clubs_dict.get(club_name, 0) + 1

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
                log.info(f"Successfully Synced: {club_name} (Rank {absolute_club_rank + 1})")

    send_summary(new_count, shift_count, new_clubs_dict, shift_clubs_dict)

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
