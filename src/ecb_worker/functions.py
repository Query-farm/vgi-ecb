"""ECB dataset discovery, SDMX dimensions/code lists and historical observations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.invocation import BindResponse
from vgi.table_function import BindParams, OutputCollector, ProcessParams, TableFunctionGenerator, init_single_worker
from vgi_rpc import ArrowSerializableDataclass

from .api import IDENTIFIER, KEY, NS, identifier, label, observation_rows, period, request
from .meta import column, function_meta
from .transport import ApiError
from .values import integer, source_json, timestamp

DATASETS = pa.schema(
    [
        column("flow", pa.string(), "SDMX dataflow identifier."),
        column("agency", pa.string(), "Maintaining agency identifier."),
        column("version", pa.string(), "Published dataflow version."),
        column("name", pa.string(), "Translated dataset name."),
        column("description", pa.string(), "Translated dataset description when supplied."),
        column("structure_id", pa.string(), "Referenced data structure identifier."),
        column("structure_agency", pa.string(), "Maintaining agency of the data structure."),
        column("structure_version", pa.string(), "Referenced data structure version."),
    ]
)
DIMENSIONS = pa.schema(
    [
        column("dimension", pa.string(), "Dimension identifier used in SDMX keys."),
        column(
            "position", pa.int64(), "One-based series-key position; the observation dimension may have no position."
        ),
        column("is_time", pa.bool_(), "Whether this is the time dimension at observation level."),
        column("codelist", pa.string(), "Referenced code list, if the dimension has an enumeration."),
        column("codelist_agency", pa.string(), "Maintaining agency for the code list."),
        column("codelist_version", pa.string(), "Referenced code-list version."),
        column("concept", pa.string(), "Referenced statistical concept identifier."),
    ]
)
CODES = pa.schema(
    [
        column("code", pa.string(), "Code used as one dimension-key component."),
        column("name", pa.string(), "Translated code label."),
        column("description", pa.string(), "Translated code description when supplied."),
        column("parent_code", pa.string(), "Parent code for hierarchical classifications, if supplied."),
        column("attributes_json", pa.string(), "Original code XML attributes."),
    ]
)
SERIES = pa.schema(
    [
        column("flow", pa.string(), "Requested dataflow identifier."),
        column("series_key", pa.string(), "Dot-separated source series key; NULL for dataset-wide deletion markers."),
        column("frequency", pa.string(), "Source frequency code."),
        column("title", pa.string(), "Source series title when supplied."),
        column("unit", pa.string(), "Source units, without currency conversion."),
        column("unit_multiplier", pa.int64(), "Source base-ten exponent; values are not rescaled."),
        column("dimensions_json", pa.string(), "Complete series dimension IDs and values."),
        column("attributes_json", pa.string(), "Effective inherited source attributes."),
        column("dataset_action", pa.string(), "Source SDMX action, including Delete markers."),
        column("valid_from", pa.string(), "Source dataset validFromDate; not an inferred observation release date."),
        column("valid_to", pa.string(), "Source dataset validToDate when supplied."),
        column("dataset_attributes_json", pa.string(), "Complete source dataset XML attributes."),
    ]
)
OBSERVATIONS = pa.schema(
    [
        *SERIES,
        column(
            "period", pa.string(), "Native SDMX period; NULL for a deletion marker without individual observations."
        ),
        column("value", pa.float64(), "Numeric observation in published units; NULL when unavailable or deleted."),
        column("value_text", pa.string(), "Original numeric source text for exact decimal conversion."),
        column("observation_status", pa.string(), "Source observation status code when supplied."),
    ]
)


@dataclass(frozen=True, kw_only=True)
class BaseArgs:
    """Maintaining agency, version and a bounded output size."""

    agency: Annotated[str, Arg("agency", default="ECB", pattern=IDENTIFIER, doc="Maintaining SDMX agency identifier.")]
    version: Annotated[
        str, Arg("version", default="latest", pattern=IDENTIFIER, doc="Published artifact version or latest.")
    ]
    max_rows: Annotated[
        int,
        Arg(
            "max_rows",
            default=100000,
            ge=1,
            le=1000000,
            doc=(
                "Explicit output cap after a complete bounded source response; use dates and keys to "
                "reduce source work."
            ),
        ),
    ]


@dataclass(frozen=True, kw_only=True)
class DatasetArgs(BaseArgs):
    """Metadata discovery for one or all dataflows."""

    flow: Annotated[
        str,
        Arg("flow", default="all", pattern=IDENTIFIER, doc="Dataflow identifier; all discovers the agency's catalog."),
    ]
    language: Annotated[
        str,
        Arg(
            "language",
            default="en",
            pattern=r"^[a-z]{2}$",
            doc="Preferred metadata language; falls back to English or the first available label.",
        ),
    ]


@dataclass(frozen=True, kw_only=True)
class FlowArgs(BaseArgs):
    """One dataflow's structure."""

    flow: Annotated[str, Arg(0, pattern=IDENTIFIER, doc="Dataflow identifier returned by datasets(), for example EXR.")]


