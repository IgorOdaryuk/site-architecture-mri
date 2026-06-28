# Site Architecture MRI

Local SEO architecture analyzer.

## Install

pip install -r requirements.txt

## Run

python3 architecture_engine.py https://example.com --clusters 6

## Output

- architecture_pages.csv
- architecture_summary.json
- architecture_map.html


## Roadmap

### AI Traffic Layer

Future module:

Combine Site Architecture MRI with Google Analytics 4.

Goals:

- Detect traffic from ChatGPT
- Detect traffic from Gemini
- Detect traffic from Perplexity
- Detect traffic from Copilot
- Detect traffic from Claude

For every URL calculate:

- AI Sessions
- Internal PageRank
- Inbound Links
- Cluster
- Page Type
- Revenue Opportunity Score

Example:

URL:
/ai-citation-visibility

AI Sessions: 12

Internal PageRank: Low

Inbound Links: 3

Recommendation:

Increase internal authority by adding links from:

- /services
- /blog
- related topical pages

Long-term vision:

Site Architecture MRI should prioritize pages that already receive AI traffic and estimate the business impact of improving their internal architecture.
