"""Central bank values, pagination and authentication through real worker processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from vgi.arguments import Arguments
from vgi.client import Client
from vgi.invocation import BindResponse

from ecb_worker.auth import validate_http_auth
from ecb_worker.functions import State
from test.mock_api.api_server import ApiServer


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiServer]:
    server = ApiServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ECB_API_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ECB_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("ECB_MIN_INTERVAL_SECONDS", "0")
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def ecb_client(api: ApiServer) -> Iterator[Client]:
    with Client([sys.executable, "-m", "ecb_worker.worker"], pool=None) as client:
        yield client


def table(client: Client, name: str, *positional: Any, **named: Any) -> pa.Table:
    bound: list[BindResponse] = []
    batches = list(
        client.table_function(
            function_name=name,
            schema_path=["main"],
            bind_result_callback=bound.append,
            arguments=Arguments(
                positional=tuple(pa.scalar(v) for v in positional), named={k: pa.scalar(v) for k, v in named.items()}
            ),
        )
    )
    return pa.Table.from_batches(batches, schema=bound[-1].output_schema)


WORKER_TOKEN = "fixture-only-worker-token-with-32-characters"


@pytest.fixture()
def ecb_http(api: ApiServer, tmp_path: Path) -> Iterator[str]:
    port_file = tmp_path / "port"
    environment = os.environ.copy()
    environment.update(VGI_BEARER_TOKENS=f"{WORKER_TOKEN}=analyst", VGI_PROXY_PROOF_MODE="off")
    environment.pop("VGI_JWT_ISSUER", None)
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "ecb_worker.worker", "--http", "--port", "0", "--port-file", str(port_file)],
            stdout=log,
            stderr=log,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 20
            while not port_file.exists():
                assert process.poll() is None, "HTTP worker exited before publishing its port"
                if time.monotonic() >= deadline:
                    pytest.fail("HTTP worker did not start within 20 seconds")
                time.sleep(0.05)
            location = "http://127.0.0.1:" + port_file.read_text().strip()
            while True:
                try:
                    with urllib.request.urlopen(location + "/health", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        pytest.fail("HTTP worker did not become ready")
                    time.sleep(0.05)
            yield location
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            messages = log.read()
            assert WORKER_TOKEN not in messages


@pytest.mark.parametrize("token", [None, "incorrect-token"])
def test_http_rpc_rejects_missing_or_wrong_bearer(ecb_http: str, api: ApiServer, token: str | None) -> None:
    headers = {"Authorization": "Bearer " + token} if token else {}
    request = urllib.request.Request(ecb_http + "/__describe__", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=5)
    assert exc.value.code == 401
    exc.value.close()
    with (
        pytest.raises(Exception, match="authentication rejected"),
        Client(transport="http", base_url=ecb_http, bearer_token=token, pool=None) as client,
    ):
        table(client, "datasets")
    assert api.requests == []


def test_http_health_remains_available_without_bearer(ecb_http: str) -> None:
    with urllib.request.urlopen(ecb_http + "/health", timeout=5) as response:
        assert response.status == 200


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        ",",
        WORKER_TOKEN,
        "=analyst",
        f"{WORKER_TOKEN}=",
        "short=analyst",
        f"{WORKER_TOKEN}=analyst,",
        f"{WORKER_TOKEN}=analyst,{WORKER_TOKEN}=other",
    ],
)
def test_bad_bearer_configuration_fails_without_exposing_token(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("VGI_BEARER_TOKENS", value)
    with pytest.raises(ValueError, match="Invalid VGI_BEARER_TOKENS") as exc:
        validate_http_auth()
    assert WORKER_TOKEN not in str(exc.value)


def test_bearer_configuration_accepts_multiple_principals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VGI_BEARER_TOKENS", f"{WORKER_TOKEN}=analyst,{WORKER_TOKEN}-second=service")
    validate_http_auth()
    monkeypatch.delenv("VGI_BEARER_TOKENS")
    validate_http_auth()


def test_bad_bearer_configuration_stops_http_startup(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["VGI_BEARER_TOKENS"] = WORKER_TOKEN
    port_file = tmp_path / "port"
    result = subprocess.run(
        [sys.executable, "-m", "ecb_worker.worker", "--http", "--port-file", str(port_file)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert result.returncode != 0
    assert "Invalid VGI_BEARER_TOKENS" in result.stderr
    assert WORKER_TOKEN not in result.stderr + result.stdout
    assert not port_file.exists()


def test_http_authenticated_data(ecb_http: str, api: ApiServer) -> None:
    with Client(transport="http", base_url=ecb_http, bearer_token=WORKER_TOKEN, pool=None) as client:
        result = table(client, "observations", "EXR", "D.USD.EUR.SP00.A")
    assert result.num_rows == 3
    assert len(api.requests) == 1
    assert all(WORKER_TOKEN not in str(record) for record in api.requests)


def test_state_roundtrip_has_no_values_or_credentials() -> None:
    state = State()
    assert State.deserialize_from_bytes(state.serialize_to_bytes()) == state
    assert not any("token" in name or "key" in name or "value" in name for name in state.__dataclass_fields__)


def test_discovery(ecb_client: Client, api: ApiServer) -> None:
    assert table(ecb_client, "datasets")["flow"].to_pylist() == ["EXR"]
    dimensions = table(ecb_client, "dimensions", "EXR").to_pylist()
    assert [row["position"] for row in dimensions] == [1, 2, 3, 4, 5, None]
    assert dimensions[-1]["is_time"] is True
    assert dimensions[1]["codelist"] == "CL_CURRENCY"
    assert table(ecb_client, "codes", "CL_CURRENCY")["code"].to_pylist() == ["EUR", "USD", "JPY"]
    assert all("structure+xml;version=2.1" in r["accept"] for r in api.requests)


def test_observations_and_source_filters(ecb_client: Client, api: ApiServer) -> None:
    result = table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A")
    assert result["value_text"].to_pylist() == ["1.10", None, "1.20"]
    assert result["value"].to_pylist() == [1.1, None, 1.2]
    assert result["observation_status"].to_pylist() == ["A", "M", "A"]
    assert result["unit_multiplier"].to_pylist() == [0, 0, 0]
    assert json.loads(result["dimensions_json"][0].as_py())["CURRENCY_DENOM"] == "EUR"
    result = table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A", start_period="2024-01-03", last_n=1)
    assert result["period"].to_pylist() == ["2024-01-04"]
    assert api.requests[-1]["query"]["startPeriod"] == ["2024-01-03"]
    assert api.requests[-1]["query"]["lastNObservations"] == ["1"]
    assert "genericdata+xml;version=2.1" in api.requests[-1]["accept"]
    assert table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A", max_rows=1).num_rows == 1
    assert table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A", start_period="2100").num_rows == 0


def test_history_and_metadata_only(ecb_client: Client, api: ApiServer) -> None:
    result = table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A", include_history=True)
    assert result.num_rows == 6
    assert result["valid_to"].to_pylist() == ["2024-02-01T00:00:00Z"] * 3 + [None] * 3
    assert result["value_text"][0].as_py() == "0.90"
    assert table(ecb_client, "series", "EXR", "D.USD.EUR.SP00.A")["unit"].to_pylist() == ["USD"]
    assert api.requests[-1]["query"]["detail"] == ["nodata"]


def test_empty_conditional_and_deletion(ecb_client: Client, api: ApiServer) -> None:
    api.mode = "EMPTY"
    assert table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A").num_rows == 0
    api.mode = "UNCHANGED"
    assert (
        table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A", updated_after="2024-01-01T00:00:00Z").num_rows == 0
    )
    with pytest.raises(Exception, match="HTTP 304"):
        table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A")
    api.mode = "DELETE"
    result = table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A").to_pylist()
    assert len(result) == 1 and result[0]["period"] is None and result[0]["dataset_action"] == "Delete"


@pytest.mark.parametrize(
    "mode,match",
    [
        ("DUPLICATE", "duplicate"),
        ("BADVALUE", "numeric"),
        ("HTML", "unexpected"),
        ("UNSAFE", "unsafe XML"),
        ("REDIRECT", "HTTP 302"),
        ("ERROR", "HTTP 400"),
    ],
)
def test_invalid_responses(ecb_client: Client, api: ApiServer, mode: str, match: str) -> None:
    api.mode = mode
    with pytest.raises(Exception, match=match):
        table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A")


def test_retry(ecb_client: Client, api: ApiServer) -> None:
    api.mode = "RETRY"
    assert table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A").num_rows == 3
    assert api.attempts == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_period": "bad"},
        {"start_period": "2024-02-01", "end_period": "2024-01-01"},
        {"updated_after": "2024-01-01"},
    ],
)
def test_invalid_arguments_before_network(ecb_client: Client, api: ApiServer, kwargs: dict[str, Any]) -> None:
    with pytest.raises(
        Exception, match=r"(?i)(series_codes|invalid|expected|must|none|null|period|date|timestamp|layer|argument)"
    ):
        table(ecb_client, "observations", "EXR", "D.USD.EUR.SP00.A", **kwargs)
    assert not api.requests


def test_attribute_inheritance_and_dataset_deletion() -> None:
    from ecb_worker.api import NS, observation_rows
    from ecb_worker.xml import parse_xml
    from test.mock_api.api_server import add, data

    root = parse_xml(data({}, ""))
    dataset = root.find("m:DataSet", NS)
    assert dataset is not None
    attrs = add(dataset, "g:Attributes")
    add(attrs, "g:Value", {"id": "DECIMALS", "value": "4"})
    rows = observation_rows(root, "EXR")
    assert json.loads(rows[0]["attributes_json"])["DECIMALS"] == "4"
    for child in list(dataset):
        dataset.remove(child)
    dataset.set("action", "Delete")
    rows = observation_rows(root, "EXR")
    assert rows[0]["series_key"] is None and rows[0]["period"] is None


def test_invalid_calendar_dates_and_repeated_series() -> None:
    import copy

    from ecb_worker.api import NS, observation_rows, period
    from ecb_worker.transport import ApiError
    from ecb_worker.xml import parse_xml
    from test.mock_api.api_server import data

    with pytest.raises(ApiError, match="YYYY-MM-DD"):
        period("2024-02-30")
    root = parse_xml(data({}, ""))
    dataset = root.find("m:DataSet", NS)
    assert dataset is not None
    series = dataset.find("g:Series", NS)
    assert series is not None
    dataset.append(copy.deepcopy(series))
    with pytest.raises(ApiError, match="duplicate series"):
        observation_rows(root, "EXR")
