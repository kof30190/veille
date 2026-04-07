#!/usr/bin/env python3
"""
Veille V2 — Détection avancée, diff intelligent, avis, légal, réseaux sociaux.
"""
import json, os, re, time, hashlib, requests, difflib, uuid
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

ZONE_COLORS = {'Brignon': '#3B82F6', 'Sainte-Anastasie': '#10B981', 'Uzès': '#8B5CF6', 'Nîmes': '#F59E0B', 'Alès': '#EF4444', 'Saint-Geniès-de-Malgoirès': '#EC4899'}

CAMOFOX_URL = "http://localhost:9377"
# Vérifie si camofox est disponible au démarrage
try:
    _cf_health = requests.get(f"{CAMOFOX_URL}/health", timeout=3).json()
    CAMOFOX_AVAILABLE = _cf_health.get("ok", False)
except:
    CAMOFOX_AVAILABLE = False

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

def camofox_fetch(url, user_id="veille", wait=3):
    """Récupère une page via CamoFox (anti-détection). Retourne (text, status)."""
    if not CAMOFOX_AVAILABLE:
        return None, "camofox_unavailable"
    session_key = uuid.uuid4().hex[:8]
    tab_id = None
    try:
        resp = requests.post(f"{CAMOFOX_URL}/tabs",
            json={"userId": user_id, "sessionKey": session_key, "url": url},
            timeout=20)
        if resp.status_code != 200:
            return None, f"camofox_tab_{resp.status_code}"
        tab_id = resp.json().get("tabId")
        if not tab_id:
            return None, "camofox_no_tabid"
        time.sleep(wait)
        snap = requests.get(f"{CAMOFOX_URL}/tabs/{tab_id}/snapshot",
            params={"userId": user_id}, timeout=20)
        if snap.status_code != 200:
            return None, f"camofox_snap_{snap.status_code}"
        text = snap.json().get("snapshot", "")
        return text, "ok_camofox"
    except Exception as e:
        return None, f"camofox_err:{str(e)[:60]}"
    finally:
        if tab_id:
            try:
                requests.delete(f"{CAMOFOX_URL}/tabs/{tab_id}", timeout=5)
            except:
                pass

def fetch(url, timeout=15, verify=True, use_camofox_fallback=True):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=verify)
        if r.status_code == 200:
            return r.text, "ok"
        return None, f"http_{r.status_code}"
    except:
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
            if r.status_code == 200:
                return r.text, "ok_nossl"
            return None, f"http_{r.status_code}"
        except Exception as e:
            pass
    # Fallback camofox si requests échoue
    if use_camofox_fallback and CAMOFOX_AVAILABLE:
        return camofox_fetch(url)
    return None, "all_methods_failed"

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
    """2. Google Maps — note et avis via CamoFox (fallback DDG)"""
    name = company.get('google_maps_search', company['name'])
    result = {'id': company['id'], 'source': 'google_reviews', 'status': 'ok', 'changes': []}

    # Tentative via CamoFox → DuckDuckGo (pas de popup consentement)
    if CAMOFOX_AVAILABLE:
        try:
            search_url = f"https://duckduckgo.com/?q={quote_plus(name + ' avis site:google.com/maps OR maps.google.com')}&kl=fr-fr"
            text, status = camofox_fetch(search_url, user_id="veille-gmaps", wait=4)
            if text:
                ratings = re.findall(r'(\d[,\.]\d)\s*(?:étoile|sur 5|/\s*5)', text, re.IGNORECASE)
                review_counts = re.findall(r'([\d\s\u202f]+)\s*avis', text, re.IGNORECASE)
                recent = re.findall(r'il y a \d+ (?:jour|semaine|mois)', text, re.IGNORECASE)
                if ratings:
                    result['changes'].append({'type': 'rating', 'note': ratings[0].replace(',', '.') + '/5', 'source': 'camofox'})
                if review_counts:
                    count_str = re.sub(r'\D', '', review_counts[0])
                    if count_str.isdigit():
                        result['changes'].append({'type': 'review_count', 'count': int(count_str)})
                if recent:
                    result['changes'].append({'type': 'recent_activity', 'detail': recent[0]})
                if ratings or review_counts:
                    return result
        except:
            pass

    # Fallback DDG Lite
    url = f"https://lite.duckduckgo.com/lite/?q=avis+{quote_plus(name)}"
    try:
        content, status = fetch(url, use_camofox_fallback=False)
        if content:
            tree_text = extract_text(content)
            ratings = re.findall(r'(\d[,.]?\d?)\s*/\s*5', tree_text, re.IGNORECASE)
            review_count = re.findall(r'(\d+)\s*avis', tree_text, re.IGNORECASE)
            if ratings:
                result['changes'].append({'type': 'rating', 'note': ratings[0].replace(',', '.') + '/5'})
            if review_count:
                result['changes'].append({'type': 'review_count', 'count': int(review_count[0])})
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