@dataclass(frozen=True, kw_only=True)
class CodeArgs(BaseArgs):
    """A published code list."""

    codelist: Annotated[
        str, Arg(0, pattern=IDENTIFIER, doc="Code-list identifier returned by dimensions(), for example CL_CURRENCY.")
    ]
    language: Annotated[
        str,
        Arg(
            "language", default="en", pattern=r"^[a-z]{2}$", doc="Preferred code-label language with English fallback."
        ),
    ]


@dataclass(frozen=True, kw_only=True)
class DataArgs(FlowArgs):
    """Source-side SDMX selection and revision controls."""

    key: Annotated[
        str,
        Arg(
            1,
            pattern=KEY,
            doc=(
                "Dot-separated dimension values in dimensions() order; empty components are wildcards "
                "and '+' selects alternatives."
            ),
        ),
    ]
    start_period: Annotated[
        str, Arg("start_period", default="", doc="Inclusive native SDMX lower period bound; empty leaves it open.")
    ]
    end_period: Annotated[
        str, Arg("end_period", default="", doc="Inclusive native SDMX upper period bound; empty leaves it open.")
    ]
    updated_after: Annotated[
        str,
        Arg(
            "updated_after",
            default="",
            doc=("Only changes after this timezone-qualified ISO 8601 instant; empty disables incremental filtering."),
        ),
    ]
    include_history: Annotated[
        bool,
        Arg(
            "include_history",
            default=False,
            doc=(
                "Request previous dataset versions; source action and validity fields are preserved "
                "without inventing vintages."
            ),
        ),
    ]
    first_n: Annotated[
        int,
        Arg(
            "first_n",
            default=0,
            ge=0,
            le=1000000,
            doc="Earliest observations per matching series; zero leaves this source limit unset.",
        ),
    ]
    last_n: Annotated[
        int,
        Arg(
            "last_n",
            default=0,
            ge=0,
            le=1000000,
            doc="Latest observations per matching series; zero leaves this source limit unset.",
        ),
    ]


@dataclass(kw_only=True)
class State(ArrowSerializableDataclass):
    """Completion marker for one bounded SDMX response."""

    done: bool = False


@init_single_worker
class EcbFunction[T: BaseArgs](TableFunctionGenerator[T, State]):
    """Bounded XML responses exposed as typed Arrow tables."""

    FIXED_SCHEMA: ClassVar[pa.Schema]

    @classmethod
    def on_bind(cls, params: BindParams[T]) -> BindResponse:
        """Validate route components and source selection before opening a connection."""
        args = params.args
        identifier(args.agency)
        identifier(args.version)
        if isinstance(args, (DatasetArgs, FlowArgs)):
            identifier(args.flow)
        if isinstance(args, CodeArgs):
            identifier(args.codelist)
        if isinstance(args, DataArgs):
            if len(args.key) > 4000 or re.fullmatch(KEY, args.key) is None:
                raise ApiError("Invalid or oversized SDMX key")
            period(args.start_period)
            period(args.end_period)
            if args.start_period and args.end_period and args.start_period > args.end_period:
                raise ApiError("start_period must not be after end_period")
            if args.updated_after:
                timestamp(args.updated_after)
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def initial_state(cls, params: ProcessParams[T]) -> State:
        """Create a small cursor with no source records or credentials."""
        return State()

    @classmethod
    def fetch(cls, args: T) -> list[dict[str, Any]]:
        """Retrieve one complete metadata or data response."""
        raise NotImplementedError

    @classmethod
    def process(cls, params: ProcessParams[T], state: State, out: OutputCollector) -> None:
        """Emit validated records using the declared result schema."""
        if state.done:
            out.finish()
            return
        rows = cls.fetch(params.args)[: params.args.max_rows]
        try:
            batch = pa.RecordBatch.from_pylist(rows, schema=params.output_schema)
        except (pa.ArrowException, ValueError, OverflowError):
            raise ApiError("ECB response cannot be represented by the declared schema") from None
        state.done = True
        out.emit(batch)


