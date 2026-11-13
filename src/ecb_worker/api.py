"""ECB SDMX 2.1 XML requests, metadata and observation decoding."""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element

from .transport import ApiError, Config, request_bytes
from .values import integer, iso_date, number, source_json
from .xml import parse_xml

NS = {
    name: "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/" + suffix
    for name, suffix in {
        "m": "message",
        "s": "structure",
        "c": "common",
        "g": "data/generic",
    }.items()
}
IDENTIFIER = r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$"
KEY = r"^[A-Za-z0-9_+-]*(?:\.[A-Za-z0-9_+-]*)*$"
STRUCTURE_MIME = "application/vnd.sdmx.structure+xml;version=2.1"
DATA_MIME = "application/vnd.sdmx.genericdata+xml;version=2.1"


def identifier(value: str) -> str:
    """Validate one SDMX route component without URL syntax."""
    if re.fullmatch(IDENTIFIER, value) is None or ".." in value:
        raise ApiError("SDMX identifiers must contain only letters, digits, underscores, periods and dashes")
    return value


def period(value: str) -> str:
    """Accept documented SDMX reporting-period bounds."""
    if (
        value
        and re.fullmatch(r"\d{4}(?:-(?:S[12]|Q[1-4]|W(?:0[1-9]|[1-4]\d|5[0-3])|(?:0[1-9]|1[0-2])(?:-\d{2})?))?", value)
        is None
    ):
        raise ApiError("Period bounds must use SDMX year, half-year, quarter, month, week or ISO date format")
    if len(value) == 10:
        iso_date(value)
    return value


def request(endpoint: str, query: list[tuple[str, str]], *, data: bool = False) -> Element | None:
    """Fetch explicit SDMX XML, interpreting only documented empty statuses as no data."""
    response = request_bytes(
        endpoint,
        query,
        Config.from_env(),
        accept=DATA_MIME if data else STRUCTURE_MIME,
        allow_not_modified=data and any(k == "updatedAfter" for k, _ in query),
    )
    if data and response.status in {204, 304}:
        return None
    root = parse_xml(response.body)
    expected = "GenericData" if data else "Structure"
    if root.tag != "{" + NS["m"] + "}" + expected:
        raise ApiError("ECB returned an unexpected SDMX document or API error")
    if root.find(".//m:Error", NS) is not None or root.find(".//m:ErrorMessage", NS) is not None:
        raise ApiError("ECB returned an SDMX error")
    return root


def label(node: Element, name: str, language: str) -> str | None:
    """Select the requested translated label, then English, then the first available label."""
    elements = node.findall("c:" + name, NS)
    for wanted in (language, "en"):
        for item in elements:
            if item.get("{http://www.w3.org/XML/1998/namespace}lang") == wanted:
                return item.text
    return elements[0].text if elements else None


def values(node: Element | None) -> dict[str, str]:
    """Decode a unique SDMX key or attribute group."""
    result: dict[str, str] = {}
    if node is None:
        return result
    for item in node.findall("g:Value", NS):
        name, value = item.get("id"), item.get("value")
        if not name or value is None or name in result:
            raise ApiError("ECB response has invalid or duplicate SDMX attributes")
        result[name] = value
    return result


def observation_rows(root: Element | None, flow: str, *, metadata_only: bool = False) -> list[dict[str, Any]]:
    """Preserve dataset actions, version intervals and inherited observation attributes."""
    if root is None:
        return []
    datasets = root.findall("m:DataSet", NS)
    if not datasets:
        raise ApiError("ECB data response is missing its dataset")
    output: list[dict[str, Any]] = []
    for dataset in datasets:
        action = dataset.get("action", "Information")
        if action not in {"Append", "Replace", "Delete", "Information"}:
            raise ApiError("ECB response has an unsupported dataset action")
        base = values(dataset.find("g:Attributes", NS))
        groups = [
            (values(group.find("g:GroupKey", NS)), values(group.find("g:Attributes", NS)))
            for group in dataset.findall("g:Group", NS)
        ]
        all_series = dataset.findall("g:Series", NS)
        if not all_series and action == "Delete":
            all_series = [Element("empty-delete")]
        if dataset.findall("g:Obs", NS):
            raise ApiError("ECB returned unsupported dataset-level observations")
        seen_series: set[str] = set()
        for series in all_series:
            dimensions = values(series.find("g:SeriesKey", NS))
            if not dimensions and action != "Delete":
                raise ApiError("ECB series is missing its dimension key")
            signature = source_json(dimensions)
            if signature in seen_series:
                raise ApiError("ECB response contains duplicate series keys within a dataset")
            seen_series.add(signature)
            attributes = base.copy()
            for key, group_attributes in groups:
                if all(dimensions.get(k) == v for k, v in key.items()):
                    attributes.update(group_attributes)
            attributes.update(values(series.find("g:Attributes", NS)))
            shared = {
                "flow": flow,
                "series_key": ".".join(dimensions.values()) if dimensions else None,
                "frequency": dimensions.get("FREQ"),
                "title": attributes.get("TITLE"),
                "unit": attributes.get("UNIT"),
                "unit_multiplier": integer(attributes.get("UNIT_MULT"), optional=True),
                "dimensions_json": source_json(dimensions),
                "attributes_json": source_json(attributes),
                "dataset_action": action,
                "valid_from": dataset.get("validFromDate"),
                "valid_to": dataset.get("validToDate"),
                "dataset_attributes_json": source_json(dataset.attrib),
            }
            if metadata_only:
                output.append(shared)
                continue
            observations = series.findall("g:Obs", NS)
            if not observations and action == "Delete":
                output.append({**shared, "period": None, "value": None, "value_text": None, "observation_status": None})
            seen: set[str] = set()
            for observation in observations:
                dimension = observation.find("g:ObsDimension", NS)
                native_period = dimension.get("value") if dimension is not None else None
                if not native_period or native_period in seen:
                    raise ApiError("ECB response has a missing or duplicate observation period")
                seen.add(native_period)
                value_node = observation.find("g:ObsValue", NS)
                numeric, raw_value = number(value_node.get("value") if value_node is not None else None)
                effective = {**attributes, **values(observation.find("g:Attributes", NS))}
                output.append(
                    {
                        **shared,
                        "period": native_period,
                        "value": numeric,
                        "value_text": raw_value,
                        "unit": effective.get("UNIT"),
                        "unit_multiplier": integer(effective.get("UNIT_MULT"), optional=True),
                        "attributes_json": source_json(effective),
                        "observation_status": effective.get("OBS_STATUS"),
                    }
                )
    return output
