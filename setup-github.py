#!/usr/bin/env python3
"""Create GitHub repo, initialize and push veille project."""
import subprocess, os, json, urllib.request, sys

TOKEN = "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"
OWNER = "kof30190"
REPO_NAME = "veille"

headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "Hermes-Agent"
}

# 1. Create private repo
url = "https://api.github.com/user/repos"
data = json.dumps({"name": REPO_NAME, "private": True, "description": "Veille technologique - Menuiseries & artisans Brignon/Uzès"}).encode()
req = urllib.request.Request(url, data=data, headers=headers, method="POST")

try:
    resp = urllib.request.urlopen(req)
    repo = json.loads(resp.read().decode())
    print(f"✅ Repo créé: {repo['html_url']}")
    clone_url = repo['clone_url']
except urllib.error.HTTPError as e:
    body = json.loads(e.read().decode())
    if "already exists" in json.dumps(body).lower():
        print(f"✅ Repo existe déjà")
        clone_url = f"https://github.com/{OWNER}/{REPO_NAME}.git"
    else:
        print(f"❌ Erreur: {e.code} - {body}")
        sys.exit(1)

# 2. Initialize git and push
os.chdir("/root/veille")
subprocess.run(["git", "init"], capture_output=True, check=True)
subprocess.run(["git", "add", "."], capture_output=True, check=True)
subprocess.run(["git", "commit", "-m", "Initial commit - veille project"], 
    capture_output=True, check=True,
    env={**os.environ, "GIT_AUTHOR_NAME": "Hermes Agent", "GIT_AUTHOR_EMAIL": "hermes@local",
         "GIT_COMMITTER_NAME": "Hermes Agent", "GIT_COMMITTER_EMAIL": "hermes@local"})
subprocess.run(["git", "branch", "-M", "main"], capture_output=True, check=True)
subprocess.run(["git", "remote", "add", "origin", clone_url], capture_output=True)

# 3. Push with token in auth
subprocess.run(["git", "config", "http.extraHeader", f"Authorization: token {TOKEN}"], 
    capture_output=True, check=True)

push_result = subprocess.run(
    ["git", "push", "-u", "--force", "origin", "main"],
    capture_output=True, text=True
)
if push_result.returncode == 0:
    print(f"✅ Push réussi!")
else:
    print(f"Push output: {push_result.stdout}")
    print(f"Push error: {push_result.stderr}")

# 4. Enable GitHub Pages
pages_url = f"https://api.github.com/repos/{OWNER}/{REPO_NAME}/pages"
pages_data = json.dumps({
    "build_type": "branch",
    "source": {"branch": "main", "path": "/"}
}).encode()
pages_req = urllib.request.Request(pages_url, data=pages_data, headers=headers, method="POST")

try:
    pages_resp = urllib.request.urlopen(pages_req)
    pages = json.loads(pages_resp.read().decode())
    print(f"✅ GitHub Pages activé: {pages.get('html_url', 'N/A')}")
except urllib.error.HTTPError as e:
    body = json.loads(e.read().decode())
    print(f"⚠️ Pages: {e.code} - {body.get('message', 'unknown')}")

print(f"\n📍 Repo: https://github.com/{OWNER}/{REPO_NAME}")
print(f"📍 Pages: https://{OWNER}.github.io/{REPO_NAME}/")
