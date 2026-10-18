"""Shared conversion engine, migrated from the original CLI implementation."""

from __future__ import annotations

import ast
import math
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Third-party packages are loaded after CLI parsing so --help works even when
# runtime packages have not been installed yet.
np: Any = None
pd: Any = None
savemat: Any = None
can: Any = None
cantools: Any = None
yaml: Any = None


def load_runtime_dependencies() -> None:
    global np, pd, savemat, can, cantools, yaml

    try:
        import can as _can
        import cantools as _cantools
        import numpy as _np
        import pandas as _pd
        import yaml as _yaml
        from scipy.io import savemat as _savemat
    except ImportError as exc:
        missing = getattr(exc, "name", None) or str(exc)
        raise RuntimeError(
            f"Missing Python dependency: {missing}\n"
            "Install requirements with:\n"
            "  python -m pip install python-can cantools pandas openpyxl scipy pyyaml"
        ) from exc

    np = _np
    pd = _pd
    savemat = _savemat
    can = _can
    cantools = _cantools
    yaml = _yaml


# -----------------------------------------------------------------------------
# Behavior
# -----------------------------------------------------------------------------

PREPEND_ZERO_TO_INPUT = True
INPUT_ZERO_TIME_EPS = 1e-12
MIN_FALLBACK_DURATION_S = 1.0
EXCEL_HEADER_SCAN_ROWS = 20

# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

_log_callback: ContextVar[Callable[[str], None] | None] = ContextVar("log_callback", default=None)


def log(msg: str = "") -> None:
    callback = _log_callback.get()
    if callback is None:
        print(msg, flush=True)
    else:
        callback(msg)


def start_step(index: int, total: int, title: str) -> float:
    """Print one compact phase header and return its start time."""
    log(f"\n[{index}/{total}] {title}")
    return time.perf_counter()


def finish_step(started_at: float, summary: str) -> None:
    log(f"  OK | {summary} | {time.perf_counter() - started_at:.2f}s")


def norm(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def last_token(s: Any) -> str:
    if s is None:
        return ""
    text = str(s).strip()
    if not text:
        return ""
    parts = re.split(r"[./\\:]", text)
    return parts[-1].strip()


def is_valid_matlab_identifier(name: str) -> bool:
    # MATLAB identifiers: start with a letter, then letters/digits/underscore.
    # namelengthmax is 63 in current MATLAB releases.
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", name))


def safe_default_value(dtype: str) -> float | int | bool:
    dt = normalize_dtype(dtype)
    if dt == "boolean":
        return False
    return 0


def normalize_dtype(dtype: str) -> str:
    dt = str(dtype or "double").strip().lower()
    aliases = {
        "bool": "boolean",
        "logical": "boolean",
        "boolean_t": "boolean",
        "real32_t": "single",
        "float32": "single",
        "float": "single",
        "real64_t": "double",
        "float64": "double",
        "uint8_t": "uint8",
        "uint16_t": "uint16",
        "uint32_t": "uint32",
        "uint64_t": "uint64",
        "int8_t": "int8",
        "int16_t": "int16",
        "int32_t": "int32",
        "int64_t": "int64",
    }
    return aliases.get(dt, dt)


_WARNED_DTYPES: set[str] = set()


def cast_signal_data(values: Any, dtype: str) -> Any:
    """Cast decoded physical values to the datatype declared by the TXT schema.

    Integer conversion intentionally rounds to nearest with halves away from
    zero, then saturates to the destination range. This is much closer to
    MATLAB numeric casts than NumPy's default truncation/wrap behavior.
    """
    arr = np.asarray(values)
    dt = normalize_dtype(dtype)

    if dt == "boolean":
        return np.asarray(arr != 0, dtype=np.bool_)
    if dt == "double":
        return np.asarray(arr, dtype=np.float64)
    if dt == "single":
        return np.asarray(arr, dtype=np.float32)

    np_type_by_name = {
        "uint8": np.uint8,
        "uint16": np.uint16,
        "uint32": np.uint32,
        "uint64": np.uint64,
        "int8": np.int8,
        "int16": np.int16,
        "int32": np.int32,
        "int64": np.int64,
    }
    if dt in np_type_by_name:
        target = np_type_by_name[dt]
        work = np.asarray(arr, dtype=np.float64)
        work = np.nan_to_num(work, nan=0.0, posinf=0.0, neginf=0.0)
        work = np.sign(work) * np.floor(np.abs(work) + 0.5)
        limits = np.iinfo(target)
        work = np.clip(work, limits.min, limits.max)
        return work.astype(target)

    if dt not in _WARNED_DTYPES:
        _WARNED_DTYPES.add(dt)
        log(
            f"  [WARN DATATYPE] Unsupported pure-Python datatype '{dtype}'. "
            "Data will be stored as double."
        )
    return np.asarray(arr, dtype=np.float64)


# -----------------------------------------------------------------------------
# CLI + YAML mapping config
# -----------------------------------------------------------------------------


@dataclass
class SelectedPaths:
    excel: Path | None
    dbc_folder: Path | None
    blf_files: list[Path]
    schema_files: list[Path]
    output_folder: Path
    mapping_config: Path | None
    matlab_exe: Path | None
    output_format: str = "mat"
    input_sheets: tuple[str, ...] = ()
    output_sheets: tuple[str, ...] = ()
    element_column: str | None = None
    can_column: str | None = None
    interface_column: str | None = None
    dtype_column: str | None = None
    header_row: int | None = None


@dataclass(frozen=True)
class InputCanMapping:
    interface: str
    element: str
    can_signal: str
    formula: str = ""
    status_mapping: dict[float, float] | None = None

    @property
    def target_key(self) -> tuple[str, str]:
        return norm(self.interface), norm(self.element)

    @property
    def target_name(self) -> str:
        return f"{self.interface}.{self.element}"


@dataclass(frozen=True)
class InputForce:
    """Constant value for an input element that is not sourced from CAN."""

    interface: str
    element: str
    value: float

    @property
    def target_key(self) -> tuple[str, str]:
        return norm(self.interface), norm(self.element)

    @property
    def target_name(self) -> str:
        return f"{self.interface}.{self.element}"


def load_input_mapping_config(
    config_path: Path | None,
) -> tuple[list[InputCanMapping], list[InputForce]]:
    """Load input CAN mappings and non-CAN constant forces from YAML.

    ``input_mappings`` maps an Interface.DataElement to a CAN signal, with
    optional status/formula transforms.

    ``input_forces`` sets a constant model value for inputs that are NOT
    sourced from CAN. A forced input bypasses CAN decoding and is held constant
    over the entire BLF/simulation duration.
    """
    if config_path is None:
        return [], []

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid YAML mapping config {config_path}: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RuntimeError("Mapping config root must be a YAML mapping/object.")

    entries = raw.get("input_mappings", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise RuntimeError("'input_mappings' must be a YAML list.")

    mappings: list[InputCanMapping] = []
    seen_mapping_targets: set[tuple[str, str]] = set()

    for idx, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"input_mappings[{idx}] must be a YAML mapping/object.")
        if item.get("enabled", True) is False:
            continue

        interface = str(item.get("interface", "") or "").strip()
        element = str(item.get("element", "") or "").strip()
        can_signal = str(item.get("can_signal", "") or "").strip()
        formula = str(item.get("formula", "") or "").strip()
        status_mapping = parse_status_mapping(
            item.get("status_mapping", None),
            f"input_mappings[{idx}].status_mapping",
        )

        if not interface or not element or not can_signal:
            raise RuntimeError(
                f"input_mappings[{idx}] requires non-empty "
                "'interface', 'element', and 'can_signal'."
            )

        if formula:
            validate_signal_formula(formula)

        mapping = InputCanMapping(
            interface=interface,
            element=element,
            can_signal=can_signal,
            formula=formula,
            status_mapping=status_mapping,
        )
        if mapping.target_key in seen_mapping_targets:
            raise RuntimeError(
                f"Duplicate input mapping target in YAML: {mapping.target_name}. "
                "Each Interface.Element can have only one configured CAN source."
            )
        seen_mapping_targets.add(mapping.target_key)
        mappings.append(mapping)

    force_entries = raw.get("input_forces", [])
    if force_entries is None:
        force_entries = []
    if not isinstance(force_entries, list):
        raise RuntimeError("'input_forces' must be a YAML list.")

    forces: list[InputForce] = []
    seen_force_targets: set[tuple[str, str]] = set()

    for idx, item in enumerate(force_entries, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"input_forces[{idx}] must be a YAML mapping/object.")
        if item.get("enabled", True) is False:
            continue

        interface = str(item.get("interface", "") or "").strip()
        element = str(item.get("element", "") or "").strip()
        raw_value = item.get("value", None)

        if not interface or not element:
            raise RuntimeError(f"input_forces[{idx}] requires non-empty 'interface' and 'element'.")
        if raw_value is None or raw_value == "":
            raise RuntimeError(f"input_forces[{idx}] requires numeric 'value'.")

        if isinstance(raw_value, bool):
            value = float(int(raw_value))
        else:
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"input_forces[{idx}].value must be numeric, got {raw_value!r}."
                ) from exc

        if not math.isfinite(value):
            raise RuntimeError(f"input_forces[{idx}].value must be finite, got {raw_value!r}.")

        force = InputForce(interface=interface, element=element, value=value)
        if force.target_key in seen_force_targets:
            raise RuntimeError(f"Duplicate input force target in YAML: {force.target_name}.")
        if force.target_key in seen_mapping_targets:
            raise RuntimeError(
                "Input target is configured in both input_mappings and input_forces: "
                f"{force.target_name}. input_forces is only for non-CAN inputs."
            )

        seen_force_targets.add(force.target_key)
        forces.append(force)

    return mappings, forces


