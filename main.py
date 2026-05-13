name: Uma Tracker Layer 1 Fix

on:
  schedule:
    - cron: '10 15 * * *' # 11:10 PM PHT
  workflow_dispatch:

jobs:
  track:
    runs-on: ubuntu-latest  # Fix: changed from 'runs-with'
    strategy:
      matrix:
        # Reduced initial range to verify the fix works
        range: ["0 300", "300 600", "600 900", "900 1200", "1200 1500"]
      max-parallel: 1  # Sequential to avoid triggering firewalls
    
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Cloudflare WARP
        uses: fscarmen/warp-on-actions@v1.4
        with:
          stack: dual # Provides both IPv4 and IPv6

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: pip install requests pymongo dnspython

      - name: Verify IP Change
        run: curl -s https://api.ipify.org # This should show a Cloudflare IP, not Azure
        
      - name: Run Tracking Batch
        run: python main.py ${{ matrix.range }}
        env:
          MONGO_URI: ${{ secrets.MONGO_URI }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
