#!/usr/bin/env python3
"""
LATAM News Scraper — Colombia & Mexico
Server-side RSS fetcher (no CORS restrictions)
Outputs news.json for the CP-360 IT Dashboard

Repo: https://github.com/shaullazar/dashboard-news
The dashboard reads:
  https://raw.githubusercontent.com/shaullazar/dashboard-news/main/news.json
"""
import json, re, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

OUTPUT = Path(__file__).parent / "news.json"

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, application/atom+xml, text/xml, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
})

# Colombia — tried in order, first that returns articles wins
COLOMBIA_SOURCES = [
    ("The Bogota Post",  "https://thebogotapost.com/feed/"),
    ("La Nacion CO",     "https://www.lanacion.com.co/feed/"),
    ("El Tiempo CO",     "https://www.eltiempo.com/rss/"),
    ("El Colombiano",    "https://www.elcolombiano.com/arc/outboundfeeds/rss/"),
    ("El Espectador",    "https://www.elespectador.com/arcio/rss/"),
    ("Semana CO",        "https://www.semana.com/rss/"),
    ("Blu Radio CO",     "https://www.bluradio.com/feed"),
]

# Mexico — tried in order, first that returns articles wins
MEXICO_SOURCES = [
    ("Aristegui Noticias", "https://aristeguinoticias.com/feed/"),
    ("Animal Politico",    "https://animalpolitico.com/feed"),
    ("Infobae MX",         "https://www.infobae.com/feeds/rss/mexico/"),
    ("El Financiero MX",   "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/"),
    ("Expansion MX",       "https://expansion.mx/rss"),
    ("SDPnoticias",        "https://www.sdpnoticias.com/rss/"),
    ("Proceso MX",         "https://www.proceso.com.mx/rss/"),
]


def strip_cdata(text):
    return re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.DOTALL)


def strip_tags(text):
    return re.sub(r'<[^>]+>', '', text).strip()


def fetch_feed(name, url, max_items=10):
    """Fetch and parse one RSS/Atom feed. Returns list of article dicts."""
    try:
        r = SESSION.get(url, timeout=18, allow_redirects=True)
        r.raise_for_status()
        content = r.content

        # Quick check it's XML-ish
        sample = content[:200].lstrip()
        if not (sample.startswith(b'<') or sample.startswith(b'\xef\xbb\xbf<')):
            print(f"  ❌ {name}: Not XML (got: {sample[:80]!r})")
            return []

        # Parse — try raw bytes first, then cleaned text
        root = None
        for attempt in (content, strip_cdata(content.decode(r.encoding or 'utf-8', errors='replace')).encode('utf-8')):
            try:
                root = ET.fromstring(attempt)
                break
            except ET.ParseError:
                continue

        if root is None:
            print(f"  ❌ {name}: XML parse failed")
            return []

        # Find items (RSS) or entries (Atom)
        items = root.findall('.//item')
        if not items:
            ns = 'http://www.w3.org/2005/Atom'
            items = root.findall(f'.//{{{ns}}}entry') or root.findall('.//entry')
        if not items:
            print(f"  ❌ {name}: No <item>/<entry> elements")
            return []

        articles = []
        atom_ns = 'http://www.w3.org/2005/Atom'

        for item in items[:max_items]:
            # --- title ---
            title = ''
            for tag in ('title', f'{{{atom_ns}}}title'):
                el = item.find(tag)
                if el is not None:
                    title = strip_tags(strip_cdata(el.text or '')).strip()
                    if title:
                        break
            if not title:
                continue

            # --- link ---
            link = ''
            link_el = item.find('link')
            if link_el is not None:
                link = (link_el.text or link_el.get('href', '')).strip()
            if not link:
                link_el = item.find(f'{{{atom_ns}}}link')
                if link_el is not None:
                    link = (link_el.get('href', '') or link_el.text or '').strip()
            if not link:
                guid = item.find('guid')
                if guid is not None and (guid.text or '').startswith('http'):
                    link = guid.text.strip()
            if not link.startswith('http'):
                continue

            # --- pub date ---
            pub = ''
            for tag in ('pubDate', 'published', 'updated',
                        '{http://purl.org/dc/elements/1.1/}date'):
                el = item.find(tag)
                if el is None:
                    el = item.find(f'{{{atom_ns}}}{tag.split("}")[-1]}')
                if el is not None and el.text:
                    pub = el.text.strip()
                    break

            articles.append({"title": title, "link": link, "source": name, "pub": pub})

        print(f"  ✅ {name}: {len(articles)} articles")
        return articles

    except requests.exceptions.Timeout:
        print(f"  ❌ {name}: Timeout")
        return []
    except requests.exceptions.RequestException as e:
        print(f"  ❌ {name}: {e}")
        return []
    except Exception as e:
        print(f"  ❌ {name}: Unexpected — {e}")
        traceback.print_exc()
        return []


def scrape_country(label, sources):
    """Try sources in order; return articles from first working one."""
    for name, url in sources:
        articles = fetch_feed(name, url)
        if articles:
            return articles
    print(f"  ⚠️  All {label} sources failed")
    return []


def main():
    print("=" * 55)
    print("LATAM News Scraper")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 55)

    print("\n🇨🇴 Colombia:")
    colombia = scrape_country("Colombia", COLOMBIA_SOURCES)

    print("\n🇲🇽 Mexico:")
    mexico = scrape_country("Mexico", MEXICO_SOURCES)

    # Fall back to existing data if a country failed
    existing = {}
    if OUTPUT.exists():
        try:
            existing = json.loads(OUTPUT.read_text(encoding='utf-8'))
        except Exception:
            pass

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "colombia": colombia or existing.get("colombia", []),
        "mexico":   mexico   or existing.get("mexico",   []),
    }

    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n✅ news.json: {len(output['colombia'])} CO + {len(output['mexico'])} MX articles")


if __name__ == "__main__":
    main()
