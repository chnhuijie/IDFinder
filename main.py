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

def send_summary(structural_changes, micro_changes):
    """Sends combined macro and detailed micro player movements to Discord."""
    if not DISCORD_WEBHOOK_URL: return
    
    messages = structural_changes + micro_changes
    if messages:
        # Chunk into batches of 20 to prevent hitting Discord payload limits
        for i in range(0, len(messages), 20):
            chunk = messages[i : i + 20]
            try:
                discord_req.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(chunk)})
                time.sleep(1.0)
            except Exception as e:
                log.error(f"Discord error: {e}")

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
    run_timestamp = time.time()
    
    log.info(f"--- Starting Sync: Range {start} to {end} ---")
    session.get("https://uma.moe/ranking", impersonate="chrome120")
    
    data = safe_get(f"{BASE_API}/list?page=0&limit=200&sort_by=rank&sort_dir=asc")
    if not data or "circles" not in data: 
        log.error("Failed to fetch Top Circles list.")
        return

    target_clubs = data["circles"][start:end]
    
    # Map absolute live ranks for clubs in this batch slice
    live_club_ranks = {}
    for idx, club in enumerate(target_clubs):
        c_name = club.get("name")
        if c_name:
            live_club_ranks[c_name] = start + idx + 1

    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    log.info("Caching current database state...")
    db_state = {rec["mid"]: rec for rec in db.find({}, {"mid": 1, "club": 1, "name": 1})}
    
    staged_data = {}
    incoming_club_player_counts = {} 
    micro_changes = []
    
    # 1. Parse active rosters and capture individual movements
    for club in target_clubs:
        cid, club_name = club.get("circle_id"), club.get("name")
        club_url = f"{BASE_API}?circle_id={cid}&year={curr_year}&month={curr_month}"
        detail = safe_get(club_url)
        
        if detail and "members" in detail:
            staged_data[club_name] = []
            incoming_club_player_counts[club_name] = 0
            
            for m in (detail.get("members") or []):
                p_id = str(m.get("viewer_id") or m.get("id"))
                p_name = m.get("name") or m.get("nickname") or "Unknown"
                
                prev_record = db_state.get(p_id)
                status = "STABLE"
                prev_club = prev_record.get("club") if prev_record else None
                
                if not prev_record:
                    status = "NEW"
                    incoming_club_player_counts[club_name] += 1
                    micro_changes.append(f"📥 **{p_name}** (`{p_id}`) has joined **{club_name}**")
                elif prev_club != club_name:
                    status = "SHIFT"
                    incoming_club_player_counts[club_name] += 1
                    micro_changes.append(f"🔄 **{p_name}** (`{p_id}`) transferred: **{prev_club}** ➡️ **{club_name}**")
                
                staged_data[club_name].append({
                    "id": p_id, "name": p_name, "status": status, "prev_club": prev_club
                })

    # 2. Check for missing players to catch club dropouts
    old_club_missing_counts = {}
    live_player_ids = {p["id"] for club_mems in staged_data.values() for p in club_mems}
    
    for p_id, rec in db_state.items():
        old_club = rec.get("club")
        if old_club in live_club_ranks: 
            if p_id not in live_player_ids:
                old_club_missing_counts[old_club] = old_club_missing_counts.get(old_club, 0) + 1
            else:
                current_rank = live_club_ranks.get(old_club)
                if current_rank and current_rank > 100 and start < 100:
                    old_club_missing_counts[old_club] = old_club_missing_counts.get(old_club, 0) + 1

    # 3. Evaluate Macro Structural Changes (Entries & Exits)
    structural_changes = []
    ignored_clubs = set()

    # Detect Entries
    for club_name, count in incoming_club_player_counts.items():
        if count >= 25:
            rank = live_club_ranks.get(club_name, 0)
            ignored_clubs.add(club_name)
            
            if rank <= 100 and start < 100:
                structural_changes.append(f"🏰 📈 **{club_name}** has entered the **Top 100** (Rank: #{rank})!")
            elif rank > 100:
                structural_changes.append(f"🏰 📈 **{club_name}** has entered the **Top 200** (Rank: #{rank})!")

    # Detect Exits
    for club_name, count in old_club_missing_counts.items():
        if count >= 25:
            current_rank = live_club_ranks.get(club_name)
            ignored_clubs.add(club_name)
            
            if not current_rank:
                structural_changes.append(f"📉 🚫 **{club_name}** has dropped out of the **Top 200** entirely.")
            elif current_rank > 100 and start < 100:
                structural_changes.append(f"⚠️ 📉 **{club_name}** has dropped out of the **Top 100** (Current Rank: #{current_rank}).")

    # 4. Filter micro spam if the club underwent a massive macro change
    filtered_micro_changes = []
    for msg in micro_changes:
        if not any(club in msg for club in ignored_clubs):
            filtered_micro_changes.append(msg)

    # 5. Database Batch Updates with absolute ranking telemetry saved
    ops = []
    for club_name, members in staged_data.items():
        current_assigned_rank = live_club_ranks.get(club_name, 200)
        for m in members:
            ops.append(UpdateOne(
                {"mid": m["id"]},
                {"$set": {
                    "name": m["name"], 
                    "club": club_name, 
                    "last_rank": current_assigned_rank,
                    "last_seen": run_timestamp
                }},
                upsert=True
            ))
            
    if ops: 
        db.bulk_write(ops, ordered=False)
        log.info(f"Batch execution complete. Synced {len(ops)} records.")

    send_summary(structural_changes, filtered_micro_changes)

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
