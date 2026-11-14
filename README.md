# vgi-ecb

Python VGI worker for European Central Bank statistics. It exposes five typed SQL
functions with discovery metadata, original source values and HTTP bearer authentication.

See the [executed SQL-first notebook](notebooks/README.md) for discovering exchange-rate
dimensions, comparing currencies on common dates and testing lookback sensitivity.

## Run locally

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```sh
cd /absolute/path/to/vgi-ecb
make build
```

Stock DuckDB 2.0.0 with the signed Query.Farm VGI extension:

```sql
SET allow_extension_repositories = 'allowed';
CREATE EXTENSION REPOSITORY IF NOT EXISTS query_farm
  WITH PREFIX 'https://duckdb-extensions.query.farm';
INSTALL vgi FROM query_farm;
LOAD vgi FROM query_farm;
ATTACH 'ecb' (TYPE vgi,
  LOCATION '/absolute/path/to/vgi-ecb/.venv/bin/vgi-ecb-worker');

SELECT period, value, value_text, unit
FROM ecb.main.observations('EXR', 'D.USD.EUR.SP00.A',
  start_period := '2024-01-02', end_period := '2024-01-05')
ORDER BY period;
```

For Haybarn 2.0.0rc11, use its VGI extension and the same `ATTACH`/`SELECT` statements.
The worker can also use `launch:/absolute/path/to/worker` for Unix-socket pooling.
Diagnostics go to stderr; stdout belongs to Arrow IPC in stdio mode.

## SQL interface

| Function | Purpose |
|---|---|
| `datasets(flow := 'all')` | Published SDMX dataflows and structure references. |
| `dimensions(flow)` | Ordered key dimensions and code-list references. |
| `codes(codelist)` | Code values, labels and hierarchy parents. |
| `series(flow, key)` | Matching series metadata using the source `nodata` mode. |
| `observations(flow, key)` | Current data, source history and incremental updates. |

SDMX keys follow the dimension order returned by `dimensions`. Empty components
are wildcards; `+` selects alternatives. Named `start_period`/`end_period`,
`first_n`/`last_n` and `updated_after` filter at the source. `include_history := true`
requests previous dataset versions when available. `agency` defaults to `ECB`,
`version` to `latest`, and metadata `language` to `en`.

`valid_from`, `valid_to` and `dataset_action` reproduce source fields. They are not
invented observation release dates or a guarantee of a complete ALFRED archive.
A deletion without individual observations has a NULL `period`; a dataset-wide
deletion also has a NULL `series_key`. A conditional HTTP 304 returns an empty
result only when `updated_after` was requested. HTTP 204 also means no observations.

Observation, series, group and dataset attributes are combined in precedence order.
`unit_multiplier` is a base-ten exponent; the worker does not rescale values.
`max_rows` defaults to 100,000 (maximum 1,000,000) and caps emitted rows after the
complete bounded XML response is validated. The API does not offer ordinary
row-offset pagination; narrow keys and dates to stay within response limits.

