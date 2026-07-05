import os
import time
import requests
from collections import Counter
from pymongo import MongoClient, UpdateOne, DeleteOne
from utils import safe_get 

UMA_API_KEY = os.getenv("UMA_API_KEY")
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
    print("Initializing high-speed notification sweep...")
    time.sleep(15) # Brief buffer to ensure the 1-minute rate limit window is clean
    
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    blacklist_col = client["uma_tracker"]["blacklist"]
    
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

    top500_leavers_raw = []
    
    # --- GLOBAL RAM BATCHING ---
    global_bulk_updates = []
    
    if missing_players:
        known_botters = set(doc["mid"] for doc in blacklist_col.find({}, {"mid": 1}))
        
        for player in missing_players:
            club_id = player.get("club_id")
            club_details = clubs_info.get(club_id, {"rank": 999, "last_updated": 0})
            
            if club_details["last_updated"] <= cutoff_time:
                continue 
                
            if club_details["rank"] <= 500:
                player_mid = player.get("mid")
                
                if int(player_mid) in known_botters:
                    global_bulk_updates.append(UpdateOne(
                        {"_id": player["_id"]}, 
                        {"$set": {"club": None, "club_id": None, "club_tier": "Unranked", "previous_club": None, "previous_club_id": None}}
                    ))
                    continue
                
                # Fast Pacing for Profile verification (360req/min limit)
                time.sleep(0.35) 
                
                try:
                    profile_url = f"https://uma.moe/api/v4/user/profile/{player_mid}"
                    prof_data = safe_get(profile_url, UMA_API_KEY)
                    
                    if prof_data == "RATE_LIMIT":
                        print(f"Rate limited on Profile API for {player_mid}. Freezing for 45 seconds...")
                        time.sleep(45)  
                        
                        prof_data = safe_get(profile_url, UMA_API_KEY) # Second attempt
                        if prof_data == "RATE_LIMIT":
                            print(f"Still blocked. Skipping {player_mid} to protect pipeline.")
                            continue        

                    # 404: Account was wiped/banned. Do not send to /cl.
                    if prof_data == "NOT_FOUND":
                        global_bulk_updates.append(UpdateOne(
                            {"_id": player["_id"]}, 
                            {"$set": {"club": None, "club_id": None, "club_tier": "Unranked", "previous_club": None, "previous_club_id": None}}
                        ))
                        print(f"BAN DETECTED (404): {player.get('name')}. Ignored.")
                        continue

                    # 200: Data Flicker check
                    if isinstance(prof_data, dict):
                        live_circle = prof_data.get("circle")
                        
                        if live_circle and live_circle.get("circle_id") == club_id:
                            global_bulk_updates.append(UpdateOne(
                                {"_id": player["_id"]}, 
                                {"$set": {"last_seen": time.time()}}
                            ))
                            print(f"FLICKER CAUGHT: {player.get('name')} is still in {player.get('club')}. Ignored.")
                            continue 
                            
                except Exception as e:
                    print(f"Profile check failed for {player_mid}: {e}")
                    continue

                # Passed anti-flicker! Add to leaver list for Discord and the /cl Applicant Queue
                top500_leavers_raw.append({
                    "_id": player["_id"],
                    "id": player_mid, 
                    "name": player.get("name", "Unknown"), 
                    "old_club": player.get("club"), 
                    "old_club_id": club_id, 
                    "rank": club_details["rank"]
                })

    leaver_counts = Counter((l['old_club_id'], l['old_club']) for l in top500_leavers_raw)
    dropped_clubs = [c for c, count in leaver_counts.items() if count >= 25]
    is_api_outage = len(dropped_clubs) > 60
    
    individual_leavers = []

    if is_api_outage:
        print("CRITICAL: Global API Outage detected. Halting leaver processing.")
    else:
        for l in top500_leavers_raw:
            if (l['old_club_id'], l['old_club']) in dropped_clubs:
                global_bulk_updates.append(DeleteOne({"_id": l["_id"]}))
            else:
                individual_leavers.append(l)
                # Formats for Bamboo's `/cl` queue (club: None, previous_club: Set)
                global_bulk_updates.append(UpdateOne(
                    {"_id": l["_id"]}, 
                    {"$set": {"club": None, "club_id": None, "club_tier": "Unranked", "previous_club": l["old_club"], "previous_club_id": l["old_club_id"]}}
                ))

    # Single Massive Execution to the DB
    if global_bulk_updates:
        print(f"Executing Global Write Array: {len(global_bulk_updates)} operations.")
        db.bulk_write(global_bulk_updates, ordered=False)

    print("\n=== FINAL TRACKING SUMMARY ===")
    print(f"Normal Top 500 Leavers Sent to /cl: {len(individual_leavers)}")
    print(f"Number of players entered tracking pool: {len(new_players)}")
    print(f"Transfers detected between tracked clubs: {len(transfers)}")
    print("==============================\n")

    if not DISCORD_WEBHOOK_URL: 
        client.close()
        return
        
    messages = []
    
    if top500_leavers_raw or new_players or transfers:
        if top500_leavers_raw:
            if is_api_outage:
                messages.append("**API OUTAGE DETECTED:** Mass data loss suspected. Leaver tracking suspended to protect database.")
            else:
                if dropped_clubs:
                    messages.append("**Club Dropoff Detected**")
                    for club_id, club_name in dropped_clubs:
                        c_rank = clubs_info.get(club_id, {}).get("rank", 999)
                        rank_str = f"Rank {c_rank}" if c_rank != 999 else "Unranked"
                        messages.append(f"  • **{club_name}** ({rank_str}) | Lost tracking for {leaver_counts[(club_id, club_name)]} players.")
                        
                if individual_leavers:
                    messages.append("**Top 500 Club Leavers Detected** *(Awaiting /check)*")
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

    messages.append("\n*Data provided by [uma.moe](https://uma.moe/)*")
    
    send_discord_in_chunks(DISCORD_WEBHOOK_URL, messages)
    
    db.update_many({"last_seen": {"$gt": cutoff_time}}, {"$set": {"is_new_flag": False, "is_transfer_flag": False}})

    client.close()

if __name__ == "__main__":
    process_post_scan_transfers()
