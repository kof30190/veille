#!/usr/bin/env python3
import os, json, base64, urllib.request, sys

TOKEN = "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"
OWNER = "kof30190"
REPO = "veille"
VEILLE_DIR = "/root/veille"

headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Hermes-Agent",
    "Content-Type": "application/json"
}

# 1. Get current SHA
ref_url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/ref/heads/main"
req = urllib.request.Request(ref_url, headers=headers)
ref_data = json.loads(urllib.request.urlopen(req).read().decode())
commit_sha = ref_data["object"]["sha"]

# 2. Get tree
commit_url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/commits/{commit_sha}"
req = urllib.request.Request(commit_url, headers=headers)
commit_data = json.loads(urllib.request.urlopen(req).read().decode())
tree_sha = commit_data["tree"]["sha"]

# 3. Upload files
blob_url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/blobs"
files_to_upload = [
    ("index.html", os.path.join(VEILLE_DIR, "index.html")),
    ("veille.py", os.path.join(VEILLE_DIR, "veille.py")),
    ("cron-veille.py", os.path.join(VEILLE_DIR, "cron-veille.py")),
    ("veille-data.json", os.path.join(VEILLE_DIR, "veille-data.json")),
    ("history/snapshot_history.json", os.path.join(VEILLE_DIR, "history", "snapshot_history.json")),
]

blobs = []
for path, local_path in files_to_upload:
    if os.path.exists(local_path):
        with open(local_path, 'rb') as f:
            content = base64.b64encode(f.read()).decode()
        data = json.dumps({"content": content, "encoding": "base64"}).encode()
        req = urllib.request.Request(blob_url, data=data, headers=headers)
        resp = json.loads(urllib.request.urlopen(req).read().decode())
        blobs.append((path, resp["sha"]))
        print(f"  ✅ {path}")

# 4. Create new tree
tree_data = json.dumps({
    "base_tree": tree_sha,
    "tree": [{"path": p, "mode": "100644", "type": "blob", "sha": s} for p, s in blobs]
}).encode()
req = urllib.request.Request(f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees", data=tree_data, headers=headers)
new_tree_sha = json.loads(urllib.request.urlopen(req).read().decode())["sha"]

# 5. Create commit
from datetime import datetime, timezone, timedelta
now = datetime.now(timezone(timedelta(hours=1))).isoformat()
commit_data = json.dumps({
    "message": "Update V2 - veille avancée avec diff, social, legal, alerts",
    "tree": new_tree_sha,
    "parents": [commit_sha],
    "author": {"name": "Hermes Agent", "email": "hermes@local", "date": now},
}).encode()
req = urllib.request.Request(f"https://api.github.com/repos/{OWNER}/{REPO}/git/commits", data=commit_data, headers=headers)
new_commit = json.loads(urllib.request.urlopen(req).read().decode())["sha"]

# 6. Update ref
ref_data = json.dumps({"sha": new_commit, "force": False}).encode()
req = urllib.request.Request(ref_url, data=ref_data, headers=headers)
urllib.request.urlopen(req)

print("✅ Push réussi !")
