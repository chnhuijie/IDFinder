import os
import time
import requests
from collections import Counter
from pymongo import MongoClient, UpdateOne

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def send_discord_in_chunks(webhook_url, messages):
    current_chunk = []
    current_length = 0

    for line in messages:
        if current_length + len(line) + 1 > 1900:
            requests.post(webhook_url, json={"content": "\n".join(current_chunk)})
            time.sleep(1.5)  
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line) + 1

    if current_chunk:
        requests.post(webhook_url, json={"content": "\n".join(current_chunk)})

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    
    db.create_index([("last_seen", 1)])
    db.create_index([("updated_at", 1)], expireAfterSeconds=2592000)
    
    cutoff_time = time.time() - 14400
    missing_players = list(db.find({"last_seen": {"$lte": cutoff_time}, "club_id": {"$ne": None}}))
    top250_leavers = []
    
    if missing_players:
        unique_club_ids = list(set(p.get("club_id") for p in missing_players if p.get("club_id")))
        clubs_data = list(clubs_col.find({"circle_id": {"$in": unique_club_ids}}))
        clubs_map = {c["circle_id"]: c.get("last_known_rank", 999) for c in clubs_data}
        bulk_updates = []
        
        for player in missing_players:
            club_id = player.get("club_id")
            last_rank = clubs_map.get(club_id, 999)
            
            if last_rank < 250:
                top250_leavers.append({
                    "id": player.get("mid"),
                    "name": player.get("name", "Unknown"),
                    "old_club": player.get("club"),
                    "rank": last_rank + 1
                })
                bulk_updates.append(UpdateOne(
                    {"_id": player["_id"]}, 
                    {"$set": {"club": None, "club_id": None, "previous_club": None, "club_tier": "Unranked"}}
                ))
        
        if bulk_updates:
            db.bulk_write(bulk_updates, ordered=False)

    new_players = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_new_flag": True}, {"club": 1}))
    transfers = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_transfer_flag": True}, {"club": 1}))

    new_clubs_dict = Counter(p.get("club", "Unknown Club") for p in new_players)
    shift_clubs_dict = Counter(p.get("club", "Unknown Club") for p in transfers)

    if not DISCORD_WEBHOOK_URL: 
        client.close()
        return
        
    messages = []

    if top250_leavers:
        messages.append("**Top 250 Club Leavers Detected**")
        messages.append("*Left their club and dropped completely off the leaderboard:*")
        for leaver in sorted(top250_leavers, key=lambda x: x['rank']):
            messages.append(f"  • `ID: {leaver['id']}` | **{leaver['name']}** left **{leaver['old_club']}** (Rank {leaver['rank']})")
        messages.append("")

    if new_players:
        messages.append(f"**{len(new_players)}** new players entered the tracking pool.")
        for club, count in new_clubs_dict.most_common(15):
            messages.append(f"  • **{club}**: +{count} new player(s)")
        messages.append("")

    if transfers:
        messages.append(f"**{len(transfers)}** players moved between tracked clubs.")
        for club, count in shift_clubs_dict.most_common(15):
            messages.append(f"  • **{club}**: +{count} transferred player(s)")

    if messages:
        send_discord_in_chunks(DISCORD_WEBHOOK_URL, messages)
        print("📢 Detailed Discord notification successfully delivered!")
        print("🧼 Wiping temporary operational flags and snapshots for tomorrow's run...")
        db.update_many(
            {"last_seen": {"$gt": cutoff_time}}, 
            {"$set": {
                "is_new_flag": False, 
                "is_transfer_flag": False,
                "historical_club_snapshot": None,
                "historical_club_id_snapshot": None
            }}
        )
    else:
        print("💤 No roster movements detected tonight. Operational flags intact.")

    client.close()

if __name__ == "__main__":
    process_post_scan_transfers()
