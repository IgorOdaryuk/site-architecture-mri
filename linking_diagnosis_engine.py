class LinkingDiagnosisEngine:
    def __init__(self, pages):
        self.pages = pages

    def run(self):
        issues = []

        for page in self.pages:
            url = page.get("url", "")
            inbound_links = page.get("inbound_links", 0)
            depth = page.get("depth", 0)
            pagerank = page.get("pagerank", 0)

            is_money_page = self.is_money_page(url)

            if is_money_page and inbound_links < 3:
                issues.append({
                    "severity": "high",
                    "issue": "Weak internal linking on money page",
                    "url": url,
                    "why_it_matters": "This page may generate leads, but it receives too few internal links.",
                    "what_to_fix": "Add more internal links from relevant service, location, and blog pages.",
                    "anchor_ideas": self.anchor_ideas(url)
                })

            if is_money_page and depth > 3:
                issues.append({
                    "severity": "high",
                    "issue": "Money page is too deep",
                    "url": url,
                    "why_it_matters": "Important commercial pages should be reachable in fewer clicks.",
                    "what_to_fix": "Link to this page from homepage, main service hub, or location pages.",
                    "anchor_ideas": self.anchor_ideas(url)
                })

            if is_money_page and pagerank < 0.01:
                issues.append({
                    "severity": "medium",
                    "issue": "Low internal authority",
                    "url": url,
                    "why_it_matters": "The site is not passing enough internal authority to this page.",
                    "what_to_fix": "Add links from high-authority pages inside the site.",
                    "anchor_ideas": self.anchor_ideas(url)
                })

        return issues

    def is_money_page(self, url):
        money_words = [
            "repair", "service", "installation", "pricing",
            "location", "city", "near-me", "emergency"
        ]
        return any(word in url.lower() for word in money_words)

    def anchor_ideas(self, url):
        clean = url.strip("/").split("/")[-1]
        phrase = clean.replace("-", " ")
        return [
            phrase,
            f"{phrase} service",
            f"professional {phrase}"
        ]