# -----------------------------------------------------------------------------
# Optional CAN status -> model status mapping
# -----------------------------------------------------------------------------


def parse_status_mapping(value: Any, label: str = "status_mapping") -> dict[float, float]:
    """Parse a YAML mapping whose keys are CAN values and values are model values.

    Example:
        {"0": 0, "4": 1, "7": 2}

    means CAN values 0/4/7 are converted back to model statuses 0/1/2.
    Unlisted CAN values are preserved unchanged.
    """
    if value is None or value == "":
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(
            f'{label} must be a YAML mapping, for example {{"0": 0, "4": 1, "7": 2}}.'
        )

    result: dict[float, float] = {}
    for raw_src, raw_dst in value.items():
        try:
            src = float(str(raw_src).strip())
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{label} contains non-numeric CAN value key: {raw_src!r}") from exc

        if isinstance(raw_dst, bool):
            dst = float(int(raw_dst))
        else:
            try:
                dst = float(raw_dst)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"{label}[{raw_src!r}] must map to a numeric model value, got {raw_dst!r}."
                ) from exc

        if not math.isfinite(src) or not math.isfinite(dst):
            raise RuntimeError(
                f"{label} only supports finite numeric values; got {raw_src!r}: {raw_dst!r}."
            )
        if src in result:
            raise RuntimeError(f"{label} contains duplicate numeric CAN key {src:g}.")
        result[src] = dst

    return result


def apply_status_mapping(
    values: Any,
    status_mapping: dict[float, float],
    target_name: str,
) -> Any:
    """Convert decoded CAN status values back to model/application status values.

    Mapping direction is CAN -> model. Values not listed in the table are left
    unchanged and logged once, which allows partial status tables when desired.
    """
    x = np.asarray(values, dtype=np.float64)
    if x.size == 0 or not status_mapping:
        return x

    result = x.copy()
    matched = np.zeros(x.shape, dtype=bool)

    for can_value, model_value in status_mapping.items():
        mask = np.isclose(x, can_value, rtol=0.0, atol=1e-9)
        if np.any(mask):
            result[mask] = model_value
            matched |= mask

    if not np.all(matched):
        unmapped = np.unique(x[~matched])
        preview = ", ".join(f"{float(v):g}" for v in unmapped[:10])
        suffix = " ..." if unmapped.size > 10 else ""
        log(
            f"  [WARN] {target_name}: status_mapping has no entry for CAN value(s): "
            f"{preview}{suffix}; keeping original value(s)."
        )

    return result


# -----------------------------------------------------------------------------
# Safe per-signal arithmetic formulas
# -----------------------------------------------------------------------------

_ALLOWED_FORMULA_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
_ALLOWED_FORMULA_UNARYOPS = (ast.UAdd, ast.USub)


def _normalize_signal_formula(formula: str) -> str:
    """Convert shorthand such as '*1000' into a normal expression 'x*1000'."""
    expr = str(formula or "").strip()
    if not expr:
        return ""

    # Convenient mapping syntax:
    #   *1000   -> x*1000
    #   /10     -> x/10
    #   +5      -> x+5
    #   -2.5    -> x-2.5
    if expr[0] in "+-*/%":
        expr = "x" + expr
    return expr


