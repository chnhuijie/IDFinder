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

# Tracking the top 100 circles is safer for API stability
# 100 circles * ~30 members = ~3000 players tracked
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
    except (json.JSONDecodeError, FileNotFoundError):
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
    """First get the list of top circles, then fetch details for each."""
    all_players = {}
    
    print("Step 1: Fetching Top Circle list...")
    try:
        # Fetching the first page of circles (Top 100)
        r = requests.get(f"{API_URL}/list?page=0&limit={MAX_CLUBS_TO_SCAN}&sort_by=rank&sort_dir=asc", timeout=15)
        r.raise_for_status()
        circles = r.json().get("circles", [])
    except Exception as e:
        print(f"Failed to fetch circle list: {e}")
        return {}

    print(f"Step 2: Fetching details for {len(circles)} clubs...")
    for idx, c in enumerate(circles):
        cid = c.get("circle_id")
        club_name = c.get("name")
        
        try:
            # We must hit the detail endpoint to get the 'members' key
            res = requests.get(f"{API_URL}/{cid}", timeout=10)
            if res.status_code == 200:
                data = res.json()
                members = data.get("members", [])
                
                for m in members:
                    mid = str(m.get("id"))
                    all_players[mid] = {
                        "name": m.get("name"),
                        "club": club_name,
                        "rank": m.get("rank") or 9999
                    }
            
            # Print progress every 20 clubs so logs don't look frozen
            if (idx + 1) % 20 == 0:
                print(f"Processed {idx + 1}/{len(circles)} clubs...")
            
            # Rate limit safety: 200ms sleep between requests
            time.sleep(0.2)
            
        except Exception as e:
            print(f"Error skipping club {club_name}: {e}")
            continue

    return all_players

# =========================
# MAIN LOGIC
# =========================
def main():
    current_players = get_top_members()
    total_found = len(current_players)
    print(f"Total unique players found: {total_found}")

    if total_found == 0:
        print("CRITICAL: No players found. API might be down or changed.")
        return

    previous_players = load_state()

    # INITIALIZATION
    if not previous_players:
        save_state(current_players)
        send("📊 **Tracker Initialized**\nSaved snapshot of Top 100 circles.")
        print("Initial state saved to file.")
        return

    # DIFFING
    joined, left, moved = [], [], []
    old_ids = set(previous_players.keys())
    new_ids = set(current_players.keys())

    # 1. New players in the scan range
    for i in new_ids - old_ids:
        p = current_players[i]
        joined.append(f"- `{i}` **{p['name']}** (Joined {p['club']})")

    # 2. Players who left the scan range
    for i in old_ids - new_ids:
        p = previous_players[i]
        left.append(f"- `{i}` **{p['name']}** (Left {p['club']})")

    # 3. Players who moved between clubs
    for i in old_ids & new_ids:
        old_p, new_p = previous_players[i], current_players[i]
        if old_p["club"] != new_p["club"]:
            moved.append(f"- `{i}` **{new_p['name']}**: {old_p['club']} → {new_p['club']}")

    # CONSTRUCT MESSAGES
    report_parts = []
    if joined: report_parts.append("🟢 **New Entries**\n" + "\n".join(joined[:15])) # Limit display size
    if left: report_parts.append("🔴 **Dropped Out**\n" + "\n".join(left[:15]))
    if moved: report_parts.append("🟡 **Club Transfers**\n" + "\n".join(moved[:15]))

    if report_parts:
        send("\n\n".join(report_parts))
        save_state(current_players)
        print("Changes detected and sent.")
    else:
        print("No changes detected since last run.")

if __name__ == "__main__":
    main()
