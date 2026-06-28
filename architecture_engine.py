import argparse
import csv
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

MAX_PAGES = 300
DELAY = 0.05

OUT_CSV = "architecture_pages.csv"
OUT_JSON = "architecture_summary.json"
OUT_HTML = "architecture_map.html"

HEADERS = {"User-Agent": "Mozilla/5.0 SiteArchitectureMRI"}

EXCLUDE = [
    "/wp-admin",
    "/wp-login",
    "/tag/",
    "/category/",
    "/author/",
    "/page/",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".pdf",
    ".mp4",
    ".mp3",
    ".zip",
]


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_url(url):
    parsed = urlparse(url)
    return parsed._replace(fragment="", query="").geturl().rstrip("/")


def get_domain(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def same_domain(url, domain):
    return (
        urlparse(url).netloc.replace("www.", "")
        == urlparse(domain).netloc.replace("www.", "")
    )


def should_skip(url):
    return any(part in url.lower() for part in EXCLUDE)


def fetch(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        content_type = response.headers.get("content-type", "")

        if "text/html" not in content_type:
            return None, None

        return response, BeautifulSoup(response.text, "html.parser")
    except Exception:
        return None, None


def sitemap_urls(domain):
    urls = []

    try:
        sitemap_url = domain.rstrip("/") + "/sitemap.xml"
        response = requests.get(sitemap_url, headers=HEADERS, timeout=10)
        root = ET.fromstring(response.text)

        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        for loc in root.findall(".//sm:loc", namespace):
            url = normalize_url(loc.text.strip())

            if same_domain(url, domain) and not should_skip(url):
                urls.append(url)

    except Exception as error:
        print("sitemap failed:", error)

    return list(dict.fromkeys(urls))


def extract_page(url, depth, domain):
    response, soup = fetch(url)

    if not response or not soup:
        return None, []

    title = clean(soup.title.text if soup.title else "")
    h1 = " | ".join(clean(item.get_text(" ")) for item in soup.find_all("h1"))
    h2s = [clean(item.get_text(" ")) for item in soup.find_all("h2")]
    text = clean(soup.get_text(" "))

    links = []

    for tag in soup.find_all("a", href=True):
        href = normalize_url(urljoin(url, tag["href"].strip()))

        if same_domain(href, domain) and not should_skip(href):
            links.append(href)

    embed_text = clean(
        (title + " " + h1 + " " + " ".join(h2s) + " " + text[:6000]).lower()
    )

    return {
        "url": url,
        "path": url.replace(domain, "") or "/",
        "depth": depth,
        "status": response.status_code,
        "title": title,
        "h1": h1,
        "h2_count": len(h2s),
        "word_count": len(re.findall(r"\b[a-zA-Z]{2,}\b", text)),
        "text_for_embedding": embed_text,
        "cluster": None,
        "cluster_label": None,
        "cluster_status": None,
        "pagerank": 0,
        "inbound_links": 0,
        "outbound_links": 0,
    }, list(dict.fromkeys(links))


def crawl(domain, max_pages=MAX_PAGES):
    seeds = sitemap_urls(domain)

    if seeds:
        print(f"SITEMAP URLS FOUND: {len(seeds)}")
        queue = deque([(url, 0) for url in seeds])
    else:
        queue = deque([(domain.rstrip("/"), 0)])

    seen = set()
    rows = []
    edges = []

    while queue and len(seen) < max_pages:
        url, depth = queue.popleft()
        url = normalize_url(url)

        if url in seen or should_skip(url):
            continue

        seen.add(url)
        print(f"[{len(seen)}] {url}")

        row, links = extract_page(url, depth, domain)

        if not row:
            continue

        rows.append(row)

        for link in links:
            edges.append({"from": url, "to": link})

            if link not in seen and len(seen) + len(queue) < max_pages:
                queue.append((link, depth + 1))

        time.sleep(DELAY)

    return rows, edges


def label_cluster(pages):
    raw = " ".join((page["title"] + " " + page["h1"]).lower() for page in pages)

    stop = set(
        """
        the and for with this that from your you are have has was were will not but
        how what why when into about local business businesses service services
        blog post guide page ihor odariuk home don need needs know
        """.split()
    )

    words = re.findall(r"\b[a-zA-Z][a-zA-Z\-]{2,}\b", raw)
    words = [word for word in words if word not in stop]

    phrases = []
    phrases += [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
    phrases += [" ".join(words[i : i + 2]) for i in range(len(words) - 1)]
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

    return " / ".join(item.title() for item in best) if best else "Cluster"


def cluster_pages(rows, requested_clusters=None):
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import KMeans

    texts = [row["text_for_embedding"][:6000] for row in rows]

    print("Loading local embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print("Creating embeddings...")
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    page_count = len(rows)
    cluster_count = (
        int(requested_clusters)
        if requested_clusters
        else max(2, min(8, round(page_count**0.5)))
    )

    cluster_count = max(2, min(cluster_count, page_count))

    print(f"Clustering into {cluster_count} clusters...")
    kmeans = KMeans(n_clusters=cluster_count, random_state=42, n_init="auto")
    labels = kmeans.fit_predict(embeddings)

    for row, label in zip(rows, labels):
        row["cluster"] = int(label)

    grouped = defaultdict(list)

    for row in rows:
        grouped[row["cluster"]].append(row)

    for cluster_id, pages in grouped.items():
        label = label_cluster(pages)

        if len(pages) >= 3:
            status = "strong cluster"
        elif len(pages) == 2:
            status = "weak cluster"
        else:
            status = "orphan topic"

        for page in pages:
            page["cluster_label"] = label
            page["cluster_status"] = status

    return grouped


def build_link_maps(edges, urlset):
    inbound = defaultdict(set)
    outbound = defaultdict(set)

    for edge in edges:
        source = edge["from"]
        target = edge["to"]

        if source in urlset and target in urlset and source != target:
            outbound[source].add(target)
            inbound[target].add(source)

    return inbound, outbound


def pagerank(rows, edges, iterations=30, damping=0.85):
    urls = [row["url"] for row in rows]
    urlset = set(urls)
    inbound, outbound = build_link_maps(edges, urlset)

    page_count = len(urls)

    if not page_count:
        return {}

    scores = {url: 1 / page_count for url in urls}

    for _ in range(iterations):
        new_scores = {url: (1 - damping) / page_count for url in urls}

        for url in urls:
            targets = list(outbound.get(url, []))

            if targets:
                share = scores[url] / len(targets)

                for target in targets:
                    new_scores[target] += damping * share
            else:
                share = scores[url] / page_count

                for target in urls:
                    new_scores[target] += damping * share

        scores = new_scores

    return scores


def build_html(summary, domain):
    cards = ""

    for cluster in summary["clusters"]:
        cards += '<section class="cluster">'
        cards += f'<h2>{html.escape(cluster["label"])}</h2>'
        cards += (
            f'<div class="meta">{cluster["pages"]} pages · '
            f'{html.escape(cluster["status"])} · '
            f'authority {cluster["internal_authority"]:.3f}</div>'
        )

        for page in cluster["top_pages"]:
            path = page["url"].replace(domain, "") or "/"

            cards += '<div class="page">'
            cards += (
                f'<a href="{html.escape(page["url"])}" target="_blank">'
                f"{html.escape(path)}</a>"
            )
            cards += f'<small>{html.escape(page["title"][:120])}</small>'
            cards += (
                f'<small>PR {page["pagerank"]:.4f} · '
                f'in {page["inbound_links"]} · out {page["outbound_links"]}</small>'
            )
            cards += "</div>"

        cards += "</section>"

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
<p>Local embeddings + clusters + PageRank + real internal link graph.</p>
</header>
<div class="grid">
{cards}
</div>
</body>
</html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as file:
        file.write(doc)


def save(rows, edges, grouped, domain):
    urlset = {row["url"] for row in rows}
    inbound, outbound = build_link_maps(edges, urlset)
    scores = pagerank(rows, edges)

    clean_edges = []

    for edge in edges:
        if edge["from"] in urlset and edge["to"] in urlset and edge["from"] != edge["to"]:
            clean_edges.append(edge)

    for row in rows:
        url = row["url"]
        row["pagerank"] = scores.get(url, 0)
        row["inbound_links"] = len(inbound.get(url, set()))
        row["outbound_links"] = len(outbound.get(url, set()))

    public_rows = []

    for row in rows:
        item = dict(row)
        item.pop("text_for_embedding", None)
        public_rows.append(item)

    fields = sorted(set().union(*(row.keys() for row in public_rows)))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(public_rows)

    cluster_summary = []

    for cluster_id, pages in grouped.items():
        total_pagerank = sum(page.get("pagerank", 0) for page in pages)

        top_pages = sorted(
            [
                {
                    "url": page["url"],
                    "title": page["title"],
                    "pagerank": page["pagerank"],
                    "inbound_links": page["inbound_links"],
                    "outbound_links": page["outbound_links"],
                }
                for page in pages
            ],
            key=lambda item: item["pagerank"],
            reverse=True,
        )[:10]

        cluster_summary.append(
            {
                "cluster": int(cluster_id),
                "label": pages[0]["cluster_label"],
                "pages": len(pages),
                "status": pages[0]["cluster_status"],
                "internal_authority": total_pagerank,
                "top_pages": top_pages,
            }
        )

    cluster_summary = sorted(
        cluster_summary, key=lambda item: item["internal_authority"], reverse=True
    )

    diagnosis = []

    for cluster in cluster_summary:
        if cluster["status"] == "orphan topic":
            diagnosis.append(f"Orphan topic: {cluster['label']}")
        elif cluster["status"] == "weak cluster":
            diagnosis.append(f"Weak cluster: {cluster['label']}")

    url_to_cluster = {row["url"]: row["cluster_label"] for row in rows}
    cluster_links = defaultdict(int)

    for edge in clean_edges:
        source_cluster = url_to_cluster.get(edge["from"])
        target_cluster = url_to_cluster.get(edge["to"])

        if source_cluster and target_cluster and source_cluster != target_cluster:
            cluster_links[(source_cluster, target_cluster)] += 1

    cluster_links_out = [
        {"from": source, "to": target, "links": count}
        for (source, target), count in sorted(
            cluster_links.items(), key=lambda item: item[1], reverse=True
        )
    ]

    summary = {
        "domain": domain,
        "pages": len(rows),
        "edges_count": len(clean_edges),
        "edges": clean_edges,
        "clusters": cluster_summary,
        "cluster_links": cluster_links_out,
        "diagnosis": diagnosis,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, ensure_ascii=False)

    build_html(summary, domain)

    print("\nDONE")
    print("CSV:", OUT_CSV)
    print("JSON:", OUT_JSON)
    print("HTML:", OUT_HTML)

    print("\nCLUSTERS:")
    for cluster in cluster_summary:
        print(
            f"- {cluster['label']}: {cluster['pages']} pages — "
            f"{cluster['status']} — authority {cluster['internal_authority']:.3f}"
        )

    print("\nDIAGNOSIS:")
    for item in diagnosis:
        print("-", item)


def parse_args():
    parser = argparse.ArgumentParser(description="Site Architecture MRI")
    parser.add_argument("domain", help="Website URL, e.g. https://example.com")
    parser.add_argument("--clusters", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    return parser.parse_args()


def main():
    args = parse_args()

    domain = get_domain(args.domain.rstrip("/"))

    rows, edges = crawl(domain, max_pages=args.max_pages)

    if not rows:
        print("No pages found")
        return

    grouped = cluster_pages(rows, args.clusters)
    save(rows, edges, grouped, domain)


if __name__ == "__main__":
    main()
