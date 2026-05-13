import os, time, requests as discord_req
from pymongo import MongoClient

def check_exits():
    # Environment Variables - Updated to DISCORD_WEBHOOK_URL
    MONGO_URI = os.getenv("MONGO_URI")
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL not found in environment.")
        return

    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    cutoff_time = time.time() - 3600
    exited_players = list(db.find({"last_seen": {"$lt": cutoff_time}}))
    
    if exited_players:
        exit_msgs = []
        ids_to_delete = []
        
        for p in exited_players:
            name = p.get('name', 'Unknown')
            mid = p.get('mid')
            old_club = p.get('club', 'Top 100')
            
            exit_msgs.append(f"❌ **{name}** (`{mid}`) has left **{old_club}**")
            ids_to_delete.append(p["_id"])
        
        for i in range(0, len(exit_msgs), 20):
            chunk = exit_msgs[i : i + 20]
            header = "🚫 **Scout Alert: Players no longer in Top 100**"
            payload = {"content": f"{header}\n" + "\n".join(chunk)}
            
            try:
                discord_req.post(DISCORD_WEBHOOK_URL, json=payload)
                time.sleep(1.5) 
            except Exception as e:
                print(f"Failed to send exit alert: {e}")

        if ids_to_delete:
            db.delete_many({"_id": {"$in": ids_to_delete}})
            print(f"Cleanup complete. Removed {len(ids_to_delete)} players.")
    else:
        print("No exits detected in this cycle.")

if __name__ == "__main__":
    check_exits()
