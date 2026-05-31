import os
import sys
import time
import random
import logging
import datetime
from curl_cffi import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL") 
BASE_API = "https://uma.moe/api/v4/circles"

session = requests.Session()

def safe_get(url):
    time.sleep(random.uniform(3.0, 6.0)) 
    print(f"📡 [TRACER] Initiating API GET request to: {url}", flush=True)
    try:
        res = session.get(url.rstrip('/'), impersonate="chrome120", timeout=30)
        print(f"✅ [TRACER] API Response Received: {res.status_code}", flush=True)
        
        if res.status_code == 200:
            if "application/json" not in res.headers.get("Content-Type", ""):
                print(f"🔴 [TRACER] CLOUDFLARE BLOCK DETECTED: Received HTML instead of JSON.", flush=True)
                raise RuntimeError("Cloudflare Challenge Blocked the Request.")
                
            return res.json()
        
        log.error(f"🔴 API CONNECTION FAILED: Status {res.status_code} on URL: {url}")
        raise RuntimeError(f"Bad API status code: {res.status_code}")
        
    except Exception as e:
        log.error(f"🔴 CRITICAL NETWORK ERROR: {e}")
        raise e

def get_latest_active_day(daily_fans):
    if not daily_fans or len(daily_fans) < 2:
        return 0
        
    for i in range(len(daily_fans) - 1, 0, -1):
        if daily_fans[i] > daily_fans[i - 1]:
            return i + 1 
            
    if daily_fans[0] > 0:
        return 1
        
    return 0

def process_club_sub_batch(batch_start, batch_end, curr_year, curr_month, run_id):
    api_page = batch_start // 100
    api_start = batch_start % 100
    api_end = batch_end % 100
    if api_end == 0 and batch_end > batch_start:
        api_end = 100
        
    url = f"{BASE_API}/list?page={api_page}&limit=100&sort_by=rank&sort_dir=asc"
    data = safe_get(url)
    
    if not data or "circles" not in data: 
        raise RuntimeError("API payload missing circles context.")

    target_clubs = data["circles"][api_start:api_end]
    
    print("🗄️ [TRACER] Attempting to connect to MongoDB...", flush=True)
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=15000, socketTimeoutMS=15000)
    db = client["uma_tracker"]["members"]
    club_rank_collection = client["uma_tracker"]["clubs"]
    print("🗄️ [TRACER] MongoDB connection initialized.", flush=True)
    
    discord_stream_chunk = [] 

    for index, club in enumerate(target_clubs):
        absolute_club_rank = batch_start + index 
        cid, club
