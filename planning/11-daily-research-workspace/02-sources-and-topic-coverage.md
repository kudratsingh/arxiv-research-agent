# Sources and topic coverage

Research checked **2026-11-02**. This is a proposed ingestion and topic design
for a personal, local-first daily briefing and guided deep-dive workspace.
Paid services remain a separate decision. A selectable interest and a connected
source are different objects: the application must show which interests it
can currently monitor, from which sources, and how recently it checked them.

## Source strategy

Start with **arXiv, a small user-approved list of primary-source feeds, and
manual URL/DOI/arXiv import**. Add broad scholarly metadata through OpenAlex
within its verified free allowance once its adapter is ready. Other adapters
extend coverage after the first daily workflow works. Avoid a feed assembled
only from high-volume ML preprints: the user's work also needs implementations,
datasets, official system reports, corrections, and explanatory material.

Keep six content classes distinct in the interface and data model:

| Class | What it supplies | What the user should see |
|---|---|---|
| Scholarly work | Paper, preprint, review or technical report | Publication status, version, venue, source access and cited evidence |
| Official announcement | Lab/company/research-institution article | Who is making the claim; linked paper/code; reported versus independently supported results |
| Independent reporting | Journalism and reporting | Publisher/byline/date; primary links; reporting remains separate from paper evidence |
| Implementation | Repository or software release | Repository identity, commit/release, license, maintenance signals, relation to a paper |
| Model or dataset | Artifact release | Version, model/dataset card, license, access restrictions and related work |
| Learning resource | Tutorial, lecture, documentation or course | Prerequisites, depth, source and reason it helps with a current research question |

An announcement, paper, model release and implementation may describe one
development. Cluster them into one briefing story while retaining their
separate identities and claims. User-facing clusters can say “paper + code +
release notes”; they must not imply three independent confirmations.

## Concrete starter sources

[`11-source-starters.json`](11-source-starters.json) supplies ten disabled
source options, including **eight feed endpoints confirmed by HTTP response
and a feed-root prefix** on 2026-11-02:

| Starter | Confirmed feed |
|---|---|
| arXiv Machine Learning | `https://rss.arxiv.org/rss/cs.LG` |
| arXiv Artificial Intelligence | `https://rss.arxiv.org/rss/cs.AI` |
| arXiv Computation and Language | `https://rss.arxiv.org/rss/cs.CL` |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml` |
| OpenAI News | `https://openai.com/news/rss.xml` |
| Google Research Blog | `https://research.google/blog/rss/` |
| Nature journal feed | `https://www.nature.com/nature.rss` |
| Google AI Blog | `https://blog.google/technology/ai/rss/` |

The Google DeepMind candidate returned HTTP 200 and XML content type, but its
feed root was not confirmed in the bounded prefix; it remains a manual website
option. Anthropic News is also a manual website option, with no invented RSS
address. The file records the response status, content type, date, read bound
and verification limit. These were small endpoint checks, not complete feed
parses or article/PDF imports.

Every source is **disabled by default**, metadata/link-out only, with automatic
full-text fetch off. The owner chooses the initial source subset with their
interests. Re-check endpoints during adapter implementation, show a backfill
preview before importing feed history, and keep the arXiv category feeds on
one shared rate governor. Feed availability does not establish permission to
republish a publisher's article content.

## Source adapter decisions

The factual access notes below are current-source observations, not service
availability promises. Re-check access and terms when implementing an adapter.
Store an adapter version, verification date and deployment quota policy.