class Datasets(EcbFunction[DatasetArgs]):
    """Discover published ECB SDMX dataflows."""

    FIXED_SCHEMA = DATASETS
    Meta = function_meta(
        "datasets",
        "Discover ECB datasets",
        (
            "List dataflows and their referenced data structures. Use flow to select one "
            "artifact; all lists available dataflows. Discovery does not retrieve observations."
        ),
        DATASETS,
        "SELECT flow, name FROM ecb.main.datasets(flow := 'EXR') ORDER BY flow",
    )

    @classmethod
    def fetch(cls, args: DatasetArgs) -> list[dict[str, Any]]:
        """Read flow names and their referenced structure identifiers."""
        root = request(f"dataflow/{args.agency}/{args.flow}/{args.version}", [("references", "none")])
        assert root is not None
        result = []
        for item in root.findall(".//s:Dataflows/s:Dataflow", NS):
            ref = item.find("s:Structure/Ref", NS)
            if not item.get("id") or ref is None or not ref.get("id"):
                raise ApiError("ECB dataflow metadata is missing its identifier or structure reference")
            result.append(
                {
                    "flow": item.get("id"),
                    "agency": item.get("agencyID"),
                    "version": item.get("version"),
                    "name": label(item, "Name", args.language),
                    "description": label(item, "Description", args.language),
                    "structure_id": ref.get("id"),
                    "structure_agency": ref.get("agencyID"),
                    "structure_version": ref.get("version"),
                }
            )
        return result


class Dimensions(EcbFunction[FlowArgs]):
    """Discover ordered dimensions and code-list references."""

    FIXED_SCHEMA = DIMENSIONS
    Meta = function_meta(
        "dimensions",
        "Discover ECB dimensions",
        (
            "Return the dataflow's series-key dimensions in their declared positions plus its "
            "time dimension. Code-list references supply arguments for codes()."
        ),
        DIMENSIONS,
        (
            "SELECT dimension, position, codelist FROM ecb.main.dimensions('EXR') ORDER BY "
            "position NULLS LAST, dimension"
        ),
    )

    @classmethod
    def fetch(cls, args: FlowArgs) -> list[dict[str, Any]]:
        """Resolve the flow's structure without relying on a hardcoded dimension order."""
        root = request(f"dataflow/{args.agency}/{args.flow}/{args.version}", [("references", "all")])
        assert root is not None
        flows = [n for n in root.findall(".//s:Dataflows/s:Dataflow", NS) if n.get("id") == args.flow]
        if len(flows) != 1:
            raise ApiError("ECB returned an ambiguous or missing dataflow")
        ref = flows[0].find("s:Structure/Ref", NS)
        if ref is None:
            raise ApiError("ECB dataflow is missing its structure reference")
        structures = [
            n
            for n in root.findall(".//s:DataStructures/s:DataStructure", NS)
            if all(n.get(k) == ref.get(k) for k in ("id", "agencyID", "version"))
        ]
        if len(structures) != 1:
            raise ApiError("ECB response is missing the referenced data structure")
        dimensions = structures[0].find("s:DataStructureComponents/s:DimensionList", NS)
        if dimensions is None:
            raise ApiError("ECB data structure is missing its dimensions")
        result = []
        for item in dimensions:
            enumeration = item.find("s:LocalRepresentation/s:Enumeration/Ref", NS)
            concept = item.find("s:ConceptIdentity/Ref", NS)
            if not item.get("id"):
                raise ApiError("ECB dimension is missing its identifier")
            result.append(
                {
                    "dimension": item.get("id"),
                    "position": integer(item.get("position"), optional=True),
                    "is_time": item.tag.endswith("}TimeDimension"),
                    "codelist": enumeration.get("id") if enumeration is not None else None,
                    "codelist_agency": enumeration.get("agencyID") if enumeration is not None else None,
                    "codelist_version": enumeration.get("version") if enumeration is not None else None,
                    "concept": concept.get("id") if concept is not None else None,
                }
            )
        return result


