#!/usr/bin/env python3
import json, urllib.request

# Token from user input in this session (not from file)
TOKEN = os.environ.get('GH_TOKEN') or "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"

print(f"Token starts with: {TOKEN[:15]}...")

url = "https://api.github.com/user"
headers = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json"}
req = urllib.request.Request(url, headers=headers)
try:
    resp = json.loads(urllib.request.urlopen(req).read().decode())
    print(f"✅ Token valid! User: {resp['login']}")
except Exception as e:
    print(f"❌ Token error: {e}")
