"""Small synthetic SDMX structures and generic data for deterministic SQL contracts."""

from __future__ import annotations

import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

API_KEY = "public-api-no-upstream-key"
PREFIX = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/"
NS = {"m": PREFIX + "message", "s": PREFIX + "structure", "c": PREFIX + "common", "g": PREFIX + "data/generic"}


def add(parent: Element, tag: str, attributes: dict[str, str] | None = None, text: str | None = None) -> Element:
    prefix, name = tag.split(":") if ":" in tag else ("", tag)
    element = SubElement(parent, "{" + NS[prefix] + "}" + name if prefix else name, attributes or {})
    element.text = text
    return element


def metadata() -> bytes:
    root = Element("{" + NS["m"] + "}Structure")
    structures = add(root, "m:Structures")
    flow = add(add(structures, "s:Dataflows"), "s:Dataflow", {"id": "EXR", "agencyID": "ECB", "version": "1.0"})
    add(flow, "c:Name", {"{http://www.w3.org/XML/1998/namespace}lang": "en"}, "Exchange rates fixture")
    add(add(flow, "s:Structure"), "Ref", {"id": "ECB_EXR1", "agencyID": "ECB", "version": "1.0"})
    structure = add(
        add(structures, "s:DataStructures"), "s:DataStructure", {"id": "ECB_EXR1", "agencyID": "ECB", "version": "1.0"}
    )
    dimensions = add(add(structure, "s:DataStructureComponents"), "s:DimensionList")
    for position, name in enumerate(["FREQ", "CURRENCY", "CURRENCY_DENOM", "EXR_TYPE", "EXR_SUFFIX"], 1):
        dimension = add(dimensions, "s:Dimension", {"id": name, "position": str(position)})
        add(add(dimension, "s:ConceptIdentity"), "Ref", {"id": name})
        enumeration = add(add(dimension, "s:LocalRepresentation"), "s:Enumeration")
        add(
            enumeration,
            "Ref",
            {"id": "CL_CURRENCY" if name.startswith("CURRENCY") else "CL_" + name, "agencyID": "ECB", "version": "1.0"},
        )
    add(dimensions, "s:TimeDimension", {"id": "TIME_PERIOD"})
    codes = add(
        add(structures, "s:Codelists"), "s:Codelist", {"id": "CL_CURRENCY", "agencyID": "ECB", "version": "1.0"}
    )
    for code, title in [("EUR", "Euro"), ("USD", "US dollar"), ("JPY", "Japanese yen")]:
        node = add(codes, "s:Code", {"id": code})
        add(node, "c:Name", {"{http://www.w3.org/XML/1998/namespace}lang": "en"}, title)
    return bytes(tostring(root, encoding="utf-8", xml_declaration=True))


def data(query: dict[str, list[str]], mode: str) -> bytes:
    root = Element("{" + NS["m"] + "}GenericData")
    dataset = add(root, "m:DataSet", {"action": "Replace", "validFromDate": "2024-02-01T00:00:00Z"})
    series = add(dataset, "g:Series")
    key = add(series, "g:SeriesKey")
    for name, value in zip(
        ["FREQ", "CURRENCY", "CURRENCY_DENOM", "EXR_TYPE", "EXR_SUFFIX"], ["D", "USD", "EUR", "SP00", "A"], strict=True
    ):
        add(key, "g:Value", {"id": name, "value": value})
    attributes = add(series, "g:Attributes")
    for name, value in [("TITLE", "Fixture USD per EUR"), ("UNIT", "USD"), ("UNIT_MULT", "0")]:
        add(attributes, "g:Value", {"id": name, "value": value})
    rows = [("2024-01-02", "1.10"), ("2024-01-03", None), ("2024-01-04", "1.20")]
    rows = [row for row in rows if query.get("startPeriod", [""])[0] <= row[0] <= query.get("endPeriod", ["9999"])[0]]
    if query.get("firstNObservations"):
        rows = rows[: int(query["firstNObservations"][0])]
    if query.get("lastNObservations"):
        rows = rows[-int(query["lastNObservations"][0]) :]
    if mode == "DUPLICATE":
        rows += rows[:1]
    if mode == "BADVALUE":
        rows = [("2024-01-02", "invalid")]
    if mode == "DELETE":
        dataset.set("action", "Delete")
        rows = []
    if query.get("detail") != ["nodata"]:
        for native_period, obs_value in rows:
            obs = add(series, "g:Obs")
            add(obs, "g:ObsDimension", {"value": native_period})
            if obs_value is not None:
                add(obs, "g:ObsValue", {"value": obs_value})
            add(add(obs, "g:Attributes"), "g:Value", {"id": "OBS_STATUS", "value": "A" if obs_value else "M"})
    if query.get("includeHistory") == ["true"]:
        old = copy.deepcopy(dataset)
        old.set("validFromDate", "2024-01-01T00:00:00Z")
        old.set("validToDate", "2024-02-01T00:00:00Z")
        for node in old.iter("{" + NS["g"] + "}ObsValue"):
            node.set("value", "0.90")
        root.insert(0, old)
    return bytes(tostring(root, encoding="utf-8", xml_declaration=True))


class ApiServer(ThreadingHTTPServer):
    """Local service with controllable transport and response failures."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests: list[dict[str, Any]] = []
        self.mode = ""
        self.attempts = 0


class Handler(BaseHTTPRequestHandler):
    """Serve synthetic metadata and data without writing request logs."""

    server: ApiServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        self.server.requests.append({"path": url.path, "query": query, "accept": self.headers.get("Accept")})
        self.server.attempts += 1
        parts = url.path.strip("/").split("/")
        mode = self.server.mode
        if parts[0] == "data" and len(parts) > 1:
            flow = parts[1].split(",")[1]
            if flow != "EXR":
                mode = flow
        status = 200
        body = data(query, mode) if parts[0] == "data" else metadata()
        if mode == "EMPTY":
            status, body = 204, b""
        if mode == "UNCHANGED":
            status, body = 304, b""
        if mode == "HTML":
            body = b"<html>Not an API response</html>"
        if mode == "UNSAFE":
            body = b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><foo>&x;</foo>'
        if mode == "RETRY" and self.server.attempts == 1:
            status, body = 429, b""
        if mode == "REDIRECT":
            status, body = 302, b""
        if mode == "ERROR":
            status, body = 400, b"invalid"
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        if status == 429:
            self.send_header("Retry-After", "0")
        if status == 302:
            self.send_header("Location", "https://example.invalid/")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ApiServer()
    print(f"PORT:{server.server_port}", flush=True)
    server.serve_forever()
