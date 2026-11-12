# ADR-002: Build a rider-facing product on the pipeline

- **Status:** Accepted
- **Date:** 2026-11-11
- **Scope:** What the project is, who it is for, and what was cut to make room
- **Supersedes:** the v1 "Ghost Bus Tracker" spec and its week-4 streaming plan; the part of ADR-001 decision 1 that adds Swiftly as a streaming source

## Context

The first version of this project was a data platform: archive Metro's feeds, classify trips, publish a dashboard and a dataset, and add a Kafka-compatible stream in week 4. A repo was started for it (`la-ghost-bus`) and then scrapped. This repo starts clean; nothing from that one carries over except the ideas listed below.

Two things changed.

1. **The target changed.** The owner is aiming at Summer 2027 software engineering internships at startups and mid-size companies, with data engineering as his specialty. Data engineering internships are far rarer than software engineering ones, and startups mostly hire interns under a software engineering title.
2. **The strongest signal for that target is a product real people use,** built end to end, with depth that survives a technical deep-dive. A pipeline with a dashboard reads as data engineering only.

A scored comparison of ten alternative projects (campus tools, a housing marketplace, a Raft key-value store, a collaborative editor, developer tools, AI agent products, and a UCSB bus app on Santa Barbara MTD feeds) put two transit products on top. The owner chose the LA Metro version for its originality and technical depth, accepting its main weakness: he is not an LA rider, so getting users takes deliberate outreach.

## Decision

Build **Ghost Bus LA**: a web app with reliability lookup and commute alerts, a public API, and an open dataset, on top of the archive and classification pipeline. `docs/SPEC.md` and `docs/spec/` are the design.

| Kept from the first version | Cut | Added |
| --- | --- | --- |
| Poller, raw archive, raw-bytes rule, fetch log, crosswalk (ADR-001) | Redpanda and Iceberg streaming path | FastAPI service with a public REST API |
| dbt models, missed-trip method, validation against Metro's report | Swiftly as a second source (kept only as a fallback if the Metro API is unusable) | Next.js web app |
| Airflow, backfills, schedule versioning | Evidence or Streamlit dashboard | Email-link accounts and saved commutes |
| Tests, CI, Terraform, decision records | Shape projection of GPS points | Alert engine: detector, transactional outbox, delivery worker |
| Open dataset, findings | A second agency | Observability, SLOs, load tests, security review |
| | | Rider research and a planned launch |

Three ideas worked out during the scrapped attempt are good and are carried into this spec as planned decisions, to be written as fresh ADRs when their work starts (`docs/SPEC.md` section 5):

- **ADR-003, operating standards:** an explain-back merge gate, SLOs with an error budget, an incident log, and new tools adopted only on evidence.
- **ADR-004, bronze storage and guardrails:** content-addressed keys with conditional writes, a rebuildable `derived/` prefix, deletes on raw data denied by bucket policy, Terraform state in S3.
- **ADR-005, likely-missing detector:** a simple micro-batch detector first; streaming only if that baseline misses its bars.

## Alternatives considered

- **Keep the data platform.** Stronger for pure data engineering roles; weaker for the roles that exist in volume at the target companies.
- **Switch to the UCSB bus app.** Easier to get users, since the owner rides those buses. Less original (several apps already show Santa Barbara MTD arrivals) and less depth without the missed-trip analysis. It scored within the margin of judgment of this option.
- **Keep streaming and add the product.** Too much for eight weeks. Streaming is rarely probed at the intern level, while users, API design, and correctness under failure are.
- **Continue in the old repo.** Its history and decision records describe a different project. A clean history that starts with the product is easier for a reviewer to follow.

## Consequences

**Good**

- One project supports two resume angles: product and API for software roles, pipeline and data quality for data roles.
- The alert engine is a compact, hard, well-known problem (exactly-once effects under crashes) and a strong interview story.
- Real users create feedback, incidents, and trade-offs that can't be invented.

**Costs and risks**

- The streaming story is gone unless the baseline detector proves it is needed. If asked, the honest answer is here: micro-batching every 10 minutes meets the statistics' needs, alerts run on a separate hot path, and a stream would add cost and operations for no rider benefit so far. The scale-up path is a queue between detector and workers.
- Scope is larger: four systems for one person. `docs/SPEC.md` section 7 defines the cut order.
- User acquisition is the weakest link. Outreach is scheduled work from M1, and launch is planned for the first week of January.
- The project stores personal data (emails and commute patterns), which brings privacy and security obligations (`docs/spec/05-infra-ops.md` sections 11 and 12).
- The scrapped repo's Terraform created a data bucket and a budget in AWS. M0 imports them into this repo's Terraform or destroys them, so nothing is left unmanaged.

## Clarifications to ADR-001

- **Decisions 1 and 3:** the day-1 probe (`docs/research/day1-probe.md`) found the Metro API's REST realtime endpoints empty and its canceled-service API dead since 2022, while its WebSocket streams are live. Realtime data is therefore taken as snapshots cut from the WebSocket, announced cancellations are read from trip updates, and there is no HTTP polling of realtime feeds. ADR-021 records this when written. A Swiftly key is requested as a second source.
- **Decision 6:** its key format (`<fetched_at>_<sha>`) and duplicate check are replaced by content-addressed keys with conditional writes, recorded in ADR-004 and specified in `docs/spec/01-data-pipeline.md` section 2.4. Its partitioning by UTC fetch date and its fetch log stand.
- All other decisions in ADR-001 stand.