def _parse_signal_formula(formula: str) -> ast.Expression:
    expr = _normalize_signal_formula(formula)
    if not expr:
        raise ValueError("formula is empty")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid formula syntax: {formula!r}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Expression):
            continue
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_FORMULA_BINOPS):
                raise ValueError(f"operator is not allowed in formula: {formula!r}")
            continue
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_FORMULA_UNARYOPS):
                raise ValueError(f"unary operator is not allowed in formula: {formula!r}")
            continue
        if isinstance(node, ast.Name):
            if node.id != "x":
                raise ValueError(f"only variable 'x' is allowed in formula: {formula!r}")
            continue
        if isinstance(node, ast.Load):
            continue
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(f"only numeric constants are allowed in formula: {formula!r}")
            continue
        if isinstance(node, _ALLOWED_FORMULA_BINOPS + _ALLOWED_FORMULA_UNARYOPS):
            continue
        raise ValueError(f"unsupported expression in formula {formula!r}: {type(node).__name__}")

    return tree


def validate_signal_formula(formula: str) -> None:
    try:
        _parse_signal_formula(formula)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid signal formula {formula!r}. Supported examples: "
            "'*1000', '/10', '+5', '-2.5', 'x*1000+5'. "
            f"Details: {exc}"
        ) from exc


def _eval_signal_formula_node(node: ast.AST, x: Any) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_signal_formula_node(node.body, x)
    if isinstance(node, ast.Name):
        return x
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.UnaryOp):
        value = _eval_signal_formula_node(node.operand, x)
        if isinstance(node.op, ast.UAdd):
            return +value
        if isinstance(node.op, ast.USub):
            return -value
    if isinstance(node, ast.BinOp):
        left = _eval_signal_formula_node(node.left, x)
        right = _eval_signal_formula_node(node.right, x)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left**right
    raise RuntimeError(f"Unsupported formula node: {type(node).__name__}")


