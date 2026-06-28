import csv
import json
from collections import defaultdict
from pathlib import Path

PAGES_CSV = Path("architecture_pages.csv")
SUMMARY_JSON = Path("architecture_summary.json")
OUTPUT = Path("linking_diagnosis.md")

MONEY_WORDS = [
    "service", "services", "repair", "seo", "lsa", "lead", "leads",
    "automation", "visibility", "map-pack", "cannibalization"
]


def to_float(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def is_money_page(url):
    url = url.lower()
    return any(word in url for word in MONEY_WORDS) and "/blog/" not in url


def anchor_ideas(url):
    slug = url.rstrip("/").split("/")[-1]
    phrase = slug.replace("-", " ")
    return [phrase, f"{phrase} service", f"{phrase} strategy"]


def load_pages():
    with PAGES_CSV.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_summary():
    with SUMMARY_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_link_maps(edges):
    inbound = defaultdict(set)
    outbound = defaultdict(set)

    for edge in edges:
        src = edge.get("from")
        dst = edge.get("to")

        if not src or not dst or src == dst:
            continue

        outbound[src].add(dst)
        inbound[dst].add(src)

    return inbound, outbound


def recommend_sources(target, pages, inbound):
    target_url = target["url"]
    target_cluster = target.get("cluster_label", "")
    existing_sources = inbound.get(target_url, set())

    candidates = []

    for page in pages:
        src = page["url"]

        if src == target_url or src in existing_sources:
            continue

        score = 0
        reasons = []

        if page.get("cluster_label") == target_cluster:
            score += 50
            reasons.append("same cluster")

        pr = to_float(page.get("pagerank", 0))
        score += pr * 100

        if "/blog/" not in src:
            score += 20
            reasons.append("hub/service page")

        if src.rstrip("/").endswith("/services"):
            score += 30
            reasons.append("main services hub")

        if score > 5:
            candidates.append({
                "url": src,
                "score": score,
                "reason": ", ".join(reasons) or "higher internal authority"
            })

    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:5]


def diagnose(pages, summary):
    edges = summary.get("edges", [])
    inbound, outbound = build_link_maps(edges)

    issues = []

    for page in pages:
        url = page["url"]
        pr = to_float(page.get("pagerank", 0))
        in_count = len(inbound.get(url, set()))
        out_count = len(outbound.get(url, set()))
        cluster_status = page.get("cluster_status", "")
        cluster = page.get("cluster_label", "")

        money = is_money_page(url)

        if money and in_count < 5:
            issues.append({
                "severity": "high",
                "issue": "Commercial page has too few internal links",
                "url": url,
                "cluster": cluster,
                "pagerank": pr,
                "inbound": in_count,
                "outbound": out_count,
                "why": "This page looks like a service or lead page, but too few internal pages point to it.",
                "fix": "Add internal links from relevant hub, service, and related article pages.",
                "sources": recommend_sources(page, pages, inbound),
                "anchors": anchor_ideas(url),
            })

        if money and pr < 0.04:
            issues.append({
                "severity": "high",
                "issue": "Commercial page has weak internal authority",
                "url": url,
                "cluster": cluster,
                "pagerank": pr,
                "inbound": in_count,
                "outbound": out_count,
                "why": "This page may be important for leads, but internal PageRank is low.",
                "fix": "Link to it from stronger pages with higher internal authority.",
                "sources": recommend_sources(page, pages, inbound),
                "anchors": anchor_ideas(url),
            })

        if cluster_status in ["orphan topic", "weak cluster"] and in_count < 5:
            issues.append({
                "severity": "medium",
                "issue": f"{cluster_status.title()} has weak support",
                "url": url,
                "cluster": cluster,
                "pagerank": pr,
                "inbound": in_count,
                "outbound": out_count,
                "why": "This topic has weak architecture support.",
                "fix": "Add supporting pages and internal links.",
                "sources": recommend_sources(page, pages, inbound),
                "anchors": anchor_ideas(url),
            })

    return issues


def write_report(issues):
    order = {"high": 0, "medium": 1, "low": 2}
    issues = sorted(
        issues,
        key=lambda x: (order.get(x["severity"], 9), x["inbound"], x["pagerank"])
    )

    lines = ["# Linking Diagnosis Report", ""]

    if not issues:
        lines.append("No major linking issues found.")
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
        return

    for i, item in enumerate(issues, 1):
        lines.append(f"## {i}. {item['issue']}")
        lines.append("")
        lines.append(f"- Severity: **{item['severity']}**")
        lines.append(f"- Target URL: {item['url']}")
        lines.append(f"- Cluster: {item['cluster']}")
        lines.append(f"- Current inbound links: **{item['inbound']}**")
        lines.append(f"- Current outbound links: **{item['outbound']}**")
        lines.append(f"- PageRank: **{item['pagerank']:.4f}**")
        lines.append("")
        lines.append(f"**Why it matters:** {item['why']}")
        lines.append("")
        lines.append(f"**What to fix:** {item['fix']}")
        lines.append("")
        lines.append("**Add links from:**")

        if item["sources"]:
            for source in item["sources"]:
                lines.append(f"- {source['url']} — {source['reason']}")
        else:
            lines.append("- No clear source found. Review manually.")

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
