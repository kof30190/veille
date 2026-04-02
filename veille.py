#!/usr/bin/env python3
"""
Script de veille technologique - Menuiseries et artisans Brignon/Uzès
Scrape les sites des entreprises, détecte les changements, génère le rapport HTML.
"""
import json
import os
import re
import time
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

TZ = timezone(timedelta(hours=1))  # Paris
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_FILE = os.path.join(DATA_DIR, "veille-data.json")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
REPORT_FILE = os.path.join(DATA_DIR, "index.html")
os.makedirs(HISTORY_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

def load_companies():
    with open(COMPANIES_FILE) as f:
        return json.load(f)

def load_history():
    """Load previous day's snapshot hashes"""
    history_file = os.path.join(HISTORY_DIR, "snapshot_hashes.json")
    if os.path.exists(history_file):
        with open(history_file) as f:
            return json.load(f)
    return {"hashes": {}, "last_run": None, "alerts": []}

def save_history(history):
    history_file = os.path.join(HISTORY_DIR, "snapshot_hashes.json")
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)

def hash_content(content):
    """Create deterministic hash of page content (normalized)"""
    # Remove dynamic parts that change every load
    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL|re.IGNORECASE)
    content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL|re.IGNORECASE)
    # Remove timestamps, session IDs, CSRF tokens
    content = re.sub(r'(?i)(csrf|session|token|timestamp|nonce)=[^"\'>\s]+', '', content)
    content = re.sub(r'(?i)date:\s*\w+,\s*\d+\s+\w+\s+\d+', '', content)
    # Normalize whitespace
    content = re.sub(r'\s+', ' ', content).strip()
    return hashlib.sha256(content.encode()).hexdigest()[:12]

def fetch_page(url, timeout=15):
    """Fetch a page and return content + status"""
    if not url or not url.startswith('http'):
        return None, "no_url"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=True)
        if resp.status_code == 200:
            return resp.text, "ok"
        return None, f"http_{resp.status_code}"
    except requests.exceptions.SSLError:
        # Retry without SSL verification
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
            if resp.status_code == 200:
                return resp.text, "ok_nossl"
            return None, f"http_{resp.status_code}"
        except Exception as e:
            return None, f"error_{str(e)[:50]}"
    except Exception as e:
        return None, f"error_{str(e)[:50]}"

def extract_title(html):
    """Safely extract page title"""
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE|re.DOTALL)
    return m.group(1).strip() if m else 'N/A'

def extract_text_content(html):
    """Extract visible text from HTML"""
    if not html:
        return ""
    # Remove scripts and styles
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL|re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def detect_keywords(text):
    """Detect relevant keywords in page content"""
    keywords = {
        'nouveau': ['nouveau', 'nouveauté', 'nouvel', 'nouvelle', 'lancement', 'inauguration'],
        'promotion': ['promotion', 'soldes', 'offre', 'réduction', 'promo', 'remise', 'devis gratuit'],
        'service': ['service', 'prestation', 'realisation', 'réalisation', 'projet', 'chantier'],
        'certification': ['certification', 'qualibat', 'rge', 'norme', 'certifié', 'label'],
        'contact': ['contact', 'devis', 'rdv', 'rendez-vous', 'formulaire'],
    }
    found = {}
    text_lower = text.lower()
    for category, words in keywords.items():
        matches = [w for w in words if w in text_lower]
        if matches:
            found[category] = matches
    return found

def check_company(company, old_hashes):
    """Check a single company for changes"""
    result = {
        'id': company['id'],
        'name': company['name'],
        'website': company['website'],
        'status': 'unknown',
        'change_type': None,
        'details': {},
        'timestamp': datetime.now(TZ).isoformat()
    }
    
    url = company.get('website', '')
    if not url:
        result['status'] = 'no_website'
        return result
    
    content, status = fetch_page(url)
    result['status'] = status
    
    if status != 'ok' and status != 'ok_nossl':
        result['change_type'] = 'error'
        result['details'] = {'error': status}
        return result
    
    # Hash comparison
    current_hash = hash_content(content)
    old_hash = old_hashes.get(company['id'])
    old_hashes[company['id']] = current_hash
    
    if old_hash and old_hash != current_hash:
        result['change_type'] = 'content_changed'
        # Extract what changed (simplified - full text diff)
        text = extract_text_content(content)
        keywords = detect_keywords(text)
        result['details'] = {
            'old_hash': old_hash,
            'new_hash': current_hash,
            'keywords_found': keywords,
            'has_contact_form': 'formulaire' in text.lower() or 'contact' in text.lower(),
            'content_length': len(text),
            'page_title': extract_title(content)
        }
    elif old_hash:
        result['change_type'] = 'no_change'
    else:
        result['change_type'] = 'first_scan'
        text = extract_text_content(content)
        keywords = detect_keywords(text)
        result['details'] = {
            'hash': current_hash,
            'keywords_found': keywords,
            'content_length': len(text),
            'page_title': extract_title(content)
        }
    
    # Small delay to be polite
    time.sleep(1)
    return result

