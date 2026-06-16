import os
import sys
import time
import random
import logging
import dateutil.parser
from datetime import datetime
from pymongo import MongoClient, UpdateOne
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
UMA_API_KEY = os.getenv("UMA_API_KEY") 
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BASE_API = "https://uma.moe/api/v4/circles"

def safe_get(url, retries=3):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://uma.moe/",
        "Origin": "https://uma.moe"
    }
    if UMA_API_KEY:
        headers["X-API-Key"] = UMA_API_KEY
        
    for attempt in range(retries):
        time.sleep(random.uniform(4.0, 8.0)) 
        try:
            response = requests.get(url, headers=headers, impersonate="chrome120", timeout=20)
            if response.status_code == 200:
                return response.json()
            log.warning(f"API returned {response.status_code} on attempt {attempt+1}")
        except Exception as e:
            log.warning(f"Request failed: {e} on attempt {attempt+1}")
        time.sleep(10)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts.")

def process_club_sub_batch(api_start, api_end):
    client = MongoClient(MONGO_URI)
    clubs_col = client["uma_tracker"]["clubs"]
    members_col = client["uma_tracker"]["members"]
    
    limit = 100
    api_page = api_start // limit
    
    url = f"{BASE_API}/list?page={api_page}&limit={limit}&sort_by=rank&sort_dir=asc"
    log.info(f"Fetching global list: {url}")
    data = safe_get(url)
    
    if not data or "circles" not in data: 
        raise RuntimeError("API payload missing circles context.")

    slice_start = api_start % limit
    slice_end = slice_start + (api_end - api_start)
    target_clubs = data["circles"][slice_start:slice_end]
    
    if len(target_clubs) == 0:
        log.warning(f" API List empty. Switching to Database Fallback Mode...")
        db_clubs = list(clubs_col.find({"last_known_rank": {"$gte": api_start + 1, "$lte": api_end}}).sort("last_known_rank", 1))
        if not db_clubs:
            client.close()
            raise RuntimeError("Database Fallback failed.")
            
        target_clubs = []
        for db_club in db_clubs:
            c_id = db_club.get("circle_id")
            try:
                direct_data = safe_get(f"{BASE_API}?circle_id={c_id}")
                if direct_data and "circle" in direct_data:
                    target_clubs.append(direct_data["circle"])
            except Exception as e:
                log.error(f"Failed to fetch {c_id}: {e}")
                continue

    current_scan_time = time.time()
    stream_buffer = []
    
    for club_summary in target_clubs:
        c_id = club_summary.get("circle_id")
        club_name = club_summary.get("name")
        club_rank = club_summary.get("monthly_rank") or club_summary.get("live_rank") or 999
        
        log.info(f"Scanning Club: {club_name} (ID: {c_id}, Rank: {club_rank})")
        
        circle_data = None
        max_payload_retries = 3
        
        for attempt in range(max_payload_retries):
            try:
                temp_data = safe_get(f"{BASE_API}?circle_id={c_id}")
                
                club_info_temp = temp_data.get("circle", {})
                official_count = club_info_temp.get("member_count")
                actual_count = len(temp_data.get("members", []))
                
                if official_count is not None and actual_count < official_count:
                    log.warning(f"⚠️ API Glitch for {club_name}: Got {actual_count}/{official_count} members. Retrying (Attempt {attempt+1}/{max_payload_retries})...")
                    time.sleep(5)
                    continue
                
                circle_data = temp_data
                break 
                
            except Exception as e:
                log.error(f"Failed to fetch details for {club_name} on attempt {attempt+1}: {e}")
                time.sleep(5)
                
        if not circle_data or "members" not in circle_data:
            log.error(f"❌ Completely failed to get valid roster for {club_name} after {max_payload_retries} attempts. Skipping.")
            continue
            
        club_info = circle_data.get("circle", {})
        official_member_count = club_info.get("member_count")
        
        if official_member_count is not None:
            sorted_members = sorted(circle_data["members"], key=lambda x: x.get("last_updated") or "", reverse=True)
            active_members = sorted_members[:official_member_count]
        else:
            club_updated_dt = dateutil.parser.isoparse(club_info.get("last_updated", "2000-01-01T00:00:00Z"))
            active_members = [m for m in circle_data["members"] if m.get("last_updated") and (club_updated_dt - dateutil.parser.isoparse(m["last_updated"])).total_seconds() <= 86400]

        if len(active_members) == 0:
            log.warning(f"⚠️ Roster for {club_name} evaluated to 0 members. Skipping update to protect DB.")
            continue
            
        clubs_col.update_one({"circle_id": c_id}, {"$set": {"name": club_name, "last_known_rank": club_rank, "last_updated": current_scan_time, "raw_data": club_info}}, upsert=True)

        viewer_ids = [m.get("viewer_id") for m in active_members]
        existing_members = {m["mid"]: m for m in members_col.find({"mid": {"$in": viewer_ids}})}
        
        member_bulk_ops = []
        for member in active_members:
            viewer_id = member.get("viewer_id")
            current_total_fans = member.get("fans", 0)
            prev_data = existing_members.get(viewer_id, {})
            
            daily_gain = max(0, current_total_fans - prev_data.get("total_fans", current_total_fans))
            
            update_doc = {
                "$set": {
                    "mid": viewer_id, "name": member.get("trainer_name"), "club": club_name, "club_id": c_id, "club_tier": "Ranked",
                    "last_seen": current_scan_time, "updated_at": datetime.utcnow(),
                    "total_fans": current_total_fans, "monthly_gain": member.get("fans_monthly", 0),
                    "daily_gain": daily_gain, "api_last_updated": member.get("last_updated")
                },
                "$setOnInsert": {"is_new_flag": True}
            }
            if prev_data.get("club_id") and prev_data.get("club_id") != c_id:
                update_doc["$set"].update({"is_transfer_flag": True, "previous_club_id": prev_data.get("club_id")})
            
            member_bulk_ops.append(UpdateOne({"mid": viewer_id}, update_doc, upsert=True))
            
        if member_bulk_ops:
            members_col.bulk_write(member_bulk_ops, ordered=False)

        formatted_line = f"**Synced:** `{club_name}` (Rank {club_rank}) | Active: {len(active_members)}/30"
        stream_buffer.append((club_rank, formatted_line))

        if len(stream_buffer) == 20:
            if DISCORD_WEBHOOK_URL:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": f"**Data Stream: Ranks {min(r for r,l in stream_buffer)} to {max(r for r,l in stream_buffer)}**\n" + "\n".join(l for r,l in stream_buffer)}, timeout=10)
            stream_buffer = []
            
    client.close()

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(1)
    process_club_sub_batch(int(sys.argv[1]), int(sys.argv[2]))