def apply_signal_formula(values: Any, formula: str, target_name: str) -> Any:
    """Apply a validated arithmetic transform before datatype conversion."""
    tree = _parse_signal_formula(formula)
    x = np.asarray(values, dtype=np.float64)
    try:
        with np.errstate(all="ignore"):
            result = _eval_signal_formula_node(tree, x)
        result = np.asarray(result, dtype=np.float64)
        if result.ndim == 0:
            result = np.full(x.shape, float(result), dtype=np.float64)
        else:
            result = np.broadcast_to(result, x.shape).astype(np.float64, copy=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to apply formula {formula!r} to {target_name}: {exc}") from exc

    if not np.all(np.isfinite(result)):
        raise RuntimeError(f"Formula {formula!r} produced NaN/Inf for {target_name}.")
    return result


# -----------------------------------------------------------------------------
# TXT schema
# -----------------------------------------------------------------------------

_SCHEMA_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")


def _strip_schema_inline_comment(line: str) -> str:
    # Keep it conservative: only # is treated as an inline comment marker.
    # Lines starting with // or % are also comments.
    stripped = line.strip()
    if stripped.startswith("//") or stripped.startswith("%"):
        return ""
    return line.split("#", 1)[0].strip()


def load_signal_schema(schema_files: list[Path]) -> list[dict[str, Any]]:
    """Read Interface.Element : datatype files and create interface metadata.

    Dimension is always 1. Duplicate identical lines are accepted. A duplicate
    Interface.Element with different datatypes is rejected.
    """
    interfaces_by_key: dict[str, dict[str, Any]] = {}
    elements_by_target: dict[tuple[str, str], dict[str, Any]] = {}
    source_by_target: dict[tuple[str, str], tuple[Path, int]] = {}

    for schema_path in schema_files:
        try:
            text = schema_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = schema_path.read_text(encoding="cp1252")

        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = _strip_schema_inline_comment(raw_line)
            if not line:
                continue

            m = _SCHEMA_RE.match(line)
            if not m:
                raise RuntimeError(
                    f"Invalid schema line in {schema_path}:{line_no}\n"
                    f"  {raw_line}\n"
                    "Expected: Interface.Element : datatype"
                )

            interface_name, element_name, dtype = m.groups()
            dtype = dtype.strip()
            if not dtype:
                raise RuntimeError(f"Empty datatype in {schema_path}:{line_no}: {raw_line}")

            if not is_valid_matlab_identifier(interface_name):
                raise RuntimeError(
                    f"Invalid MATLAB interface identifier in {schema_path}:{line_no}: "
                    f"{interface_name}"
                )
            if not is_valid_matlab_identifier(element_name):
                raise RuntimeError(
                    f"Invalid MATLAB element identifier in {schema_path}:{line_no}: {element_name}"
                )

            ik = norm(interface_name)
            ek = norm(element_name)
            target = (ik, ek)

            if target in elements_by_target:
                old = elements_by_target[target]
                if normalize_dtype(old["dataType"]) != normalize_dtype(dtype):
                    old_path, old_line = source_by_target[target]
                    raise RuntimeError(
                        "Conflicting datatype for the same schema target:\n"
                        f"  {interface_name}.{element_name}\n"
                        f"  {old_path}:{old_line} -> {old['dataType']}\n"
                        f"  {schema_path}:{line_no} -> {dtype}"
                    )
                continue

            if ik not in interfaces_by_key:
                interfaces_by_key[ik] = {
                    "name": interface_name,
                    "elements": [],
                }

            elem = {
                "name": element_name,
                "dataType": dtype,
            }
            interfaces_by_key[ik]["elements"].append(elem)
            elements_by_target[target] = elem
            source_by_target[target] = (schema_path, line_no)

    interfaces = list(interfaces_by_key.values())
    if not interfaces:
        raise RuntimeError("No valid Interface.Element entries were found in TXT schema.")

    return interfaces


# -----------------------------------------------------------------------------
# DBC loading
# -----------------------------------------------------------------------------


@dataclass
class DbcCandidate:
    dbc_file: str
    message_name: str
    frame_id: int
    is_extended: bool
    signal_name: str
    message_obj: Any

    @property
    def key(self) -> tuple[str, str, int, bool, str]:
        return (
            self.dbc_file,
            self.message_name,
            self.frame_id,
            self.is_extended,
            self.signal_name,
        )


def load_dbc_folder(
    folder: Path,
) -> tuple[dict[str, list[DbcCandidate]], set[str]]:
    """Load one DBC file or all DBC files recursively from a folder."""
    dbc_paths = (
        [folder]
        if folder.is_file()
        else sorted(
            path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() == ".dbc"
        )
    )
    if not dbc_paths:
        raise RuntimeError(f"No .dbc file found under:\n{folder}")

    dbs: list[tuple[Path, Any]] = []
    signal_candidates: dict[str, list[DbcCandidate]] = defaultdict(list)
    all_signal_names: set[str] = set()

    for p in dbc_paths:
        try:
            db = cantools.database.load_file(str(p), strict=False)
            dbs.append((p, db))
        except Exception as exc:
            log(f"  [WARN] Skip DBC {p.name}: {exc}")

    if not dbs:
        raise RuntimeError("No DBC file could be loaded.")

    for p, db in dbs:
        for msg in db.messages:
            for sig in msg.signals:
                all_signal_names.add(sig.name)
                signal_candidates[norm(sig.name)].append(
                    DbcCandidate(
                        dbc_file=str(p),
                        message_name=msg.name,
                        frame_id=int(msg.frame_id),
                        is_extended=bool(msg.is_extended_frame),
                        signal_name=sig.name,
                        message_obj=msg,
                    )
                )

    total_messages = sum(len(db.messages) for _, db in dbs)
    log(
        f"  DBC loaded: {len(dbs)}/{len(dbc_paths)} file(s), "
        f"{total_messages} message(s), {len(all_signal_names)} unique signal(s)"
    )
    return signal_candidates, all_signal_names


# -----------------------------------------------------------------------------
# Excel mapping detector
# -----------------------------------------------------------------------------


def value_match_score(
    series: pd.Series,
    known_norms: set[str],
    take_last_token: bool = False,
) -> int:
    hits = 0
    for v in series.dropna().astype(str):
        n = norm(last_token(v) if take_last_token else v)
        if n and n in known_norms:
            hits += 1
    return hits


def resolve_excel_sheet_name(excel_file: Any, requested_sheet: str) -> str:
    by_norm = {str(s).strip().lower(): str(s) for s in excel_file.sheet_names}
    key = requested_sheet.strip().lower()
    if key not in by_norm:
        available = ", ".join(excel_file.sheet_names)
        raise RuntimeError(
            f"Sheet '{requested_sheet}' was not found in Excel.\nAvailable sheets: {available}"
        )
    return by_norm[key]


def interfaces_from_names(
    all_interfaces: list[dict[str, Any]],
    interface_names: Iterable[str],
) -> list[dict[str, Any]]:
    by_norm = {norm(str(i.get("name", ""))): i for i in all_interfaces if i.get("name")}
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in interface_names:
        key = norm(name)
        if key and key in by_norm and key not in seen:
            matched.append(by_norm[key])
            seen.add(key)
    return matched


def select_input_interfaces(
    all_interfaces: list[dict[str, Any]],
    excel_matched_interfaces: list[dict[str, Any]],
    config_mappings: list[InputCanMapping],
    input_forces: list[InputForce],
) -> list[dict[str, Any]]:
    by_norm = {norm(str(i.get("name", ""))): i for i in all_interfaces if i.get("name")}

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Include interfaces represented by the selected input sheets, in workbook order.
    for intf in excel_matched_interfaces:
        k = norm(intf.get("name", ""))
        if k and k not in seen:
            selected.append(intf)
            seen.add(k)

    # Include interfaces referenced only by YAML CAN overrides.
    for m in config_mappings:
        k = norm(m.interface)
        if k in by_norm and k not in seen:
            selected.append(by_norm[k])
            seen.add(k)

    # Include interfaces referenced only by YAML constant forces.
    for force in input_forces:
        k = norm(force.interface)
        if k in by_norm and k not in seen:
            selected.append(by_norm[k])
            seen.add(k)

    return selected


def apply_input_mapping_config(
    input_interfaces: list[dict[str, Any]],
    interface_element_to_can: dict[tuple[str, str], str],
    signal_candidates: dict[str, list[DbcCandidate]],
    mappings: list[InputCanMapping],
) -> None:
    if not mappings:
        return

    available_targets: set[tuple[str, str]] = set()
    canonical_target_names: dict[tuple[str, str], str] = {}

    for intf in input_interfaces:
        intf_name = str(intf.get("name", ""))
        for elem in intf.get("elements", []) or []:
            elem_name = str(elem.get("name", ""))
            key = (norm(intf_name), norm(elem_name))
            available_targets.add(key)
            canonical_target_names[key] = f"{intf_name}.{elem_name}"

    log(f"  YAML CAN overrides: {len(mappings)}")
    for mapping in mappings:
        target = mapping.target_key
        if target not in available_targets:
            raise RuntimeError(
                f"Configured input target does not exist in signal definitions:\n  {mapping.target_name}"
            )

        candidates = list(signal_candidates.get(norm(mapping.can_signal), []))
        if not candidates:
            raise RuntimeError(
                "Configured CAN signal was not found in loaded DBC files:\n"
                f"  Target     : {mapping.target_name}\n"
                f"  CAN signal : {mapping.can_signal}"
            )

        interface_element_to_can[target] = mapping.can_signal
        canonical_target = canonical_target_names.get(target, mapping.target_name)
        status_text = (
            f" | status_mapping={len(mapping.status_mapping)} entries"
            if mapping.status_mapping
            else ""
        )
        formula_text = f" | formula={mapping.formula}" if mapping.formula else ""
        if mapping.status_mapping or mapping.formula or len(candidates) > 1:
            log(
                f"    {canonical_target} <- {mapping.can_signal}"
                f"{status_text}{formula_text} | DBC candidates={len(candidates)}"
            )


def validate_input_forces(
    input_interfaces: list[dict[str, Any]],
    interface_element_to_can: dict[tuple[str, str], str],
    forces: list[InputForce],
) -> None:
    """Validate constant forces. They are intentionally restricted to non-CAN inputs."""
    if not forces:
        return

    available_targets: set[tuple[str, str]] = set()
    canonical_target_names: dict[tuple[str, str], str] = {}
    for intf in input_interfaces:
        intf_name = str(intf.get("name", ""))
        for elem in intf.get("elements", []) or []:
            elem_name = str(elem.get("name", ""))
            key = (norm(intf_name), norm(elem_name))
            available_targets.add(key)
            canonical_target_names[key] = f"{intf_name}.{elem_name}"

    log(f"  Input forces: {len(forces)}")
    for force in forces:
        target = force.target_key
        if target not in available_targets:
            raise RuntimeError(
                "Configured input force target does not exist in signal definitions:\n"
                f"  {force.target_name}"
            )

        # Exact target CAN mapping means this input is CAN-backed. Do not silently
        # override it because input_forces is reserved for non-CAN inputs.
        exact_can = str(interface_element_to_can.get(target, "") or "").strip()
        if exact_can:
            raise RuntimeError(
                "input_forces can only be used for inputs that are not mapped to CAN:\n"
                f"  Target     : {force.target_name}\n"
                f"  CAN signal : {exact_can}\n"
                "Remove the CAN mapping or remove this input_force entry."
            )

        canonical_target = canonical_target_names.get(target, force.target_name)
        log(f"    {canonical_target} = {force.value:g}")


# -----------------------------------------------------------------------------
# BLF decoding
# -----------------------------------------------------------------------------


@dataclass
class CandidateSamples:
    candidate: DbcCandidate
    times_abs: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)


