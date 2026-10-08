# Decision Lab requirements audit

Checked 2026-10-08 against the complete page text supplied by the student for the [course Decision Lab](https://tiangong-lca-decision-lab.ecodino73.chatgpt.site/). Direct site access from this cloud environment returned HTTP 403 at the network proxy, so this audit is limited to that supplied text. The site form was not submitted by the tool.

| Page requirement | Evidence in this repository | Status |
| --- | --- | --- |
| One packaged BC1 1 L electric kettle at the factory gate; 723 g kettle and 137.8 g packaging | [`README.md`](../README.md), [`data/bom.csv`](../data/bom.csv) | Covered; arithmetic checked |
| Source of shared BOM | README §2; [`data/manifest.csv`](../data/manifest.csv) | Page attribution recorded; original 2020 report not independently checked |
| TianGong and USLCI search, process choices and alternatives | README §4; [`data/background_mapping.csv`](../data/background_mapping.csv); [`docs/decision-log.md`](decision-log.md) | Covered with explicit proxies and gaps |
| Reproducible code, dependencies, retrieval instructions and matrix calculation | README §§5–6; [`scripts/calculate_screening.py`](../scripts/calculate_screening.py); [`requirements.txt`](../requirements.txt) | Covered |
| Units, upstream providers, characterization and missing data | README §§4–7; [`results/unlinked_providers.csv`](../results/unlinked_providers.csv) | Checked and disclosed; supplier closure and full GWP characterization fail |
| Ten README sections, results, uncertainty and Codex decisions | [`README.md`](../README.md); [`results/summary.json`](../results/summary.json) | All sections present; modeled four-gas subtotal is not a complete factory-gate GWP100 |
| Predict main contributor before calculating | README §10; decision log | No contemporaneous prediction recorded; cannot be recreated honestly |
| Public GitHub independent commit and 40-character SHA | Git history and course submission form | Check after push; SHA must be placed in form, not README |
| Compare classmates' results and test one changed choice in a separate revision | README §10 | Pending class comparison; preserve this independent run first |
| Course form: name, email, alias, repository URL, full SHA, submission code | External course form | Student action required; personal information and course code are not stored here |

The page text says to publish only redistributable data and exclude secrets. This repository contains the BOM, links/identifiers, code and derived outputs; it does not contain database dumps, API keys, `.env` files, a name or email. The USLCI and TianGong source archives are retrieved when the script runs and are not committed.
