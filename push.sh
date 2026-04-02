#!/bin/bash
# Push to GitHub with token
TOKEN="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"
cd /root/veille
git add index.html history/snapshot_hashes.json
git diff --cached --quiet && echo "No changes" || {
    DATE=$(date +"%d/%m/%Y")
    git commit -m "Update report $DATE" && \
    git push https://${TOKEN}@github.com/kof30190/veille.git main 2>&1
}