def collapse_duplicate_times(t: Any, y: Any) -> tuple[Any, Any]:
    if len(t) <= 1:
        return t, y

    order = np.argsort(t, kind="stable")
    t = t[order]
    y = y[order]

    _, rev_idx = np.unique(t[::-1], return_index=True)
    last_indices = len(t) - 1 - rev_idx
    last_indices.sort()
    return t[last_indices], y[last_indices]


def collect_can_signals(
    interfaces: list[dict[str, Any]],
    element_to_can: dict[str, str],
    interface_element_to_can: dict[tuple[str, str], str],
    skip_targets: set[tuple[str, str]] | None = None,
) -> set[str]:
    """Collect only CAN signals that can actually feed selected scenario elements."""
    skip_targets = skip_targets or set()
    signals: set[str] = set()
    for intf in interfaces:
        interface_name = str(intf.get("name", ""))
        for elem in intf.get("elements", []) or []:
            element_name = str(elem.get("name", ""))
            target = (norm(interface_name), norm(element_name))
            if target in skip_targets:
                continue
            can_signal = interface_element_to_can.get(
                target, element_to_can.get(norm(element_name), "")
            )
            if can_signal:
                signals.add(str(can_signal))
    return signals


def build_decode_requests(
    can_signals: Iterable[str],
    signal_candidates: dict[str, list[DbcCandidate]],
) -> dict[str, list[DbcCandidate]]:
    requests: dict[str, list[DbcCandidate]] = {}
    for can_signal in can_signals:
        key = norm(can_signal)
        if key and key not in requests:
            requests[key] = list(signal_candidates.get(key, []))
    return requests


def decode_blf(
    blf_path: Path,
    requests: dict[str, list[DbcCandidate]],
) -> tuple[dict[str, dict[str, Any]], float]:
    frame_tasks: dict[
        tuple[int, bool],
        dict[tuple[str, str, int, bool], dict[str, Any]],
    ] = defaultdict(dict)

    sample_store: dict[tuple[str, tuple[str, str, int, bool, str]], CandidateSamples] = {}

    for request_key, candidates in requests.items():
        for c in candidates:
            sample_store[(request_key, c.key)] = CandidateSamples(c)
            frame_key = (c.frame_id, c.is_extended)
            msg_key = (c.dbc_file, c.message_name, c.frame_id, c.is_extended)
            if msg_key not in frame_tasks[frame_key]:
                frame_tasks[frame_key][msg_key] = {
                    "message": c.message_obj,
                    "requests": [],
                }
            frame_tasks[frame_key][msg_key]["requests"].append((request_key, c))

    first_ts: float | None = None
    last_ts: float | None = None
    total_frames = 0
    decoded_frames = 0

    with can.BLFReader(str(blf_path)) as reader:
        for frame in reader:
            total_frames += 1

            ts = getattr(frame, "timestamp", None)
            if ts is None:
                continue
            ts = float(ts)
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)

            if getattr(frame, "is_error_frame", False) or getattr(frame, "is_remote_frame", False):
                continue

            frame_id = int(frame.arbitration_id)
            is_ext = bool(getattr(frame, "is_extended_id", False))
            tasks = frame_tasks.get((frame_id, is_ext))
            if not tasks:
                continue

            data = bytes(frame.data)

            for task in tasks.values():
                msg = task["message"]
                try:
                    values = msg.decode(
                        data,
                        decode_choices=False,
                        scaling=True,
                        allow_truncated=False,
                    )
                except Exception:
                    continue

                any_hit = False
                for request_key, cand in task["requests"]:
                    sig_name = cand.signal_name
                    if sig_name not in values:
                        continue
                    value = values[sig_name]
                    if not isinstance(value, (int, float, bool, np.number)):
                        continue
                    try:
                        fv = float(value)
                    except Exception:
                        continue

                    store = sample_store[(request_key, cand.key)]
                    store.times_abs.append(ts)
                    store.values.append(fv)
                    any_hit = True

                if any_hit:
                    decoded_frames += 1

    if first_ts is None:
        raise RuntimeError("BLF does not contain a CAN frame with a valid timestamp.")

    duration = max(
        MIN_FALLBACK_DURATION_S,
        (last_ts - first_ts) if last_ts is not None else 0.0,
    )

    selected: dict[str, dict[str, Any]] = {}

    for request_key, candidates in requests.items():
        ranked = []
        for c in candidates:
            store = sample_store[(request_key, c.key)]
            ranked.append((len(store.times_abs), c, store))
        ranked.sort(key=lambda x: x[0], reverse=True)

        if not ranked or ranked[0][0] == 0:
            selected[request_key] = {
                "status": "NO_BLF_SAMPLES" if candidates else "NOT_IN_DBC",
                "candidate_count": len(candidates),
                "samples": 0,
                "time": np.array([], dtype=np.float64),
                "data": np.array([], dtype=np.float64),
                "candidate": None,
            }
            continue

        _, candidate, store = ranked[0]
        t = np.asarray(store.times_abs, dtype=np.float64) - first_ts
        y = np.asarray(store.values, dtype=np.float64)
        t, y = collapse_duplicate_times(t, y)

        second_n = ranked[1][0] if len(ranked) > 1 else 0
        status = "DECODED"
        if len(candidates) > 1 and second_n > 0:
            status = "DECODED_AMBIGUOUS_DBC"

        selected[request_key] = {
            "status": status,
            "candidate_count": len(candidates),
            "samples": int(len(t)),
            "time": t,
            "data": y,
            "candidate": candidate,
        }

        if len(candidates) > 1:
            log(
                f"  [AUTO DBC] {candidate.signal_name} -> "
                f"{candidate.message_name} @ {Path(candidate.dbc_file).name} "
                f"({len(t)} samples, {len(candidates)} candidates)"
            )

    log(
        f"  BLF: {total_frames:,} frame(s), {decoded_frames:,} matched decode(s), "
        f"duration={duration:.3f}s, requested={len(requests)} signal(s)"
    )
    return selected, duration


# -----------------------------------------------------------------------------
# Scenario preparation + Dataset MAT packaging
# -----------------------------------------------------------------------------


@dataclass
class SideStats:
    interfaces: int = 0
    signals: int = 0
    decoded: int = 0
    forced: int = 0
    defaulted: int = 0
    no_mapping: int = 0
    not_in_dbc: int = 0
    no_blf_samples: int = 0
    ambiguous_dbc: int = 0


