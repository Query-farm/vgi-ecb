# Changelog

## 0.1.1 (2026-11-14)

- The catalog comment is now one plain-text sentence saying what the worker covers (rule
  VGI001). The longer Markdown description stays in the catalog's `vgi.doc_md` and
  `vgi.doc_llm` tags.
- Verify HTTPS against the operating-system trust store (truststore). Standalone Python
  builds such as uv's ship without a usable CA bundle, so every live request failed with
  "network request failed".
- Composed example queries: observations or series decoded through codes() code lists,
  plus a composed agent test task.

## 0.1.0

Initial European Central Bank worker with five typed SQL functions, authenticated HTTP,
source-aware parsing, bounded retries and reproducible engine/artifact contracts.
