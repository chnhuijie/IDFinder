import os, sys, time, random, logging, datetime
import requests as discord_req
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

# ... [Keep your existing imports and session setup] ...

def send_discord_summary(exits, shift_count, new_count):
    if not DISCORD_WEBHOOK: return
    
    messages = []
    
    # 1. Newcomers (Count only)
    if new_count > 0:
        messages.append(f"🆕 **{new_count}** new players entered the Top 100.")

    # 2. Shifts (Count only)
    if shift_count > 0:
        messages.append(f"🔄 **{shift_count}** players moved between Top 100 clubs.")

    # 3. Exits (IDs included)
    if exits:
        messages.append("🚫 **Players who exited the Top 100:**")
        # Send Exit IDs in chunks of 20
        for i in range(0, len(exits), 20):
            chunk = exits[i : i + 20]
            content = "\n".join(messages) + "\n" + "\n".join(chunk)
            discord_req.post(DISCORD_WEBHOOK, json={"content": content})
            messages = [] # Clear so we only send the header once
    elif messages:
        # If there are counts but no exits, just send the counts
        discord_req.post(DISCORD_WEBHOOK, json={"content": "\n".join(messages)})

def main(start, end):
    # ... [Keep initial setup/API fetch logic] ...
    
    shift_count = 0
    new_count = 0
    exits = [] # This is now handled in notify.py, but we track counts here

    for club in target:
        # ... [API fetch detail logic] ...
        if detail and "members" in detail:
            ops = []
            for m in (detail.get("members") or []):
                p_id = str(m.get("viewer_id") or m.get("id") or m.get("mid"))
                p_name = m.get("name") or m.get("nickname") or "Unknown"

                # Check previous state
                prev_record = db.find_one({"mid": p_id})
                
                if not prev_record:
                    new_count += 1
                elif prev_record.get("club") != club_name:
                    shift_count += 1
                
                ops.append(UpdateOne(
                    {"mid": p_id},
                    {"$set": {"name": p_name, "club": club_name, "last_seen": time.time()}},
                    upsert=True
                ))
            # ... [Bulk write logic] ...

    # Send the "Joiner/Shifter" summary
    send_discord_summary([], shift_count, new_count)
