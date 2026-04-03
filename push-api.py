#!/usr/bin/env python3
"""Push files to GitHub repo via requests library."""
import requests, json, base64, os
from datetime import datetime, timezone, timedelta

TOKEN = "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"
OWNER = "kof30190"
REPO = "veille"
VEILLE_DIR = "/root/veille"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
base = f"https://api.github.com/repos/{OWNER}/{REPO}"

def api_get(url):
    r = requests.get(f"{base}/{url}", headers=headers)
    return r

def api_put(url, data=None):
    r = requests.put(f"{base}/{url}", headers=headers, json=data)
    return r

# Step 1: Get the current ref
print("Getting current ref...")
r = api_get("git/ref/heads/main")
print(f"  Status: {r.status_code}")
if r.status_code != 200:
    print(r.text[:500])
    raise Exception(f"Failed to get ref: {r.status_code}")

commit_sha = r.json()["object"]["sha"]
print(f"  Current commit: {commit_sha[:8]}")

# Step 2: Get the commit to find tree
r = api_get(f"git/commits/{commit_sha}")
tree_sha = r.json()["tree"]["sha"]
print(f"  Current tree: {tree_sha[:8]}")

# Step 3: Upload files via content API (simpler than git blobs API)
files = [
    "index.html",
    "veille.py", 
    "cron-veille.py",
    "veille-data.json",
]

for filename in files:
    filepath = os.path.join(VEILLE_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            content = f.read()
        
        # Use the contents API to commit directly
        b64 = base64.b64encode(content).decode()
        
        r = api_get(f"contents/{filename}")
        old_sha = r.json().get("sha") if r.status_code == 200 else None
        
        data = {
            "message": f"Update {filename}",
            "content": b64,
            "branch": "main",
        }
        if old_sha:
            data["sha"] = old_sha
        
        url = f"contents/{filename}"
        r = api_put(url, data=data)
        status = "OK" if r.status_code in [200, 201] else f"ERR {r.status_code}"
        print(f"  {filename}: {status}")
        if r.status_code not in [200, 201]:
            print(f"    Response: {r.text[:200]}")

print("✅ Push complet!")
