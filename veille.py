#!/usr/bin/env python3
"""
Veille V2 — Détection avancée, diff intelligent, avis, légal, réseaux sociaux.
"""
import json, os, re, time, hashlib, requests, difflib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, quote_plus

TZ = timezone(timedelta(hours=1))
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_FILE = os.path.join(DATA_DIR, "veille-data.json")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
REPORT_FILE = os.path.join(DATA_DIR, "index.html")
os.makedirs(HISTORY_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': 'text/html,*/*;q=0.8', 'Accept-Language': 'fr-FR,fr;q=0.9',
}

ZONE_COLORS = {'Brigon': '#3B82F6', 'Sainte-Anastasie': '#10B981', 'Uzès': '#8B5CF6', 'Nîmes': '#F59E0B', 'Alès': '#EF4444'}

# ══════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════
def load_json(path):
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def load_history():
    return load_json(os.path.join(HISTORY_DIR, "snapshot_history.json")) if os.path.exists(os.path.join(HISTORY_DIR, "snapshot_history.json")) else {"hashes": {}, "texts": {}, "changes_log": [], "last_run": None}

def fetch(url, timeout=15, verify=True):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=verify)
        return r.text if r.status_code == 200 else None, f"ok" if r.status_code == 200 else f"http_{r.status_code}"
    except:
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
            return r.text if r.status_code == 200 else None, "ok_nossl" if r.status_code == 200 else f"http_{r.status_code}"
        except Exception as e:
            return None, f"error:{str(e)[:80]}"

def extract_text(html):
    if not html:
        return ""
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', text).strip()

def extract_title(html):
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE|re.DOTALL)
    return m.group(1).strip() if m else None

def normalize(text):
    """Remove timestamps, session IDs, etc."""
    text = re.sub(r'(?i)(csrf|session|token|nonce|_utm)=[^"&#\s]+', '', text)
    text = re.sub(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', 'DATE', text)
    text = re.sub(r'\b\d{2}:\d{2}(:\d{2})?\b', 'TIME', text)
    return re.sub(r'\s+', ' ', text).strip()

def detect_keywords(text):
    kws = {
        'nouveau': ['nouveau', 'nouveauté', 'nouvel', 'nouvelle', 'lancement', 'inauguration', 'ouverture'],
        'promotion': ['promotion', 'soldes', 'offre', 'réduction', 'promo', 'remise', 'devis gratuit'],
        'service': ['service', 'prestation', 'realisation', 'réalisation', 'projet', 'chantier', 'catalogue'],
        'certification': ['certification', 'qualibat', 'rge', 'norme', 'certifié', 'label', 'QualiPAC', 'Qualibat'],
        'technologie': ['pompe à chaleur', 'pac', 'domotique', 'connecté', 'motorisation', 'solaire', 'photovoltaïque'],
    }
    found = {}
    tl = text.lower()
    for cat, words in kws.items():
        m = [w for w in words if w in tl]
        if m:
            found[cat] = m
    return found

def smart_diff(old_text, new_text, window=80):
    """Generate a human-readable diff showing what changed"""
    if not old_text or not new_text:
        return []
    
    old_words = normalize(old_text).split()
    new_words = normalize(new_text).split()
    
    # Use difflib for proper diff
    diff = list(difflib.unified_diff(old_words, new_words, lineterm=''))
    
    additions = []
    deletions = []
    
    for line in diff:
        if line.startswith('+'):
            additions.append(line[1:])
        elif line.startswith('-'):
            deletions.append(line[1:])
    
    results = []
    if additions:
        diff_pct = len(additions) / max(len(new_words), 1) * 100
        if diff_pct > 2:  # Filter out tiny changes
            sample = ' '.join(additions[:30])
            results.append({
                'type': 'additions',
                'count': len(additions),
                'sample': sample[:300] + '...' if len(sample) > 300 else sample,
                'diff_pct': round(diff_pct, 1)
            })
    
    if deletions:
        diff_pct = len(deletions) / max(len(old_words), 1) * 100
        if diff_pct > 2:
            sample = ' '.join(deletions[:30])
            results.append({
                'type': 'deletions',
                'count': len(deletions),
                'sample': sample[:300] + '...' if len(sample) > 300 else sample,
                'diff_pct': round(diff_pct, 1)
            })
    
    return results

def is_significant_change(old_text, new_text, threshold=5):
    """Check if the change is worth reporting"""
    if not old_text or not new_text:
        return True
    old_norm = normalize(old_text)
    new_norm = normalize(new_text)
    # Use SequenceMatcher for similarity
    sm = difflib.SequenceMatcher(None, old_norm, new_norm)
    similarity = sm.ratio()
    return (1 - similarity) * 100 > threshold

# ══════════════════════════════════════════
# MONITORS
# ══════════════════════════════════════════
def monitor_website(company, history):
    """1. Website — smart diff"""
    url = company.get('website', '')
    result = {'id': company['id'], 'name': company['name'], 'source': 'site', 'status': 'unknown', 'changes': []}
    
    if not url or not url.startswith('http'):
        result['status'] = 'no_website'
        return result
    
    content, status = fetch(url)
    result['status'] = status
    
    if not content:
        result['changes'].append({'type': 'error', 'details': status})
        return result
    
    text = extract_text(content)
    title = extract_title(content)
    old_text = history.get('texts', {}).get(company['id'], '')
    old_title = history.get('titles', {}).get(company['id'], '')
    
    # Update history
    hist = history.setdefault('texts', {})
    hist[company['id']] = text
    if title:
        history.setdefault('titles', {})[company['id']] = title
    
    # Smart diff
    if old_text:
        diffs = smart_diff(old_text, text)
        sig = is_significant_change(old_text, text)
        
        if sig or diffs:
            change = {
                'type': 'content_changed',
                'diffs': diffs,
                'significant': sig
            }
            if old_title and title and old_title != title:
                change['title_change'] = {'old': old_title, 'new': title}
            keywords = detect_keywords(text)
            if keywords:
                change['keywords'] = keywords
            result['changes'].append(change)
        else:
            result['changes'].append({'type': 'no_change'})
    else:
        keywords = detect_keywords(text)
        result['changes'].append({
            'type': 'first_scan',
            'keywords': keywords,
            'title': title,
            'content_len': len(text)
        })
    
    return result

def monitor_google_reviews(company):
    """2. Google Reviews — check for new reviews via DuckDuckGo"""
    name = company.get('google_maps_search', company['name'])
    result = {'id': company['id'], 'source': 'google_reviews', 'status': 'ok', 'changes': []}
    
    url = f"https://lite.duckduckgo.com/lite/?q=avis+{quote_plus(name)}"
    try:
        content, status = fetch(url)
        if content:
            tree_text = extract_text(content)
            # Look for rating patterns and recent mentions
            ratings = re.findall(r'(\d[,.]?\d?)\s*/\s*5', tree_text, re.IGNORECASE)
            review_count = re.findall(r'(\d+)\s*avis', tree_text, re.IGNORECASE)
            
            if ratings:
                result['changes'].append({
                    'type': 'rating',
                    'note': ratings[0].replace(',', '.') + '/5'
                })
            if review_count:
                result['changes'].append({
                    'type': 'review_count',
                    'count': int(review_count[0])
                })
            # Check for recent review mentions
            recent_keywords = ['dernier', 'récent', 'nouveau', 'il y a', 'avis récent']
            for kw in recent_keywords:
                if kw in tree_text.lower():
                    result['changes'].append({'type': 'recent_activity', 'detail': f'Mention activité récente'})
                    break
    except:
        pass
    
    return result

def monitor_pappers(company):
    """3. Legal/Pappers — check for legal changes"""
    search = company.get('pappers_search', company['name'])
    result = {'id': company['id'], 'source': 'pappers_legal', 'status': 'ok', 'changes': []}
    
    # Check Pappers.fr for company info
    url = f"https://www.pappers.fr/recherche?q={quote_plus(search)}"
    try:
        content, status = fetch(url)
        if content:
            text = extract_text(content)
            
            # Extract key legal data
            # Capital, SIREN/SIRET, dirigant, code APE, date de création, etc.
            capital = re.findall(r'capital\s*[:\-]?\s*(\d[\d\s]*\s*€)', text, re.IGNORECASE)
            dirigeant = re.findall(r'(?:dirigeant|président|gérant)\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', text, re.IGNORECASE)
            ape = re.findall(r'(?:code\s*)?APE?\s*[:\-]?\s*(\d{4}\s*[A-Z])', text, re.IGNORECASE)
            siren = re.findall(r'(?:SIREN|SIRET)\s*[:\-]?\s*(\d{3}\s*\d{3}\s*\d{3}\s*\d{5})', text, re.IGNORECASE)
            
            legal_data = {}
            if capital:
                legal_data['capital'] = capital[0].strip()
            if dirigeant:
                legal_data['dirigeant'] = dirigeant[0]
            if ape:
                legal_data['ape'] = ape[0]
            if siren:
                legal_data['siren_siret'] = siren[0].replace(' ', '')
            
            # Check against history
            old_legal = result.get('legal_data', {})
            if legal_data:
                for key, val in legal_data.items():
                    if key in old_legal and old_legal[key] != val:
                        result['changes'].append({'type': 'legal_change', 'field': key, 'old': old_legal[key], 'new': val})
            
            if legal_data:
                result['legal_data'] = legal_data
                if not result['changes']:
                    result['changes'].append({'type': 'no_change', 'data': legal_data})
    except:
        result['status'] = 'error'
    
    return result

def monitor_social_media(company):
    """4. Social Media monitoring"""
    result = {'id': company['id'], 'source': 'social_media', 'changes': [], 'profiles': {}}
    
    social_urls = {}
    for platform in ['facebook', 'instagram', 'linkedin']:
        val = company.get(platform, '')
        # Clean Facebook pixel URLs
        if platform == 'facebook' and val:
            val = re.search(r'(https?://www\.facebook\.com/[^?&]+)', val)
            val = val.group(1) if val else ''
        if val:
            social_urls[platform] = val
    
    if not social_urls:
        result['changes'].append({'type': 'no_social', 'detail': 'Aucun réseau social trouvé'})
        return result
    
    for platform, url in social_urls.items():
        try:
            content, status = fetch(url, timeout=10)
            if content:
                text = extract_text(content)
                result['profiles'][platform] = {'url': url, 'status': 'reachable'}
                
                # Extract recent activity indicators
                # Look for recent dates, posts, "publié il y a" patterns
                recent_patterns = ['il y a \d+', 'publié le', 'dernière publication']
                for pat in recent_patterns:
                    matches = re.findall(pat, text, re.IGNORECASE)
                    if matches:
                        result['profiles'][platform]['recent_activity'] = True
                        break
                
                # Check if account is active
                if 'page introuvable' in text.lower() or 'not found' in text.lower():
                    result['profiles'][platform]['status'] = 'inactive'
        except:
            result['profiles'][platform] = {'url': url, 'status': 'unreachable'}
    
    return result

def monitor_google_alerts(company):
    """5. Google Alerts style — monitor mentions of company"""
    name = company.get('google_maps_search', company['name'])
    result = {'id': company['id'], 'source': 'mentions', 'changes': []}
    
    # Search for recent mentions in French news/sites
    url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(name)}+menuiserie+actualité"
    try:
        content, _ = fetch(url)
        if content:
            text = extract_text(content)
            # Look for news-style patterns
            news_keywords = ['inaugure', 'nouveauté', 'embauche', 'ouverture', 'chantier', 'remporte', 'marché public', 'appel d\'offres']
            mentions = []
            tl = text.lower()
            for kw in news_keywords:
                if kw in tl:
                    mentions.append(kw)
            
            if mentions:
                result['changes'].append({'type': 'mentions_new', 'keywords': mentions})
            else:
                result['changes'].append({'type': 'no_mentions'})
        else:
            result['changes'].append({'type': 'no_results'})
    except:
        pass
    
    return result

