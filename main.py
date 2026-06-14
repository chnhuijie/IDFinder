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
    headers = {}
    if UMA_API_KEY:
        headers["X-API-Key"] = UMA_API_KEY
        
    for attempt in range(retries):
        time.sleep(random.uniform(3.0, 6.0))
        try:
            response = requests.get(url, headers=headers, impersonate="chrome110", timeout=15)
            if response.status_code == 200:
                return response.json()
            log.warning(f"API returned {response.status_code} on attempt {attempt+1}")
        except Exception as e:
            log.warning(f"Request failed: {e} on attempt {attempt+1}")
        time.sleep(5)
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
        log.warning(f"⚠️ API List empty for page {api_page}. Switching to Database Fallback Mode...")
        
        db_clubs = list(clubs_col.find({
            "last_known_rank": {"$gte": api_start + 1, "$lte": api_end}
        }).sort("last_known_rank", 1))
        
        if not db_clubs:
            client.close()
            raise RuntimeError("Database Fallback failed: No historical clubs found in local database.")
            
        target_clubs = []
        for db_club in db_clubs:
            c_id = db_club.get("circle_id")
            direct_url = f"{BASE_API}?circle_id={c_id}"
            
            try:
                direct_data = safe_get(direct_url)
                if direct_data and "circle" in direct_data:
                    target_clubs.append(direct_data["circle"])
            except Exception as e:
                log.error(f"Failed to fetch individual club {c_id}: {e}")
                continue

    current_scan_time = time.time()
    stream_buffer = []
    
    for club_summary in target_clubs:
        c_id = club_summary.get("circle_id")
        club_name = club_summary.get("name")
        club_rank = club_summary.get("monthly_rank") or club_summary.get("live_rank") or 999
        
        direct_url = f"{BASE_API}?circle_id={c_id}"
        
        try:
            circle_data = safe_get(direct_url)
        except Exception as e:
            log.error(f"Failed to fetch details for {club_name}: {e}")
            continue
            
        if not circle_data or "members" not in circle_data:
            continue
            
        club_info = circle_data.get("circle", {})
        clubs_col.update_one(
            {"circle_id": c_id},
            {"$set": {
                "name": club_name,
                "last_known_rank": club_rank,
                "last_updated": current_scan_time,
                "raw_data": club_info
            }},
            upsert=True
        )

        official_member_count = club_info.get("member_count")
        
        if official_member_count is not None:
            sorted_members = sorted(
                circle_data["members"], 
                key=lambda x: x.get("last_updated") or "", 
                reverse=True
            )
            active_members = sorted_members[:official_member_count]
        else:
            club_last_updated_str = club_info.get("last_updated")
            if not club_last_updated_str:
                active_members = circle_data["members"]
            else:
                club_updated_dt = dateutil.parser.isoparse(club_last_updated_str)
                active_members = []
                
                for member in circle_data["members"]:
                    member_updated_str = member.get("last_updated")
                    if not member_updated_str:
                        continue
                        
                    member_updated_dt = dateutil.parser.isoparse(member_updated_str)
                    if (club_updated_dt - member_updated_dt).total_seconds() > 86400:
                        continue 
                        
                    active_members.append(member)

        viewer_ids = [m.get("viewer_id") for m in active_members]
        existing_members = {m["mid"]: m.get("club_id") for m in members_col.find({"mid": {"$in": viewer_ids}}, {"mid": 1, "club_id": 1})}
        
        member_bulk_ops = []
        for member in active_members:
            viewer_id = member.get("viewer_id")
            trainer_name = member.get("trainer_name")
            
            is_transfer = False
            prev_club_id = existing_members.get(viewer_id)
            if prev_club_id and prev_club_id != c_id:
                is_transfer = True
            
            update_doc = {
                "$set": {
                    "mid": viewer_id,
                    "name": trainer_name,
                    "club": club_name,
                    "club_id": c_id,
                    "club_tier": "Ranked",
                    "last_seen": current_scan_time,
                    "updated_at": datetime.utcnow()
                },
                "$setOnInsert": {
                    "is_new_flag": True
                }
            }
            
            if is_transfer:
                update_doc["$set"]["is_transfer_flag"] = True
                update_doc["$set"]["previous_club_id"] = prev_club_id
            
            member_bulk_ops.append(
                UpdateOne({"mid": viewer_id}, update_doc, upsert=True)
            )
            
        if member_bulk_ops:
            members_col.bulk_write(member_bulk_ops, ordered=False)

        active_count = official_member_count if official_member_count is not None else len(active_members)
        formatted_line = f"**Synced:** `{club_name}` (Rank {club_rank}) | Active: {active_count}/30"
        stream_buffer.append((club_rank, formatted_line))

        if len(stream_buffer) == 20:
            if DISCORD_WEBHOOK_URL:
                try:
                    ranks = [item[0] for item in stream_buffer]
                    lines = [item[1] for item in stream_buffer]
                    payload = f"**Data Stream: Ranks {min(ranks)} to {max(ranks)}**\n" + "\n".join(lines)
                    requests.post(DISCORD_WEBHOOK_URL, json={"content": payload}, timeout=10)
                except Exception as e:
                    log.error(f"Failed to send Discord stream: {e}")
            stream_buffer = []
            
    if stream_buffer and DISCORD_WEBHOOK_URL:
        try:
            ranks = [item[0] for item in stream_buffer]
            lines = [item[1] for item in stream_buffer]
            payload = f"**Data Stream: Ranks {min(ranks)} to {max(ranks)}**\n" + "\n".join(lines)
            requests.post(DISCORD_WEBHOOK_URL, json={"content": payload}, timeout=10)
        except Exception as e:
            log.error(f"Failed to send final Discord stream: {e}")

    client.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        log.error("Usage: python main.py <start_index> <end_index>")
        sys.exit(1)
        
    start_idx = int(sys.argv[1])
    end_idx = int(sys.argv[2])
    process_club_sub_batch(start_idx, end_idx)