def generate_html_report(data, changes):
    """Generate beautiful HTML report"""
    now = datetime.now(TZ).strftime('%d/%m/%Y à %H:%M')
    
    zones = {}
    for c in changes:
        zone = next((comp['zone'] for comp in data['companies'] if comp['id'] == c['id']), 'Inconnu')
        if zone not in zones:
            zones[zone] = []
        zones[zone].append(c)
    
    # Count changes
    changed = [c for c in changes if c['change_type'] == 'content_changed']
    errors = [c for c in changes if c['change_type'] == 'error']
    first = [c for c in changes if c['change_type'] == 'first_scan']
    unchanged = [c for c in changes if c['change_type'] == 'no_change']
    no_site = [c for c in changes if c['change_type'] == 'no_website']
    
    zone_colors = {
        'Brignon': '#3B82F6',
        'Sainte-Anastasie': '#10B981',
        'Uzès': '#8B5CF6',
        'Nîmes': '#F59E0B',
        'Alès': '#EF4444',
    }
    
    change_icons = {
        'content_changed': '<span style="color: #F59E0B;">⚡ Changement détecté</span>',
        'first_scan': '<span style="color: #3B82F6;">🆕 Premier scan</span>',
        'no_change': '<span style="color: #6B7280;">✓ Inchangé</span>',
        'error': '<span style="color: #EF4444;">❌ Erreur</span>',
        'no_website': '<span style="color: #6B7280;">— Pas de site</span>',
    }
    
    status_bg = {
        'content_changed': 'rgba(245, 158, 11, 0.1)',
        'first_scan': 'rgba(59, 130, 246, 0.1)',
        'no_change': 'rgba(107, 114, 128, 0.05)',
        'error': 'rgba(239, 68, 68, 0.1)',
        'no_website': 'rgba(107, 114, 128, 0.05)',
    }
    
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Veille - Menuiseries Brignon/Uzès</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0F172A;
    color: #E2E8F0;
    line-height: 1.6;
    padding: 20px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 2rem;
    background: linear-gradient(135deg, #60A5FA, #A78BFA);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }}
  .subtitle {{
    color: #94A3B8;
    font-size: 0.95rem;
    margin-bottom: 30px;
  }}
  .summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 30px;
  }}
  .stat {{
    background: #1E293B;
    border-radius: 12px;
    padding: 16px;
    text-align: center;
    border: 1px solid #334155;
  }}
  .stat-num {{
    font-size: 2rem;
    font-weight: 700;
  }}
  .stat-label {{
    font-size: 0.8rem;
    color: #64748B;
    margin-top: 4px;
  }}
  .zone {{
    margin-bottom: 30px;
  }}
  .zone-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 15px;
    padding-bottom: 8px;
    border-bottom: 2px solid;
  }}
  .zone-name {{
    font-size: 1.3rem;
    font-weight: 700;
  }}
  .zone-count {{
    background: rgba(100,116,139,0.2);
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 0.8rem;
    color: #94A3B8;
  }}
  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px;
  }}
  .card {{
    background: #1E293B;
    border-radius: 12px;
    padding: 16px;
    border: 1px solid #334155;
    transition: transform 0.15s;
  }}
  .card:hover {{
    transform: translateY(-2px);
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8px;
  }}
  .card-name {{
    font-weight: 600;
    font-size: 1rem;
    color: #F1F5F9;
  }}
  .card-type {{
    font-size: 0.8rem;
    color: #94A3B8;
    margin-bottom: 8px;
  }}
  .card-meta {{
    font-size: 0.8rem;
    color: #64748B;
  }}
  .card-meta a {{
    color: #60A5FA;
    text-decoration: none;
  }}
  .card-meta a:hover {{
    text-decoration: underline;
  }}
  .card-keywords {{
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }}
  .keyword {{
    background: rgba(96, 165, 250, 0.15);
    color: #60A5FA;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
  }}
  .keyword.promo {{
    background: rgba(16, 185, 129, 0.15);
    color: #34D399;
  }}
  .keyword.cert {{
    background: rgba(251, 191, 36, 0.15);
    color: #FBBF24;
  }}
  .footer {{
    text-align: center;
    color: #475569;
    font-size: 0.8rem;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid #1E293B;
  }}
</style>
</head>
<body>

