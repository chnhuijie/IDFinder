import requests

def check_player_integrity(viewer_id, api_key=None):
    """
    Queries the uma.moe Shame API. 
    Returns (True, "Reason") if botter, (False, None) if clean.
    """
    shame_url = f"https://uma.moe/api/v4/shame/viewer/{viewer_id}?days=60"
    headers = {
        "Accept": "application/json",
        "User-Agent": "IDFinder-Integrity-Check"
    }
    if api_key:
        headers["X-API-Key"] = api_key
        
    try:
        res = requests.get(shame_url, headers=headers, timeout=10)
        if res.status_code != 200:
            return False, None
            
        data = res.json()
        score_data = data.get("score")
        
        if not score_data:
            return False, None
            
        # Null-safe score fallback
        sus_score = score_data.get("suspicion_score") or 0
        
        if sus_score >= 15:
            return True, f"High Suspicion Score ({sus_score})"
            
        evidence = score_data.get("evidence", {})
        reasons = evidence.get("reasons", [])
        
        bad_flags = [
            "automation-like pattern", 
            "very short high-fan", 
            "very short trainings"
        ]
        
        for r in reasons:
            label = r.get("label", "").lower()
            msg = r.get("message", "").lower()
            
            if any(flag in label or flag in msg for flag in bad_flags):
                return True, f"Auto-Flag: {r.get('label')}"
                
        return False, None
        
    except Exception as e:
        print(f"Integrity check failed for {viewer_id}: {e}")
        return False, None
