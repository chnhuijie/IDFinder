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

def send_summary(new_count, shift_count, structural_changes):
    """Sends a summary to Discord, filtering out player spam if a club falls/enters rank."""
    if not DISCORD_WEBHOOK_URL: return
    messages = []
    
    # Add macro club alerts first
    for alert in structural_changes:
        messages.append(alert)
        
    # Add individual statistics if they weren't filtered out by macro events
    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered tracked clubs.")
    if shift_count > 0:
        messages.append(f"🔄 **{shift_count}** players moved between tracked clubs.")
    
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
    
    # Requesting up to 200 to accommodate your new logic parameters
    data = safe_get(f"{BASE_API}/list?page=0&limit=200&sort_by=rank&sort_dir=asc")
    if not data or "circles" not in data: 
        log.error("Failed to fetch Top Circles list.")
        return

    target_clubs = data["circles"][start:end]
    live_club_names = {club.get("name") for club in target_clubs if club.get("name")}

    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    # 1. Cache current DB state into memory to optimize lookups and track mass dropouts
    log.info("Caching current database state...")
    db_state = {rec["mid"]: rec for rec in db.find({}, {"mid": 1, "club": 1})}
    
    # 2. Stage live data to inspect it for macro movements before mutating data or counts
    staged_data = {}
    incoming_club_player_counts = {} # club_name -> count of players who look "new" to this club
    
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
                
                if not prev_record:
                    status = "NEW"
                    incoming_club_player_counts[club_name] += 1
                elif prev_record.get("club") != club_name:
                    status = "SHIFT"
                    incoming_club_player_counts[club_name] += 1
                
                staged_data[club_name].append({
                    "id": p_id, "name": p_name, "status": status, "prev_club": prev_record.get("club") if prev_record else None
                })

    # 3. Figure out if any tracked clubs completely left the tracked bracket
    # Count how many players from old clubs are missing from the current live scrape
    old_club_missing_counts = {}
    live_player_ids = {p["id"] for club_mems in staged_data.values() for p in club_mems}
    
    for p_id, rec in db_state.items():
        if p_id not in live_player_ids:
            old_club = rec.get("club")
            if old_club:
                old_club_missing_counts[old_club] = old_club_missing_counts.get(old_club, 0) + 1

    # 4. Filter macro changes vs micro player changes
    structural_changes = []
    ignored_incoming_clubs = set()
    ignored_outgoing_clubs = set()

    # Club entered tracked list (> 25 players look brand new/shifted into this single club)
    for club_name, count in incoming_club_player_counts.items():
        if count >= 25:
            structural_changes.append(f"🏰 **{club_name}** has entered the tracked rankings.")
            ignored_incoming_clubs.add(club_name)

    # Club dropped out of tracked list (> 25 players from this club completely disappeared from live data)
    for club_name, count in old_club_missing_counts.items():
        if count >= 25:
            structural_changes.append(f"📉 **{club_name}** has dropped out of the tracked rankings.")
            ignored_outgoing_clubs.add(club_name)

    # 5. Calculate precise metrics and prepare DB updates
    new_count = 0
    shift_count = 0
    ops = []

    for club_name, members in staged_data.items():
        # If the club itself is flagged as newly entering, suppress its individual entries
        suppress_incoming = club_name in ignored_incoming_clubs
        
        for m in members:
            if m["status"] == "NEW" and not suppress_incoming:
                new_count += 1
            elif m["status"] == "SHIFT":
                # Suppress if target club is brand new, or origin club just fell out
                if not suppress_incoming and m["prev_club"] not in ignored_outgoing_clubs:
                    shift_count += 1

            ops.append(UpdateOne(
                {"mid": m["id"]},
                {"$set": {
                    "name": m["name"], 
                    "club": club_name, 
                    "last_seen": time.time()
                }},
                upsert=True
            ))
            
    # Execute database writes
    if ops: 
        db.bulk_write(ops, ordered=False)
        log.info(f"Successfully Bulk Synced {len(ops)} players across target range.")

    # 6. Dispatch clean notification
    send_summary(new_count, shift_count, structural_changes)

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
