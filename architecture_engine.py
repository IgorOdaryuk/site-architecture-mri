import requests, re, json, csv, sys, time, html
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import defaultdict, Counter, deque

DOMAIN = "https://odariuk.com"
MAX_PAGES = 300
DELAY = 0.05

OUT_CSV = "architecture_pages.csv"
OUT_JSON = "architecture_summary.json"
OUT_HTML = "architecture_map.html"

HEADERS = {"User-Agent": "Mozilla/5.0 ArchitectureEngineBot"}

EXCLUDE = ["/wp-admin", "/wp-login", "/tag/", "/category/", "/author/", "/page/",
           ".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".mp4", ".mp3", ".zip"]

def clean(x):
    return re.sub(r"\s+", " ", x or "").strip()

def norm(url):
    p = urlparse(url)
    return p._replace(fragment="", query="").geturl().rstrip("/")

def same_domain(url):
    return urlparse(url).netloc.replace("www.", "") == urlparse(DOMAIN).netloc.replace("www.", "")

def skip(url):
    return any(x in url.lower() for x in EXCLUDE)

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if "text/html" not in r.headers.get("content-type", ""):
            return None, None
        return r, BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None, None

def sitemap_urls():
    urls = []
    try:
        r = requests.get(DOMAIN.rstrip("/") + "/sitemap.xml", headers=HEADERS, timeout=10)
        root = ET.fromstring(r.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall(".//sm:loc", ns):
            u = norm(loc.text.strip())
            if same_domain(u) and not skip(u):
                urls.append(u)
    except Exception as e:
        print("sitemap failed:", e)
    return list(dict.fromkeys(urls))

def extract_page(url, depth):
    r, soup = fetch(url)
    if not r or not soup:
        return None, []

    title = clean(soup.title.text if soup.title else "")
    h1 = " | ".join(clean(x.get_text(" ")) for x in soup.find_all("h1"))
    h2s = [clean(x.get_text(" ")) for x in soup.find_all("h2")]
    text = clean(soup.get_text(" "))

    links = []
    for a in soup.find_all("a", href=True):
        href = norm(urljoin(url, a["href"].strip()))
        if same_domain(href) and not skip(href):
            links.append(href)

    embed_text = clean((title + " " + h1 + " " + " ".join(h2s) + " " + text[:6000]).lower())

    return {
        "url": url,
        "depth": depth,
        "status": r.status_code,
        "title": title,
        "h1": h1,
        "h2_count": len(h2s),
        "word_count": len(re.findall(r"\b[a-zA-Z]{2,}\b", text)),
        "text_for_embedding": embed_text,
        "cluster": None,
        "cluster_label": None,
        "cluster_status": None,
        "pagerank": 0
    }, links

def crawl():
    seeds = sitemap_urls()
    if seeds:
        print(f"SITEMAP URLS FOUND: {len(seeds)}")
        q = deque([(u, 0) for u in seeds])
    else:
        q = deque([(DOMAIN.rstrip("/"), 0)])

    seen, rows, edges = set(), [], []

    while q and len(seen) < MAX_PAGES:
        url, depth = q.popleft()
        url = norm(url)

        if url in seen or skip(url):
            continue

        seen.add(url)
        print(f"[{len(seen)}] {url}")

        row, links = extract_page(url, depth)
        if not row:
            continue

        rows.append(row)

        for link in links:
            edges.append({"from": url, "to": link})
            if link not in seen and len(seen) + len(q) < MAX_PAGES:
                q.append((link, depth + 1))

        time.sleep(DELAY)

    return rows, edges

def label_cluster(pages):
    raw = " ".join((p["title"] + " " + p["h1"]).lower() for p in pages)

    stop = set("""
    the and for with this that from your you are have has was were will not but how what why when into about
    local business businesses service services blog post guide page ihor odariuk home don need needs know
    """.split())

    words = re.findall(r"\b[a-zA-Z][a-zA-Z\-]{2,}\b", raw)
    words = [w for w in words if w not in stop]

    phrases = []
    phrases += [" ".join(words[i:i+3]) for i in range(len(words)-2)]
    phrases += [" ".join(words[i:i+2]) for i in range(len(words)-1)]
    phrases += words

    best = []
    for phrase, count in Counter(phrases).most_common(30):
        if len(phrase) < 4:
            continue
        if phrase in best:
            continue
        best.append(phrase)
        if len(best) >= 3:
            break

    return " / ".join(x.title() for x in best) if best else "Cluster"

def cluster_pages(rows, requested_clusters=None):
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import KMeans

    texts = [r["text_for_embedding"][:6000] for r in rows]

    print("Loading local embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print("Creating embeddings...")
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    n = len(rows)
    k = int(requested_clusters) if requested_clusters else max(2, min(8, round(n ** 0.5)))
    k = max(2, min(k, n))

    print(f"Clustering into {k} clusters...")
    km = KMeans(n_clusters=k, random_state=42, n_init="auto")
    labels = km.fit_predict(embeddings)

    for r, label in zip(rows, labels):
        r["cluster"] = int(label)

    grouped = defaultdict(list)
    for r in rows:
        grouped[r["cluster"]].append(r)

    for cid, pages in grouped.items():
        label = label_cluster(pages)
        status = "strong cluster" if len(pages) >= 3 else ("weak cluster" if len(pages) == 2 else "orphan topic")
        for p in pages:
            p["cluster_label"] = label
            p["cluster_status"] = status

    return grouped

def pagerank(rows, edges, iterations=30, damping=0.85):
    urls = [r["url"] for r in rows]
    urlset = set(urls)
    outlinks = defaultdict(list)

    for e in edges:
        if e["from"] in urlset and e["to"] in urlset:
            outlinks[e["from"]].append(e["to"])

    n = len(urls)
    if not n:
        return {}

    pr = {u: 1 / n for u in urls}

    for _ in range(iterations):
        new = {u: (1 - damping) / n for u in urls}
        for u in urls:
            targets = outlinks.get(u, [])
            if targets:
                share = pr[u] / len(targets)
                for v in targets:
                    new[v] += damping * share
            else:
                share = pr[u] / n
                for v in urls:
                    new[v] += damping * share
        pr = new

    return pr

def build_html(summary):
    cards = ""

    for c in summary["clusters"]:
        cards += '<section class="cluster">'
        cards += f'<h2>{html.escape(c["label"])}</h2>'
        cards += f'<div class="meta">{c["pages"]} pages · {html.escape(c["status"])} · authority {c["internal_authority"]:.3f}</div>'

        for p in c["top_pages"]:
            path = p["url"].replace(DOMAIN, "") or "/"
            cards += '<div class="page">'
            cards += f'<a href="{html.escape(p["url"])}" target="_blank">{html.escape(path)}</a>'
            cards += f'<small>{html.escape(p["title"][:120])}</small>'
            cards += f'<small>PR {p["pagerank"]:.4f}</small>'
            cards += '</div>'

        cards += '</section>'

    doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Architecture Map</title>
<style>
body {{ margin:0; background:#111; color:#eee; font-family:Arial,sans-serif; }}
header {{ padding:22px; background:#1b1b1b; border-bottom:1px solid #333; position:sticky; top:0; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:18px; padding:18px; }}
.cluster {{ background:#181818; border:1px solid #333; border-radius:14px; padding:16px; }}
h2 {{ margin:0 0 8px 0; }}
.meta {{ color:#aaa; margin-bottom:14px; }}
.page {{ padding:9px 0; border-bottom:1px solid #282828; }}
a {{ color:#fff; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
small {{ display:block; color:#888; margin-top:4px; line-height:1.35; }}
</style>
</head>
<body>
<header>
<h1>Architecture Map: {html.escape(summary["domain"])}</h1>
<p>Local embeddings + automatic clusters. Strong = 3+ pages, weak = 2 pages, orphan = 1 page.</p>
</header>
<div class="grid">
{cards}
</div>
</body>
</html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(doc)

def save(rows, edges, grouped):
    pr = pagerank(rows, edges)

    for r in rows:
        r["pagerank"] = pr.get(r["url"], 0)

    public_rows = []
    for r in rows:
        rr = dict(r)
        rr.pop("text_for_embedding", None)
        public_rows.append(rr)

    fields = sorted(set().union(*(r.keys() for r in public_rows)))
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(public_rows)

    cluster_summary = []
    for cid, pages in grouped.items():
        total_pr = sum(p.get("pagerank", 0) for p in pages)
        top_pages = sorted(
            [{"url": p["url"], "title": p["title"], "pagerank": p["pagerank"]} for p in pages],
            key=lambda x: x["pagerank"],
            reverse=True
        )[:10]

        cluster_summary.append({
            "cluster": int(cid),
            "label": pages[0]["cluster_label"],
            "pages": len(pages),
            "status": pages[0]["cluster_status"],
            "internal_authority": total_pr,
            "top_pages": top_pages
        })

    cluster_summary = sorted(cluster_summary, key=lambda x: x["internal_authority"], reverse=True)

    diagnosis = []
    for c in cluster_summary:
        if c["status"] == "orphan topic":
            diagnosis.append(f"Orphan topic: {c['label']}")
        elif c["status"] == "weak cluster":
            diagnosis.append(f"Weak cluster: {c['label']}")

    url_to_cluster = {r["url"]: r["cluster_label"] for r in rows}
    cluster_links = defaultdict(int)

    for e in edges:
        src = url_to_cluster.get(e["from"])
        dst = url_to_cluster.get(e["to"])
        if src and dst and src != dst:
            cluster_links[(src, dst)] += 1

    cluster_links_out = [
        {"from": a, "to": b, "links": n}
        for (a, b), n in sorted(cluster_links.items(), key=lambda x: x[1], reverse=True)
    ]

    summary = {
        "domain": DOMAIN,
        "pages": len(rows),
        "edges": len(edges),
        "clusters": cluster_summary,
        "cluster_links": cluster_links_out,
        "diagnosis": diagnosis
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    build_html(summary)

    print("\nDONE")
    print("CSV:", OUT_CSV)
    print("JSON:", OUT_JSON)
    print("HTML:", OUT_HTML)

    print("\nCLUSTERS:")
    for c in cluster_summary:
        print(f"- {c['label']}: {c['pages']} pages — {c['status']} — authority {c['internal_authority']:.3f}")

    print("\nCLUSTER LINKS:")
    for link in cluster_links_out[:20]:
        print(f"- {link['from']} -> {link['to']}: {link['links']} links")

    print("\nDIAGNOSIS:")
    for d in diagnosis:
        print("-", d)

def main():
    global DOMAIN

    args = sys.argv[1:]
    if args and not args[0].startswith("--"):
        DOMAIN = args[0].rstrip("/")

    requested_clusters = None
    if "--clusters" in args:
        i = args.index("--clusters")
        requested_clusters = int(args[i + 1])

    rows, edges = crawl()
    if not rows:
        print("No pages found")
        return

    grouped = cluster_pages(rows, requested_clusters)
    save(rows, edges, grouped)

if __name__ == "__main__":
    main()