def monitor_social_media(company, history=None):
    """4. Social Media monitoring — avec suivi des changements"""
    cid = company['id']
    result = {'id': cid, 'source': 'social_media', 'changes': [], 'profiles': {}}
    if history is None:
        history = {}

    social_urls = {}
    for platform in ['facebook', 'instagram', 'linkedin']:
        val = company.get(platform, '')
        if platform == 'facebook' and val:
            m = re.search(r'(https?://www\.facebook\.com/[^?&]+)', val)
            val = m.group(1) if m else val
        if val:
            social_urls[platform] = val

    if not social_urls:
        result['changes'].append({'type': 'no_social', 'detail': 'Aucun réseau social trouvé'})
        return result

    prev_social = history.setdefault('social', {}).setdefault(cid, {})

    for platform, url in social_urls.items():
        try:
            use_camofox = platform in ('facebook', 'instagram') and CAMOFOX_AVAILABLE
            if use_camofox:
                text, status = camofox_fetch(url, user_id="veille-social", wait=4)
            else:
                content, status = fetch(url, timeout=10, use_camofox_fallback=CAMOFOX_AVAILABLE)
                text = extract_text(content) if content else None

            if text:
                profile = {'url': url, 'status': 'reachable'}

                # Activité récente
                recent = re.findall(r'il y a \d+ (?:heure|jour|semaine|mois|minute)', text, re.IGNORECASE)
                if recent:
                    profile['recent_activity'] = recent[0]

                # Posts / publications
                posts = re.findall(r'(\d+)\s*(?:publication|post|photo|vidéo)', text, re.IGNORECASE)
                if posts:
                    profile['posts'] = posts[0]

                # Followers/likes
                followers = re.findall(r'([\d\s,]+)\s*(?:j\'aime|abonné|follower|like)', text, re.IGNORECASE)
                followers_clean = re.sub(r'\D', '', followers[0]) if followers else None
                if followers_clean:
                    profile['followers'] = followers_clean

                # Page inactive
                if any(x in text.lower() for x in ['page introuvable', 'not found', 'indisponible', 'content not found']):
                    profile['status'] = 'inactive'

                result['profiles'][platform] = profile

                # ── Comparaison avec historique ──
                prev = prev_social.get(platform, {})

                # Nouveau post détecté (activité récente fraîche = heure/jour)
                if recent and any(x in recent[0] for x in ['heure', 'minute']):
                    prev_recent = prev.get('recent_activity', '')
                    if recent[0] != prev_recent:
                        result['changes'].append({
                            'type': 'social_new_post',
                            'platform': platform,
                            'detail': recent[0]
                        })

                # Changement de followers
                if followers_clean and prev.get('followers'):
                    try:
                        diff = int(followers_clean) - int(prev['followers'])
                        if abs(diff) >= 5:
                            result['changes'].append({
                                'type': 'social_followers_change',
                                'platform': platform,
                                'old': prev['followers'],
                                'new': followers_clean,
                                'diff': diff
                            })
                    except:
                        pass

                # Compte réactivé (était unreachable, maintenant reachable)
                if prev.get('status') in ('unreachable', 'inactive') and profile['status'] == 'reachable':
                    result['changes'].append({
                        'type': 'social_reactivated',
                        'platform': platform
                    })

                # Mise à jour historique
                prev_social[platform] = {
                    'status': profile['status'],
                    'followers': followers_clean or prev.get('followers'),
                    'recent_activity': recent[0] if recent else prev.get('recent_activity'),
                    'posts': posts[0] if posts else prev.get('posts'),
                }
            else:
                result['profiles'][platform] = {'url': url, 'status': 'unreachable'}
                # Compte disparu
                if prev_social.get(platform, {}).get('status') == 'reachable':
                    result['changes'].append({
                        'type': 'social_went_offline',
                        'platform': platform
                    })
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
# DISCOVERY — Nouvelles entreprises
# ══════════════════════════════════════════
DISCOVERY_QUERIES = [
    "menuiserie Brignon Gard",
    "menuiserie Uzès 30700",
    "menuiserie Alès 30100",
    "artisan menuisier Saint-Chaptes Gard",
    "artisan menuisier Sainte-Anastasie Gard",
    "fermetures volets stores Uzès",
    "aluminium PVC fenêtres Pont-Saint-Esprit",
    "menuiserie sur mesure Gard 30",
    "stores motorisés Uzès Brignon",
    "pergola véranda Gard Uzès",
]

