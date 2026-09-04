# Site Architecture MRI

Crawls a website, groups its pages into topic clusters with local sentence embeddings, computes internal PageRank from the real link graph, and turns that into two plain-English reports: which topics are structurally weak, and which commercial pages are starved of internal links and where to link them from.

Built for local-SEO sites where the question is not "is this page optimised" but "does the architecture support the pages that make money". Everything runs locally; no API keys.

## What it does

1. **Crawl** — seeds from `sitemap.xml` (falls back to the homepage), follows internal links up to `--max-pages` (default 300), skips admin, tag, category, author and media URLs. Per page: status, depth, title, H1, H2 count, word count, outbound links.
2. **Cluster** — embeds title + H1 + H2s + first 6,000 characters with `all-MiniLM-L6-v2` (sentence-transformers, runs on CPU), then KMeans. Cluster count defaults to √pages clamped to 2..8, or `--clusters N`. Each cluster gets an auto label from its most frequent title/H1 phrases and a status: **strong cluster** (3+ pages), **weak cluster** (2), **orphan topic** (1).
3. **Link graph** — inbound and outbound counts per page, PageRank over internal links (damping 0.85, 30 iterations), cluster-to-cluster link counts.
4. **Report** — priority actions per cluster and a linking diagnosis for money pages with concrete source pages and anchor ideas.

## Install

```bash
pip install -r requirements.txt
```

Dependencies: `requests`, `beautifulsoup4`, `sentence-transformers`, `scikit-learn`. The embedding model (~90 MB) downloads on first run.

## Run

```bash
# 1. crawl + cluster + PageRank
python3 architecture_engine.py https://example.com --clusters 6 --max-pages 300

# 2. priority actions per cluster
python3 action_engine.py

# 3. internal-linking diagnosis for money pages
python3 linking_report.py
```

## Output

| File | Produced by | Contents |
|---|---|---|
| `architecture_pages.csv` | `architecture_engine.py` | One row per page: url, depth, status, title, h1, h2_count, word_count, cluster, cluster_label, cluster_status, pagerank, inbound_links, outbound_links |
| `architecture_summary.json` | `architecture_engine.py` | Clusters with top pages by PageRank, full internal edge list, cluster-to-cluster link counts, diagnosis lines |
| `architecture_map.html` | `architecture_engine.py` | Static dark-theme map: one card per cluster with its pages, PageRank and link counts |
| `site_actions.md` | `action_engine.py` | Clusters sorted by priority (orphans first, then weak, then low-authority strong) with one action each |
| `linking_diagnosis.md` | `linking_report.py` | Per money page: severity, inbound/outbound, PageRank, why it matters, top 5 source pages to link from, anchor ideas |

The CSV, JSON and HTML are gitignored. The two Markdown reports in this repo are a real run against [odariuk.com](https://odariuk.com) (19 pages, 201 internal edges) and show what the output looks like.

### Example: `site_actions.md`

```
# Site Action Report: https://odariuk.com

## Priority actions

### 1. Gets / Impressions Months Templated / Months Templated Seo
- Status: orphan topic
- Pages: 1
- Internal authority: 0.020
- Action: Turn it from a single-page topic into a real cluster. Add 2 supporting articles and link them back to the main page.

### 3. Lsa Credits Recovered / Credits Recovered One / Recovered One Cycle
- Status: weak cluster
- Pages: 2
- Internal authority: 0.108
- Action: Strengthen it. Add 1–2 supporting pages and create clear internal links between them.

### 5. Rankings / Backlinks / Seo Automation
- Status: strong cluster
- Pages: 10
- Internal authority: 0.601
- Action: Keep as a core cluster. Review whether it links clearly to the main service or conversion page.
```

### Example: `linking_diagnosis.md`

```
## 1. Orphan Topic has weak support
- Severity: medium
- Target URL: https://odariuk.com/blog/lsa-conversion-problem-not-leads
- Current inbound links: 3 · outbound: 11 · PageRank: 0.0169

Add links from:
- https://odariuk.com/services — hub/service page, main services hub
- https://odariuk.com/ai-citation-visibility — hub/service page
- https://odariuk.com/lsa-lead-recovery — hub/service page

Anchor ideas:
- lsa conversion problem not leads
- lsa conversion problem not leads service
```

## Tuning for your site

- **Money pages.** `linking_report.py` treats a URL as commercial when it contains one of `MONEY_WORDS` (`service`, `repair`, `seo`, `lsa`, `lead`, ...) and is not under `/blog/`. Edit that list for your vertical. `linking_diagnosis_engine.py` is the same logic as an importable class with a home-services word list (`repair`, `installation`, `pricing`, `location`, `near-me`, `emergency`).
- **Thresholds.** A money page is flagged when it has fewer than 5 inbound links or PageRank below 0.04. Orphan and weak clusters are flagged below 5 inbound links.
- **Cluster labels.** `label_cluster()` has a stop-word list; add your brand and boilerplate words there so labels describe topics, not navigation.
- **Crawl scope.** `EXCLUDE` in `architecture_engine.py` lists path fragments to skip; `DELAY` is the per-request pause (0.05 s).

## Limits

- Embeddings are English-only in practice (`all-MiniLM-L6-v2`); word counts also assume Latin script.
- KMeans needs a cluster count; the default heuristic is a starting point, not a truth. Re-run with `--clusters` and compare.
- PageRank is computed over crawled pages only. Pages beyond `--max-pages` or blocked by `EXCLUDE` do not exist to the graph.
- Redirect chains are followed by `requests`; the final URL is not recorded separately.

## License

MIT
