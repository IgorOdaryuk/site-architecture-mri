import csv
import json
from collections import defaultdict
from pathlib import Path

PAGES_CSV = Path("architecture_pages.csv")
SUMMARY_JSON = Path("architecture_summary.json")
OUTPUT = Path("linking_diagnosis.md")


MONEY_WORDS = [
    "service",
    "services",
    "repair",
    "seo",
    "lsa",
    "ai-citation",
    "lead",
    "leads",
    "automation",
    "visibility",
    "map-pack",
    "cannibalization",
]


def is_money_page(url):
    u = url.lower()
    return any(word in u for word in MONEY_WORDS)


def make_anchor_ideas(url):
    slug = url.rstrip("/").split("/")[-1]
    phrase = slug.replace("-", " ")

    return [
        phrase,
        f"{phrase} strategy",
        f"{phrase} service",
    ]


def load_pages():
    if not PAGES_CSV.exists():
        raise FileNotFoundError("architecture_pages.csv not found. Run architecture_engine.py first.")

    with PAGES_CSV.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_summary():
    if not SUMMARY_JSON.exists():
        raise FileNotFoundError("architecture_summary.json not found. Run architecture_engine.py first.")

    with SUMMARY_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def to_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def build_cluster_lookup(summary):
    cluster_lookup = {}

    for cluster in summary.get("clusters", []):
        label = cluster.get("label", "")
        status = cluster.get("status", "")
        authority = cluster.get("internal_authority", 0)

        for page in cluster.get("top_pages", []):
            cluster_lookup[page.get("url")] = {
                "label": label,
                "status": status,
                "authority": authority,
            }

    return cluster_lookup


def find_source_pages(pages, target_page):
    target_url = target_page.get("url", "")
    target_cluster = target_page.get("cluster_label", "")
    target_slug = target_url.rstrip("/").split("/")[-1].replace("-", " ").lower()

    candidates = []

    for page in pages:
        source_url = page.get("url", "")

        if source_url == target_url:
            continue

        score = 0

        source_cluster = page.get("cluster_label", "")
        source_pr = to_float(page.get("pagerank", 0))
        source_title = (page.get("title") or "").lower()
        source_h1 = (page.get("h1") or "").lower()

        if source_cluster and source_cluster == target_cluster:
            score += 50

        if target_slug and target_slug in source_title:
            score += 20

        if target_slug and target_slug in source_h1:
            score += 20

        score += source_pr * 100

        if score > 0:
            candidates.append({
                "url": source_url,
                "score": score,
                "reason": "Relevant cluster/title match or stronger internal authority",
            })

    candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
    return candidates[:5]


def diagnose(pages, summary):
    issues = []

    cluster_lookup = build_cluster_lookup(summary)

    for page in pages:
        url = page.get("url", "")
        depth = to_int(page.get("depth", 0))
        pagerank = to_float(page.get("pagerank", 0))
        cluster_status = page.get("cluster_status", "")
        cluster_label = page.get("cluster_label", "")

        page["cluster_label"] = cluster_label
        page["cluster_status"] = cluster_status

        money_page = is_money_page(url)

        if money_page and pagerank < 0.03:
            issues.append({
                "severity": "high",
                "issue": "Money page has weak internal authority",
                "url": url,
                "pagerank": pagerank,
                "cluster": cluster_label,
                "why": "This looks like a commercial or lead-related page, but internal PageRank is low.",
                "fix": "Add internal links from stronger related pages.",
                "sources": find_source_pages(pages, page),
                "anchors": make_anchor_ideas(url),
            })

        if money_page and depth > 2:
            issues.append({
                "severity": "high",
                "issue": "Money page is too deep",
                "url": url,
                "pagerank": pagerank,
                "cluster": cluster_label,
                "why": "Important commercial pages should be reachable in fewer clicks.",
                "fix": "Link to this page from homepage, services page, or a strong hub page.",
                "sources": find_source_pages(pages, page),
                "anchors": make_anchor_ideas(url),
            })

        if cluster_status in ["orphan topic", "weak cluster"]:
            issues.append({
                "severity": "medium",
                "issue": f"{cluster_status.title()} needs support",
                "url": url,
                "pagerank": pagerank,
                "cluster": cluster_label,
                "why": "This page belongs to a topic area without enough supporting pages or internal structure.",
                "fix": "Create supporting pages and link them back to this URL.",
                "sources": find_source_pages(pages, page),
                "anchors": make_anchor_ideas(url),
            })

    return issues


def write_report(issues):
    lines = []
    lines.append("# Linking Diagnosis Report")
    lines.append("")
    lines.append("This report shows exact URLs where internal linking should be improved.")
    lines.append("")

    if not issues:
        lines.append("No linking issues found.")
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
        return

    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues = sorted(issues, key=lambda x: (severity_order.get(x["severity"], 9), x["pagerank"]))

    for i, item in enumerate(issues, 1):
        lines.append(f"## {i}. {item['issue']}")
        lines.append("")
        lines.append(f"- Severity: **{item['severity']}**")
        lines.append(f"- Target URL: {item['url']}")
        lines.append(f"- Cluster: {item['cluster']}")
        lines.append(f"- PageRank: {item['pagerank']:.4f}")
        lines.append("")
        lines.append(f"**Why it matters:** {item['why']}")
        lines.append("")
        lines.append(f"**What to fix:** {item['fix']}")
        lines.append("")

        lines.append("**Add internal links from:**")
        if item["sources"]:
            for source in item["sources"]:
                lines.append(f"- {source['url']}")
        else:
            lines.append("- No strong source page found. Review manually.")
        lines.append("")

        lines.append("**Anchor ideas:**")
        for anchor in item["anchors"]:
            lines.append(f"- {anchor}")

        lines.append("")
        lines.append("---")
        lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    pages = load_pages()
    summary = load_summary()

    issues = diagnose(pages, summary)
    write_report(issues)

    print("DONE")
    print("Output:", OUTPUT)


if __name__ == "__main__":
    main()
    