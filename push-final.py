#!/usr/bin/env python3
"""Test new token and push files."""
import requests, json, base64, os
from datetime import datetime, timezone, timedelta

# Read token from credentials file
TOKEN = None
with open('/root/.hermes/credentials.env') as f:
    for line in f:
        if line.strip().startswith('GITHUB_TOKEN='):
            TOKEN = line.strip().split('=', 1)[1]
            break

print(f"Token loaded: {TOKEN[:10]}...")

OWNER = "kof30190"
REPO = "veille"
VEILLE_DIR = "/root/veille"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
base = f"https://api.github.com/repos/{OWNER}/{REPO}"

# Step 1: Test token
r = requests.get(f"{base}/git/ref/heads/main", headers=headers)
print(f"Token test: {r.status_code}")
if r.status_code == 200:
    print("✅ Token valide!")
else:
    print(f"❌ Erreur: {r.text[:200]}")
    exit(1)

# Step 2: Upload index.html via contents API
print("\nPushing index.html...")
with open(os.path.join(VEILLE_DIR, "index.html"), 'rb') as f:
    content = f.read()
b64 = base64.b64encode(content).decode()

r = requests.get(f"{base}/contents/index.html", headers=headers)
old_sha = r.json().get("sha") if r.status_code == 200 else None

data = {"message": "Update V2 - rapport veille", "content": b64, "branch": "main"}
if old_sha:
    data["sha"] = old_sha

r = requests.put(f"{base}/contents/index.html", headers=headers, json=data)
print(f"  index.html: {r.status_code}")
if r.status_code not in [200, 201]:
    print(f"    Response: {r.text[:300]}")

# Step 3: Upload veille.py
print("\nPushing veille.py...")
with open(os.path.join(VEILLE_DIR, "veille.py"), 'rb') as f:
    content = f.read()
b64 = base64.b64encode(content).decode()

r = requests.get(f"{base}/contents/veille.py", headers=headers)
old_sha = r.json().get("sha") if r.status_code == 200 else None

data = {"message": "Update V2 - veille avancée", "content": b64, "branch": "main"}
if old_sha:
    data["sha"] = old_sha

r = requests.put(f"{base}/contents/veille.py", headers=headers, json=data)
print(f"  veille.py: {r.status_code}")

# Step 4: Upload cron-veille.py
print("\nPushing cron-veille.py...")
with open(os.path.join(VEILLE_DIR, "cron-veille.py"), 'rb') as f:
    content = f.read()
b64 = base64.b64encode(content).decode()

r = requests.get(f"{base}/contents/cron-veille.py", headers=headers)
old_sha = r.json().get("sha") if r.status_code == 200 else None

data = {"message": "Update cron V2", "content": b64, "branch": "main"}
if old_sha:
    data["sha"] = old_sha

r = requests.put(f"{base}/contents/cron-veille.py", headers=headers, json=data)
print(f"  cron-veille.py: {r.status_code}")

# Step 5: Upload veille-data.json
print("\nPushing veille-data.json...")
with open(os.path.join(VEILLE_DIR, "veille-data.json"), 'rb') as f:
    content = f.read()
b64 = base64.b64encode(content).decode()

r = requests.get(f"{base}/contents/veille-data.json", headers=headers)
old_sha = r.json().get("sha") if r.status_code == 200 else None

data = {"message": "Update data V2 - social/legal", "content": b64, "branch": "main"}
if old_sha:
    data["sha"] = old_sha

r = requests.put(f"{base}/contents/veille-data.json", headers=headers, json=data)
print(f"  veille-data.json: {r.status_code}")

# Step 6: Upload history
hist_file = os.path.join(VEILLE_DIR, "history", "snapshot_history.json")
if os.path.exists(hist_file):
    print("\nPushing history...")
    with open(hist_file, 'rb') as f:
        content = f.read()
    b64 = base64.b64encode(content).decode()
    
    r = requests.get(f"{base}/contents/history/snapshot_history.json", headers=headers)
    old_sha = r.json().get("sha") if r.status_code == 200 else None
    
    data = {"message": "Update history", "content": b64, "branch": "main"}
    if old_sha:
        data["sha"] = old_sha
    
    r = requests.put(f"{base}/contents/history/snapshot_history.json", headers=headers, json=data)
    print(f"  snapshot_history.json: {r.status_code}")

print("\n✅ Tous les fichiers poussés!")