def build_mat_scenario(
    side_name: str,
    interfaces: list[dict[str, Any]],
    element_to_can: dict[str, str],
    interface_element_to_can: dict[tuple[str, str], str],
    decoded: dict[str, dict[str, Any]],
    duration: float,
    formulas_by_target: dict[tuple[str, str], str] | None = None,
    status_mappings_by_target: dict[tuple[str, str], dict[float, float]] | None = None,
    forces_by_target: dict[tuple[str, str], float] | None = None,
    prepend_zero: bool = True,
) -> tuple[dict[str, Any], SideStats]:
    scenario: dict[str, Any] = {}
    stats = SideStats()
    formulas_by_target = formulas_by_target or {}
    status_mappings_by_target = status_mappings_by_target or {}
    forces_by_target = forces_by_target or {}

    def lookup_can(interface_name: str, element_name: str) -> str:
        specific = (norm(interface_name), norm(element_name))
        if specific in interface_element_to_can:
            return interface_element_to_can[specific]
        return element_to_can.get(norm(element_name), "")

    for intf in interfaces:
        intf_name = str(intf.get("name", ""))
        intf_struct: dict[str, Any] = {}

        for elem in intf.get("elements", []) or []:
            elem_name = str(elem.get("name", ""))

            dtype = str(elem.get("dataType", "double") or "double")
            target_key = (norm(intf_name), norm(elem_name))
            target_name = f"{intf_name}.{elem_name}"
            is_input = side_name in ("input", "SWC_INF")
            is_forced = is_input and target_key in forces_by_target

            status = "NO_MAPPING"
            t = np.array([], dtype=np.float64)
            y = np.array([], dtype=np.float64)

            if is_forced:
                # input_forces is intentionally independent of CAN. Two ZOH samples
                # are sufficient to hold the value over the complete simulation.
                forced_value = float(forces_by_target[target_key])
                t = np.asarray([0.0, max(float(duration), 1e-9)], dtype=np.float64)
                y = np.asarray([forced_value, forced_value], dtype=np.float64)
                status = "FORCED"
                stats.forced += 1
            else:
                can_signal = lookup_can(intf_name, elem_name)
                info = decoded.get(norm(can_signal)) if can_signal else None

                if can_signal:
                    if info is None:
                        status = "NOT_IN_DBC"
                    else:
                        status = str(info.get("status", "NOT_IN_DBC"))
                        t = np.asarray(info.get("time", []), dtype=np.float64)
                        y = np.asarray(info.get("data", []), dtype=np.float64)

                if (
                    PREPEND_ZERO_TO_INPUT
                    and prepend_zero
                    and is_input
                    and t.size > 0
                    and y.size > 0
                    and float(t[0]) > INPUT_ZERO_TIME_EPS
                ):
                    t = np.insert(t, 0, 0.0)
                    y = np.insert(y, 0, 0.0)

                use_default = y.size == 0
                if use_default:
                    default = safe_default_value(dtype)
                    t = np.asarray([0.0, max(float(duration), 1e-9)], dtype=np.float64)
                    y = np.asarray([default, default], dtype=np.float64)
                    stats.defaulted += 1
                else:
                    stats.decoded += 1

                status_mapping = status_mappings_by_target.get(target_key, {})
                if status_mapping:
                    y = apply_status_mapping(y, status_mapping, target_name)

                formula = formulas_by_target.get(target_key, "")
                if formula:
                    y = apply_signal_formula(y, formula, target_name)

            typed_y = cast_signal_data(y, dtype).reshape(-1, 1)
            t = np.asarray(t, dtype=np.float64).reshape(-1, 1)

            # Keep the leaf intentionally simple and MATLAB-readable.
            intf_struct[elem_name] = {
                "Time": t,
                "Data": typed_y,
            }

            stats.signals += 1
            if status == "NO_MAPPING":
                stats.no_mapping += 1
            elif status == "NOT_IN_DBC":
                stats.not_in_dbc += 1
            elif status == "NO_BLF_SAMPLES":
                stats.no_blf_samples += 1
            elif status == "DECODED_AMBIGUOUS_DBC":
                stats.ambiguous_dbc += 1

        if intf_struct:
            scenario[intf_name] = intf_struct
            stats.interfaces += 1

    return scenario, stats


def matlab_quote(path_or_text: str) -> str:
    """Escape text for a MATLAB single-quoted character vector."""
    return str(path_or_text).replace("'", "''")


def save_raw_scenarios_mat(
    path: Path,
    input_scenario: dict[str, Any],
    output_scenario: dict[str, Any],
) -> None:
    """Write both prepared scenarios into one temporary MAT file."""
    if not input_scenario and not output_scenario:
        raise RuntimeError("At least one input/output raw scenario must be non-empty.")
    savemat(
        path,
        {
            "RawInputScenario": input_scenario,
            "RawOutputScenario": output_scenario,
        },
        do_compression=True,
        long_field_names=True,
    )


def make_dataset_packager_script(
    raw_mat: Path,
    input_mat: Path,
    output_mat: Path,
    script_path: Path,
) -> None:
    """Generate one MATLAB helper that packages both Dataset MAT files."""
    m = f"""
%% AUTO-GENERATED. Package both raw scenarios in one MATLAB session.
rawPath    = '{matlab_quote(str(raw_mat))}';
inputPath  = '{matlab_quote(str(input_mat))}';
outputPath = '{matlab_quote(str(output_mat))}';

S = load(rawPath, 'RawInputScenario', 'RawOutputScenario');
if ~isfield(S, 'RawInputScenario') || ~isfield(S, 'RawOutputScenario')
    error('Raw input/output scenario variables are missing from %s', rawPath);
end

Scenario = localBuildDataset(S.RawInputScenario);
save(inputPath, 'Scenario', '-v7.3');
inputCount = numElements(Scenario);

Scenario = localBuildDataset(S.RawOutputScenario);
save(outputPath, 'Scenario', '-v7.3');
outputCount = numElements(Scenario);

fprintf('[PACKAGER] input=%d output=%d\\n', inputCount, outputCount);

function Scenario = localBuildDataset(rawScenario)
    Scenario = Simulink.SimulationData.Dataset;
    Scenario.Name = 'Scenario';

    interfaceNames = fieldnames(rawScenario);
    for ii = 1:numel(interfaceNames)
        interfaceName = interfaceNames{{ii}};
        rawBus = rawScenario.(interfaceName);
        busValue = struct();

        elementNames = fieldnames(rawBus);
        for ee = 1:numel(elementNames)
            elementName = elementNames{{ee}};
            leaf = rawBus.(elementName);

            if ~isfield(leaf, 'Time') || ~isfield(leaf, 'Data')
                error('Invalid raw leaf: %s.%s', interfaceName, elementName);
            end

            t = double(leaf.Time(:));
            y = leaf.Data;
            if isvector(y) && numel(y) == numel(t)
                y = reshape(y, [], 1);
            end
            if size(y,1) ~= numel(t)
                error('Time/Data size mismatch for %s.%s: Time=%d, Data rows=%d', ...
                    interfaceName, elementName, numel(t), size(y,1));
            end

            ts = timeseries(y, t, 'Name', elementName);
            try
                ts.DataInfo.Interpolation = tsdata.interpolation('zoh');
            catch
                % Keep MATLAB default only if this metadata API differs.
            end
            busValue.(elementName) = ts;
        end

        Scenario = addElement(Scenario, busValue, interfaceName);
    end
end
"""
    script_path.write_text(m, encoding="utf-8")


