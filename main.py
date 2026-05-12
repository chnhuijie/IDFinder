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

# Scanning 50 clubs is safer for GitHub Action stability and rate limits
MAX_CLUBS_TO_SCAN = 100 
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
        print("Webhook missing or message empty.")
        return
    try:
        r = requests.post(WEBHOOK_URL, json={"content": msg[:1990]})
        r.raise_for_status()
        print("Discord message sent successfully.")
    except Exception as e:
        print(f"Failed to send Discord message: {e}")

# =========================
# DATA FETCHING
# =========================
def get_top_members():
    all_players = {}
    print("Fetching Circle List...")
    try:
        # Get circles from API
        r = requests.get(f"{API_URL}/list?page=0&limit={MAX_CLUBS_TO_SCAN}&sort_by=rank&sort_dir=asc", timeout=15)
        r.raise_for_status()
        circles = r.json().get("circles", [])
    except Exception as e:
        print(f"Failed to fetch circles: {e}")
        return {}

    for idx, c in enumerate(circles):
        cid = c.get("circle_id")
        club_name = c.get("name")
        
        # We always start by adding the leader since they are in the list data
        # This prevents the '0 players found' error even if detail fetch fails
        leader_id = str(c.get("leader_viewer_id"))
        if leader_id and leader_id != "None":
            all_players[leader_id] = {"name": c.get("leader_name"), "club": club_name}
        
        try:
            res = requests.get(f"{API_URL}/{cid}", timeout=10)
            if res.status_code == 200:
                data = res.json()
                # Check different possible keys for the member list
                member_list = data.get("members") or data.get("players") or []
                
                if isinstance(member_list, list):
                    for m in member_list:
                        mid = str(m.get("id") or m.get("viewer_id"))
                        if mid and mid != "None":
                            all_players[mid] = {"name": m.get("name"), "club": club_name}
            
            if (idx + 1) % 10 == 0: 
                print(f"Processed {idx + 1}/{len(circles)} clubs...")
            
            time.sleep(0.3) # Respect API rate limits
            
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
        print("CRITICAL: No players found. Check API connectivity.")
        return

    previous = load_state()
    
    # Check if state is actually empty
    if not previous:
        save_state(current_players)
        send(f"📊 **Tracker Initialized**\nNow tracking {total_found} players in Top {MAX_CLUBS_TO_SCAN} clubs.")
        print("Initial state saved.")
        return

    joined, left, moved = [], [], []
    old_ids, new_ids = set(previous.keys()), set(current_players.keys())

    for i in new_ids - old_ids:
        joined.append(f"- `{i}` **{current_players[i]['name']}** (Joined {current_players[i]['club']})")
    
    for i in old_ids - new_ids:
        left.append(f"- `{i}` **{previous[i]['name']}** (Left {previous[i]['club']})")

    for i in old_ids & new_ids:
        if previous[i]["club"] != current_players[i]["club"]:
            moved.append(f"- `{i}` **{current_players[i]['name']}**: {previous[i]['club']} → {current_players[i]['club']}")

    report = []
    if joined: report.append("🟢 **New Entries**\n" + "\n".join(joined[:10]))
    if left: report.append("🔴 **Dropped Out**\n" + "\n".join(left[:10]))
    if moved: report.append("🟡 **Transfers**\n" + "\n".join(moved[:10]))

    if report:
        send("\n\n".join(report))
        save_state(current_players)
        print("Discord notification triggered.")
    else:
        print("No changes found since last check.")

if __name__ == "__main__":
    main()