class Codes(EcbFunction[CodeArgs]):
    """Inspect published dimension values."""

    FIXED_SCHEMA = CODES
    Meta = function_meta(
        "codes",
        "Discover ECB dimension codes",
        (
            "List values, translated labels and optional hierarchy parents from one SDMX code "
            "list. Use the agency and version returned by dimensions()."
        ),
        CODES,
        "SELECT code, name FROM ecb.main.codes('CL_CURRENCY') WHERE code IN ('USD','EUR') ORDER BY code",
    )

    @classmethod
    def fetch(cls, args: CodeArgs) -> list[dict[str, Any]]:
        """Read code values from the requested maintained artifact."""
        root = request(f"codelist/{args.agency}/{args.codelist}/{args.version}", [])
        assert root is not None
        lists = [n for n in root.findall(".//s:Codelists/s:Codelist", NS) if n.get("id") == args.codelist]
        if len(lists) != 1:
            raise ApiError("ECB returned an ambiguous or missing code list")
        result = []
        for item in lists[0].findall("s:Code", NS):
            if not item.get("id"):
                raise ApiError("ECB code list contains an invalid code")
            parent = item.find("s:Parent/Ref", NS)
            result.append(
                {
                    "code": item.get("id"),
                    "name": label(item, "Name", args.language),
                    "description": label(item, "Description", args.language),
                    "parent_code": parent.get("id") if parent is not None else None,
                    "attributes_json": source_json(item.attrib),
                }
            )
        return result


def fetch_data(args: DataArgs, *, metadata_only: bool = False) -> list[dict[str, Any]]:
    """Retrieve source-selected series or observations with optional revision history."""
    query = [("detail", "nodata" if metadata_only else "full"), ("includeHistory", str(args.include_history).lower())]
    for name, value in [
        ("startPeriod", args.start_period),
        ("endPeriod", args.end_period),
        ("updatedAfter", args.updated_after),
    ]:
        if value:
            query.append((name, value))
    for name, limit in [("firstNObservations", args.first_n), ("lastNObservations", args.last_n)]:
        if limit:
            query.append((name, str(limit)))
    root = request(f"data/{args.agency},{args.flow},{args.version}/{args.key}", query, data=True)
    return observation_rows(root, args.flow, metadata_only=metadata_only)


class Series(EcbFunction[DataArgs]):
    """Inspect matching series without observation payloads."""

    FIXED_SCHEMA = SERIES
    Meta = function_meta(
        "series",
        "Inspect ECB series",
        (
            "Return matching series dimensions, titles, units and effective metadata using the "
            "source nodata mode. Required positional arguments are flow and key; all remaining "
            "controls are named arguments."
        ),
        SERIES,
        "SELECT series_key, title, unit FROM ecb.main.series('EXR', 'D.USD.EUR.SP00.A') ORDER BY series_key",
    )

    @classmethod
    def fetch(cls, args: DataArgs) -> list[dict[str, Any]]:
        """Fetch only series-level data and attributes."""
        return fetch_data(args, metadata_only=True)


class Observations(EcbFunction[DataArgs]):
    """Retrieve current observations or source-provided historical versions."""

    FIXED_SCHEMA = OBSERVATIONS
    Meta = function_meta(
        "observations",
        "Read ECB observations",
        (
            "Retrieve observations with original periods, values, units and SDMX attributes. "
            "include_history preserves source dataset actions and validity intervals; these are "
            "not inferred ALFRED-style vintage dates. Deletions without individual observations "
            "have a NULL period. Required positional arguments are flow and key; remaining "
            "controls are named."
        ),
        OBSERVATIONS,
        (
            "SELECT period, value, unit FROM ecb.main.observations('EXR', 'D.USD.EUR.SP00.A', "
            "start_period := '2024-01-02', end_period := '2024-01-05') ORDER BY period"
        ),
    )

    @classmethod
    def fetch(cls, args: DataArgs) -> list[dict[str, Any]]:
        """Fetch a complete bounded SDMX response before applying an explicit output cap."""
        return fetch_data(args)


FUNCTIONS: list[type[Any]] = [Datasets, Dimensions, Codes, Series, Observations]