<h1>🔍 Veille Concurrentielle</h1>
<div class="subtitle">Menuiseries & Artisans — Brignon / Uzès · Rapport du {now}</div>

<div class="summary">
  <div class="stat">
    <div class="stat-num" style="color: #60A5FA;">{len(data['companies'])}</div>
    <div class="stat-label">Entreprises surveillées</div>
  </div>
  <div class="stat">
    <div class="stat-num" style="color: #F59E0B;">{len(changed)}</div>
    <div class="stat-label">Changements</div>
  </div>
  <div class="stat">
    <div class="stat-num" style="color: #3B82F6;">{len(first)}</div>
    <div class="stat-label">Premiers scans</div>
  </div>
  <div class="stat">
    <div class="stat-num" style="color: #6B7280;">{len(unchanged)}</div>
    <div class="stat-label">Inchangés</div>
  </div>
  <div class="stat">
    <div class="stat-num" style="color: #EF4444;">{len(errors)}</div>
    <div class="stat-label">Erreurs</div>
  </div>
</div>

"""
    
    for zone, zone_changes in sorted(zones.items()):
        color = zone_colors.get(zone, '#64748B')
        html += f"""
<div class="zone">
  <div class="zone-header" style="border-color: {color};">
    <span class="zone-name" style="color: {color};">{zone}</span>
    <span class="zone-count">{len(zone_changes)} entreprise{'' if len(zone_changes) <= 1 else 's'}</span>
  </div>
  <div class="cards">
"""
        for c in sorted(zone_changes, key=lambda x: (x['change_type'] != 'content_changed', x['name'])):
            comp = next((co for co in data['companies'] if co['id'] == c['id']), None)
            status_html = change_icons.get(c['change_type'], c['change_type'])
            bg = status_bg.get(c['change_type'], '')
            
            details = c.get('details', {})
            keywords = details.get('keywords_found', {})
            kw_html = ''
            if keywords:
                kw_items = []
                for cat, words in keywords.items():
                    cls = 'promo' if cat in ['promotion', 'service'] else ('cert' if cat == 'certification' else '')
                    for w in words:
                        kw_items.append(f'<span class="keyword {cls}">{w}</span>')
                if kw_items:
                    kw_html = f'<div class="card-keywords">{"".join(kw_items)}</div>'
            
            phone = comp['phone'] if comp else ''
            website = comp['website'] if comp else ''
            website_html = f'<a href="{website}" target="_blank">Visiter →</a>' if website else 'Pas de site'
            
            html += f"""
    <div class="card" style="background: {bg};">
      <div class="card-header">
        <span class="card-name">{c['name']}</span>
        <span style="font-size: 0.85rem;">{status_html}</span>
      </div>
      <div class="card-type">{comp['type'] if comp else ''}</div>
      <div class="card-meta">
        {phone} · {website_html}
      </div>
      {kw_html}
    </div>
"""
        html += """  </div>
</div>
"""
    
    html += f"""
<div class="footer">
  Veille automatique · {len(data['companies'])} entreprises · Généré le {now}
</div>

</body>
</html>"""
    
    return html

def main():
    data = load_companies()
    history = load_history()
    old_hashes = history.get('hashes', {})
    
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Début de la veille ({len(data['companies'])} entreprises)")
    
    changes = []
    for company in data['companies']:
        print(f"  → {company['name']}...", end=' ', flush=True)
        result = check_company(company, old_hashes)
        changes.append(result)
        print(f"{result['change_type']} ({result['status']})")
    
    # Save updated history
    history['hashes'] = old_hashes
    history['last_run'] = datetime.now(TZ).isoformat()
    save_history(history)
    
    # Generate report
    report = generate_html_report(data, changes)
    with open(REPORT_FILE, 'w') as f:
        f.write(report)
    
    # Summary
    changed = [c for c in changes if c['change_type'] == 'content_changed']
    errors = [c for c in changes if c['change_type'] == 'error']
    first = [c for c in changes if c['change_type'] == 'first_scan']
    
    msg = f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Veille terminée: "
    msg += f"{len(changed)} changements, {len(first)} premiers scans, {len(errors)} erreurs"
    print(msg)
    
    # Return report for Telegram message
    if changed:
        change_names = [c['name'] for c in changed]
        msg += f"\n\n⚡ Changements: {', '.join(change_names)}"
    
    if errors:
        error_names = [c['name'] for c in errors]
        msg += f"\n\n❌ Erreurs: {', '.join(error_names)}"
    
    print(f"\n---TELEGRAM_MSG---\n{msg}")
    print("---REPORT_PATH---")
    print(REPORT_FILE)

if __name__ == '__main__':
    main()