Official references: [API overview](https://data.ecb.europa.eu/help/api/overview),
[data requests](https://data.ecb.europa.eu/help/api/data),
[content negotiation](https://data.ecb.europa.eu/help/api/content-negotiation).

## Authentication and deployment

The official upstream API is public and needs no API key. HTTP access to this
worker is a separate authentication boundary. Configure one or more strong bearer
tokens through `VGI_BEARER_TOKENS`, using `token=principal` pairs separated by commas:

```sh
# Inject real values from your deployment secret manager; do not commit them.
export VGI_BEARER_TOKENS="${WORKER_BEARER_TOKEN}=analytics"
.venv/bin/vgi-ecb-worker --http --host 127.0.0.1 --port 8000
```

Tokens must contain 32–4096 characters from the documented bearer alphabet
(letters, digits, `.`, `_`, `~`, `+`, `/`, `-`), without `=`, commas or whitespace.
Malformed configuration stops startup without printing the token. Unset bearer
configuration leaves the SDK in its default anonymous mode: set it for shared
services. The SDK also supports OIDC/JWT configuration; this project's measured
authentication contract covers static bearer tokens, including multiple principals.
`/health` stays unauthenticated for readiness checks; RPC endpoints require the token.

```sql
INSTALL httpfs FROM core;
LOAD httpfs;
ATTACH 'ecb' (TYPE vgi, LOCATION 'https://your-worker.example',
  bearer_token '<injected-worker-token>');
```

Use TLS at your reverse proxy for remote access, with restricted network ingress,
request/concurrency limits and a deployment secret manager. Process-local request
spacing does not coordinate across replicas; allocate a shared source request budget
at the deployment layer. No credentials are sent to the central bank or serialized
into continuation state. Query failures omit upstream response bodies and URLs.

```sh
docker build -t vgi-ecb:local .
docker run --rm -p 127.0.0.1:8000:8000 \
  --env VGI_BEARER_TOKENS vgi-ecb:local
# Stdio container transport:
docker run --rm -i vgi-ecb:local stdio
```

The container uses Python 3.13, locked dependencies, an unprivileged UID and a
health check. Add platform resource limits appropriate to query concurrency and
response sizes. Do not publish unauthenticated containers directly to the Internet.

## Operations and data semantics

NULL SQL arguments are rejected. Missing observations become SQL NULL; original
numeric strings remain in `value_text` for explicit DECIMAL conversion. `value`
is a DOUBLE convenience column and has ordinary binary floating-point limits.
Units, frequency, seasonal-adjustment categories and source period conventions are
preserved, not harmonized across banks. Use function arguments for source filtering;
SQL `WHERE` clauses run after retrieval. An explicit `max_rows` cap intentionally
returns a subset; it is not an implicit source pagination limit.

Each source request has a timeout, bounded response size, retry budget, process-local
spacing and retries for 429/5xx/network failures. Retry-After is respected; a delay
beyond the budget fails the query instead of retrying early. Redirects are rejected.
Malformed or inconsistent responses fail visibly rather than becoming partial success.
There is no persistent cache or automatic background polling. SQL consumers should
use transactions/staging tables when persisting streamed results from an API.

| Environment setting | Default | Meaning |
|---|---|---|
| `ECB_API_BASE_URL` | Official API endpoint | Operator-controlled HTTPS override; no URL credentials, query or fragment. |
| `ECB_TIMEOUT_SECONDS` | 30 | Socket timeout (0.1–120 seconds). |
| `ECB_MAX_ATTEMPTS` | 4 | Attempts per page/request (1–6). |
| `ECB_RETRY_BUDGET_SECONDS` | 120 | Total request/retry budget (1–600 seconds). |
| `ECB_MIN_INTERVAL_SECONDS` | 0.6 | Minimum spacing between requests in one process (0–60 seconds). |
| `ECB_MAX_RESPONSE_BYTES` | 16 MiB | Response bound (1 KiB–64 MiB); narrow source selection on overflow. |
| `ECB_ALLOW_INSECURE_HTTP` | unset | `1` permits only explicit loopback HTTP fixtures. |

TLS certificate verification is always enabled. If a managed Python installation
cannot find your system CA store, point `SSL_CERT_FILE` at the trusted CA bundle;
do not disable verification. ECB and BoE XML parsers reject DTDs, entities and
external references. BoJ JSON parsing rejects non-finite numbers and preserves
fractional numeric lexemes before Arrow conversion.

## Verification and release

```sh
make check        # Ruff format/lint, mypy strict, pydoclint, pytest, real SQL, metadata
make smoke-live   # Explicit live checks against the official source
make package      # Wheel and source archive in dist/
uv run python ci/verify-artifacts.py --python 3.13
```

`make check` runs original starter and product SQL tests over Haybarn stdio, Unix
launch and HTTP, followed by metadata assurance L2 and stock DuckDB 2.0.0 over stdio
and authenticated HTTP. Fixtures are deterministic and do not require real keys.
The metadata gate fails on info findings and has no waivers. CI repeats checks on
Linux/Windows and Python 3.13/3.14, plus container and installed artifact contracts.
Local verification reports live in `build/`; see [VALIDATION.md](VALIDATION.md).

Starter: [Query.Farm Python starter](https://github.com/Query-farm/vgi-starter-python),
revision `9cca9105474d6e0052b8e343c8ea21f3d1a7503c`, template 1.3.0.
The locked SDK is `vgi-python 0.51.1` with `vgi-rpc 0.53.1`; keep those protocol
versions aligned with the tested extension. Original examples/tests remain under
`examples/starter_samples`, separate from this worker's public catalog.

The included release workflow gates tagged releases on CI and produces signed
artifacts and provenance. No remote repository, package publication or hosted
service is created by a local build. Source code is 0BSD; the banks' data terms
and attribution requirements apply separately. Source/API changes may require a
worker update. Report reproducible failures with a redacted query and source period,
without credentials or private server URLs.
