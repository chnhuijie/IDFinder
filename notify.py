import os, time, requests as discord_req
from pymongo import MongoClient

def check_exits():
    MONGO_URI = os.getenv("MONGO_URI")
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL not found in environment.")
        return

    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    club_db = client["uma_tracker"]["clubs"]
    
    # 2-Hour Time Window
    cutoff_time = time.time() - 7200
    
    # Evaluate global leaderboard exits by verifying club listings
    active_clubs = list(club_db.find({}))
    active_club_names = {c["name"] for c in active_clubs}
    
    # 1. Process Individual Missing Flags
    exited_players = list(db.find({"last_seen": {"$lt": cutoff_time}}))
    
    if exited_players:
        top_100_leavers = []
        top_200_leavers = []
        ids_to_purge = []
        
        for p in exited_players:
            mid = p.get('mid')
            tier = p.get('club_tier', 'Top 100')
            old_club = p.get('club', 'Unknown')
            
            # Evaluate if the club dropped out of the Top 200 completely
            if old_club not in active_club_names:
                if tier == "Top 100":
                    top_100_leavers.append(str(mid))
                else:
                    top_200_leavers.append(str(mid))
            ids_to_purge.append(p["_id"])

        # Send structured alerts depending on tier origin
        if top_100_leavers:
            msg = "**❌ LEAVER IDs DETECTED (Dropped out of Top 100):**\n```text\n" + "\n".join(top_100_leavers) + "\n```"
            discord_req.post(DISCORD_WEBHOOK_URL, json={"content": msg})
            
        if top_200_leavers:
            msg = "**❌ LEAVER IDs DETECTED (Dropped out of Top 200):**\n```text\n" + "\n".join(top_200_leavers) + "\n```"
            discord_req.post(DISCORD_WEBHOOK_URL, json={"content": msg})

        if ids_to_purge:
            db.delete_many({"_id": {"$in": ids_to_purge}})

    # 2. Process Your "25 or More" Roster Threshold Rule
    for club in active_clubs:
        c_name = club.get("name")
        c_rank = club.get("last_known_rank", 999)
        
        # Count current verified members checked in during tonight's loop
        active_member_count = db.count_documents({"club": c_name, "last_seen": {"$gte": cutoff_time}})
        
        # If roster drops below your critical limit
        if active_member_count > 0 and active_member_count < 25:
            tier_label = "Top 100" if c_rank < 100 else "Top 200"
            alert_payload = {
                "content": f"⚠️ **Critical Threshold Alert:** Club **{c_name}** ({tier_label}, Rank {c_rank + 1}) has dropped below your threshold with only **{active_member_count}** active tracked members!"
            }
            try:
                discord_req.post(DISCORD_WEBHOOK_URL, json=alert_payload)
            except Exception as e:
                print(f"Failed to post threshold warning: {e}")

if __name__ == "__main__":
    check_exits()
