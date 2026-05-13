import os, sys, time, random, logging, datetime
import requests as discord_req
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Environment Variables - Updated to DISCORD_WEBHOOK_URL
MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def send_summary(new_count, shift_count):
    """Sends a brief count summary to Discord instead of a wall of IDs."""
    if not DISCORD_WEBHOOK_URL: return
    messages = []
    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered the Top 100.")
    if shift_count > 0:
        messages.append(f"🔄 **{shift_count}** players moved between Top 100 clubs.")
    
    if messages:
        try:
            discord_req.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(messages)})
        except Exception as e:
            log.error(f"Discord error: {e}")

def safe_get(url):
    """Jittered requests to mimic human browsing and avoid IP flags."""
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
    
    data = safe_get(f"{BASE_API}/list?page=0&limit=100&sort_by=rank&sort_dir=asc")
    if not data or "circles" not in data: 
        log.error("Failed to fetch Top 100 list.")
        return

    target_clubs = data["circles"][start:end]
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    new_count = 0
    shift_count = 0
    
    for club in target_clubs:
        cid, club_name = club.get("circle_id"), club.get("name")
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
                elif prev_record.get("club") != club_name:
                    shift_count += 1

                ops.append(UpdateOne(
                    {"mid": p_id},
                    {"$set": {
                        "name": p_name, 
                        "club": club_name, 
                        "last_seen": time.time()
                    }},
                    upsert=True
                ))
            
            if ops: 
                db.bulk_write(ops, ordered=False)
                log.info(f"Successfully Synced: {club_name}")

    send_summary(new_count, shift_count)

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
