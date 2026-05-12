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
MAX_CLUBS_TO_SCAN = 1500 
API_URL = "https://uma.moe/api/v4/circles"

# =========================
# STATE HELPERS
# =========================
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

# =========================
# THROTTLING PROTECTION
# =========================
def safe_get(url):
    """Handles API throttling and returns JSON or None."""
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 429:
            # If throttled, wait based on header or default to 60s
            wait = int(response.headers.get("Retry-After", 60))
            print(f"Throttled! Sleeping for {wait} seconds...")
            time.sleep(wait)
            return safe_get(url) 
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Request failed: {url} -> {e}")
        return None

# =========================
# DATA FETCHING
# =========================
def get_top_members():
    all_players = {}
    circles = []
    
    print("Step 1: Fetching 1500 Circle IDs...")
    for page in range(15):
        data = safe_get(f"{API_URL}/list?page={page}&limit=100&sort_by=rank&sort_dir=asc")
        if data and "circles" in data:
            circles.extend(data["circles"])
            time.sleep(0.5)
        else: break

    print(f"Step 2: Fetching rosters for {len(circles)} clubs...")
    for idx, c in enumerate(circles):
        cid = c.get("circle_id")
        club_name = c.get("name")
        
        detail = safe_get(f"{API_URL}/{cid}")
        if detail:
            # Attempt to pull full roster
            members = detail.get("members") or []
            if isinstance(members, list) and len(members) > 0:
                for m in members:
                    mid = str(m.get("id") or m.get("viewer_id"))
                    all_players[mid] = {"name": m.get("name"), "club": club_name}
            else:
                # Fallback to leader if roster is blocked/empty
                lid = str(c.get("leader_viewer_id"))
                all_players[lid] = {"name": c.get("leader_name"), "club": club_name}
        
        if (idx + 1) % 100 == 0:
            print(f"Progress: {idx + 1}/{len(circles)} scanned...")
        time.sleep(0.4) 

    return all_players

# =========================
# MAIN LOGIC
# =========================
def main():
    current_players = get_top_members()
    if not current_players:
        print("No data collected. Ending run.")
        return

    previous = load_state()
    if not previous:
        save_state(current_players)
        send_discord(f"📊 **Tracker Initialized**\nTracking {len(current_players)} players in Top 1500.")
        return

    old_ids = set(previous.keys())
    new_ids = set(current_players.keys())

    joined = [f"- `{i}` **{current_players[i]['name']}** ({current_players[i]['club']})" for i in (new_ids - old_ids)]
    vanished = [f"- `{i}` **{previous[i]['name']}** (Last seen: {previous[i]['club']})" for i in (old_ids - new_ids)]
    transfers = [f"- `{i}` **{current_players[i]['name']}**: {previous[i]['club']} → {current_players[i]['club']}" 
                 for i in (old_ids & new_ids) if previous[i]["club"] != current_players[i]["club"]]

    report = []
    if joined: report.append("🟢 **New Entries**\n" + "\n".join(joined[:10]))
    if vanished: report.append("🔴 **Left Top 1500 Entirely**\n" + "\n".join(vanished[:10]))
    if transfers: report.append("🟡 **Club Transfers**\n" + "\n".join(transfers[:10]))

    if report:
        send_discord("\n\n".join(report))
        save_state(current_players)
        print("Updates sent.")
    else:
        print("No movement detected.")

if __name__ == "__main__":
    main()