def make_batch_dataset_packager_script(
    jobs: list[tuple[Path, Path | None, Path | None]], script_path: Path
) -> None:
    """Build all Dataset files in one MATLAB session, retaining original packager logic."""
    lines = ["%% AUTO-GENERATED BLF batch packager", "jobs = {"]
    for raw_mat, input_mat, output_mat in jobs:
        lines.append(
            f"    '{matlab_quote(str(raw_mat))}', "
            f"'{matlab_quote(str(input_mat)) if input_mat else ''}', "
            f"'{matlab_quote(str(output_mat)) if output_mat else ''}';"
        )
    lines += [
        "};",
        "for k = 1:size(jobs, 1)",
        "    S = load(jobs{k,1}, 'RawInputScenario', 'RawOutputScenario');",
        "    for side = 2:3",
        "        if isempty(jobs{k,side}), continue; end",
        "        if side == 2, raw = S.RawInputScenario; else, raw = S.RawOutputScenario; end",
        "        Scenario = localBuildDataset(raw);",
        "        save(jobs{k,side}, 'Scenario', '-v7.3');",
        "        fprintf('[PACKAGER] %d/%d side=%d elements=%d\\n', k, size(jobs,1), side, numElements(Scenario));",
        "    end",
        "end",
    ]
    # Reuse the established MATLAB localBuildDataset code verbatim.
    lines += [
        "function Scenario = localBuildDataset(rawScenario)",
        "    Scenario = Simulink.SimulationData.Dataset;",
        "    Scenario.Name = 'Scenario';",
        "    interfaceNames = fieldnames(rawScenario);",
        "    for ii = 1:numel(interfaceNames)",
        "        interfaceName = interfaceNames{ii};",
        "        rawBus = rawScenario.(interfaceName);",
        "        busValue = struct();",
        "        elementNames = fieldnames(rawBus);",
        "        for ee = 1:numel(elementNames)",
        "            elementName = elementNames{ee};",
        "            leaf = rawBus.(elementName);",
        "            if ~isfield(leaf, 'Time') || ~isfield(leaf, 'Data')",
        "                error('Invalid raw leaf: %s.%s', interfaceName, elementName);",
        "            end",
        "            t = double(leaf.Time(:));",
        "            y = leaf.Data;",
        "            if isvector(y) && numel(y) == numel(t)",
        "                y = reshape(y, [], 1);",
        "            end",
        "            if size(y,1) ~= numel(t)",
        "                error('Time/Data size mismatch for %s.%s', interfaceName, elementName);",
        "            end",
        "            ts = timeseries(y, t, 'Name', elementName);",
        "            try",
        "                ts.DataInfo.Interpolation = tsdata.interpolation('zoh');",
        "            catch",
        "            end",
        "            busValue.(elementName) = ts;",
        "        end",
        "        Scenario = addElement(Scenario, busValue, interfaceName);",
        "    end",
        "end",
    ]
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_matlab_batch(matlab_exe: Path, script_path: Path, cwd: Path) -> None:
    """Run one headless MATLAB process and keep successful output concise."""
    cmd = [
        str(matlab_exe),
        "-batch",
        f"run('{matlab_quote(str(script_path))}')",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    combined = "\n".join(
        part.strip() for part in (proc.stdout, proc.stderr) if part and part.strip()
    )
    if proc.returncode != 0:
        if combined:
            log("\n[MATLAB OUTPUT]")
            log(combined)
        raise RuntimeError(f"MATLAB Dataset packaging failed with exit code {proc.returncode}.")

    # On success, show only lines intentionally emitted by our packager.
    for line in combined.splitlines():
        if "[PACKAGER]" in line:
            log(f"  {line.strip()}")


def save_dataset_mats(
    matlab_exe: Path,
    input_mat: Path,
    output_mat: Path,
    input_scenario: dict[str, Any],
    output_scenario: dict[str, Any],
    workdir: Path,
) -> None:
    """Package input and output Dataset MAT files with exactly one MATLAB launch."""
    raw_mat = workdir / "raw_scenarios.mat"
    helper = workdir / "package_datasets.m"
    save_raw_scenarios_mat(raw_mat, input_scenario, output_scenario)
    make_dataset_packager_script(raw_mat, input_mat, output_mat, helper)
    run_matlab_batch(matlab_exe, helper, cwd=workdir)

    missing = [str(p) for p in (input_mat, output_mat) if not p.is_file()]
    if missing:
        raise RuntimeError(
            "MATLAB completed but expected Dataset MAT file(s) were not created:\n  "
            + "\n  ".join(missing)
        )


def print_side_summary(label: str, stats: SideStats) -> None:
    log(
        f"  {label:<8} interfaces={stats.interfaces}, signals={stats.signals}, "
        f"decoded={stats.decoded}, forced={stats.forced}, defaulted={stats.defaulted}"
    )
    issues = []
    for name, value in (
        ("no_mapping", stats.no_mapping),
        ("not_in_dbc", stats.not_in_dbc),
        ("no_blf_samples", stats.no_blf_samples),
        ("ambiguous_dbc", stats.ambiguous_dbc),
    ):
        if value:
            issues.append(f"{name}={value}")
    if issues:
        log(f"           warnings: {', '.join(issues)}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def _convert(paths: SelectedPaths) -> int:
    total_started = time.perf_counter()
    log("=" * 72)
    log(" BLF -> MAT")
    log("=" * 72)

    load_runtime_dependencies()
    paths.output_folder.mkdir(parents=True, exist_ok=True)
    input_mapping_config, input_forces = load_input_mapping_config(paths.mapping_config)

    log("\n[CONFIG]")
    log(f"  BLF    : {len(paths.blf_files)} file(s)")
    log(f"  Excel  : {paths.excel}")
    log(f"  DBC    : {paths.dbc_folder}")
    log(f"  Schema : {len(paths.schema_files)} file(s)")
    log(f"  YAML   : {paths.mapping_config if paths.mapping_config else '(none)'}")
    log(f"  Output : {paths.output_folder}")

    from .mapping import resolve_setup

    started = start_step(1, 5, "Load optional DBC definitions")
    signal_candidates, dbc_signal_names = (
        load_dbc_folder(paths.dbc_folder) if paths.dbc_folder else ({}, set())
    )
    finish_step(started, f"{len(dbc_signal_names)} unique CAN signal(s)")
    started = start_step(2, 5, "Resolve optional Excel/TXT/YAML mappings")
    setup = resolve_setup(
        paths, signal_candidates, dbc_signal_names, input_mapping_config, input_forces
    )
    all_interfaces = setup.interfaces
    input_interfaces = select_input_interfaces(
        all_interfaces,
        interfaces_from_names(all_interfaces, setup.input_names),
        input_mapping_config,
        input_forces,
    )
    output_interfaces = interfaces_from_names(all_interfaces, setup.output_names)
    in_elem_map, in_specific_map = setup.input_elements, setup.input_specific
    out_elem_map, out_specific_map = setup.output_elements, setup.output_specific
    if not input_interfaces and not output_interfaces and paths.output_format == "dataset":
        raise RuntimeError(
            "Dataset export needs signal definitions: supply DBC, Excel, TXT or YAML. Use --format mat for raw CAN frames."
        )

    apply_input_mapping_config(
        input_interfaces=input_interfaces,
        interface_element_to_can=in_specific_map,
        signal_candidates=signal_candidates,
        mappings=input_mapping_config,
    )
    validate_input_forces(
        input_interfaces=input_interfaces,
        interface_element_to_can=in_specific_map,
        forces=input_forces,
    )
    finish_step(
        started,
        f"IN={len(input_interfaces)} interface(s), OUT={len(output_interfaces)} interface(s), "
        f"YAML overrides={len(input_mapping_config)}, forces={len(input_forces)}",
    )

    input_forces_by_target = {force.target_key: force.value for force in input_forces}
    input_formulas = {
        mapping.target_key: mapping.formula for mapping in input_mapping_config if mapping.formula
    }
    input_status_mappings = {
        mapping.target_key: mapping.status_mapping
        for mapping in input_mapping_config
        if mapping.status_mapping
    }

    # Decode only signals that can feed selected interfaces. CAN signals replaced by
    # input_forces are excluded completely from BLF decode work.
    requested_signals = collect_can_signals(
        input_interfaces,
        in_elem_map,
        in_specific_map,
        skip_targets=set(input_forces_by_target),
    )
    requested_signals.update(collect_can_signals(output_interfaces, out_elem_map, out_specific_map))

    started = start_step(3, 5, "Decode all BLF files and prepare scenarios")
    decode_requests = build_decode_requests(requested_signals, signal_candidates)
    used_names: set[str] = set()
    packaged_files: list[tuple[Path | None, Path | None]] = []
    frame_files: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="signal_editor_dataset_") as td:
        workdir = Path(td)
        jobs: list[tuple[Path, Path | None, Path | None]] = []
        for index, blf_path in enumerate(paths.blf_files, start=1):
            log(f"\n  [BLF {index}/{len(paths.blf_files)}] {blf_path.name}")
            # Distinct subfolders can contain BLFs with identical stems.
            stem = blf_path.stem
            if stem.lower() in used_names:
                suffix = 2
                while f"{stem}_{suffix}".lower() in used_names:
                    suffix += 1
                stem = f"{stem}_{suffix}"
            used_names.add(stem.lower())
            if paths.dbc_folder:
                decoded, duration = decode_blf(blf_path, decode_requests)
            else:
                from .frames import export_frames

                frame_mat = paths.output_folder / f"{stem}.mat"
                duration = export_frames(blf_path, frame_mat)
                frame_files.append(frame_mat)
                decoded = {}

            input_scenario, input_stats = build_mat_scenario(
                side_name="input",
                interfaces=input_interfaces,
                element_to_can=in_elem_map,
                interface_element_to_can=in_specific_map,
                decoded=decoded,
                duration=duration,
                formulas_by_target=input_formulas,
                status_mappings_by_target=input_status_mappings,
                forces_by_target=input_forces_by_target,
                prepend_zero=bool(paths.excel or paths.schema_files),
            )
            output_scenario, output_stats = build_mat_scenario(
                side_name="output",
                interfaces=output_interfaces,
                element_to_can=out_elem_map,
                interface_element_to_can=out_specific_map,
                decoded=decoded,
                duration=duration,
            )
            inferred_only = paths.dbc_folder and not any(
                (paths.excel, paths.schema_files, input_mapping_config, input_forces)
            )
            input_suffix = "signals" if inferred_only else "input"
            input_mat = (
                paths.output_folder / f"{stem}_{input_suffix}.mat" if input_scenario else None
            )
            output_mat = paths.output_folder / f"{stem}_output.mat" if output_scenario else None
            if not input_scenario and not output_scenario:
                continue
            if paths.output_format == "mat":
                for target, scenario in (
                    (input_mat, input_scenario),
                    (output_mat, output_scenario),
                ):
                    if target:
                        savemat(
                            target,
                            {"Scenario": scenario},
                            do_compression=True,
                            long_field_names=True,
                        )
                packaged_files.append((input_mat, output_mat))
                print_side_summary("Input", input_stats)
                print_side_summary("Output", output_stats)
                continue
            raw_mat = workdir / f"raw_{index:05d}.mat"
            save_raw_scenarios_mat(raw_mat, input_scenario, output_scenario)
            jobs.append((raw_mat, input_mat, output_mat))
            packaged_files.append((input_mat, output_mat))
            print_side_summary("Input", input_stats)
            print_side_summary("Output", output_stats)
        finish_step(started, f"Prepared {len(paths.blf_files)} BLF file(s)")

        if jobs:
            started = start_step(5, 5, "Package Dataset MAT files (one MATLAB launch)")
            helper = workdir / "package_datasets.m"
            make_batch_dataset_packager_script(jobs, helper)
            run_matlab_batch(paths.matlab_exe, helper, cwd=workdir)
            missing = [str(p) for pair in packaged_files for p in pair if p and not p.is_file()]
            if missing:
                raise RuntimeError(
                    "MATLAB did not create expected MAT files:\n" + "\n".join(missing)
                )
            finish_step(started, f"{len(jobs)} scenario batch(es) packaged")

    log("\n[SUMMARY]")
    log(f"  BLF files : {len(paths.blf_files)}")
    log(f"  MAT files : {sum(bool(p) for pair in packaged_files for p in pair) + len(frame_files)}")
    log(f"  Output    : {paths.output_folder}")
    log(f"  Total     : {time.perf_counter() - total_started:.2f}s")
    log("  MATLAB    : " + ("1 headless -batch invocation" if jobs else "not required"))
    return 0


def convert(paths: SelectedPaths, log_callback: Callable[[str], None] | None = None) -> int:
    """Run the same conversion for CLI and GUI; callbacks stay local to this context."""
    token = _log_callback.set(log_callback)
    try:
        return _convert(paths)
    finally:
        _log_callback.reset(token)
