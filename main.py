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

# Scaled to track 1500 clubs
MAX_CLUBS_TO_SCAN = 1500 
API_URL = "https://uma.moe/api/v4/circles"

# =========================
# STATE HELPERS
# =========================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) and data else {}
    except:
        return {}

def save_state(data):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def send(msg):
    if not WEBHOOK_URL or not msg: 
        return
    # Discord character limit safety
    requests.post(WEBHOOK_URL, json={"content": msg[:1990]})

# =========================
# DATA FETCHING
# =========================
def get_top_members():
    all_players = {}
    circles = []
    
    print("Step 1: Fetching Circle List (Pages 0-14)...")
    # Fetch 15 pages to get 1500 circles
    for page in range(15):
        try:
            url = f"{API_URL}/list?page={page}&limit=100&sort_by=rank&sort_dir=asc"
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            batch = r.json().get("circles", [])
            if not batch:
                break
            circles.extend(batch)
            print(f"Collected {len(circles)} circles...")
            time.sleep(0.5) # Be polite to the API
        except Exception as e:
            print(f"Error on page {page}: {e}")
            break

    print(f"Step 2: Fetching details for {len(circles)} clubs...")
    for idx, c in enumerate(circles):
        cid = c.get("circle_id")
        club_name = c.get("name")
        
        # Immediate fallback: add Leader from the list data
        leader_id = str(c.get("leader_viewer_id"))
        if leader_id and leader_id != "None":
            all_players[leader_id] = {"name": c.get("leader_name"), "club": club_name}
        
        try:
            # Fetch deeper member list
            res = requests.get(f"{API_URL}/{cid}", timeout=10)
            if res.status_code == 200:
                data = res.json()
                member_list = data.get("members") or data.get("players") or []
                
                if isinstance(member_list, list):
                    for m in member_list:
                        mid = str(m.get("id") or m.get("viewer_id"))
                        if mid and mid != "None":
                            all_players[mid] = {"name": m.get("name"), "club": club_name}
            
            if (idx + 1) % 50 == 0:
                print(f"Progress: {idx + 1}/{len(circles)} clubs scanned...")
            
            # Slightly higher sleep to prevent 429 errors during long runs
            time.sleep(0.4) 
            
        except:
            continue

    return all_players

# =========================
# MAIN LOGIC
# =========================
def main():
    current_players = get_top_members()
    total_found = len(current_players)
    print(f"Total players found: {total_found}")

    if total_found == 0:
        print("CRITICAL: No data found.")
        return

    previous = load_state()
    
    if not previous:
        save_state(current_players)
        send(f"📊 **Tracker Initialized (Top 1500)**\nTracking {total_found} players.")
        return

    joined, left, moved = [], [], []
    old_ids, new_ids = set(previous.keys()), set(current_players.keys())

    for i in new_ids - old_ids:
        joined.append(f"- `{i}` **{current_players[i]['name']}** ({current_players[i]['club']})")
    
    for i in old_ids - new_ids:
        left.append(f"- `{i}` **{previous[i]['name']}** ({previous[i]['club']})")

    for i in old_ids & new_ids:
        if previous[i]["club"] != current_players[i]["club"]:
            moved.append(f"- `{i}` **{current_players[i]['name']}**: {previous[i]['club']} → {current_players[i]['club']}")

    report = []
    # Discord can only handle about 15-20 lines per section before hitting char limits
    if joined: report.append("🟢 **New Entries** (Showing first 10)\n" + "\n".join(joined[:10]))
    if left: report.append("🔴 **Dropped Out** (Showing first 10)\n" + "\n".join(left[:10]))
    if moved: report.append("🟡 **Transfers** (Showing first 10)\n" + "\n".join(moved[:10]))

    if report:
        send("\n\n".join(report))
        save_state(current_players)
        print("Updates sent.")
    else:
        print("No changes found.")

if __name__ == "__main__":
    main()
