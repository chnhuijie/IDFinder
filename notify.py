import os, time, logging, requests as discord_req
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def check_exits():
    MONGO_URI = os.getenv("MONGO_URI")
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    
    if not DISCORD_WEBHOOK_URL:
        log.error("Error: DISCORD_WEBHOOK_URL not found in environment.")
        return

    client = MongoClient(MONGO_URI)
    db = client["uma_tracker"]["members"]
    
    # 1. Capture any player who was completely missed by all 10 matrix chunks today
    # 5400 seconds (1.5 hours) cleanly covers the linear matrix execution window
    cutoff_time = time.time() - 5400 
    exited_players = list(db.find({"last_seen": {"$lt": cutoff_time}}))
    
    if exited_players:
        top_100_exits = []
        ids_to_delete = []
        
        for p in exited_players:
            name = p.get('name', 'Unknown')
            mid = p.get('mid')
            old_club = p.get('club', 'Unknown Club')
            last_rank = p.get('last_rank', 200) 
            ids_to_delete.append(p["_id"])
            
            # CRITICAL FILTER: Only alert if their last tracked location was a Top 100 club
            if last_rank <= 100:
                top_100_exits.append(f"❌ **{name}** (`{mid}`) has vanished from **{old_club}** (Last Rank: #{last_rank})")
        
        # 2. Forward alerts to your Discord Webhook
        if top_100_exits:
            for i in range(0, len(top_100_exits), 20):
                chunk = top_100_exits[i : i + 20]
                header = "🚨 **CRITICAL EXITS: Players dropped from Top 100 out of Top 200 completely** 🚨"
                payload = {"content": f"{header}\n" + "\n".join(chunk)}
                try:
                    discord_req.post(DISCORD_WEBHOOK_URL, json=payload)
                    time.sleep(1.5)
                except Exception as e:
                    log.error(f"Failed to send exit alert batch: {e}")

        # 3. Securely remove the files from the tracking collection so they don't alert again tomorrow
        if ids_to_delete:
            db.delete_many({"_id": {"$in": ids_to_delete}})
            log.info(f"Cleanup complete. Pruned {len(ids_to_delete)} total historical records.")
    else:
        log.info("No system exits detected in this workflow cycle.")

if __name__ == "__main__":
    check_exits()
