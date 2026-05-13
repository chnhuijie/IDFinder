import os, time, requests
from pymongo import MongoClient

def check_exits():
    client = MongoClient(os.getenv("MONGO_URI"))
    db = client["uma_tracker"]["members"]
    webhook = os.getenv("DISCORD_WEBHOOK")
    
    # 1. Find anyone who wasn't updated in the last 1 hour
    # This means they are no longer in ANY of the top 100 clubs
    one_hour_ago = time.time() - 3600
    leaver_cursor = db.find({"last_seen": {"$lt": one_hour_ago}})
    
    exit_list = []
    to_delete = []
    
    for p in leaver_cursor:
        exit_list.append(f"❌ {p['name']} (`{p['mid']}`) left **{p['club']}**")
        to_delete.append(p["_id"])

    # 2. Report the IDs to Discord
    if exit_list:
        for i in range(0, len(exit_list), 20):
            chunk = exit_list[i:i+20]
            header = "🚫 **Exit Alert: IDs no longer in Top 100**"
            requests.post(webhook, json={"content": f"{header}\n" + "\n".join(chunk)})

    # 3. Clean up the database so they don't get reported twice
    if to_delete:
        db.delete_many({"_id": {"$in": to_delete}})

if __name__ == "__main__":
    check_exits()
