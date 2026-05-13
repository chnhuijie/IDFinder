import requests
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

# =========================
# CONFIG
# =========================
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state", "member_state.json")
API_URL = "https://uma.moe/api/v4/circles"
MAX_WORKERS = 5 # Number of simultaneous requests. Don't go too high or you'll get banned.

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)

# STATE HELPERS
def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def save_state(data):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def send_discord(msg):
    if not WEBHOOK_URL or not msg: return
    # Split message if it exceeds Discord's 2000 char limit
    for chunk in [msg[i:i+1900] for i in range(0, len(msg), 1900)]:
        session.post(WEBHOOK_URL, json={"content": chunk})

def safe_get(url):
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", 30))
            print(f"Throttled. Sleeping {wait}s...")
            time.sleep(wait)
            return safe_get(url)
        if response.status_code != 200: return None
        return response.json()
    except Exception:
        return None

def fetch_roster(circle_data):
    """Worker function for parallel execution"""
    cid = circle_data.get("circle_id")
    club_name = circle_data.get("name")
    
    detail = safe_get(f"{API_URL}/{cid}")
    players = {}
    
    if detail:
        members = detail.get("members") or []
        if isinstance(members, list) and len(members) > 0:
            for m in members:
                mid = str(m.get("id") or m.get("viewer_id"))
                players[mid] = {"name": m.get("name"), "club": club_name}
        else:
            lid = str(circle_data.get("leader_viewer_id"))
            players[lid] = {"name": circle_data.get("leader_name"), "club": club_name}
    
    return players

def get_top_members():
    all_players = {}
    circles = []
    
    print(">>> Step 1: Fetching Circle IDs...")
    for page in range(5): 
        data = safe_get(f"{API_URL}/list?page={page}&limit=100&sort_by=rank&sort_dir=asc")
        if data and "circles" in data:
            circles.extend(data["circles"])
        time.sleep(0.2) # Small buffer

    print(f">>> Step 2: Fetching rosters for {len(circles)} clubs using {MAX_WORKERS} workers...")
    
    # Using ThreadPoolExecutor to run requests in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(fetch_roster, circles))

    for batch in results:
        all_players.update(batch)

    return all_players

def main():
    start_time = time.time()
    current_players = get_top_members()
    
    if not current_players:
        print("No data collected.")
        return

    previous = load_state()
    if not previous:
        save_state(current_players)
        send_discord(f"📊 **Tracker Initialized**\nTracking {len(current_players)} players.")
        return

    # Comparison Logic
    old_ids = set(previous.keys())
    new_ids = set(current_players.keys())

    joined = [f"- **{current_players[i]['name']}** ({current_players[i]['club']})" for i in (new_ids - old_ids)]
    vanished = [f"- **{previous[i]['name']}** (Last: {previous[i]['club']})" for i in (old_ids - new_ids)]
    transfers = [f"- **{current_players[i]['name']}**: {previous[i]['club']} → {current_players[i]['club']}" 
                 for i in (old_ids & new_ids) if previous[i]["club"] != current_players[i]["club"]]

    report = []
    if joined: report.append("🟢 **New Entries**\n" + "\n".join(joined[:20]))
    if vanished: report.append("🔴 **Left Top 500**\n" + "\n".join(vanished[:20]))
    if transfers: report.append("🟡 **Club Transfers**\n" + "\n".join(transfers[:20]))

    if report:
        send_discord("\n\n".join(report))
        save_state(current_players)
    
    print(f"Finished in {round(time.time() - start_time, 2)} seconds.")

if __name__ == "__main__":
    main()