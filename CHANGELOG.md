# Changelog

## Unreleased

- Verify HTTPS against the operating-system trust store (truststore). Standalone Python
  builds such as uv's ship without a usable CA bundle, so every live request failed with
  "network request failed".
- Composed example queries: observations or series decoded through codes() code lists,
  plus a composed agent test task.

## 0.1.0

Initial European Central Bank worker with five typed SQL functions, authenticated HTTP,
source-aware parsing, bounded retries and reproducible engine/artifact contracts.
