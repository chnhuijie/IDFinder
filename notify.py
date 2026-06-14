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
            requests.post(webhook_url, json={"content": "\n".join(current_chunk)}, timeout=15)
            time.sleep(1.5)  
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line) + 1

    if current_chunk:
        requests.post(webhook_url, json={"content": "\n".join(current_chunk)}, timeout=15)

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
        clubs_info = {c["circle_id"]: {"rank": c.get("last_known_rank", 999), "last_updated": c.get("last_updated", 0)} for c in clubs_data}
        
        bulk_updates = []
        
        for player in missing_players:
            club_id = player.get("club_id")
            club_details = clubs_info.get(club_id, {"rank": 999, "last_updated": 0})
            
            if club_details["last_updated"] > cutoff_time:
                continue 
                
            last_rank = club_details["rank"]
            
            if last_rank < 250:
                top250_leavers.append({
                    "id": player.get("mid"),
                    "name": player.get("name", "Unknown"),
                    "old_club": player.get("club"),
                    "old_club_id": club_id, 
                    "rank": last_rank + 1
                })
                bulk_updates.append(UpdateOne(
                    {"_id": player["_id"]}, 
                    {"$set": {"club": None, "club_id": None, "previous_club": None, "club_tier": "Unranked"}}
                ))
        
        if bulk_updates:
            db.bulk_write(bulk_updates, ordered=False)

    new_players = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_new_flag": True}, {"club": 1, "club_id": 1}))
    transfers = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_transfer_flag": True}, {"club": 1, "club_id": 1}))

    new_clubs_dict = Counter((p.get("club_id"), p.get("club", "Unknown Club")) for p in new_players)
    shift_clubs_dict = Counter((p.get("club_id"), p.get("club", "Unknown Club")) for p in transfers)

    if not DISCORD_WEBHOOK_URL: 
        client.close()
        return
        
    messages = []

    if top250_leavers:
        leaver_counts = Counter((leaver['old_club_id'], leaver['old_club']) for leaver in top250_leavers)
        dropped_clubs = [club_tuple for club_tuple, count in leaver_counts.items() if count >= 25]
        
        if len(dropped_clubs) > 10:
            messages.append("🚨 **CRITICAL API OUTAGE DETECTED** 🚨")
            messages.append(f"*`uma.moe` failed to return data for {len(dropped_clubs)} Top-250 clubs. The API is likely offline or your scrapers are blocked. Individual dropoff alerts have been paused to prevent spam.*")
            messages.append("")
            individual_leavers = [] 
        else:
            individual_leavers = [leaver for leaver in top250_leavers if (leaver['old_club_id'], leaver['old_club']) not in dropped_clubs]

            if dropped_clubs:
                messages.append("**Club Dropoff Detected**")
                messages.append("*The following clubs dropped completely off the Top 250 leaderboard:*")
                for club_id, club_name in dropped_clubs:
                    club_rank = next((l['rank'] for l in top250_leavers if l['old_club_id'] == club_id), "??")
                    leaver_count = leaver_counts[(club_id, club_name)]
                    messages.append(f"  • **{club_name}** (Rank {club_rank}) | Lost tracking for {leaver_count} players.")
                messages.append("")

            if individual_leavers:
                messages.append("**Top 250 Club Leavers Detected**")
                messages.append("*Left their club and dropped completely off the leaderboard:*")
                for leaver in sorted(individual_leavers, key=lambda x: x['rank']):
                    messages.append(f"  • `ID: {leaver['id']}` | **{leaver['name']}** left **{leaver['old_club']}** (Rank {leaver['rank']})")
                messages.append("")

    if new_players:
        messages.append(f"**{len(new_players)}** new players entered the tracking pool.")
        for (club_id, club_name), count in new_clubs_dict.most_common(15):
            messages.append(f"  • **{club_name}**: +{count} new player(s)")
        messages.append("")

    if transfers:
        messages.append(f"**{len(transfers)}** players moved between tracked clubs.")
        for (club_id, club_name), count in shift_clubs_dict.most_common(15):
            messages.append(f"  • **{club_name}**: +{count} transferred player(s)")

    if messages:
        send_discord_in_chunks(DISCORD_WEBHOOK_URL, messages)
        db.update_many(
            {"last_seen": {"$gt": cutoff_time}}, 
            {"$set": {
                "is_new_flag": False, 
                "is_transfer_flag": False,
                "historical_club_snapshot": None,
                "historical_club_id_snapshot": None
            }}
        )

    client.close()

if __name__ == "__main__":
    process_post_scan_transfers()
