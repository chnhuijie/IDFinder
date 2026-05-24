import os
import time
import requests
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def process_post_scan_transfers():
    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    clubs_col = client["uma_tracker"]["clubs"]
    
    # Core performance enforcement index
    db.create_index([("last_seen", 1)])
    
    cutoff_time = time.time() - 14400
    
    # ------------------------------------------------------------------
    # 1. 🕵️‍♂️ PROCESS TRUE ELITE GRID LEAVERS
    # ------------------------------------------------------------------
    missing_players = list(db.find({"last_seen": {"$lte": cutoff_time}, "club_id": {"$ne": None}}))
    top250_leavers = []
    
    for player in missing_players:
        club_data = clubs_col.find_one({"circle_id": player.get("club_id")})
        if club_data and club_data.get("last_known_rank", 999) < 250:
            top250_leavers.append({
                "id": player.get("mid"),
                "name": player.get("name", "Unknown"),
                "old_club": player.get("club"),
                "rank": club_data.get("last_known_rank", 0) + 1
            })
            # Remove club association since they are free agents off the tracking grid
            db.update_one(
                {"_id": player["_id"]}, 
                {"$set": {"club": None, "club_id": None, "previous_club": None, "club_tier": "Unranked"}}
            )

    # ------------------------------------------------------------------
    # 2. 📊 GATHER FLAGS & COUNT PER CLUB IN RAM
    # ------------------------------------------------------------------
    new_players = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_new_flag": True}))
    transfers = list(db.find({"last_seen": {"$gt": cutoff_time}, "is_transfer_flag": True}))

    # Dictionaries to hold our breakdowns
    new_clubs_dict = {}
    shift_clubs_dict = {}

    for p in new_players:
        club_name = p.get("club", "Unknown Club")
        new_clubs_dict[club_name] = new_clubs_dict.get(club_name, 0) + 1

    for p in transfers:
        club_name = p.get("club", "Unknown Club")
        shift_clubs_dict[club_name] = shift_clubs_dict.get(club_name, 0) + 1

    if not DISCORD_WEBHOOK_URL: 
        client.close()
        return
        
    messages = []

    # ------------------------------------------------------------------
    # 3. 📢 FORMAT BUNDLES (Matches your clean image layout)
    # ------------------------------------------------------------------
    
    # Section A: Elite Leavers
    if top250_leavers:
        messages.append("⚠️ **Top 250 Elite Leavers / Free Agents Spotted**")
        messages.append("*Left their club and dropped completely off the leaderboard grid:*")
        for leaver in sorted(top250_leavers, key=lambda x: x['rank']):
            messages.append(f"  • `ID: {leaver['id']}` | **{leaver['name']}** left **{leaver['old_club']}** (Rank {leaver['rank']})")
        messages.append("")

    # Section B: New Players Breakdown
    if new_players:
        messages.append(f"🆕 **{len(new_players)}** new players entered the tracking pool.")
        # Sort clubs by most new players, showing top 15 to stay within Discord limits
        sorted_new_clubs = sorted(new_clubs_dict.items(), key=lambda x: x[1], reverse=True)
        for club, count in sorted_new_clubs[:15]:
            messages.append(f"  • **{club}**: +{count} new player(s)")
        messages.append("")

    # Section C: Active Transfers Breakdown
    if transfers:
        messages.append(f"🔄 **{len(transfers)}** players moved between tracked clubs.")
        # Sort clubs by most incoming transfers, showing top 15
        sorted_shift_clubs = sorted(shift_clubs_dict.items(), key=lambda x: x[1], reverse=True)
        for club, count in sorted_shift_clubs[:15]:
            messages.append(f"  • **{club}**: +{count} transferred player(s)")

    # ------------------------------------------------------------------
    # 4. 🔥 DELIVER & RESET ENVIRONMENT
    # ------------------------------------------------------------------
    if messages:
        # Use simple chunking to avoid Discord's 2000 character hard block
        full_message = "\n".join(messages)
        if len(full_message) > 1900:
            chunks = [messages[i:i + 20] for i in range(0, len(messages), 20)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": "\n".join(chunk)})
        else:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": full_message})
            
        print("📢 Detailed Discord notification successfully delivered!")

        print("🧼 Wiping temporary operational flags and snapshots for tomorrow's run...")
        db.update_many(
            {"last_seen": {"$gt": cutoff_time}}, 
            {"$set": {
                "is_new_flag": False, 
                "is_transfer_flag": False,
                "historical_club_snapshot": None
            }}
        )
    else:
        print("💤 No roster movements detected tonight. Operational flags intact.")

    client.close()

if __name__ == "__main__":
    process_post_scan_transfers()
