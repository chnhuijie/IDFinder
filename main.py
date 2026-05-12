import requests
import json
import os

# =========================
# CONFIG
# =========================
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state", "member_state.json")

TOP_N = 1000
API_URL = "https://uma.moe/api/v4/circles/list"

# =========================
# STATE & HELPERS
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
    if not WEBHOOK_URL: return
    requests.post(WEBHOOK_URL, json={"content": msg[:1990]})

# =========================
# FETCH & BUILD
# =========================
def fetch_all_circles():
    circles = []
    page = 0
    MAX_PAGES = 15

    while page < MAX_PAGES:
        # Added with_members=true to ensure the API includes the member list
        url = f"{API_URL}?page={page}&limit=100&sort_by=rank&sort_dir=asc&with_members=true"
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            
            # Diagnostic: Print keys of the first circle to verify structure in logs
            if page == 0 and data.get("circles"):
                print(f"DEBUG: First circle keys: {list(data['circles'][0].keys())}")
                
            batch = data.get("circles", [])
            if not batch: break
            circles.extend(batch)
            if len(batch) < 100: break
            page += 1
        except Exception as e:
            print(f"Fetch error: {e}")
            break
    return circles

def build_members(circles):
    members = {}
    for c in circles:
        club_name = c.get("name")
        # Handle cases where members might be in 'members' or 'players'
        member_list = c.get("members") or c.get("players") or []
        
        if isinstance(member_list, list):
            for m in member_list:
                mid = str(m.get("id"))
                if mid and mid != "None":
                    members[mid] = {
                        "name": m.get("name"),
                        "club": club_name,
                        "rank": m.get("rank") if m.get("rank") is not None else 9999
                    }
    return members

# =========================
# MAIN LOGIC
# =========================
def main():
    print("Fetching data with member details...")
    circles = fetch_all_circles()
    all_members = build_members(circles)
    
    print(f"Total unique members found: {len(all_members)}")
    
    if not all_members:
        print("CRITICAL: No members found. Structure check required.")
        return

    current = dict(sorted(all_members.items(), key=lambda x: x[1]["rank"])[:TOP_N])
    previous = load_state()

    if not previous:
        save_state(current)
        send("📊 Initial Top 1000 snapshot saved.")
        print("Initial state saved.")
        return

    # Diffing
    joined, left, moved = [], [], []
    old_ids, new_ids = set(previous.keys()), set(current.keys())

    for i in new_ids - old_ids: joined.append(f"- `{i}` {current[i]['name']} | {current[i]['club']}")
    for i in old_ids - new_ids: left.append(f"- `{i}` {previous[i]['name']} | {previous[i]['club']}")
    for i in old_ids & new_ids:
        if previous[i]["club"] != current[i]["club"]:
            moved.append(f"- `{i}` {current[i]['name']}: {previous[i]['club']} → {current[i]['club']}")

    messages = []
    if joined: messages.append("🟢 **Entered Top 1000**\n" + "\n".join(joined))
    if left: messages.append("🔴 **Dropped out of Top 1000**\n" + "\n".join(left))
    if moved: messages.append("🟡 **Club Transfers**\n" + "\n".join(moved))

    if messages:
        send("\n".join(messages))
        save_state(current)
        print("Updates sent.")
    else:
        print("No changes detected.")

if __name__ == "__main__":
    main()
