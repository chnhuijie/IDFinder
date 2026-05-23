import os, time, requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    
    # 🕒 4-Hour Safety Cutoff Window 
    cutoff_time = time.time() - 14400
    
    # ------------------------------------------------------------------
    # 📊 SEED RUN PROTECTION CHECK
    # ------------------------------------------------------------------
    # Check if this is the first time expanding to 500. 
    # If total tracked clubs in DB is low, we skip "flux alerts" for tonight 
    # to prevent a massive first-scan freeze.
    total_historic_clubs = clubs_col.count_documents({})
    is_first_scale_run = total_historic_clubs < 450 
    
    # ------------------------------------------------------------------
    # 🏰 CLUB LEADERBOARD FLUX DETECTOR (ENTERS/LEAVES TOP 500)
    # ------------------------------------------------------------------
    dropped_clubs = []
    new_clubs = []
    
    # Only calculate structural entry/exit alerts if we actually have historical data to compare against!
    if not is_first_scale_run:
        # A. Detect clubs that left the Top 500
        dropped_clubs_cursor = list(clubs_col.find({"last_updated": {"$lte": cutoff_time}}))
        if dropped_clubs_cursor:
            dropped_ids = []
            for c in dropped_clubs_cursor:
                dropped_clubs.append({
                    "name": c.get("name"),
                    "old_rank": c.get("last_known_rank", 999) + 1
                })
                dropped_ids.append(c["_id"])
            clubs_col.delete_many({"_id": {"$in": dropped_ids}})

        # B. Detect clubs that just entered the Top 500
        active_clubs_meta = list(clubs_col.find({"last_updated": {"$gt": cutoff_time}}))
        for c in active_clubs_meta:
            club_name = c.get("name")
            if club_name:
                # Fast indexed lookup: see if this club had an active record BEFORE tonight
                # If its last_updated was NEVER set before tonight's window, it's a new entry
                if c.get("last_updated", 0) <= cutoff_time:
                    has_tracked_members = db.find_one({"club": club_name, "club_tier": {"$ne": "Unranked"}})
                    if not has_tracked_members:
                        new_clubs.append({
                            "name": club_name,
                            "current_rank": c.get("last_known_rank", 0) + 1
                        })
    else:
        print("🌱 Seed Run Detected: Populating new 201-500 club tiers into database. Skipping flux alerts for tonight.")

    # ------------------------------------------------------------------
    # 🕵️‍♂️ TARGETED TOP 250 LEAVER DETECTOR
    # ------------------------------------------------------------------
    missing_players = db.find({"last_seen": {"$lte": cutoff_time}})
    top250_leavers = []
    
    for player in missing_players:
        prev_club_name = player.get("club")
        p_id = player.get("mid")
        p_name = player.get("name") or "Unknown"
        
        if prev_club_name:
            club_data = clubs_col.find_one({"name": prev_club_name})
            if club_data:
                last_rank = club_data.get("last_known_rank", 999)
                if last_rank < 250:
                    top250_leavers.append({
                        "id": p_id,
                        "name": p_name,
                        "old_club": prev_club_name,
                        "rank": last_rank + 1
                    })
                    
                    db.update_one(
                        {"_id": player["_id"]}, 
                        {"$set": {"previous_club": None, "club": None, "club_tier": "Unranked"}}
                    )

    # ------------------------------------------------------------------
    # 🔄 ACTIVE TRANSFER & NEW PLAYER METRICS
    # ------------------------------------------------------------------
    active_players = db.find({"last_seen": {"$gt": cutoff_time}})
    
    new_count = 0
    shift_count = 0
    new_clubs_dict = {}
    shift_clubs_dict = {}
    
    for player in active_players:
        current_club = player.get("club")
        previous_club = player.get("previous_club")
        
        if not previous_club:
            new_count += 1
            new_clubs_dict[current_club] = new_clubs_dict.get(current_club, 0) + 1
            db.update_one({"_id": player["_id"]}, {"$set": {"previous_club": current_club}})
            
        elif previous_club != current_club:
            shift_count += 1
            shift_clubs_dict[current_club] = shift_clubs_dict.get(current_club, 0) + 1
            db.update_one({"_id": player["_id"]}, {"$set": {"previous_club": current_club}})

    # ------------------------------------------------------------------
    # 📢 DISCORD PAYLOAD GENERATION & DELIVERY
    # ------------------------------------------------------------------
    if not DISCORD_WEBHOOK_URL: return
    messages = []
    
    if (dropped_clubs or new_clubs) and not is_first_scale_run:
        messages.append("📊 **Leaderboard Structural Changes Spotted**")
        for dc in sorted(dropped_clubs, key=lambda x: x['old_rank']):
            messages.append(f"  • 🟥 **{dc['name']}** has **dropped completely out** of the Top 500 (Was Rank {dc['old_rank']})")
        for nc in sorted(new_clubs, key=lambda x: x['current_rank']):
            messages.append(f"  • 🟩 **{nc['name']}** has **entered the Top 500** leaderboard grid (Currently Rank {nc['current_rank']})")
        messages.append("")

    if top250_leavers:
        messages.append("⚠️ **Top 250 Elite Leavers / Free Agents Spotted**")
        messages.append("*Left their club and dropped completely off the leaderboard grid:*")
        for leaver in sorted(top250_leavers, key=lambda x: x['rank']):
            messages.append(f"  • `ID: {leaver['id']}` | **{leaver['name']}** left **{leaver['old_club']}** (Rank {leaver['rank']})")
        messages.append("") 

    # On a seed run, filter out the initial 9000-player explosion from spamming Discord
    if new_count > 0 and not is_first_scale_run:
        messages.append(f"🆕 **{new_count}** new players entered the tracking pool.")
        for club, count in sorted(new_clubs_dict.items(), key=lambda x: x[1], reverse=True)[:15]: # Cap preview list to top 15 entries
            messages.append(f"  • **{club}**: +{count} new player(s)")
            
    if shift_count > 0:
        messages.append(f"\n🔄 **{shift_count}** players moved between tracked clubs.")
        for club, count in sorted(shift_clubs_dict.items(), key=lambda x: x[1], reverse=True)[:15]:
            messages.append(f"  • **{club}**: +{count} transferred player(s)")
            
    if messages:
        full_message = "\n".join(messages)
        if len(full_message) > 1900:
            chunks = [messages[i:i + 20] for i in range(0, len(messages), 20)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(chunk)})
        else:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": full_message})

    client.close()

if __name__ == "__main__":
    process_post_scan_transfers()
