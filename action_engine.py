import json
from pathlib import Path

INPUT = Path("architecture_summary.json")
OUTPUT = Path("site_actions.md")


def load_summary():
    if not INPUT.exists():
        raise FileNotFoundError(
            "architecture_summary.json not found. Run architecture_engine.py first."
        )

    with INPUT.open("r", encoding="utf-8") as f:
        return json.load(f)


def priority_score(cluster):
    pages = cluster.get("pages", 0)
    authority = cluster.get("internal_authority", 0)

    if pages == 1:
        return 100 + authority
    if pages == 2:
        return 70 + authority
    if pages >= 3 and authority < 0.1:
        return 40 + authority

    return 10 + authority


def action_for_cluster(cluster):
    label = cluster.get("label", "Unknown cluster")
    pages = cluster.get("pages", 0)
    status = cluster.get("status", "")

    if status == "orphan topic":
        return (
            f"Turn **{label}** from a single-page topic into a real cluster. "
            "Add 2 supporting articles and link them back to the main page."
        )

    if status == "weak cluster":
        return (
            f"Strengthen **{label}**. It has only 2 pages. "
            "Add 1–2 supporting pages and create clear internal links between them."
        )

    if pages >= 3:
        return (
            f"Keep **{label}** as a core cluster. Review whether it links clearly "
            "to the main service or conversion page."
        )

    return f"Review **{label}** manually."


def main():
    summary = load_summary()

    clusters = summary.get("clusters", [])
    clusters = sorted(clusters, key=priority_score, reverse=True)

    lines = []
    lines.append(f"# Site Action Report: {summary.get('domain', '')}")
    lines.append("")
    lines.append("## Priority actions")
    lines.append("")

    for i, cluster in enumerate(clusters, 1):
        label = cluster.get("label", "Unknown cluster")
        pages = cluster.get("pages", 0)
        status = cluster.get("status", "")
        authority = cluster.get("internal_authority", 0)

        lines.append(f"### {i}. {label}")
        lines.append("")
        lines.append(f"- Status: **{status}**")
        lines.append(f"- Pages: **{pages}**")
        lines.append(f"- Internal authority: **{authority:.3f}**")
        lines.append(f"- Action: {action_for_cluster(cluster)}")
        lines.append("")

    lines.append("## What not to do first")
    lines.append("")
    lines.append(
        "- Do not start with meta descriptions before fixing weak or orphan clusters."
    )
    lines.append(
        "- Do not publish random new posts unless they strengthen a target cluster."
    )
    lines.append(
        "- Do not treat all pages equally. Fix architecture before polishing details."
    )
    lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")

    print("DONE")
    print("Output:", OUTPUT)


if __name__ == "__main__":
    main()
