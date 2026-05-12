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
# DIAGNOSTIC MAIN
# =========================
def main():
    print(f"--- DIAGNOSTIC RUN ---")
    print(f"Checking Path: {STATE_FILE}")
    
    # 1. Test API
    print("Fetching from API...")
    try:
        r = requests.get(f"{API_URL}?page=0&limit=100&sort_by=rank&sort_dir=asc", timeout=10)
        r.raise_for_status()
        data = r.json()
        raw_circles = data.get("circles", [])
        print(f"API Success: Found {len(raw_circles)} circles on page 0")
    except Exception as e:
        print(f"API FAILURE: {e}")
        return

    # 2. Test Member Building
    members = {}
    for c in raw_circles:
        club_name = c.get("name")
        for m in c.get("members", []):
            mid = str(m.get("id"))
            members[mid] = {"name": m.get("name"), "club": club_name, "rank": m.get("rank", 9999)}
    
    print(f"Member Build: Processed {len(members)} unique members from first page")

    # 3. Test State Loading
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            raw_content = f.read()
            print(f"Current File Content: '{raw_content}'")
    else:
        print("State file does not exist yet.")

    # 4. Attempt Write
    print("Attempting to write 10 members for test...")
    test_data = dict(list(members.items())[:10])
    
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(test_data, f, indent=2)
        print("WRITE SUCCESSFUL")
    except Exception as e:
        print(f"WRITE FAILED: {e}")

    # 5. Discord Heartbeat
    if WEBHOOK_URL:
        requests.post(WEBHOOK_URL, json={"content": "🛠 Diagnostic run complete. Check GitHub logs!"})
        print("Discord notification sent.")
    else:
        print("No Webhook URL found in env.")

if __name__ == "__main__":
    main()
