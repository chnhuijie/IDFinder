import os, time, requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    
    # 🕒 4-Hour Cutoff Window to verify who was missing tonight
    cutoff_time = time.time() - 14400
    
    # ------------------------------------------------------------------
    # 🕵️‍♂️ NEW FEATURE: TARGETED TOP 250 LEAVER DETECTOR
    # ------------------------------------------------------------------
    # 1. Find players who were NOT updated tonight (dropped out of top 500)
    missing_players = db.find({"last_seen": {"$lte": cutoff_time}})
    
    top250_leavers = []
    
    for player in missing_players:
        prev_club_name = player.get("club")
        p_id = player.get("mid")
        p_name = player.get("name") or "Unknown"
        
        if prev_club_name:
            # Look up the previous club's rank recorded during the last cycle
            club_data = clubs_col.find_one({"name": prev_club_name})
            if club_data:
                # MongoDB rank index starts at 0, so rank 249 is absolute Rank 250
                last_rank = club_data.get("last_known_rank", 999)
                
                if last_rank < 250:
                    top250_leavers.append({
                        "id": p_id,
                        "name": p_name,
                        "old_club": prev_club_name,
                        "rank": last_rank + 1
                    })
                    
                    # Clean up their profile status in the database so they don't 
                    # trigger alerts repeatedly on subsequent nights
                    db.update_one(
                        {"_id": player["_id"]}, 
                        {"$set": {"previous_club": None, "club": None, "club_tier": "Unranked"}}
                    )

    # ------------------------------------------------------------------
    # 🔄 EXISTING FEATURE: ACTIVE TRANSFER & NEW PLAYER METRICS
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
    # 📢 DISCORD PAYLOAD GENERATION & CHUNKING
    # ------------------------------------------------------------------
    if not DISCORD_WEBHOOK_URL: return
    messages = []
    
    # 🟥 Alert Section: Elite Free Agents (Left Top 250 -> Missing from Top 500)
    if top250_leavers:
        messages.append("⚠️ **Top 250 Elite Leavers / Free Agents Spotted**")
        messages.append("*Left their club and dropped completely off the Top 500 radar:*")
        for leaver in sorted(top250_leavers, key=lambda x: x['rank']):
            messages.append(f"  • `ID: {leaver['id']}` | **{leaver['name']}** left **{leaver['old_club']}** (Rank {leaver['rank']})")
        messages.append("") # Spacer Line

    # 🆕 Alert Section: New Entries
    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered the tracking pool.")
        for club, count in sorted(new_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} new player(s)")
            
    # 🔄 Alert Section: Roster Swaps
    if shift_count > 0:
        messages.append(f"\n🔄 **{shift_count}** players moved between tracked clubs.")
        for club, count in sorted(shift_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} transferred player(s)")
            
    # Delivery Engine: Protects against Discord's 2000 character limits
    if messages:
        full_message = "\n".join(messages)
        if len(full_message) > 1900:
            # Safe chunk fallback loops every 20 lines to prevent payload cutting
            chunks = [messages[i:i + 20] for i in range(0, len(messages), 20)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(chunk)})
        else:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": full_message})

if __name__ == "__main__":
    process_post_scan_transfers()
