import time
from curl_cffi import requests

BASE_API = "https://uma.moe/api/v4"

def safe_get(url, api_key=None):
    """Centralized API fetcher mimicking the successful Discord Bot connection profile."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://uma.moe/",
        "Origin": "https://uma.moe",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        # Utilizing curl_cffi to cleanly bypass browser fingerprinting checks
        response = requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            print(f"[Rate Limited] 429 received for {url}. Backing off...")
            return "RATE_LIMIT"
        elif response.status_code == 404:
            return "NOT_FOUND"
    except Exception as e:
        print(f"[API Error] Request failed for {url}: {e}")
    return None

def check_player_integrity(viewer_id, api_key=None, retries=3):
    """Queries the Hall of Shame API matching the bot's structural parameters."""
    shame_url = f"{BASE_API}/shame/viewer/{viewer_id}?days=60"
    
    for attempt in range(retries):
        data = safe_get(shame_url, api_key)
        
        if data == "RATE_LIMIT":
            time.sleep(2)
            continue
            
        if data == "NOT_FOUND" or not data or not data.get("score"):
            return False, None
            
        score_data = data.get("score")
        sus_score = score_data.get("suspicion_score") or 0
        
        # Tightened suspicion matrix fallback matching active enforcement needs
        if sus_score >= 15:
            return True, f"High Suspicion Matrix ({sus_score})"
            
        evidence = score_data.get("evidence", {})
        reasons = evidence.get("reasons", [])
        bad_flags = ["automation-like pattern", "very short high-fan", "very short trainings"]
        
        for r in reasons:
            label = r.get("label", "").lower()
            msg = r.get("message", "").lower()
            if any(flag in label or flag in msg for flag in bad_flags):
                return True, f"Auto-Flag: {r.get('label')}"
                
        return False, None

    return False, None
