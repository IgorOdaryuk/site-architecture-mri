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
    """Page URLs from /sitemap.xml, following sitemap indexes one level down.

    WordPress and most SEO plugins publish an index that points at post-,
    page- and category-sitemaps; the index itself lists no pages.
    """
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    def read(url):
        response = requests.get(url, headers=HEADERS, timeout=10)
        return ET.fromstring(response.text)

    urls = []
    try:
        root = read(domain.rstrip("/") + "/sitemap.xml")
        children = [loc.text.strip() for loc in root.findall(".//sm:sitemap/sm:loc", namespace)]
        for child in children:
            try:
                root_child = read(child)
            except Exception as error:
                print("sitemap failed:", child, error)
                continue
            urls += [loc.text.strip() for loc in root_child.findall(".//sm:url/sm:loc", namespace)]
        urls += [loc.text.strip() for loc in root.findall(".//sm:url/sm:loc", namespace)]
    except Exception as error:
        print("sitemap failed:", error)

    out = []
    for raw in urls:
        url = normalize_url(raw)
        if same_domain(url, domain) and not should_skip(url) and not url.endswith(".xml"):
            out.append(url)
    return list(dict.fromkeys(out))


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


STOP = set(
    """
    the and for with this that from your you are have has was were will not but
    how what why when into about our its can all any more most best top new vs
    page home blog post guide www com net org html php https http index
    """.split()
)


def page_phrases(page, site_words=frozenset()):
    """Words and two-word phrases, each built inside ONE title/H1/slug.

    Phrases never cross from one page into the next: gluing a cluster's titles
    into one string is what produced labels like "Calls Found Uncomfortable".
    """
    path = re.sub(r"^https?://[^/]+", "", page["path"] or "")  # older CSVs stored the full URL
    sources = [page["title"], page["h1"], path.replace("-", " ").replace("/", " ")]
    out = []
    for source in sources:
        for part in re.split(r"[|:–—•·()\[\],?!]+| - ", source.lower()):
            words = [
                w for w in re.findall(r"[a-z][a-z0-9']{2,}", part)
                if w not in STOP and w not in site_words
            ]
            out += words
            out += [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
    return out


def site_wide_words(rows, share=0.25):
    """Words on most pages of the site (brand name in every title) say nothing."""
    if len(rows) < 5:
        return frozenset()
    df = Counter()
    for row in rows:
        df.update(set(re.findall(r"[a-z][a-z0-9']{2,}", (row["title"] + " " + row["h1"]).lower())))
    return frozenset(w for w, n in df.items() if n / len(rows) >= share)


def label_clusters(grouped, rows):
    """c-TF-IDF: a term names a cluster when it is frequent there and rare elsewhere."""
    import math

    site_words = site_wide_words(rows)
    tf = {}
    for cid, pages in grouped.items():
        counts = Counter()
        for page in pages:
            # A phrase counts once per page, so one long title cannot dominate.
            counts.update(set(page_phrases(page, site_words)))
        tf[cid] = counts

    across = Counter()
    for counts in tf.values():
        across.update(counts)
    avg_size = sum(sum(c.values()) for c in tf.values()) / max(1, len(tf))

    labels = {}
    for cid, counts in tf.items():
        size = len(grouped[cid])
        scored = []
        for term, n in counts.items():
            if size >= 3 and n < 2:
                continue  # one page's title is not the cluster's topic
            score = (n / size) * math.log(1 + avg_size / across[term])
            if " " in term:
                score *= 1.3  # "bass strings" names a topic better than "strings"
            scored.append((score, term))
        scored.sort(reverse=True)

        chosen = []
        used = set()
        top = scored[0][0] if scored else 0
        for score, term in scored:
            words = set(term.split())
            if words & used:
                continue  # "Stingray Review" after "Musicman Stingray" adds nothing
            if chosen and score < 0.6 * top:
                break  # a weak second word only muddies the name
            chosen.append(term)
            used |= words
            if len(chosen) == 2:
                break
        labels[cid] = " · ".join(t.title() for t in chosen) if chosen else f"Cluster {cid + 1}"
    return labels


# Pages every site has and no topic owns. Clustering them with the content
# pulls /about and /privacy into whatever group is largest and makes the labels
# lie; they are reported as their own group instead.
CHROME_PATTERNS = (
    "about", "contact", "privacy", "terms", "cookie", "legal", "disclaimer", "sitemap",
    "login", "signup", "register", "account", "cart", "checkout", "thank", "careers", "jobs",
    "gallery", "photos", "testimonials", "reviews", "faq", "blog", "news", "search",
)


def is_chrome(path):
    p = path.lower().strip("/")
    if p == "":
        return True  # the home page belongs to the whole site
    last = p.split("/")[-1]
    return any(last == c or last.startswith(c + "-") or last.endswith("-" + c) or p == c
               for c in CHROME_PATTERNS)


def cluster_pages(rows, requested_clusters=None):
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import KMeans

    chrome = [row for row in rows if is_chrome(row["path"])]
    rows = [row for row in rows if not is_chrome(row["path"])]
    for row in chrome:
        row["cluster"] = -1
        row["cluster_label"] = "Site pages (home, about, contact, legal)"
        row["cluster_status"] = "site chrome"
    if len(rows) < 2:
        grouped = defaultdict(list)
        for row in chrome:
            grouped[-1].append(row)
        return grouped

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

    labels_by_cluster = label_clusters(grouped, rows)

    for cluster_id, pages in grouped.items():
        label = labels_by_cluster[cluster_id]

        if len(pages) >= 3:
            status = "strong cluster"
        elif len(pages) == 2:
            status = "weak cluster"
        else:
            status = "orphan topic"

        for page in pages:
            page["cluster_label"] = label
            page["cluster_status"] = status

    if chrome:
        grouped[-1] = chrome
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
    topic_summary = [c for c in cluster_summary if c["cluster"] != -1]

    diagnosis = []

    for cluster in topic_summary:
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

    home = normalize_url(domain.rstrip("/"))
    orphans = [r["url"] for r in rows if r["inbound_links"] == 0 and normalize_url(r["url"]) != home]
    deep = [r["url"] for r in rows if r["depth"] > 3]
    fed = {link["to"] for link in cluster_links_out}
    isolated = [c["label"] for c in cluster_summary if c["label"] not in fed and len(cluster_summary) > 1]
    overview = {
        "total_pages": len(rows),
        "internal_links": len(clean_edges),
        "orphan_pages": len(orphans),
        "orphan_examples": orphans[:10],
        "pages_deeper_than_3_clicks": len(deep),
        "clusters": len(topic_summary),
        "strongest_cluster": topic_summary[0]["label"] if topic_summary else None,
        "weakest_cluster": topic_summary[-1]["label"] if topic_summary else None,
        "clusters_no_links_from_other_clusters": [c for c in isolated if c != "Site pages (home, about, contact, legal)"],
    }

    summary = {
        "domain": domain,
        "overview": overview,
        "clusters": cluster_summary,
        "cluster_links": cluster_links_out,
        "diagnosis": diagnosis,
        "pages": len(rows),
        "edges_count": len(clean_edges),
        "edges": clean_edges,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, ensure_ascii=False)

    build_html(summary, domain)

    print("\nDONE")
    print("CSV:", OUT_CSV)
    print("JSON:", OUT_JSON)
    print("HTML:", OUT_HTML)

    print("\nOVERVIEW:")
    for key, value in overview.items():
        if key != "orphan_examples":
            print(f"- {key}: {value}")

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