| Source | Role and proposed stage | Access and content boundary | Implementation decision |
|---|---|---|---|
| **arXiv API and category RSS/Atom** | First daily paper source; reuse current search/PDF tooling | arXiv metadata is CC0; article redistribution depends on each article's license. Official feeds cover active arXiv subject areas. Legacy APIs require one request every three seconds and one connection at a time. [API terms](https://info.arxiv.org/help/api/tou.html), [feeds](https://info.arxiv.org/help/rss.html) | One shared per-host request governor across search, feed and PDF work; cache metadata, preserve all categories and arXiv versions. arXiv is a preprint repository, not a complete index of all disciplines |
| **Approved RSS/Atom feeds** | First source for official research announcements and selected science reporting | RSS provides item identity and feed metadata; it does not grant a license to republish the linked article. [RSS specification](https://www.rssboard.org/rss-specification), [GUID guidance](https://www.rssboard.org/rss-profile) | User approves actual URLs and publisher scope. Begin with manually verified lab/institution feeds. Sanitize feed HTML; conditional GET; respect TTL/cache headers; store links and permitted excerpts |
| **Manual URL, DOI, arXiv ID** | First source for “read this with me” | Retrieval success and reuse permission vary by source | Show the fetched material before a deep dive; unsupported/paywalled URL becomes a saved link or metadata item, never a fabricated full-text summary |
| **OpenAlex** | Broad scholarly discovery and topic dictionaries; optional early adapter | Current docs expose four domains, 26 fields, 252 subfields and about 4,500 topics; topic assignments are inferred. A verified free key has a $1/day usage allowance; anonymous use shares a smaller network allowance and cursor paging requires a key. [Topics](https://help.openalex.org/data/topics/), [authentication](https://help.openalex.org/api/authentication/), [pricing](https://help.openalex.org/access/pricing/) | Import a versioned taxonomy dictionary; cache targeted metadata queries. Prefer bearer auth to putting keys in logged URLs. No prepaid balance or paid plan by default. Stop at free-quota exhaustion and show stale coverage. A result's abstract/full-text access is a separate field |
| **Crossref** | DOI reconciliation, publication metadata, updates and license links | Public/polite access requires no subscription; the polite pool uses contact identification. Quota/concurrency headers should govern the client. Metadata includes abstracts, but some abstracts have copyright restrictions. [REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api), [access](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication) | Enrich and resolve DOI records rather than poll the entire corpus. Preserve updated metadata as observations. Treat correction/retraction relations as first-class events |
| **PubMed and PMC** | Biomedical coverage after the core workflow | E-utilities permits 3 requests/second without a key and 10 with a key. PubMed metadata is distinct from full text. PMC permits automated article retrieval only through designated services and article license terms vary. [NCBI limits](https://support.nlm.nih.gov/kbArticle/?pn=KA-05317), [PMC developer services](https://pmc.ncbi.nlm.nih.gov/tools/developers/), [OA subset](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/) | Use ESearch/EFetch/ELink in bounded batches. Prefer sanctioned OA structured text. Track PMID, PMCID and DOI separately; never infer “full text allowed” from inclusion in PubMed/PMC alone |
| **GitHub** | Follow selected implementations/releases, then paper-code enrichment | Unauthenticated REST access is normally 60 requests/hour; authenticated user access normally 5,000/hour, with separate search/secondary limits. [GitHub limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) | Start with a bounded list of user-followed repositories. Read rate headers, use conditional requests and release IDs. Stars are a discovery signal; store license and a pinned commit before making reproducibility claims |
| **Hugging Face Hub and Papers** | Model/dataset/research-release enrichment | Official Hub documentation links current API endpoints and SDKs. Hub APIs, file resolution and pages have distinct quota buckets; quotas can change. Official CLI documentation includes paper discovery. [Hub API](https://huggingface.co/docs/hub/en/api), [limits](https://huggingface.co/docs/hub/main/rate-limits), [Papers CLI](https://github.com/huggingface/huggingface_hub/blob/main/docs/source/en/guides/cli.md) | Use the documented API/SDK; do not scrape dynamic pages as the primary adapter. Community interest is separate from evidence quality. Capture model/dataset IDs, revision, license and gating |
| **Semantic Scholar** | Optional citation-graph enrichment; reuse existing adapter | Scholarly graph metadata and paper references. Verify the actual grant and current limits through the official developer page; availability can be throttled. [Developer portal](https://www.semanticscholar.org/product/api) | Best-effort enrichment, not a dependency for a daily digest to finish. Do not guess article reuse rights from a graph API result |

OpenAlex's current pricing/access pages were updated in October 2026. Old
tutorials advertising an unconditional 100,000 requests/day are not a safe
implementation basis. The public metadata probe used for this kit returned
all 26 field labels/IDs and reported a small debit against the free anonymous
allowance; it did not create an account, buy credits or obtain a key.

Optional later candidates include conference proceedings/OpenReview, domain
repositories such as bioRxiv, DataCite datasets, standards bodies, and selected
government/university news. Each needs its own source review before activation.
A global news-search subscription or generalized web crawler is unnecessary
for the first useful version.

## Topic selection that can grow

Use three layers rather than forcing the user's interests into one tree:

1. **Broad scholarly backbone.** Import OpenAlex domains, fields, subfields and
   topics with stable external IDs and a snapshot version. This gives broad
   discoverability across sciences, engineering, health, social studies,
   humanities and arts. Preserve unclassified works and source-specific
   categories alongside these assignments.
2. **Product study tracks.** Authored ML tracks distinguish practical research
   concerns that broad scholarly labels obscure: post-training, reasoning,
   agents, retrieval, inference systems, robustness, scientific ML and so on.
   They are navigation/query aids, not an official classification.
3. **Personal interests.** The user can follow a free-text question, author,
   lab, venue, method, model, repository or project. Positive and excluded
   terms, examples, source scope, depth and cadence make it actionable.

The supplied `07-topic-seed.json` contains **384 nodes**, including all **26
verified OpenAlex field anchors**, authored study areas and **96 ML leaf
topics**. It is an initial product navigation seed. Fine-grained OpenAlex IDs
have deliberately not been invented for authored children. Implement the
dictionary import and reviewed many-to-many crosswalk before presenting these
as mapped scholarly filters. Support custom interests from the first version.

The picker should offer search, aliases, parent expansion, “follow core”,
“explore adjacent” and exclusions. Do not auto-subscribe to every child of a
large field without an item budget. Allow the user to inspect/edit the query
and examples behind a track. External topic classifications are fallible and
change; keep the classification model/snapshot version where available.

### Coverage is visible

Every chosen interest should show:

- connected sources and the last successful check;
- configured lookback/window and whether publication or ingestion time is used;
- current access: metadata, abstract, excerpts or full text;
- whether a query was truncated, rate-limited, stale or partially unavailable;
- language/source restrictions and a way to add a missing source;
- “no new items found” separately from “sources could not be checked”.

The app can offer every field in its picker before every field has a
specialized connector. It must label limited monitoring honestly. “All topics
selectable” does not mean “all literature monitored”, and “paper discovered”
does not mean “paper read”.

## Identity and update rules

Store a canonical work plus source observations and versions:

| Object | Identity rule |
|---|---|
| Scholarly work | Internal immutable ID; normalized DOI/arXiv/PMID/OpenAlex identifiers are external keys with provenance |
| arXiv version | Base ID and version kept separately; revised preprint is an update to the work, not automatically a new discovery |
| Journal publication | Link to a preprint only on reliable identifiers or an explicit reviewed relation; never merge on title similarity alone |
| Web article | Canonical publisher URL plus feed GUID/source ID; retain observed URL and retrieval hash |
| Code/model/data release | Repository/artifact ID plus release/commit/revision; relation to paper carries evidence URL and confidence |
| Story cluster | A reversible group of related observations; original items remain accessible |
| Correction/retraction | Dated event linked to affected work/version; an alert can supersede an earlier briefing |

Keep `published_at`, `updated_at`, `first_seen_at`, `fetched_at`, timezone and
source precision separately. “New today” should normally mean first seen
since the user's last successful digest, with publication date displayed.
Late index arrivals must be eligible for a clearly marked catch-up item.

Deduplicate DOI/arXiv exact matches first. Use normalized title/authors/year
only to suggest a merge requiring strong evidence or review. Syndicated news
and papers about the same topic are related, not identical.

## Acceptance checks for the source layer

Use fixtures and mocked network responses before enabling a connector:

- One paper appearing in arXiv, OpenAlex, Crossref and a feed yields one work,
  four observations and one digest story.
- A new arXiv version produces an update with a change description rather
  than an unexplained duplicate alert.
- A rate-limited source does not advance its successful watermark or claim
  zero results; replaying a run does not duplicate notifications.
- An abstract-only item cannot produce a full-text label or unsupported
  section/page citations.
- A source failure does not block the remaining digest; the coverage notice
  names what is missing.
- URL imports and redirects cannot reach loopback/private/link-local hosts;
  fetched pages, feeds and PDFs remain untrusted data with size/time bounds.
- A taxonomy update does not silently change saved interests; mappings migrate
  with lineage and a preview when membership changes materially.
- A correction/retraction or withdrawn source updates affected saved briefings
  through a visible supersession event.

The source catalogue, ranking features and final summary evidence should be
inspectable separately. Popularity, provider prestige and novelty help choose
what to read; they cannot substitute for checking what a source supports.
