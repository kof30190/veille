#!/usr/bin/env python3
"""Cron job V2 — Run daily veille, push to GitHub, send Telegram link."""
import subprocess, os, json, base64, urllib.request
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=1))
OWNER = "kof30190"
REPO = "veille"
VEILLE_DIR = "/root/veille"

def get_token():
    try:
        with open('/root/.hermes/credentials.env') as f:
            for line in f:
                if line.strip().startswith('GITHUB_TOKEN='):
                    return line.strip().split('=', 1)[1]
    except:
        pass
    return "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"

def run_veille():
    result = subprocess.run(
        ["python3", os.path.join(VEILLE_DIR, "veille.py")],
        capture_output=True, text=True, cwd=VEILLE_DIR, timeout=600
    )
    return result.stdout, result.stderr, result.returncode

def push_to_github():
    token = get_token()
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Hermes-Agent",
        "Content-Type": "application/json"
    }
    
    try:
        # 1. Get current SHA
        ref_url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/ref/heads/main"
        req = urllib.request.Request(ref_url, headers=headers)
        resp = urllib.request.urlopen(req)
        ref_data = json.loads(resp.read().decode())
        commit_sha = ref_data["object"]["sha"]
        
        # 2. Get commit tree
        commit_url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/commits/{commit_sha}"
        req = urllib.request.Request(commit_url, headers=headers)
        resp = urllib.request.urlopen(req)
        commit_data = json.loads(resp.read().decode())
        tree_sha = commit_data["tree"]["sha"]
        
        # 3. Upload index.html
        with open(os.path.join(VEILLE_DIR, "index.html"), 'rb') as f:
            content = f.read()
        blob_url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/blobs"
        blob_data = json.dumps({"content": base64.b64encode(content).decode(), "encoding": "base64"}).encode()
        req = urllib.request.Request(blob_url, data=blob_data, headers=headers)
        resp = urllib.request.urlopen(req)
        blob_sha = json.loads(resp.read().decode())["sha"]
        
        # 4. Upload history
        hist_path = os.path.join(VEILLE_DIR, "history", "snapshot_history.json")
        if os.path.exists(hist_path):
            with open(hist_path, 'rb') as f:
                hist_content = f.read()
            hist_blob = json.dumps({"content": base64.b64encode(hist_content).decode(), "encoding": "base64"}).encode()
            req = urllib.request.Request(blob_url, data=hist_blob, headers=headers)
            resp = urllib.request.urlopen(req)
            hist_sha = json.loads(resp.read().decode())["sha"]
        else:
            hist_sha = blob_sha  # fallback
        
        # 5. Create new tree
        tree_data = json.dumps({
            "base_tree": tree_sha,
            "tree": [
                {"path": "index.html", "mode": "100644", "type": "blob", "sha": blob_sha},
                {"path": "history/snapshot_history.json", "mode": "100644", "type": "blob", "sha": hist_sha}
            ]
        }).encode()
        req = urllib.request.Request(f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees", data=tree_data, headers=headers)
        resp = urllib.request.urlopen(req)
        new_tree_sha = json.loads(resp.read().decode())["sha"]
        
        # 6. Create commit
        now = datetime.now(TZ).strftime("%d/%m/%Y")
        commit_data = json.dumps({
            "message": f"Update report {now}",
            "tree": new_tree_sha,
            "parents": [commit_sha],
            "author": {"name": "Hermes Agent", "email": "hermes@local", "date": datetime.now(TZ).isoformat()},
        }).encode()
        req = urllib.request.Request(f"https://api.github.com/repos/{OWNER}/{REPO}/git/commits", data=commit_data, headers=headers)
        resp = urllib.request.urlopen(req)
        new_commit = json.loads(resp.read().decode())["sha"]
        
        # 7. Update ref
        ref_data = json.dumps({"sha": new_commit, "force": False}).encode()
        req = urllib.request.Request(ref_url, data=ref_data, headers=headers)
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"  Push API error: {e}")
        return False

def build_telegram_msg(stdout):
    lines = stdout.strip().split('\n')
    msg_lines = []
    capture = False
    for line in lines:
        if '---TELEGRAM_MSG---' in line:
            capture = True
            continue
        if capture and '---REPORT_PATH---' in line:
            capture = False
            continue
        if capture:
            msg_lines.append(line)
    return '\n'.join(msg_lines)

def main():
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Démarrage cron veille V2")
    
    # Step 1: Run veille
    stdout, stderr, code = run_veille()
    print(stdout)
    if stderr:
        print(f"STDERR: {stderr}")
    
    # Step 2: Push to GitHub via API
    pushed = push_to_github()
    print(f"  Push: {'✅ OK' if pushed else '❌ Échoué'}")
    
    # Step 3: Build and print message
    msg = build_telegram_msg(stdout)
    msg += f"\n\n📊 Rapport visuel: https://raw.githack.com/{OWNER}/{REPO}/main/index.html"
    msg += f"\n\n⏰ Prochain scan demain à 13h00"
    
    print(f"\n---FINAL_RESPONSE---\n{msg}")

if __name__ == '__main__':
    main()
