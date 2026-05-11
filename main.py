import requests
import json
import os

# =========================
# CONFIG
# =========================
API_URL = "https://uma.moe/api/v4/circles"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

STATE_FILE = "state/member_state.json"

TOP_N = 1500

# CHANGE THIS IF NEEDED AFTER INSPECTING API
RANK_FIELD = "rank"


# =========================
# STATE HANDLING
# =========================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(data):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# =========================
# WEBHOOK
# =========================
def send(msg):
    if not WEBHOOK_URL:
        print("No webhook set")
        return
    requests.post(WEBHOOK_URL, json={"content": msg})


# =========================
# FETCH DATA
# =========================
def fetch():
    r = requests.get(API_URL)
    r.raise_for_status()
    return r.json()


# =========================
# EXTRACT MEMBERS
# =========================
def extract(data):
    members = {}

    circles = data.get("circles", data if isinstance(data, list) else [])

    for c in circles:
        club = c.get("name") or c.get("club_name")

        for m in c.get("members", []):
            mid = str(m.get("id"))

            members[mid] = {
                "name": m.get("name"),
                "club": club,
                "rank": m.get(RANK_FIELD, 999999)
            }

    return members


# =========================
# TOP 1500 FILTER (GUARANTEED)
# =========================
def top_filter(members):
    sorted_members = sorted(
        members.items(),
        key=lambda x: x[1]["rank"]
    )
    return dict(sorted_members[:TOP_N])


# =========================
# COMPARE
# =========================
def diff(old, new):
    joined, left, moved = [], [], []

    old_ids = set(old.keys())
    new_ids = set(new.keys())

    for i in new_ids - old_ids:
        joined.append((i, new[i]))

    for i in old_ids - new_ids:
        left.append((i, old[i]))

    for i in old_ids & new_ids:
        if old[i]["club"] != new[i]["club"]:
            moved.append((i, old[i], new[i]))

    return joined, left, moved


# =========================
# MAIN
# =========================
def main():
    data = fetch()
    all_members = extract(data)

    current = top_filter(all_members)
    previous = load_state()

    if not previous:
        save_state(current)
        send("📊 Initial Top 1500 snapshot saved.")
        print("Init done")
        return

    joined, left, moved = diff(previous, current)

    msgs = []

    if joined:
        msg = "🟢 Entered Top 1500\n"
        for i, m in joined:
            msg += f"- `{i}` {m['name']} | {m['club']} | Rank {m['rank']}\n"
        msgs.append(msg)

    if left:
        msg = "🔴 Dropped out of Top 1500\n"
        for i, m in left:
            msg += f"- `{i}` {m['name']} | {m['club']} | Rank {m['rank']}\n"
        msgs.append(msg)

    if moved:
        msg = "🟡 Club Transfers\n"
        for i, o, n in moved:
            msg += f"- `{i}` {o['name']}\n  {o['club']} → {n['club']}\n  Rank {o['rank']} → {n['rank']}\n"
        msgs.append(msg)

    if msgs:
        send("\n".join(msgs))
        print("\n".join(msgs))
    else:
        print("No changes")

    save_state(current)


if __name__ == "__main__":
    main()
