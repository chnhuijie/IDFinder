import os
import sys
import time
import random
import logging
import datetime
import requests as discord_req
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def send_discord(title, entries):
    if not DISCORD_WEBHOOK or not entries: return
    content = f"**{title}**\n" + "\n".join(entries)
    discord_req.post(DISCORD_WEBHOOK, json={"content": content})

def safe_get(url):
    time.sleep(random.uniform(5.0, 10.0)) 
    try:
        res = session.get(url.rstrip('/'), impersonate="chrome120", timeout=30)
        if res.status_code == 200: return res.json()
    except Exception as e:
        log.error(f"Error: {e}")
    return None

def main(start, end):
    start, end = int(start), int(end)
    now_dt = datetime.datetime.now()
    curr_year, curr_month = now_dt.year, now_dt.month
    
    log.info("Warming up...")
    session.get("https://uma.moe/ranking", impersonate="chrome120")
    
    data = safe_get(f"{BASE_API}/list?page=0&limit=100&sort_by=rank&sort_dir=asc")
    if not data: return

    target = data["circles"][start:end]
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    joiners = []
    for club in target:
        cid, name = club.get("circle_id"), club.get("name")
        club_url = f"{BASE_API}?circle_id={cid}&year={curr_year}&month={curr_month}"
        detail = safe_get(club_url)
        
        if detail and "members" in detail:
            ops = []
            for m in (detail.get("members") or []):
                p_id = str(m.get("viewer_id") or m.get("id"))
                p_name = m.get("name", "Unknown")

                if not db.find_one({"mid": p_id}):
                    joiners.append(f"✅ {p_name} (`{p_id}`) -> **{name}**")

                ops.append(UpdateOne(
                    {"mid": p_id},
                    {"$set": {"name": p_name, "club": name, "last_seen": time.time()}},
                    upsert=True
                ))
            if ops: 
                db.bulk_write(ops, ordered=False)
                log.info(f"Synced: {name}")

    if joiners:
        send_discord("🆕 New Players Detected", joiners[:20]) # Limit to 20 per batch for Discord

if __name__ == "__main__":
    if len(sys.argv) == 3: main(sys.argv[1], sys.argv[2])
