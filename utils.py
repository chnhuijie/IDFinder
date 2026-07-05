import time
from curl_cffi import requests

def safe_get(url, api_key=None):
    """Centralized API fetcher mimicking a Chrome browser to bypass Cloudflare."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://uma.moe/",
        "Origin": "https://uma.moe",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    if api_key:
        headers["X-API-Key"] = api_key
        
    try:
        response = requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            return "RATE_LIMIT"
        elif response.status_code == 404:
            return "NOT_FOUND"
            
    except Exception as e:
        print(f"[API Error] Request failed for {url}: {e}")
        
    return None
