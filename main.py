import requests
import json
import os

# =========================
# CONFIG
# =========================
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Use absolute paths to ensure GitHub Actions finds the file regardless of workdir
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state", "member_state.json")

TOP_N = 1000
API_URL = "https://uma.moe/api/v4/circles/list"


# =========================
# STATE
# =========================
def load_state():
    """Loads previous state, handling missing or empty files."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Ensure we return an empty dict if the file just contains {}
            return data if isinstance(data, dict) and data else {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_state(data):
    """Saves the current state to the JSON file."""
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
    # Discord messages are capped at 2000 chars; truncate if necessary
    payload = {"content": msg[:1990]} 
    requests.post(WEBHOOK_URL, json=payload)


# =========================
# SAFE PAGINATION FETCH
# =========================
def fetch_all_circles():
    circles = []
    page = 0
    limit = 100
    MAX_PAGES = 30  # Safety limit

    while page < MAX_PAGES:
        url = f"{API_URL}?page={page}&limit={limit}&sort_by=rank&sort_dir=asc"

        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"Fetch error page {page}: {e}")
            break

        batch = data.get("circles", data)
        if not batch:
            break

        circles.extend(batch)
        if len(batch) < limit:
            break

        page += 1

    return circles


# =========================
# BUILD MEMBERS
# =========================
def build_members(circles):
    members = {}
    for c in circles:
        club = c.get("name")
        for m in c.get("members", []):
            mid = str(m.get("id"))
            # Default to a high rank if none provided to keep sorting consistent
            rank = m.get("rank") if m.get("rank") is not None else 9999
            
            members[mid] = {
                "name": m.get("name"),
                "club": club,
                "rank": rank
            }
    return members


# =========================
# TOP 1000 FILTER
# =========================
def top_filter(members):
    return dict(
        sorted(members.items(), key=lambda x: x[1]["rank"])[:TOP_N]
    )


# =========================
# DIFF ENGINE
# =========================
def diff(old, new):
    joined, left, moved, rank_changes = [], [], [], []
    old_ids = set(old.keys())
    new_ids = set(new.keys())

    for i in new_ids - old_ids:
        joined.append((i, new[i]))

    for i in old_ids - new_ids:
        left.append((i, old[i]))

    for i in old_ids & new_ids:
        o, n = old[i], new[i]
        if o["club"] != n["club"]:
            moved.append((i, o, n))
        
        # Track rank movement only if both ranks are valid
        if o["rank"] < 9999 and n["rank"] < 9999:
            delta = o["rank"] - n["rank"]
            if delta != 0:
                rank_changes.append((i, o, n, delta))

    return joined, left, moved, rank_changes


# =========================
# MAIN
# =========================
def main():
    print("Fetching data from API...")
    circles = fetch_all_circles()
    all_members = build_members(circles)

    current = top_filter(all_members)
    previous = load_state()

    # INITIALIZATION: If previous state is empty/non-existent
    if not previous:
        save_state(current)
        send("📊 Initial Top 1000 snapshot saved.")
        print("Initialized new state file.")
        return

    # COMPARISON
    joined, left, moved, rank_changes = diff(previous, current)
    messages = []

    if joined:
        msg = "🟢 **Entered Top 1000**\n"
        for i, m in joined:
            msg += f"- `{i}` {m['name']} | {m['club']} | Rank {m['rank']}\n"
        messages.append(msg)

    if left:
        msg = "🔴 **Dropped out of Top 1000**\n"
        for i, m in left:
            msg += f"- `{i}` {m['name']} | {m['club']} | Rank {m['rank']}\n"
        messages.append(msg)

    if moved:
        msg = "🟡 **Club Transfers**\n"
        for i, o, n in moved:
            msg += f"- `{i}` {o['name']}: {o['club']} → {n['club']}\n"
        messages.append(msg)

    if rank_changes:
        # Only report significant rank jumps if the list is too long
        msg = "📈 **Rank Movement**\n"
        for i, o, n, d in rank_changes:
            arrow = "📈" if d > 0 else "📉"
            msg += f"- `{i}` {o['name']} {arrow} ({o['rank']} → {n['rank']})\n"
        messages.append(msg)

    # OUTPUT
    if messages:
        final_report = "\n".join(messages)
        send(final_report)
        print("Changes detected and sent to Discord.")
        # Only save state if there were changes to prevent redundant Git commits
        save_state(current)
    else:
        print("No changes detected in Top 1000.")


if __name__ == "__main__":
    main()
