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
    
    cutoff_time = time.time() - 14400
    
    missing_players = list(db.find({"last_seen": {"$lte": cutoff_time}, "club_id": {"$ne": None}}))
    new_players = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_new_flag": True}, {"club": 1, "club_id": 1}))
    transfers = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_transfer_flag": True}, {"club": 1, "club_id": 1}))

    all_club_ids = set()
    for p in missing_players + new_players + transfers:
        if p.get("club_id"):
            all_club_ids.add(p.get("club_id"))
            
    clubs_info = {}
    if all_club_ids:
        clubs_data = list(clubs_col.find({"circle_id": {"$in": list(all_club_ids)}}))
        clubs_info = {c["circle_id"]: {"rank": c.get("last_known_rank", 999), "last_updated": c.get("last_updated", 0)} for c in clubs_data}

    top250_leavers = []
    
    if missing_players:
        bulk_updates = []
        for player in missing_players:
            club_id = player.get("club_id")
            club_details = clubs_info.get(club_id, {"rank": 999, "last_updated": 0})
            
            if club_details["last_updated"] <= cutoff_time:
                continue 
                
            if club_details["rank"] < 250:
                top250_leavers.append({
                    "id": player.get("mid"), 
                    "name": player.get("name", "Unknown"), 
                    "old_club": player.get("club"), 
                    "old_club_id": club_id, 
                    "rank": club_details["rank"]
                })
                bulk_updates.append(UpdateOne({"_id": player["_id"]}, {"$set": {"club": None, "club_id": None, "club_tier": "Unranked"}}))
        
        if bulk_updates:
            db.bulk_write(bulk_updates, ordered=False)

    print("\n=== FINAL TRACKING SUMMARY ===")
    print(f"Top 250 Club Leavers Detected: {len(top250_leavers)}")
    print(f"Number of players entered tracking pool: {len(new_players)}")
    print(f"Transfers detected between tracked clubs: {len(transfers)}")
    print("==============================\n")

    if not DISCORD_WEBHOOK_URL: 
        client.close()
        return
        
    messages = []
    
    if top250_leavers or new_players or transfers:
        if top250_leavers:
            leaver_counts = Counter((l['old_club_id'], l['old_club']) for l in top250_leavers)
            dropped_clubs = [c for c, count in leaver_counts.items() if count >= 25]
            
            if len(dropped_clubs) > 10:
                messages.append("**API OUTAGE DETECTED**")
            else:
                individual_leavers = [l for l in top250_leavers if (l['old_club_id'], l['old_club']) not in dropped_clubs]
                if dropped_clubs:
                    messages.append("**Club Dropoff Detected**")
                    for club_id, club_name in dropped_clubs:
                        c_rank = clubs_info.get(club_id, {}).get("rank", 999)
                        rank_str = f"Rank {c_rank}" if c_rank != 999 else "Unranked"
                        messages.append(f"  • **{club_name}** ({rank_str}) | Lost tracking for {leaver_counts[(club_id, club_name)]} players.")
                        
                if individual_leavers:
                    messages.append("**Top 250 Club Leavers Detected**")
                    for l in sorted(individual_leavers, key=lambda x: x['rank']):
                        rank_str = f"Rank {l['rank']}" if l['rank'] != 999 else "Unranked"
                        messages.append(f"  • `ID: {l['id']}` | **{l['name']}** left **{l['old_club']}** ({rank_str})")

        if new_players:
            messages.append(f"**{len(new_players)}** new players entered the tracking pool.")
            new_clubs = Counter((p.get("club_id"), p.get("club")) for p in new_players)
            for (c_id, c_name), count in new_clubs.most_common(15):
                c_rank = clubs_info.get(c_id, {}).get("rank", 999)
                rank_str = f"Rank {c_rank}" if c_rank != 999 else "Unranked"
                messages.append(f"  • **{c_name}** ({rank_str}): +{count} new")

        if transfers:
            messages.append(f"**{len(transfers)}** players moved between tracked clubs.")
            shift_clubs = Counter((p.get("club_id"), p.get("club")) for p in transfers)
            for (c_id, c_name), count in shift_clubs.most_common(15):
                c_rank = clubs_info.get(c_id, {}).get("rank", 999)
                rank_str = f"Rank {c_rank}" if c_rank != 999 else "Unranked"
                messages.append(f"  • **{c_name}** ({rank_str}): +{count} transferred")
    else:
        messages.append("**Scan Complete:** No movement spotted in tracked clubs.")

    send_discord_in_chunks(DISCORD_WEBHOOK_URL, messages)
    
    db.update_many({"last_seen": {"$gt": cutoff_time}}, {"$set": {"is_new_flag": False, "is_transfer_flag": False}})

    client.close()

if __name__ == "__main__":
    process_post_scan_transfers()
