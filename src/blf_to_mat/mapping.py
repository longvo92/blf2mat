"""Project-neutral workbook selection and optional schema/mapping inference."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from . import converter as core

HEADERS = {
    "element": ("data element", "element", "model signal", "target", "signal name"),
    "can": ("can signal", "dbc signal", "network signal", "source", "can"),
    "interface": ("interface", "bus", "group"),
    "dtype": ("datatype", "data type", "type"),
}


@dataclass
class MappingSetup:
    interfaces: list[dict[str, Any]] = field(default_factory=list)
    input_interfaces: list[dict[str, Any]] | None = None
    output_interfaces: list[dict[str, Any]] | None = None
    input_names: list[str] = field(default_factory=list)
    output_names: list[str] = field(default_factory=list)
    input_elements: dict[str, str] = field(default_factory=dict)
    output_elements: dict[str, str] = field(default_factory=dict)
    input_specific: dict[tuple[str, str], str] = field(default_factory=dict)
    output_specific: dict[tuple[str, str], str] = field(default_factory=dict)


def cell(value: Any) -> str:
    return "" if value is None or core.pd.isna(value) else str(value).strip()


def column_index(raw: Any, row: int, option: str | None, kind: str) -> int | None:
    headers = [core.norm(cell(value)) for value in raw.iloc[row]]
    if option:
        if option.isdigit():
            index = int(option) - 1
            if 0 <= index < len(headers):
                return index
            raise RuntimeError(f"Excel {kind} column number is out of range: {option}")
        matches = [index for index, name in enumerate(headers) if name == core.norm(option)]
        if len(matches) != 1:
            raise RuntimeError(f"Excel {kind} header must match exactly one column: {option!r}")
        return matches[0]
    matches = [
        index for index, name in enumerate(headers) if name in {core.norm(h) for h in HEADERS[kind]}
    ]
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous Excel {kind} columns; specify --{kind}-column.")
    return matches[0] if matches else None


def read_sheet(
    book: Any,
    sheet: str,
    paths: core.SelectedPaths,
    known_elements: set[str],
    known_can: set[str],
    skip_keywords: tuple[str, ...] = (),
) -> list[tuple[str, str, str, str]]:
    raw = core.pd.read_excel(book, sheet_name=sheet, header=None, dtype=object)
    if raw.empty:
        return []
    excluded = raw.apply(
        lambda row: any(
            keyword in cell(value).casefold() for value in row for keyword in skip_keywords
        ),
        axis=1,
    )
    rows = [paths.header_row - 1] if paths.header_row else range(min(20, len(raw)))
    candidates = []
    for row in rows:
        if row >= len(raw):
            raise RuntimeError(f"Header row exceeds sheet {sheet!r} length.")
        data = raw.iloc[row + 1 :].loc[~excluded]
        try:
            columns = {
                kind: column_index(raw, row, getattr(paths, f"{kind}_column"), kind)
                for kind in HEADERS
            }
        except RuntimeError:
            if paths.header_row:
                raise
            continue
        if columns["can"] is None and known_can:
            scores = [
                (core.value_match_score(data.iloc[:, index], known_can, True), index)
                for index in range(raw.shape[1])
            ]
            scores.sort(reverse=True)
            if scores and scores[0][0] and (len(scores) == 1 or scores[0][0] > scores[1][0]):
                columns["can"] = scores[0][1]
        if columns["element"] is None and known_elements:
            scores = [
                (core.value_match_score(data.iloc[:, index], known_elements, True), index)
                for index in range(raw.shape[1])
                if index != columns["can"]
            ]
            scores.sort(reverse=True)
            if scores and scores[0][0] and (len(scores) == 1 or scores[0][0] > scores[1][0]):
                columns["element"] = scores[0][1]
        if columns["can"] is None or row + 1 >= len(raw):
            continue
        if columns["element"] == columns["can"] and not paths.element_column:
            columns["element"] = None
        selected = [value for value in columns.values() if value is not None]
        if len(selected) != len(set(selected)):
            continue
        hints = sum(
            core.norm(cell(raw.iat[row, index])) in {core.norm(h) for h in HEADERS[kind]}
            for kind, index in columns.items()
            if index is not None
        )
        hits = core.value_match_score(data.iloc[:, columns["can"]], known_can, True)
        candidates.append((hints * 100 + hits, -row, columns))
    if not candidates:
        raise RuntimeError(
            f"Cannot detect mapping columns in sheet {sheet!r}; specify --header-row, --element-column and --can-column."
        )
    _, negative_row, columns = max(candidates, key=lambda item: item[:2])
    header = -negative_row
    core.log(
        f"  Excel sheet={sheet!r}, header={header + 1}, columns="
        + ", ".join(f"{key}:{index + 1}" for key, index in columns.items() if index is not None)
    )
    records = []
    current_interface = ""
    skipped = 0
    for row in range(header + 1, len(raw)):
        values = {
            kind: cell(raw.iat[row, index]) if index is not None else ""
            for kind, index in columns.items()
        }
        if values["interface"]:
            current_interface = values["interface"]
        if excluded.iat[row]:
            skipped += 1
            continue
        source = values["can"]
        target = values["element"] or source
        if not target:
            continue
        interface = current_interface
        if "." in target:
            interface, target = target.rsplit(".", 1)
        if core.norm(source) not in known_can and core.norm(core.last_token(source)) in known_can:
            source = core.last_token(source)
        records.append((interface, target, source, values["dtype"]))
    if skipped:
        core.log(f"  Excel sheet={sheet!r}: skipped {skipped} row(s) matching excel_skip_keywords.")
    return records


def add_target(interfaces: list[dict[str, Any]], interface: str, element: str, dtype: str) -> None:
    if not core.is_valid_matlab_identifier(interface) or not core.is_valid_matlab_identifier(
        element
    ):
        raise RuntimeError(
            f"Mapping target must use valid MATLAB identifiers: {interface}.{element}"
        )
    bus = next(
        (item for item in interfaces if core.norm(item["name"]) == core.norm(interface)), None
    )
    if bus is None:
        bus = {"name": interface, "elements": []}
        interfaces.append(bus)
    existing = next(
        (item for item in bus["elements"] if core.norm(item["name"]) == core.norm(element)), None
    )
    if existing:
        if dtype and core.normalize_dtype(existing["dataType"]) != core.normalize_dtype(dtype):
            raise RuntimeError(f"Conflicting datatype for {interface}.{element}")
    else:
        bus["elements"].append({"name": element, "dataType": dtype or "double"})


def safe_name(name: str, used: set[str]) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not name or not name[0].isalpha():
        name = "Signal_" + name
    base = name[:63]
    result, index = base, 2
    while core.norm(result) in used:
        suffix = f"_{index}"
        result = base[: 63 - len(suffix)] + suffix
        index += 1
    used.add(core.norm(result))
    return result


def infer_dbc(setup: MappingSetup, candidates: dict[str, list[core.DbcCandidate]]) -> None:
    buses, used_buses, used_elements = {}, set(), {}
    for entries in list(candidates.values()):
        for candidate in entries:
            key = (
                candidate.dbc_file,
                candidate.message_name,
                candidate.frame_id,
                candidate.is_extended,
            )
            if key not in buses:
                buses[key] = safe_name(candidate.message_name, used_buses)
                used_elements[key] = set()
            bus = buses[key]
            element = safe_name(candidate.signal_name, used_elements[key])
            add_target(setup.interfaces, bus, element, "double")
            # Keep same-named signals from different DBC messages independent.
            alias = "blf2mat" + hashlib.sha256(repr(candidate.key).encode()).hexdigest()
            if alias in candidates:
                raise RuntimeError("Internal DBC decode key collision")
            candidates[alias] = [candidate]
            setup.input_specific[(core.norm(bus), core.norm(element))] = alias
            if bus not in setup.input_names:
                setup.input_names.append(bus)


def resolve_setup(
    paths: core.SelectedPaths,
    candidates: dict[str, list[core.DbcCandidate]],
    names: set[str],
    mappings: list[core.InputCanMapping],
    forces: list[core.InputForce],
    excel_skip_keywords: tuple[str, ...] = (),
) -> MappingSetup:
    sided = bool(paths.input_schema or paths.output_schema)
    side_interfaces = {
        side: core.load_signal_schema([path]) if path else []
        for side, path in (("input", paths.input_schema), ("output", paths.output_schema))
    }
    if sided and not paths.excel:
        # Keep complete definitions independent, even for shared interface/element names.
        setup = MappingSetup(
            interfaces=side_interfaces["input"] + side_interfaces["output"],
            input_interfaces=side_interfaces["input"],
            output_interfaces=side_interfaces["output"],
        )
        for side, interfaces in side_interfaces.items():
            setattr(setup, side + "_names", [bus["name"] for bus in interfaces])
            setattr(
                setup,
                side + "_elements",
                {
                    core.norm(element["name"]): element["name"]
                    for bus in interfaces
                    for element in bus["elements"]
                },
            )
        return setup
    setup = MappingSetup(
        interfaces=(side_interfaces["input"] + side_interfaces["output"])
        if sided
        else core.load_signal_schema(paths.schema_files)
        if paths.schema_files
        else []
    )
    schema_supplied = bool(paths.schema_files)
    known_elements = {
        core.norm(element["name"]) for bus in setup.interfaces for element in bus["elements"]
    }
    if paths.excel:
        with core.pd.ExcelFile(paths.excel, engine="openpyxl") as book:
            explicit = bool(paths.input_sheets or paths.output_sheets)
            if explicit:
                inputs = [core.resolve_excel_sheet_name(book, name) for name in paths.input_sheets]
                outputs = [
                    core.resolve_excel_sheet_name(book, name) for name in paths.output_sheets
                ]
            elif {"swc_inf", "swc_outf"} <= {name.lower() for name in book.sheet_names}:
                # Compatibility alias only; no project naming is required.
                inputs = [core.resolve_excel_sheet_name(book, "SWC_INF")]
                outputs = [core.resolve_excel_sheet_name(book, "SWC_OUTF")]
            else:
                inputs, outputs = list(book.sheet_names), []
            count = 0
            for side, sheets in (("input", inputs), ("output", outputs)):
                definitions = side_interfaces[side] if sided else setup.interfaces
                specific = getattr(setup, side + "_specific")
                selected_names = getattr(setup, side + "_names")
                for sheet in sheets:
                    try:
                        records = read_sheet(
                            book,
                            sheet,
                            paths,
                            known_elements,
                            {core.norm(name) for name in names},
                            excel_skip_keywords,
                        )
                    except RuntimeError as exc:
                        if (
                            explicit
                            or paths.header_row
                            or any(
                                (
                                    paths.element_column,
                                    paths.can_column,
                                    paths.interface_column,
                                    paths.dtype_column,
                                )
                            )
                        ):
                            raise
                        core.log(f"  [WARN] Skip non-mapping sheet {sheet!r}: {exc}")
                        continue
                    for interface, element, source, dtype in records:
                        if schema_supplied:
                            owners = [
                                bus
                                for bus in definitions
                                if (not interface or core.norm(bus["name"]) == core.norm(interface))
                                and any(
                                    core.norm(item["name"]) == core.norm(element)
                                    for item in bus["elements"]
                                )
                            ]
                            if not owners:
                                continue
                            if len(owners) != 1:
                                raise RuntimeError(
                                    f"Ambiguous schema element {element!r}; provide an interface column or qualified target."
                                )
                            interface = owners[0]["name"]
                        else:
                            interface = interface or "Signals"
                        add_target(definitions, interface, element, dtype)
                        key = (core.norm(interface), core.norm(element))
                        if key in specific and specific[key] != source:
                            raise RuntimeError(
                                f"Conflicting Excel mapping for {interface}.{element}"
                            )
                        specific[key] = source
                        if interface not in selected_names:
                            selected_names.append(interface)
                        count += 1
            if not count:
                raise RuntimeError(
                    "No mapping rows were resolved from the selected workbook/schema."
                )
    elif setup.interfaces:
        setup.input_names = [bus["name"] for bus in setup.interfaces]
        setup.input_elements = {
            core.norm(element["name"]): element["name"]
            for bus in setup.interfaces
            for element in bus["elements"]
        }
    elif candidates and not (mappings or forces):
        infer_dbc(setup, candidates)
    for item in [*mappings, *forces]:
        if not schema_supplied:
            add_target(setup.interfaces, item.interface, item.element, "")
        if item.interface not in setup.input_names:
            setup.input_names.append(item.interface)
    if sided:
        # Explicit TXT sides also constrain Excel mappings to the declared targets.
        setup.input_interfaces = side_interfaces["input"]
        setup.output_interfaces = side_interfaces["output"]
    return setup
