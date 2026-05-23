import os, time, requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    
    cutoff_time = time.time() - 14400
    
    dropped_clubs_cursor = clubs_col.find({"last_updated": {"$lte": cutoff_time}})
    dropped_clubs = []
    for c in dropped_clubs_cursor:
        dropped_clubs.append({
            "name": c.get("name"),
            "old_rank": c.get("last_known_rank", 999) + 1
        })
        clubs_col.delete_one({"_id": c["_id"]})

    active_clubs_tonight = clubs_col.distinct("name", {"last_updated": {"$gt": cutoff_time}})
    
    new_clubs = []
    for club_name in active_clubs_tonight:
        club_meta = clubs_col.find_one({"name": club_name})
        if club_meta and club_meta.get("last_updated") > cutoff_time:
            sample_player = db.find_one({"club": club_name, "club_tier": "Unranked"})
            if sample_player and club_name not in [c['name'] for c in new_clubs]:
                new_clubs.append({
                    "name": club_name,
                    "current_rank": club_meta.get("last_known_rank", 0) + 1
                })

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

    if not DISCORD_WEBHOOK_URL: return
    messages = []
    
    if dropped_clubs or new_clubs:
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

    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered the tracking pool.")
        for club, count in sorted(new_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} new player(s)")
            
    if shift_count > 0:
        messages.append(f"\n🔄 **{shift_count}** players moved between tracked clubs.")
        for club, count in sorted(shift_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} transferred player(s)")
            
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
