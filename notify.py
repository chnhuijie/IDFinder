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
    
    # ⏱️ 2-Hour Window Fix: 2 hours = 7200 seconds.
    # Anyone who hasn't been scanned in 2 hours is verified as a true leaver.
    cutoff_time = time.time() - 7200
    
    exited_players = list(db.find({"last_seen": {"$lt": cutoff_time}}))
    
    if exited_players:
        id_list = []
        ids_to_delete = []
        
        for p in exited_players:
            mid = p.get('mid')
            if mid:
                id_list.append(str(mid))
            ids_to_delete.append(p["_id"])
        
        # Format the IDs into a clean, vertical newline list
        formatted_ids = "\n".join(id_list)
        
        # Construct payload with just the raw code block data you requested
        payload = {
            "username": "Leaderboard Tracker Bot",
            "content": f"**❌ LEAVER IDs DETECTED (Dropped out of Top 200):**\n```text\n{formatted_ids}\n```"
        }
        
        try:
            res = discord_req.post(DISCORD_WEBHOOK_URL, json=payload)
            if res.status_code == 204:
                print("✅ Leaver IDs successfully sent to Discord!")
            else:
                print(f"⚠️ Discord returned an error status: {res.status_code}")
        except Exception as e:
            print(f"Failed to send exit alert: {e}")

        # Clean old leavers out of your database collection automatically
        if ids_to_delete:
            db.delete_many({"_id": {"$in": ids_to_delete}})
            print(f"Cleanup complete. Removed {len(ids_to_delete)} old leaver records from cloud database.")
    else:
        print("✅ No exits detected in this safety cycle.")

if __name__ == "__main__":
    check_exits()
