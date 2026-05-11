import requests
import json
import os

# =========================
# CONFIG
# =========================
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
STATE_FILE = "state/member_state.json"

TOP_N = 1000

API_URL = "https://uma.moe/api/v4/circles/list"


# =========================
# STATE
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
# DISCORD
# =========================
def send(msg):
    if not WEBHOOK_URL:
        print("No webhook set")
        return
    requests.post(WEBHOOK_URL, json={"content": msg})


# =========================
# SAFE PAGINATION FETCH
# =========================
def fetch_all_circles():
    circles = []
    page = 0
    limit = 100
    MAX_PAGES = 30  # 🔥 HARD SAFETY LIMIT (prevents 6+ min runtime)

    while page < MAX_PAGES:
        url = (
            f"{API_URL}?page={page}"
            f"&limit={limit}&sort_by=rank&sort_dir=asc"
        )

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

        # stop if last page is incomplete
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

            rank = m.get("rank")
            if rank is None:
                rank = -1

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
        o = old[i]
        n = new[i]

        if o["club"] != n["club"]:
            moved.append((i, o, n))

        if o["rank"] != -1 and n["rank"] != -1:
            delta = o["rank"] - n["rank"]
            if delta != 0:
                rank_changes.append((i, o, n, delta))

    return joined, left, moved, rank_changes


# =========================
# MAIN
# =========================
def main():
    print("Fetching circles...")

    circles = fetch_all_circles()
    members = build_members(circles)

    current = top_filter(members)
    previous = load_state()

    if not previous:
        save_state(current)
        send("📊 Initial Top 1000 snapshot saved.")
        print("Initialized")
        return

    joined, left, moved, rank_changes = diff(previous, current)

    messages = []

    # JOINED
    if joined:
        msg = "🟢 Entered Top 1000\n"
        for i, m in joined:
            msg += f"- `{i}` {m['name']} | {m['club']} | Rank {m['rank']}\n"
        messages.append(msg)

    # LEFT
    if left:
        msg = "🔴 Dropped out of Top 1000\n"
        for i, m in left:
            msg += f"- `{i}` {m['name']} | {m['club']} | Rank {m['rank']}\n"
        messages.append(msg)

    # TRANSFERS
    if moved:
        msg = "🟡 Club Transfers\n"
        for i, o, n in moved:
            msg += (
                f"- `{i}` {o['name']}\n"
                f"  {o['club']} → {n['club']}\n"
                f"  Rank {o['rank']} → {n['rank']}\n"
            )
        messages.append(msg)

    # RANK MOVEMENT
    if rank_changes:
        msg = "📈 Rank Movement\n"
        for i, o, n, d in rank_changes:
            arrow = "📈" if d > 0 else "📉"
            msg += f"- `{i}` {o['name']} {arrow}\n  {o['rank']} → {n['rank']} (Δ {d})\n"
        messages.append(msg)

    # SEND
    if messages:
        send("\n".join(messages))
        print("\n".join(messages))
    else:
        print("No changes detected")

    save_state(current)


if __name__ == "__main__":
    main()
