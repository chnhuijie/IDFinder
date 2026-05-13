import os
import time
import requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def compare_and_clean():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    # Anyone not seen in the last 2 hours is considered "left"
    one_hour_ago = time.time() - 3600
    leavers = list(db.find({ "last_seen": { "$lt": one_hour_ago } }))
    
    if leavers:
        entries = [f"🚨 {p.get('name')} (`{p['mid']}`) left **{p.get('club')}**" for p in leavers]
        # Chunking for Discord character limit
        for i in range(0, len(entries), 15):
            content = "**Players Left Top 100**\n" + "\n".join(entries[i:i+15])
            requests.post(DISCORD_WEBHOOK, json={"content": content})

    # CLEANUP: Remove them so the DB stays fresh
    db.delete_many({ "last_seen": { "$lt": one_hour_ago } })

if __name__ == "__main__":
    compare_and_clean()