# ══════════════════════════════════════════
# REPORT GENERATION
# ══════════════════════════════════════════
def generate_report(data, all_results):
    """Generate HTML report"""
    now = datetime.now(TZ).strftime('%d/%m/%Y à %H:%M')
    
    # Aggregate changes
    zone_data = {}
    for r in all_results:
        zone = next((c['zone'] for c in data['companies'] if c.get('id') == r['id']), 'Autre')
        if zone not in zone_data:
            zone_data[zone] = []
        zone_data[zone].append(r)
    
    changed = [r for r in all_results if any(c.get('type') in ['content_changed', 'legal_change', 'mentions_new'] for c in r.get('changes', []))]
    errors = [r for r in all_results if r.get('status', '').startswith('error')]
    
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Veille — Menuiseries Brignon/Uzès</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
    color: #E2E8F0;
    line-height: 1.6;
    padding: 20px;
    min-height: 100vh;
  }
  .container { max-width: 1200px; margin: 0 auto; }
  
  /* Header */
  .header {
    text-align: center;
    padding: 30px 0 20px;
    border-bottom: 1px solid #334155;
    margin-bottom: 30px;
  }
  h1 {
    font-size: 2.2rem;
    background: linear-gradient(135deg, #60A5FA, #A78BFA, #F472B6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
    letter-spacing: -0.5px;
  }
  .subtitle { color: #64748B; font-size: 0.95rem; margin-top: 5px; }
  
  /* Summary cards */
  .summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 30px;
  }
  .stat-card {
    background: rgba(30, 41, 59, 0.8);
    border: 1px solid #334155;
    border-radius: 16px;
    padding: 18px;
    text-align: center;
    backdrop-filter: blur(10px);
  }
  .stat-num { font-size: 2.2rem; font-weight: 700; }
  .stat-label { font-size: 0.75rem; color: #64748B; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
  
  /* Zone sections */
  .zone { margin-bottom: 35px; }
  .zone-header {
    display: flex; align-items: center; gap: 10px; margin-bottom: 15px;
    padding-bottom: 8px; border-bottom: 2px solid;
  }
  .zone-name { font-size: 1.2rem; font-weight: 700; }
  .zone-badge {
    background: rgba(100,116,139,0.2); border-radius: 20px;
    padding: 2px 10px; font-size: 0.75rem; color: #94A3B8;
  }
  
  /* Company cards */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; }
  .card {
    background: rgba(30, 41, 59, 0.6);
    border: 1px solid #334155;
    border-radius: 14px;
    padding: 18px;
    backdrop-filter: blur(10px);
  }
  .card.changed { border-left: 3px solid #F59E0B; }
  .card.has-error { border-left: 3px solid #EF4444; }
  .card.clean { border-left: 3px solid #64748B; }
  
  .card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 6px; }
  .card-name { font-weight: 600; font-size: 1.05rem; color: #F1F5F9; }
  .card-type { font-size: 0.8rem; color: #64748B; margin-bottom: 8px; }
  .card-meta { font-size: 0.8rem; color: #94A3B8; }
  .card-meta a { color: #60A5FA; text-decoration: none; }
  .card-meta a:hover { text-decoration: underline; }
  
  .status-badge {
    font-size: 0.75rem;
    padding: 3px 8px;
    border-radius: 8px;
    display: inline-block;
    margin: 3px 2px;
  }
  .status-change { background: rgba(245, 158, 11, 0.15); color: #FBBF24; }
  .status-new { background: rgba(59, 130, 246, 0.15); color: #60A5FA; }
  .status-error { background: rgba(239, 68, 68, 0.15); color: #F87171; }
  .status-clean { background: rgba(107, 114, 128, 0.15); color: #6B7280; }
  .status-legal { background: rgba(168, 85, 247, 0.15); color: #C084FC; }
  .status-social { background: rgba(34, 197, 94, 0.15); color: #4ADE80; }
  
  .diff-box {
    background: rgba(15, 23, 42, 0.6);
    border-radius: 8px;
    padding: 10px;
    margin: 8px 0;
    font-size: 0.8rem;
    font-family: 'SF Mono', 'Consolas', monospace;
    overflow-x: auto;
  }
  .diff-add { color: #4ADE80; }
  .diff-del { color: #F87171; }
  .diff-label { color: #64748B; font-size: 0.7rem; text-transform: uppercase; }
  
  .keywords { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0 0; }
  .kw { padding: 2px 8px; border-radius: 6px; font-size: 0.7rem; }
  .kw-new { background: rgba(245, 158, 11, 0.15); color: #FBBF24; }
  .kw-promo { background: rgba(16, 185, 129, 0.15); color: #34D399; }
  .kw-tech { background: rgba(139, 92, 246, 0.15); color: #A78BFA; }
  .kw-cert { background: rgba(59, 130, 246, 0.15); color: #60A5FA; }
  
  .social-icons { display: flex; gap: 6px; margin: 8px 0 0; }
  .social-icon {
    font-size: 0.75rem; padding: 3px 8px;
    background: rgba(100,116,139,0.1); border-radius: 6px;
    color: #94A3B8; text-decoration: none;
  }
  .social-icon.active { color: #4ADE80; background: rgba(34, 197, 94, 0.1); }
  .social-icon.inactive { color: #EF4444; background: rgba(239, 68, 68, 0.1); }
  
  .footer {
    text-align: center; color: #475569; font-size: 0.75rem;
    margin-top: 40px; padding-top: 20px; border-top: 1px solid #1E293B;
  }
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>🔍 Veille Concurrentielle</h1>
  <div class="subtitle">Menuiseries & Artisans — Brignon / Uzès · Rapport du {now}</div>
</div>
"""
    
    # Summary
    n_companies = len(data['companies'])
    n_changed = len(changed)
    n_errors = len(set(r['id'] for r in errors))
    n_social = sum(1 for r in all_results if r.get('source') == 'social_media')
    
    html += f"""
<div class="summary">
  <div class="stat-card"><div class="stat-num" style="color: #60A5FA;">{n_companies}</div><div class="stat-label">Entreprises</div></div>
  <div class="stat-card"><div class="stat-num" style="color: #F59E0B;">{n_changed}</div><div class="stat-label">Changements</div></div>
  <div class="stat-card"><div class="stat-num" style="color: #EF4444;">{n_errors}</div><div class="stat-label">Erreurs</div></div>
  <div class="stat-card"><div class="stat-num" style="color: #4ADE80;">{n_social}</div><div class="stat-label">Réseaux sociaux</div></div>
</div>
"""
    
    # Zone sections
    for zone, results in sorted(zone_data.items()):
        color = ZONE_COLORS.get(zone, '#64748B')
        # Group by company
        by_company = {}
        for r in results:
            cid = r.get('id', '')
            if cid:
                by_company.setdefault(cid, []).append(r)
        
        html += f"""
<div class="zone">
  <div class="zone-header" style="border-color: {color};">
    <span class="zone-name" style="color: {color};">{zone}</span>
    <span class="zone-badge">{len(by_company)} entreprise{'' if len(by_company) <= 1 else 's'}</span>
  </div>
  <div class="cards">
"""
        for cid, company_results in by_company.items():
            comp = next((c for c in data['companies'] if c['id'] == cid), None)
            if not comp:
                continue
            
            # Determine card state
            has_change = any(r.get('changes') and any(c.get('type') in ['content_changed', 'legal_change', 'mentions_new'] for c in r['changes']) for r in company_results)
            has_error = any(r.get('status', '').startswith('error') for r in company_results)
            card_class = 'changed' if has_change else ('has-error' if has_error else 'clean')
            
            # Build status badges
            badges = []
            for r in company_results:
                for c in r.get('changes', []):
                    ctype = c.get('type', '')
                    if ctype == 'content_changed':
                        badges.append('<span class="status-badge status-change">⚡ Site modifié</span>')
                    elif ctype == 'first_scan':
                        badges.append('<span class="status-badge status-new">🆕 Nouveau</span>')
                    elif ctype == 'legal_change':
                        badges.append('<span class="status-badge status-legal">⚖️ Changement légal</span>')
                    elif ctype == 'mentions_new':
                        badges.append('<span class="status-badge status-legal">📰 Mention trouvée</span>')
                    elif ctype == 'no_change':
                        badges.append('<span class="status-badge status-clean">✓ OK</span>')
            
            # Build details
            details_html = ''
            for r in company_results:
                for c in r.get('changes', []):
                    if c.get('type') == 'content_changed' and c.get('diffs'):
                        for d in c['diffs']:
                            if d['type'] == 'additions':
                                details_html += f'<div class="diff-box"><div class="diff-label">+ Ajouts ({d["diff_pct"]}% du contenu)</div><div class="diff-add">{d["sample"][:200]}...</div></div>'
                            elif d['type'] == 'deletions':
                                details_html += f'<div class="diff-box"><div class="diff-label">- Retraits ({d["diff_pct"]}% du contenu)</div><div class="diff-del">{d["sample"][:200]}...</div></div>'
                    
                    if c.get('keywords'):
                        kw_items = []
                        for cat, words in c['keywords'].items():
                            cls = 'kw-new' if cat == 'nouveau' else ('kw-promo' if cat == 'promotion' else ('kw-tech' if cat == 'technologie' else 'kw-cert'))
                            for w in words:
                                kw_items.append(f'<span class="kw {cls}">{w}</span>')
                        if kw_items:
                            details_html += f'<div class="keywords">{"".join(kw_items)}</div>'
                    
                    if c.get('type') == 'legal_change':
                        details_html += f'<div class="diff-box"><div class="diff-label">⚖️ Modification légale</div><div>{c.get("field")}: {c.get("old")} → {c.get("new")}</div></div>'
                    
                    if r.get('source') == 'social_media' and r.get('profiles'):
                        social_html = []
                        for platform, info in r['profiles'].items():
                            status = info.get('status', '')
                            cls = 'active' if status == 'reachable' else ('inactive' if status == 'inactive' else '')
                            icon = {'facebook': 'FB', 'instagram': 'IG', 'linkedin': 'LI'}.get(platform, platform)
                            social_html.append(f'<a class="social-icon {cls}" href="{info["url"]}" target="_blank">{icon}</a>')
                        if social_html:
                            details_html += f'<div class="social-icons">{"".join(social_html)}</div>'
            
            website = comp.get('website', '')
            website_html = f'<a href="{website}" target="_blank">🌐 Site</a>' if website else 'Pas de site'
            phone = comp.get('phone', '')
            
            html += f"""
    <div class="card {card_class}">
      <div class="card-header">
        <span class="card-name">{comp['name']}</span>
      </div>
      <div class="card-type">{comp.get('type', '')}</div>
      <div class="card-meta">{phone} · {website_html}</div>
      <div style="margin: 6px 0;">{''.join(badges)}</div>
      {details_html}
    </div>
"""
        
        html += """  </div>
</div>
"""
    
    html += f"""
<div class="footer">
  Veille automatique · {n_companies} entreprises · Sources: sites web, avis Google, Pappers, réseaux sociaux · Généré à {now}
</div>
</div>
</body>
</html>"""
    
    return html

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════
def main():
    data = load_json(COMPANIES_FILE)
    history = load_history()
    
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Début veille V2 ({len(data['companies'])} entreprises)")
    
    all_results = []
    changes_log = []
    
    for company in data['companies']:
        cid = company['id']
        print(f"  📡 {company['name']}...")
        
        # 1. Website
        web_result = monitor_website(company, history)
        all_results.append(web_result)
        
        # Log changes
        for c in web_result.get('changes', []):
            if c.get('type') not in ['no_change', 'first_scan']:
                changes_log.append({'company': company['name'], 'source': 'web', **c})
        
        time.sleep(0.5)
        
        # 2. Google Reviews (only if first scan or periodically)
        reviews_result = monitor_google_reviews(company)
        all_results.append(reviews_result)
        time.sleep(0.5)
        
        # 3. Legal/Pappers (only every few days to avoid overload)
        last_legal = history.get('legal', {}).get(cid, '')
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        if last_legal != today or True:  # Always check for first run
            legal_result = monitor_pappers(company)
            all_results.append(legal_result)
            time.sleep(1)
        
        # 4. Social Media
        social_result = monitor_social_media(company)
        all_results.append(social_result)
        
        # 5. Google Alerts / Mentions
        alerts_result = monitor_google_alerts(company)
        all_results.append(alerts_result)
    
    # Save updated history
    history['last_run'] = datetime.now(TZ).isoformat()
    save_json(os.path.join(HISTORY_DIR, "snapshot_history.json"), history)
    
    # Generate report
    report = generate_report(data, all_results)
    with open(REPORT_FILE, 'w') as f:
        f.write(report)
    
    # Summary
    n_changed = len(set(r['id'] for r in all_results if any(c.get('type') in ['content_changed', 'legal_change', 'mentions_new'] for c in r.get('changes', []))))
    n_errors = len(set(r['id'] for r in all_results if r.get('status', '').startswith('error')))
    
    msg = f"🔍 Veille du {datetime.now(TZ).strftime('%d/%m/%Y')} terminée"
    msg += f"\n\n{'✅' if n_changed == 0 else f'⚡ {n_changed} changement(s) détecté(s)'}"
    if n_errors > 0:
        msg += f"\n❌ {n_errors} erreur(s) de connexion"
    
    print(f"\n---TELEGRAM_MSG---\n{msg}")
    print("---REPORT_PATH---")
    print(REPORT_FILE)

if __name__ == '__main__':
    main()
