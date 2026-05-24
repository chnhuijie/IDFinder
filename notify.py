import os
import time
import requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    
    # Core performance enforcement index
    db.create_index([("last_seen", 1)])
    
    cutoff_time = time.time() - 14400
    
    # 1. 🕵️‍♂️ Process True Elite Grid Leavers (Lookups cached via local index scan)
    missing_players = list(db.find({"last_seen": {"$lte": cutoff_time}, "club_id": {"$ne": None}}))
    top250_leavers = []
    
    for player in missing_players:
        club_data = clubs_col.find_one({"circle_id": player.get("club_id")})
        if club_data and club_data.get("last_known_rank", 999) < 250:
            top250_leavers.append({
                "id": player.get("mid"),
                "name": player.get("name", "Unknown"),
                "old_club": player.get("club"),
                "rank": club_data.get("last_known_rank", 0) + 1
            })
            # Drop club associations since they are officially free agents off the leaderboard grid
            db.update_one(
                {"_id": player["_id"]}, 
                {"$set": {"club": None, "club_id": None, "previous_club": None, "club_tier": "Unranked"}}
            )

    # 2. 📊 Gather operational flags compiled by the parallel nodes
    new_players = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_new_flag": True}))
    transfers = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_transfer_flag": True}))

    if not DISCORD_WEBHOOK_URL: 
        client.close()
        return
        
    messages = []

    # 3. 📢 Format Data Bundles
    if top250_leavers:
        messages.append("⚠️ **Top 250 Elite Leavers / Free Agents Spotted**")
        messages.append("*Left their club and dropped completely off the leaderboard grid:*")
        for leaver in sorted(top250_leavers, key=lambda x: x['rank']):
            messages.append(f"  • `ID: {leaver['id']}` | **{leaver['name']}** left **{leaver['old_club']}** (Rank {leaver['rank']})")
        messages.append("")

    if new_players:
        messages.append(f"🆕 **{len(new_players)}** new trainers entered the tracking pool.")
    if transfers:
        messages.append(f"🔄 **{len(transfers)}** roster transfers detected between tracked clubs.")

    # 4. 🔥 Deliver Content and Reset Environment Flags Safe Layer
    if messages:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(messages)})
        print("📢 Discord notification successfully delivered!")

        print("🧼 Wiping temporary operational flags and snapshots for tomorrow's run...")
        db.update_many(
            {"last_seen": {"$gt": cutoff_time}}, 
            {"$set": {
                "is_new_flag": False, 
                "is_transfer_flag": False,
                "historical_club_snapshot": None
            }}
        )
    else:
        print("💤 No roster movements detected tonight. Operational flags intact.")

    client.close()

if __name__ == "__main__":
    process_post_scan_transfers()