def _normalize_name(name):
    """Normalise un nom pour comparaison (minuscules, sans accents, sans ponctuation)."""
    import unicodedata
    name = name.lower()
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()

def _is_known(candidate_name, candidate_url, known_companies):
    """Vérifie si une entreprise est déjà suivie (par URL ou nom similaire)."""
    norm_candidate = _normalize_name(candidate_name)
    for comp in known_companies:
        # Match URL
        if candidate_url and comp.get('website'):
            cu = re.sub(r'^https?://(www\.)?', '', candidate_url.rstrip('/'))
            ku = re.sub(r'^https?://(www\.)?', '', comp['website'].rstrip('/'))
            if cu and ku and (cu in ku or ku in cu):
                return True
        # Match nom (au moins 3 mots communs significatifs)
        norm_known = _normalize_name(comp['name'])
        words_c = set(w for w in norm_candidate.split() if len(w) > 3)
        words_k = set(w for w in norm_known.split() if len(w) > 3)
        if words_c and words_k and len(words_c & words_k) >= 2:
            return True
    return False

def discover_new_companies(data, history):
    """Recherche de nouvelles entreprises non encore suivies."""
    known = data['companies']
    already_discovered = set(history.setdefault('discovered_ids', []))
    new_found = []

    for query in DISCOVERY_QUERIES:
        try:
            url = f"https://duckduckgo.com/?q={quote_plus(query)}&kl=fr-fr&ia=web"
            text, status = camofox_fetch(url, user_id="veille-discovery", wait=5)
            if not text:
                # Fallback DDG Lite
                content, _ = fetch(f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}", use_camofox_fallback=False)
                text = extract_text(content) if content else ''

            if not text:
                continue

            # Extraction des liens et titres depuis le snapshot
            # Format camofox : link "Titre" [eN]:\n  /url: https://...
            link_blocks = re.findall(r'link "([^"]{5,80})" \[e\d+\].*?/url: (https?://[^\s\n]+)', text, re.DOTALL)
            # Format texte simple (DDG Lite)
            if not link_blocks:
                links = re.findall(r'(https?://(?!(?:duckduckgo|duck|google|facebook|instagram|linkedin|wikipedia|youtube))[^\s"<>]+)', text)
                titles = re.findall(r'([A-Z][^\n.]{10,60}(?:menuiserie|fermeture|store|aluminium|bois|pergola|volet|fenêtre|ébénist)[^\n.]{0,40})', text, re.IGNORECASE)
                link_blocks = list(zip(titles, links))[:10]

            for title, link_url in link_blocks[:15]:
                # Filtrer les domaines non pertinents
                skip_domains = ['duckduckgo', 'google', 'facebook', 'instagram', 'linkedin',
                                'wikipedia', 'youtube', 'pagesjaunes', 'leboncoin', 'indeed',
                                'pole-emploi', 'lacentrale', 'pappers', 'societe.com', 'actu.fr']
                if any(d in link_url for d in skip_domains):
                    continue
                # Filtrer les titres non pertinents
                business_kw = ['menuiser', 'fermeture', 'store', 'aluminium', 'bois', 'pergola',
                               'volet', 'fenêtre', 'ebenis', 'vitr', 'clotur', 'portail', 'menuiserie']
                if not any(kw in title.lower() for kw in business_kw):
                    continue

                uid = re.sub(r'[^a-z0-9]', '-', _normalize_name(title))[:40]
                if uid in already_discovered:
                    continue
                if _is_known(title, link_url, known):
                    continue

                # Nouveau candidat !
                new_found.append({'name': title.strip(), 'url': link_url, 'query': query, 'uid': uid})
                already_discovered.add(uid)

        except Exception as e:
            pass
        time.sleep(1)

    # Mettre à jour l'historique
    history['discovered_ids'] = list(already_discovered)

    return new_found

