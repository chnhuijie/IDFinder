import requests
import json
import os
import time

# =========================
# CONFIG
# =========================
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state", "member_state.json")
MAX_CLUBS_TO_SCAN = 500 
API_URL = "https://uma.moe/api/v4/circles"


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


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
    requests.post(WEBHOOK_URL, json={"content": msg[:1990]})


# THROTTLING & ERROR PROTECTION

def safe_get(url):
    """Handles API throttling, 404s, and returns JSON or None."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        
        if response.status_code == 404:
            print(f"   ! Skipping: {url} (Not Found)")
            return None

        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", 60))
            wait = min(wait, 120) 
            print(f"   ! Throttled! Sleeping for {wait} seconds...")
            time.sleep(wait)
            return safe_get(url) 

        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"   ! Request failed: {url} -> {e}")
        return None


# DATA FETCHING

def get_top_members():
    all_players = {}
    circles = []
    
    print(">>> Step 1: Fetching 500 Circle IDs...")
    for page in range(5): 
        data = safe_get(f"{API_URL}/list?page={page}&limit=100&sort_by=rank&sort_dir=asc")
        if data and "circles" in data:
            circles.extend(data["circles"])
            print(f"    Loaded page {page + 1}/5")
            time.sleep(0.6) 
        else: break

    print(f"\n>>> Step 2: Fetching rosters for {len(circles)} clubs...")
    for idx, c in enumerate(circles):
        cid = c.get("circle_id")
        club_name = c.get("name")
        
        # LIVE PROGRESS: This prints to your GitHub Actions log immediately
        print(f"[{idx + 1}/{len(circles)}] Scanning: {club_name}")
        
        detail = safe_get(f"{API_URL}/{cid}")
        if detail:
            members = detail.get("members") or []
            if isinstance(members, list) and len(members) > 0:
                for m in members:
                    mid = str(m.get("id") or m.get("viewer_id"))
                    all_players[mid] = {"name": m.get("name"), "club": club_name}
            else:
                lid = str(c.get("leader_viewer_id"))
                all_players[lid] = {"name": c.get("leader_name"), "club": club_name}
        
        # Polite delay
        time.sleep(0.7) 

    return all_players


# MAIN LOGIC

def main():
    current_players = get_top_members()
    total_found = len(current_players)
    
    if total_found == 0:
        print("\nCRITICAL: No data collected.")
        return

    previous = load_state()
    if not previous:
        save_state(current_players)
        send_discord(f"📊 **Tracker Initialized**\nTracking {total_found} players in Top 500.")
        return

    old_ids = set(previous.keys())
    new_ids = set(current_players.keys())

    joined = [f"- `{i}` **{current_players[i]['name']}** ({current_players[i]['club']})" for i in (new_ids - old_ids)]
    vanished = [f"- `{i}` **{previous[i]['name']}** (Last seen: {previous[i]['club']})" for i in (old_ids - new_ids)]
    transfers = [f"- `{i}` **{current_players[i]['name']}**: {previous[i]['club']} → {current_players[i]['club']}" 
                 for i in (old_ids & new_ids) if previous[i]["club"] != current_players[i]["club"]]

    report = []
    if joined: report.append("🟢 **New Entries**\n" + "\n".join(joined[:15]))
    if vanished: report.append("🔴 **Left Top 500 Entirely**\n" + "\n".join(vanished[:15]))
    if transfers: report.append("🟡 **Club Transfers**\n" + "\n".join(transfers[:15]))

    if report:
        send_discord("\n\n".join(report))
        save_state(current_players)
        print(f"\nUpdates sent. Total tracked: {total_found}")
    else:
        print("\nNo movement detected.")

if __name__ == "__main__":
    main()
