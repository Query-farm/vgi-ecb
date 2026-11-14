# ECB Statistics examples

[Worker repository](https://github.com/Query-farm/vgi-ecb) · [Shared notebook tools and standard](https://github.com/Query-farm/vgi-example-notebooks)

| Notebook | Investigation | Run |
|---|---|---|
| [Compare exchange-rate changes without mixing units](01_exchange_rate_comparisons.ipynb) | Discover series and units, audit availability, compare original quotes with common-date indices, then shorten the observation window. | [Open in Colab](https://colab.research.google.com/github/Query-farm/vgi-ecb/blob/main/notebooks/01_exchange_rate_comparisons.ipynb) |

The notebook has saved live results and three SVG charts. SQL connection cells and
analytical queries stay visible. GitHub displays code cells expanded; small shared
helpers keep setup and plotting code short. Both branding marks, the linked worker
title and the Colab button are included in the notebook itself.

## Run the example

Open in Colab and run all cells, or use `uv` locally from this directory:

```sh
uv sync --locked
uv run --locked vgi-notebooks --timeout 300
```

Select `.venv/bin/python` for interactive work. The local environment includes the
runner; the notebook's bootstrap installs only the shared base package and keeps
compatible preinstalled plotting and kernel libraries. Its portable companion is
fetched from an immutable revision and checked against its SHA-256 hash. A standalone
notebook therefore does not need a worker checkout or copies of our tooling.

The visible ATTACH launches the published **v0.1.0** worker with:

```text
uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-ecb@v0.1.0 vgi-ecb-worker
```

No SDK override is needed. The worker has its own environment, separate from the
notebook kernel. Git, `uv` and network access are needed; the shared setup makes
`uv` available in Colab. No separate worker checkout or build step is needed.

## Live source and interpretation

The public [ECB SDMX API](https://data.ecb.europa.eu/help/api/overview) needs no API key.
The example fixes the official upstream URL and disables inherited loopback-test
access. It requests live public responses; there are no synthetic observations,
recorded-response fixtures or fallback data. Metadata and observations come from
independent requests, not an atomic snapshot. Failed runs leave the previous
successful notebook intact.

| Parameter | Default and meaning |
|---|---|
| `CURRENCIES` | `['USD', 'GBP', 'JPY']`; 2–5 distinct uppercase non-EUR currency codes. Availability is checked against returned metadata. |
| `LOOKBACK_DAYS` | `90`; 14–366 inclusive calendar days, not number of observations. |
| `END_DATE` | `None`; yesterday at run start in UTC. An explicit ISO date must precede today. |

Seven bounded metadata/data requests discover the flow, dimensions and code labels,
validate series units and retrieve observations once. Both date endpoints are
inclusive. `max_rows` limits returned rows after source validation; it is not
pagination or a substitute for request filters. Later calculations use materialized
SQL tables. The UTC run clock and load-completion time give retrieval context;
neither is a source publication timestamp.

Only finite positive status-`A` values are eligible. Missing dates, returned missing
values and excluded rows remain distinct. Original value text, unit multiplier,
status and dataset action are retained. Raw panels have independent vertical
scales; the rebased chart uses common usable dates and a shared scale. The inverse
quote calculation demonstrates why reciprocal percentage changes are not exactly
equal and opposite. These are historical reference quotes, not transaction returns.

TLS verification stays enabled. Released v0.1.0 uses Python's default certificate
handling; setup supplies `certifi` unless `SSL_CERT_FILE` already specifies a trust
bundle. Current main adds OS truststore handling. The notebook executes the release;
current-source compatibility is documented separately in [coverage evidence](coverage.json).
All five public SQL surfaces are demonstrated. The current source was reviewed but
not built or executed for this notebook change.

## Compare a shorter window

The closing experiment changes only the lookback. Save its outputs separately:

```sh
uv run --locked vgi-notebooks --timeout 300 \
  --parameters '{"LOOKBACK_DAYS":30}' --output-dir artifacts/short-window
```

Use the same explicit `END_DATE` in both runs when crossing a UTC day. Compare the
coverage and summary tables, the three charts and `artifacts/lookback-90/run_report.json`
with `artifacts/lookback-30/run_report.json` in the executed working directories.
Expect fewer common dates and unchanged final quotes only when the resolved end
date and source values are unchanged. The starting quote changes, so the ordering
and magnitude of endpoint changes may change. Live source revisions remain possible.

The shared runner requires an output directory for parameter overrides, rejects
unknown names and writes a notebook only after successful execution. Assertions
check dimensions, unique series/date keys, bounds, units, parsed values, common
coverage, base-100 indices and reciprocal-change identities. They do not assume
particular market directions or rankings. SVGs are embedded and linked to checked-in
image assets for sharp GitHub rendering; local review PNGs and reports are ignored.
