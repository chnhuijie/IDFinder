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
# STATE
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

# =========================
# DISCORD
# =========================
def send(msg):
    if not WEBHOOK_URL:
        print("No webhook set")
        return
    # Truncate to stay under Discord's 2000 character limit
    requests.post(WEBHOOK_URL, json={"content": msg[:1990]})

# =========================
# FETCH & BUILD
# =========================
def fetch_all_circles():
    circles = []
    page = 0
    limit = 100
    MAX_PAGES = 15 # Top 1000 is usually within the first 10-15 pages

    while page < MAX_PAGES:
        url = f"{API_URL}?page={page}&limit={limit}&sort_by=rank&sort_dir=asc"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            batch = data.get("circles", [])
            if not batch: break
            circles.extend(batch)
            if len(batch) < limit: break
            page += 1
        except Exception as e:
            print(f"Fetch error: {e}")
            break
    return circles

def build_members(circles):
    members = {}
    for c in circles:
        club_name = c.get("name")
        # Try to find the member list (API may use 'members' or 'leaderboard')
        member_list = c.get("members", [])
        
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
# DIFF ENGINE
# =========================
def diff(old, new):
    joined, left, moved, rank_changes = [], [], [], []
    old_ids, new_ids = set(old.keys()), set(new.keys())

    for i in new_ids - old_ids: joined.append((i, new[i]))
    for i in old_ids - new_ids: left.append((i, old[i]))
    for i in old_ids & new_ids:
        o, n = old[i], new[i]
        if o["club"] != n["club"]: moved.append((i, o, n))
        if o["rank"] < 9999 and n["rank"] < 9999:
            d = o["rank"] - n["rank"]
            if d != 0: rank_changes.append((i, o, n, d))
    return joined, left, moved, rank_changes

# =========================
# MAIN
# =========================
def main():
    print("Fetching data...")
    circles = fetch_all_circles()
    all_members = build_members(circles)
    
    print(f"Total unique members found: {len(all_members)}")
    
    if not all_members:
        print("CRITICAL: No members found. Check API structure.")
        return

    current = dict(sorted(all_members.items(), key=lambda x: x[1]["rank"])[:TOP_N])
    previous = load_state()

    if not previous:
        save_state(current)
        send("📊 Initial Top 1000 snapshot saved.")
        return

    joined, left, moved, rank_changes = diff(previous, current)
    messages = []

    if joined:
        msg = "🟢 **Entered Top 1000**\n"
        for i, m in joined: msg += f"- `{i}` {m['name']} | {m['club']}\n"
        messages.append(msg)

    if left:
        msg = "🔴 **Dropped out of Top 1000**\n"
        for i, m in left: msg += f"- `{i}` {m['name']} | {m['club']}\n"
        messages.append(msg)

    if moved:
        msg = "🟡 **Club Transfers**\n"
        for i, o, n in moved: msg += f"- `{i}` {o['name']}: {o['club']} → {n['club']}\n"
        messages.append(msg)

    if messages:
        send("\n".join(messages))
        save_state(current)
        print("Changes sent to Discord and state updated.")
    else:
        print("No changes detected.")

if __name__ == "__main__":
    main()
