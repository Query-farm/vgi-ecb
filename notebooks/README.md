# ECB notebooks

<a href="https://query.farm/"><img src="assets/query-farm-strata-sun.svg" alt="Query.Farm — Strata Sun" width="252"></a>

<a href="https://query.farm/vgi/"><img src="assets/vgi-logo.png" alt="VGI — Vector Gateway Interface" width="280"></a>

[Query.Farm](https://query.farm/) · [VGI](https://query.farm/vgi/) · [Haybarn](https://query.farm/products/haybarn/)

| Notebook | Investigation |
|---|---|
| [01 · Exchange-rate comparisons](01_exchange_rate_comparisons.ipynb) | Discover the EXR dimensions and code labels; audit daily USD, GBP and JPY quotes per EUR; compare original units and rebased paths on common dates; test sensitivity to a shorter lookback. |

The saved notebook contains successful live outputs and three embedded charts.
Retrieval, joins, coverage checks and financial unit calculations use visible
JupySQL `%%sql` cells through a native Haybarn connection and the real VGI worker.
Python handles configuration, validation, plotting and result-derived prose.
The results describe historical ECB reference-rate changes, not executable prices
or transaction returns.

## Install and choose a kernel

You need `uv`, Git and POSIX `env` on PATH (macOS/Linux; WSL on Windows).
Copy or download this complete **notebooks/** directory, then run from it:

```sh
uv sync --locked
uv run --locked python execute.py
```

Select `.venv/bin/python` in a Jupyter-compatible editor, then **Restart Kernel →
Run All**. The notebook environment supports Python 3.13–3.14 and pins published
Haybarn **2.0.0rc11**. No worker checkout or root environment is required.
The visible SQL launches the GitHub **v0.1.0** release using `uvx`, with
`vgi-python==0.51.1`. The release supplies Python wheel/source assets rather than
native platform archives, so `github-auto` is not used. Initial installation needs
network access; the live queries also need access to the official ECB API.

To upgrade, change the release and compatible SDK pin in the literal ATTACH cell,
rerun the default and shorter-lookback experiment, and review returned metadata,
units and source coverage. No Python variable hides the worker launch command.

Parameters, VGI `INSTALL` / `LOAD` / `ATTACH` SQL, analytical SQL, tables and chart
outputs remain expanded. Imports, styling, plot implementation, prose generation
and cleanup have portable Jupyter folding metadata and tags. VS Code may keep its
own editor folding state; use **Collapse Cell Input** on Python helper cells if
necessary. The notebook closes its connection at the end.

## Live source and bounds

The public [ECB SDMX API](https://data.ecb.europa.eu/help/api/overview) needs no API
key. Worker HTTP bearer authentication documented in the root README is a separate
deployment concern; this notebook launches a local stdio worker.

The implementation has synthetic fixtures for worker tests, but no built-in public
response replay mode. This notebook requests live data from
`https://data-api.ecb.europa.eu/service`; it does not use those test fixtures. Setup
explicitly pins this endpoint and disables inherited loopback fixture access.
There is no fallback when the source fails. An unavailable source raises a visible
error and the runner preserves the previous successful notebook.

The notebook makes seven bounded metadata/data requests: one flow, its dimensions,
three code lists, selected series metadata and one observation response. Metadata
can be larger than the filtered display; `max_rows` caps emitted rows after source
validation and is not pagination. Observations are limited by both key and dates,
then materialized once for all downstream charts.

| Parameter | Default and interpretation |
|---|---|
| `CURRENCIES` | `['USD', 'GBP', 'JPY']`; 2–5 distinct uppercase three-letter non-EUR codes. Source availability is checked. |
| `LOOKBACK_DAYS` | `90`; 14–366 inclusive calendar days, not number of observations. |
| `END_DATE` | `None`; yesterday at run start in UTC. An explicit `YYYY-MM-DD` date must precede the current UTC date. |

Both source date endpoints are inclusive. A single UTC clock determines defaults;
the observation loading time is also displayed. Neither is an observation release
timestamp. Metadata and observation responses are independent live requests.
The source can revise current values; no revision history is inferred.

The original `value_text`, `unit_multiplier`, status and dataset action remain in
the in-memory table. Raw panels use independent scales; the index uses one shared
scale and a common first observation date. Only finite positive status-`A` values
are used; missing dates, missing values and excluded rows are shown separately.
No gaps are filled with zero. A shorter common-date intersection can result when
one currency lacks a value.

TLS verification remains enabled. The notebook uses the locked `certifi` CA bundle
unless `SSL_CERT_FILE` already points to an operator-provided trust bundle. This
addresses Python installations whose default CA file cannot validate the ECB chain.

## Execute and check the experiment

From this notebook directory:

```sh
uv run --locked python execute.py
```

The runner uses a temporary kernel specification for the notebook environment;
no globally registered kernel is required. Each run starts a fresh kernel and
atomically writes a notebook only after all cells succeed. Ordinary in-memory tables are
intentional: JupySQL uses separate cursors, so cursor-local temporary tables can
disappear between cells.

Execute the final one-parameter experiment without replacing the default:

```sh
uv run --locked python execute.py \
  --parameters '{"LOOKBACK_DAYS": 30}' \
  --output-dir build/experiment
```

Overrides require `--output-dir`, and unknown parameter names are rejected. The
default run saves PNG charts and a machine-readable provenance/summary report to
`build/default/artifacts/`; an override run uses
`<output-dir>/artifacts/`. These generated directories are Git-ignored. Interactive
Run All writes to `build/default/` instead. Notebook outputs embed all
three PNGs, so the checked-in example remains readable without these directories.

Compare `run_report.json` in both artifact directories. The experiment should have
fewer common dates but identical last quotes when both runs resolve the same end
date and the source is unchanged. Changes and rankings depend on the new base date.
If running on different days, set the same explicit `END_DATE` in both runs.
The results are not guaranteed to match a saved run: live revisions and newly
available data remain distinct from changing the lookback.

An executed copy uses the original notebook directory as its working directory.
The runner supplies unchanged branding, this guide, helper, environment files and
runner beside each copy, so it can be reviewed and rerun independently. The output directory must differ from the original notebook's
directory. Restore `LOOKBACK_DAYS = 90` for the original investigation.

Notebook assertions validate dimension selection, required series, uniqueness,
units, dates, parse agreement, common coverage, base-100 indices and reciprocal
percentage-change identities. They do not require a fixed count, market direction
or ranking. Repository checks remain:

```sh
make check
```

The small [support module](notebook_support.py) handles validated parameters,
explicit upstream selection and presentation. Domain SQL stays in the notebook.
Branding assets are copied unchanged from `vgi-perps/notebooks/assets/`: the
official adaptive Strata Sun + Query.Farm wordmark and VGI product logo. The
wordmark links to Query.Farm at both the top and final bottom of the notebook.

---

<a href="https://query.farm/"><img src="assets/query-farm-strata-sun.svg" alt="Query.Farm — Strata Sun" width="210"></a>
