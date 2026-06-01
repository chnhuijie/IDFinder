import os
import sys
import time
import random
import logging
import datetime
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL") 
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def safe_get(url):
    time.sleep(random.uniform(3.0, 6.0)) 
    try:
        res = session.get(url.rstrip('/'), impersonate="chrome120", timeout=30)
        if res.status_code == 200:
            if "application/json" not in res.headers.get("Content-Type", ""):
                log.error("🔴 CLOUDFLARE BLOCK DETECTED: Crashing worker to retry on a new IP...")
                raise RuntimeError("Cloudflare Challenge Blocked the Request.")
            return res.json()
            
        log.error(f"🔴 API CONNECTION FAILED: Status {res.status_code}")
        raise RuntimeError(f"Bad API status code: {res.status_code}")
        
    except Exception as e:
        log.error(f"🔴 CRITICAL NETWORK ERROR: {e}")
        raise e

def get_latest_active_day(daily_fans):
    if not daily_fans or len(daily_fans) < 2:
        return 0
        
    for i in range(len(daily_fans) - 1, 0, -1):
        if daily_fans[i] > daily_fans[i - 1]:
            return i + 1 
            
    if daily_fans[0] > 0:
        return 1
        
    return 0

def process_club_sub_batch(batch_start, batch_end, curr_year, curr_month, run_id):
    api_page = batch_start // 100
    api_start = batch_start % 100
    api_end = batch_end % 100
    if api_end == 0 and batch_end > batch_start:
        api_end = 100
        
    url = f"{BASE_API}/list?page={api_page}&limit=100&sort_by=rank&sort_dir=asc"
    data = safe_get(url)
    
    if not data or "circles" not in data: 
        raise RuntimeError("API payload missing circles context.")

    target_clubs = data["circles"][api_start:api_end]
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=15000, socketTimeoutMS=15000)
    db = client["uma_tracker"]["members"]
    club_rank_collection = client["uma_tracker"]["clubs"]
    
    discord_stream_chunk = [] 

        for index, club in enumerate(target_clubs):
        official_rank = club.get("rank")
        if official_rank:
            absolute_club_rank = official_rank - 1
        else:
            absolute_club_rank = batch_start + index 
            
        cid, club_name = club.get("circle_id"), club.get("name")
            
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
            ops = []
            
            for m in raw_members:
                if not m: continue
                p_id = str(m.get("viewer_id") or m.get("id") or "").strip()
                
                if not p_id or p_id.lower() == "none": 
                    continue
                
                daily_fans = m.get("daily_fans", [])
                current_club_active_day = get_latest_active_day(daily_fans)

                p_name = m.get("name") or m.get("nickname") or "Unknown"
                tier_label = "Top 100" if absolute_club_rank < 100 else ("Top 200" if absolute_club_rank < 200 else "Top 500")
                
                global_tz = datetime.timezone(datetime.timedelta(hours=-15))
                current_calendar_day = datetime.datetime.now(global_tz).day

                current_player_state = db.find_one({"mid": p_id})
                
                if not current_player_state:
                    if current_calendar_day > 4 and current_club_active_day > 0:
                        if (current_calendar_day - current_club_active_day) > 3:
                            continue 
                            
                    prev_club = None
                    is_transfer = False
                    is_new_pool = True
                else:
                    db_active_day = current_player_state.get("last_active_day", -1)
                    db_active_month = current_player_state.get("last_active_month", -1)

                    if db_active_month == curr_month and current_club_active_day < db_active_day:
                        continue

                    if current_player_state.get("last_run_id") == run_id:
                        old_tracked_club_id = current_player_state.get("historical_club_id_snapshot")
                    else:
                        old_tracked_club_id = current_player_state.get("club_id")

                    prev_club = current_player_state.get("previous_club")
                    
                    if old_tracked_club_id and old_tracked_club_id != cid:
                        prev_club = current_player_state.get("club")
                        is_transfer = True
                        is_new_pool = False
                        
                        days_since_old_activity = current_calendar_day - db_active_day
                        if db_active_day > 0 and db_active_month == curr_month and days_since_old_activity > 3:
                            is_transfer = False
                            
                    else:
                        is_transfer = False
                        is_new_pool = False

                update_payload = {
                    "name": p_name, 
                    "club": club_name,
                    "club_id": cid,
                    "previous_club": prev_club,
                    "is_transfer_flag": is_transfer,
                    "is_new_flag": is_new_pool,
                    "club_tier": tier_label,
                    "last_seen": time.time(),
                    "updated_at": datetime.datetime.now(datetime.timezone.utc),
                    "last_run_id": run_id,
                    "last_active_day": current_club_active_day, 
                    "last_active_month": curr_month              
                }

                if not current_player_state or current_player_state.get("last_run_id") != run_id:
                    update_payload["historical_club_snapshot"] = current_player_state.get("club") if current_player_state else None
                    update_payload["historical_club_id_snapshot"] = cid

                ops.append(UpdateOne(
                    {"mid": p_id},
                    {"$set": update_payload},
                    upsert=True
                ))
            
            if ops: 
                db.bulk_write(ops, ordered=False)
                active_count = club.get("member_count") or detail.get("circle", {}).get("member_count") or "??"
                
                log_line = f"**Synced:** `{club_name}` (Rank {absolute_club_rank + 1}) | Active: {active_count}/30"
                log.info(log_line)
                discord_stream_chunk.append(log_line)
                
    client.close()

    if discord_stream_chunk and DISCORD_WEBHOOK_URL:
        stream_message = f"**Data Stream: Ranks {batch_start + 1} to {batch_end}**\n" + "\n".join(discord_stream_chunk)
        try:
            import requests as req 
            req.post(DISCORD_WEBHOOK_URL, json={"content": stream_message}, timeout=15)
        except Exception as e:
            log.error(f"Failed to stream to Discord: {e}")

def main(start, end):
    log.info(f"🚀 Starting Tracker Worker for Ranks {start}-{end}...")
    start, end = int(start), int(end)
    global_tz = datetime.timezone(datetime.timedelta(hours=-15))
    now_dt = datetime.datetime.now(global_tz)
    curr_year, curr_month = now_dt.year, now_dt.month
    run_id = f"{curr_year}-{curr_month:02d}-{now_dt.day:02d}"
    
    try:
        session.get("https://uma.moe/ranking", impersonate="chrome120", timeout=30)
    except:
        pass
        
    current_step = start
    while current_step < end:
        next_step = min(current_step + 20, end)
        process_club_sub_batch(current_step, next_step, curr_year, curr_month, run_id)
        current_step = next_step
        if current_step < end:
            time.sleep(random.uniform(10.0, 20.0))

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
