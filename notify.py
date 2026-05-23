import os, time, requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    
    # 🕒 4-Hour Safety Cutoff Window 
    # Ensures all parallel cloud nodes have fully completed writing before we check for missing members
    cutoff_time = time.time() - 14400
    
    # ------------------------------------------------------------------
    # 🕵️‍♂️ ELITE FREE AGENT DETECTOR (TOP 250 LEAVERS)
    # ------------------------------------------------------------------
    # Look for players whose last_seen was NOT updated during tonight's sweep
    missing_players = db.find({"last_seen": {"$lte": cutoff_time}})
    
    top250_leavers = []
    
    for player in missing_players:
        prev_club_name = player.get("club")
        p_id = player.get("mid")
        p_name = player.get("name") or "Unknown"
        
        if prev_club_name:
            # Cross-reference the club's rank recorded tonight
            club_data = clubs_col.find_one({"name": prev_club_name})
            if club_data:
                # MongoDB index 0-249 represents Absolute Ranks 1 to 250
                last_rank = club_data.get("last_known_rank", 999)
                
                if last_rank < 250:
                    top250_leavers.append({
                        "id": p_id,
                        "name": p_name,
                        "old_club": prev_club_name,
                        "rank": last_rank + 1
                    })
                    
                    # Wipe their active tracking anchor so they don't fire alerts tomorrow night
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
        
        # Scenario A: Brand new player profile never seen before
        if not previous_club:
            new_count += 1
            new_clubs_dict[current_club] = new_clubs_dict.get(current_club, 0) + 1
            db.update_one({"_id": player["_id"]}, {"$set": {"previous_club": current_club}})
            
        # Scenario B: Existing player swapped clubs
        elif previous_club != current_club:
            shift_count += 1
            shift_clubs_dict[current_club] = shift_clubs_dict.get(current_club, 0) + 1
            db.update_one({"_id": player["_id"]}, {"$set": {"previous_club": current_club}})

    # ------------------------------------------------------------------
    # 📢 DISCORD PAYLOAD GENERATION & DELIVER
    # ------------------------------------------------------------------
    if not DISCORD_WEBHOOK_URL: return
    messages = []
    
    # Section 1: Elite Free Agents (Dropped entirely off the Top 500 radar)
    if top250_leavers:
        messages.append("⚠️ **Top 250 Elite Leavers / Free Agents Spotted**")
        messages.append("*Left their club and dropped completely off the leaderboard grid:*")
        for leaver in sorted(top250_leavers, key=lambda x: x['rank']):
            messages.append(f"  • `ID: {leaver['id']}` | **{leaver['name']}** left **{leaver['old_club']}** (Rank {leaver['rank']})")
        messages.append("") 

    # Section 2: New Entries
    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered the tracking pool.")
        for club, count in sorted(new_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} new player(s)")
            
    # Section 3: Active Roster Swaps
    if shift_count > 0:
        messages.append(f"\n🔄 **{shift_count}** players moved between tracked clubs.")
        for club, count in sorted(shift_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} transferred player(s)")
            
    # Secure delivery chunking to stay safely beneath Discord's 2000 character block caps
    if messages:
        full_message = "\n".join(messages)
        if len(full_message) > 1900:
            chunks = [messages[i:i + 20] for i in range(0, len(messages), 20)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(chunk)})
        else:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": full_message})

if __name__ == "__main__":
    process_post_scan_transfers()