# ══════════════════════════════════════════
# REPORT GENERATION
# ══════════════════════════════════════════
def generate_report(data, all_results, new_companies=None):
    """Generate HTML report"""
    now = datetime.now(TZ).strftime('%d/%m/%Y à %H:%M')
    
    # Aggregate changes
    zone_data = {}
    for r in all_results:
        zone = next((c['zone'] for c in data['companies'] if c.get('id') == r['id']), 'Autre')
        if zone not in zone_data:
            zone_data[zone] = []
        zone_data[zone].append(r)
    
    CHANGE_TYPES = ['content_changed', 'legal_change', 'mentions_new', 'social_new_post', 'social_followers_change', 'social_reactivated', 'social_went_offline']
    changed = [r for r in all_results if any(c.get('type') in CHANGE_TYPES for c in r.get('changes', []))]
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
                    elif ctype == 'social_new_post':
                        pl = c.get('platform','').upper()[:2]
                        badges.append(f'<span class="status-badge status-social">📲 Post {pl}</span>')
                    elif ctype == 'social_followers_change':
                        diff = c.get('diff', 0)
                        sign = '+' if diff > 0 else ''
                        pl = c.get('platform','').upper()[:2]
                        badges.append(f'<span class="status-badge status-social">👥 {pl} {sign}{diff}</span>')
                    elif ctype == 'social_reactivated':
                        pl = c.get('platform','').upper()[:2]
                        badges.append(f'<span class="status-badge status-social">✅ {pl} réactivé</span>')
                    elif ctype == 'social_went_offline':
                        pl = c.get('platform','').upper()[:2]
                        badges.append(f'<span class="status-badge status-error">⚠️ {pl} hors ligne</span>')
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
                        kw = c['keywords']
                        if isinstance(kw, dict):
                            for cat, words in kw.items():
                                cls = 'kw-new' if cat == 'nouveau' else ('kw-promo' if cat == 'promotion' else ('kw-tech' if cat == 'technologie' else 'kw-cert'))
                                for w in words:
                                    kw_items.append(f'<span class="kw {cls}">{w}</span>')
                        elif isinstance(kw, list):
                            for w in kw:
                                kw_items.append(f'<span class="kw kw-new">{w}</span>')
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

            # Liens réseaux sociaux depuis les données de l'entreprise
            social_links = []
            icons = {'facebook': ('FB', '#1877F2'), 'instagram': ('IG', '#E1306C'), 'linkedin': ('LI', '#0A66C2')}
            for platform, (icon, color) in icons.items():
                url_val = comp.get(platform, '')
                if url_val:
                    # Nettoyer les URLs Facebook avec paramètres
                    if platform == 'facebook':
                        m = re.search(r'(https?://www\.facebook\.com/[^?&\s]+)', url_val)
                        url_val = m.group(1) if m else url_val
                    social_links.append(f'<a href="{url_val}" target="_blank" style="display:inline-block;padding:2px 8px;border-radius:6px;font-size:0.75rem;font-weight:600;color:{color};background:rgba(255,255,255,0.05);text-decoration:none;border:1px solid {color}40;">{icon}</a>')
            social_html_inline = f'<div style="display:flex;gap:5px;margin-top:5px;">{"".join(social_links)}</div>' if social_links else ''

            html += f"""
    <div class="card {card_class}">
      <div class="card-header">
        <span class="card-name">{comp['name']}</span>
      </div>
      <div class="card-type">{comp.get('type', '')}</div>
      <div class="card-meta">{phone} · {website_html}</div>
      {social_html_inline}
      <div style="margin: 6px 0;">{''.join(badges)}</div>
      {details_html}
    </div>
"""
        
        html += """  </div>
</div>
"""
    
    # Section découverte
    if new_companies:
        html += f"""
<div class="zone">
  <div class="zone-header" style="border-color: #F472B6;">
    <span class="zone-name" style="color: #F472B6;">✨ Nouvelles entreprises détectées</span>
    <span class="zone-badge">{len(new_companies)} candidat{'s' if len(new_companies) > 1 else ''}</span>
  </div>
  <div class="cards">
"""
        for nc in new_companies:
            html += f"""
    <div class="card" style="border-left: 3px solid #F472B6;">
      <div class="card-header">
        <span class="card-name">{nc['name']}</span>
        <span class="status-badge status-new">🆕 Nouveau</span>
      </div>
      <div class="card-type">Trouvé via : {nc['query']}</div>
      <div class="card-meta"><a href="{nc['url']}" target="_blank">🌐 {nc['url'][:60]}{'...' if len(nc['url']) > 60 else ''}</a></div>
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
        social_result = monitor_social_media(company, history)
        all_results.append(social_result)
        
        # 5. Google Alerts / Mentions
        alerts_result = monitor_google_alerts(company)
        all_results.append(alerts_result)

    # 6. Découverte de nouvelles entreprises
    print(f"  🔎 Recherche de nouvelles entreprises...")
    new_companies = discover_new_companies(data, history)
    if new_companies:
        print(f"  ✨ {len(new_companies)} nouveau(x) candidat(s) trouvé(s)")

    # Save updated history
    history['last_run'] = datetime.now(TZ).isoformat()
    save_json(os.path.join(HISTORY_DIR, "snapshot_history.json"), history)

    # Generate report
    report = generate_report(data, all_results, new_companies)
    with open(REPORT_FILE, 'w') as f:
        f.write(report)

    # Summary
    CHANGE_TYPES = ['content_changed', 'legal_change', 'mentions_new', 'social_new_post', 'social_followers_change', 'social_reactivated', 'social_went_offline']
    n_changed = len(set(r['id'] for r in all_results if any(c.get('type') in CHANGE_TYPES for c in r.get('changes', []))))
    n_errors = len(set(r['id'] for r in all_results if r.get('status', '').startswith('error')))

    msg = f"🔍 Veille du {datetime.now(TZ).strftime('%d/%m/%Y')} terminée"
    msg += f"\n\n{'✅' if n_changed == 0 else f'⚡ {n_changed} changement(s) détecté(s)'}"
    if new_companies:
        msg += f"\n✨ {len(new_companies)} nouvelle(s) entreprise(s) détectée(s)"
    if n_errors > 0:
        msg += f"\n❌ {n_errors} erreur(s) de connexion"

    print(f"\n---TELEGRAM_MSG---\n{msg}")
    print("---REPORT_PATH---")
    print(REPORT_FILE)

if __name__ == '__main__':
    main()
