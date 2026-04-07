#!/usr/bin/env python3
"""Cron job V2 — Run daily veille, push to GitHub, send Telegram link."""
import subprocess, os, json
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
    """Push updated files to GitHub using git CLI (more reliable than API)."""
    try:
        now = datetime.now(TZ).strftime("%d/%m/%Y")
        # Stage and commit changed files
        subprocess.run(["git", "add", "index.html", "history/snapshot_history.json"], cwd=VEILLE_DIR, check=True, capture_output=True)
        # Check if there are any changes
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=VEILLE_DIR, capture_output=True)
        if result.returncode != 0:
            # There are changes — commit and push
            subprocess.run(["git", "commit", "-m", f"Update report {now}"], cwd=VEILLE_DIR, check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=VEILLE_DIR, check=True, capture_output=True)
            print("  Push: ✅ OK (committed & pushed)")
        else:
            print("  Push: ✅ OK (no changes to push)")
        return True
    except Exception as e:
        print(f"  Push error: {e}")
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
