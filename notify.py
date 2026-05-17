import os, time, requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    # 1. Grab all active members updated in the last 2 hours
    cutoff_time = time.time() - 7200
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

    # 2. Format and send a single consolidated alert to Discord
    if not DISCORD_WEBHOOK_URL: return
    messages = []
    
    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered the tracking pool.")
        for club, count in sorted(new_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} new player(s)")
            
    if shift_count > 0:
        messages.append(f"\n🔄 **{shift_count}** players moved between tracked clubs.")
        for club, count in sorted(shift_clubs_dict.items(), key=lambda x: x[1], reverse=True):
            messages.append(f"  • **{club}**: +{count} transferred player(s)")
            
    if messages:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(messages)})

if __name__ == "__main__":
    # Your existing leaver code here...
    # ...
    # Run the perfect transfer logic right at the end:
    process_post_scan_transfers()
