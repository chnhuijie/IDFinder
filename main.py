import sys
import time
import random
import requests

def fetch_club_data(start_idx, end_idx):
    # Setup headers to look like a real browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    
    print(f">>> Worker started. Processing clubs {start_idx} to {end_idx}...")

    # Mock list of IDs - Replace this with your actual ID fetching logic
    # all_ids = get_all_circle_ids() 
    # club_ids = all_ids[start_idx:end_idx]

    for i in range(start_idx, end_idx):
        # 1. ADD RANDOM JITTER (1 to 3 seconds)
        # This prevents the "firewall" from seeing a perfect rhythmic bot pattern
        time.sleep(1 + random.random() * 2)

        try:
            # Replace URL with your actual target API
            url = f"https://api.example.com/clubs/{i}" 
            response = requests.get(url, headers=headers, timeout=10)

            # 2. SMART RATE LIMIT HANDLING
            if response.status_code == 429:
                wait_time = int(response.headers.get("Retry-After", 60))
                print(f"!!! Throttled at ID {i}. Waiting {wait_time}s...")
                time.sleep(wait_time)
                # Simple retry logic: decrement i to try this ID again after sleep
                # (Be careful with infinite loops here)
                continue 

            if response.status_code == 200:
                print(f"Successfully fetched ID {i}")
                # Process your data here...
            
        except Exception as e:
            print(f"Error fetching ID {i}: {e}")

if __name__ == "__main__":
    # Get arguments from GitHub Matrix
    if len(sys.argv) < 3:
        print("Usage: python main.py <start_index> <end_index>")
        sys.exit(1)

    start = int(sys.argv[1])
    end = int(sys.argv[2])

    fetch_club_data(start, end)
