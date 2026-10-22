"""Command line, path validation and lazy GUI dispatch."""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from pathlib import Path

from . import __version__
from .converter import SelectedPaths, convert


def application_directory() -> Path:
    """Locate external config beside the archive, never inside a zip-import path."""
    entry = Path(sys.argv[0]).resolve()
    return entry.parent if entry.suffix.lower() == ".pyz" else Path.cwd()


def _existing_file(value: str, label: str, suffixes: tuple[str, ...] = ()) -> Path:
    p = Path(value).expanduser()
    if not p.is_file():
        raise argparse.ArgumentTypeError(f"{label} does not exist: {p}")
    if suffixes and p.suffix.lower() not in suffixes:
        allowed = ", ".join(suffixes)
        raise argparse.ArgumentTypeError(
            f"{label} must have one of these extensions: {allowed}. Got: {p}"
        )
    return p.resolve()


def _existing_dbc_source(value: str) -> Path:
    p = Path(value).expanduser()
    if p.is_dir():
        return p.resolve()
    return _existing_file(value, "DBC file or folder", (".dbc",))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blf-to-mat",
        description=(
            "Convert BLF logs to MAT. Only --blf is required. Optional DBC, Excel, "
            "TXT and YAML customize decoded signals. MATLAB is needed only for --format dataset."
        ),
        epilog=(
            "PowerShell example:\n"
            "  python .\\blf_to_mat.pyz `\n"
            "    --excel .\\Interface.xlsx `\n"
            "    --dbc-folder .\\DBC `\n"
            "    --blf .\\CAN_Log.blf `\n"
            "    --schema .\\InputSignals.txt .\\OutputSignals.txt `\n"
            "    --output .\\Output `\n"
            "    --config .\\signal_mapping.yaml `\n"
            '    --matlab "C:\\Program Files\\MATLAB\\R2024b\\bin\\matlab.exe"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-e",
        "--excel",
        required=False,
        metavar="FILE",
        help="Optional Excel mapping workbook; sheets and columns can be selected or detected.",
    )
    parser.add_argument(
        "-d",
        "--dbc",
        "--dbc-folder",
        dest="dbc_folder",
        required=False,
        metavar="FILE_OR_DIR",
        help="Optional .dbc file or folder searched recursively. --dbc-folder remains an alias.",
    )
    parser.add_argument(
        "-b",
        "--blf",
        required=False,
        metavar="FILE_OR_DIR",
        help="A single .blf file or a folder containing .blf files (including subfolders).",
    )
    parser.add_argument(
        "-s",
        "--schema",
        required=False,
        nargs="+",
        metavar="TXT",
        help=(
            "One or more TXT schema files. Format: Interface.Element : datatype. "
            "Dimension is fixed to 1."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        required=False,
        metavar="DIR",
        help="Output folder (default: mat_output beside the BLF file or inside the BLF folder).",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        metavar="FILE",
        help=(
            "Optional YAML with input CAN mappings, status/formula transforms, "
            "constant input_forces for non-CAN inputs, and excel_skip_keywords to skip rows "
            "containing any keyword in any cell (case-insensitive substring). If omitted, "
            "signal_mapping.yaml next to the .pyz (or in the working directory for source runs) is auto-loaded "
            "when present."
        ),
    )
    parser.add_argument(
        "--matlab",
        default=None,
        metavar="EXE",
        help=(
            "Path to matlab.exe. Optional when MATLAB is on PATH or installed "
            "under a common Windows MATLAB folder."
        ),
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("mat", "dataset"),
        default=None,
        help="mat: ordinary MAT without MATLAB (default); dataset: native Signal Editor Dataset. Explicit --matlab implies dataset unless --format is set.",
    )
    parser.add_argument(
        "--input-sheet",
        action="append",
        default=[],
        help="Input sheet name; repeat for multiple sheets. Default: detect mapping sheets.",
    )
    parser.add_argument(
        "--output-sheet",
        action="append",
        default=[],
        help="Output sheet name; repeat for multiple sheets.",
    )
    for option in ("element", "can", "interface", "dtype"):
        parser.add_argument(
            f"--{option}-column",
            help="Excel header name or 1-based column number; omitted columns are detected.",
        )
    parser.add_argument(
        "--header-row",
        type=int,
        help="1-based Excel header row (default: detect within the first 20 rows).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print full Python traceback when the tool fails.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--gui",
        action="store_true",
        help="Open the graphical interface (default with no arguments).",
    )
    mode.add_argument("--cli", action="store_true", help="Run conversion in the terminal.")
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check Python dependencies, Tcl/Tk and MATLAB discovery without launching MATLAB.",
    )
    return parser


def find_matlab_executable(explicit: str | None = None) -> Path:
    """Resolve MATLAB executable without any GUI/file dialog interaction."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise argparse.ArgumentTypeError(f"MATLAB executable does not exist: {p}")
        return p.resolve()

    for exe_name in ("matlab.exe", "matlab"):
        found = shutil.which(exe_name)
        if found:
            return Path(found).resolve()

    candidates: list[Path] = []
    roots_and_patterns = (
        (Path(r"C:\Program Files\MATLAB"), "R*/bin/matlab.exe"),
        (Path(r"C:\Program Files (x86)\MATLAB"), "R*/bin/matlab.exe"),
        (Path(r"C:\Tools"), "R*/bin/matlab.exe"),
        (Path(r"C:\Tools\MATLAB"), "R*/bin/matlab.exe"),
    )
    for root, pattern in roots_and_patterns:
        if root.exists():
            candidates.extend(root.glob(pattern))

    # Prefer newest release-like path when more than one installation exists.
    candidates = sorted({c.resolve() for c in candidates}, reverse=True)
    if candidates:
        return candidates[0]

    raise argparse.ArgumentTypeError(
        "MATLAB was not found. Add MATLAB to PATH or pass --matlab "
        r'"C:\Program Files\MATLAB\R2024b\bin\matlab.exe".'
    )


def resolve_paths(args: argparse.Namespace, parser: argparse.ArgumentParser) -> SelectedPaths:
    if not args.blf:
        parser.error("required for conversion: --blf")
    try:
        excel = _existing_file(args.excel, "Excel file", (".xlsx", ".xlsm")) if args.excel else None
        dbc_folder = _existing_dbc_source(args.dbc_folder) if args.dbc_folder else None
        blf_source = Path(args.blf).expanduser().resolve()
        if blf_source.is_file() and blf_source.suffix.lower() == ".blf":
            blf_files = [blf_source]
        elif blf_source.is_dir():
            blf_files = sorted(
                (p for p in blf_source.rglob("*") if p.is_file() and p.suffix.lower() == ".blf"),
                key=lambda p: str(p).lower(),
            )
            if not blf_files:
                raise argparse.ArgumentTypeError(f"No .blf files found in {blf_source}")
        else:
            raise argparse.ArgumentTypeError(f"BLF file/folder does not exist: {blf_source}")
        schema_files = [_existing_file(x, "Schema TXT", (".txt",)) for x in args.schema or []]

        if args.config:
            mapping_config = _existing_file(args.config, "Mapping config", (".yaml", ".yml"))
        else:
            default_config = application_directory() / "signal_mapping.yaml"
            mapping_config = default_config if default_config.is_file() else None

        output_format = args.output_format or ("dataset" if args.matlab else "mat")
        matlab_exe = find_matlab_executable(args.matlab) if output_format == "dataset" else None
        excel_options = [
            args.input_sheet,
            args.output_sheet,
            args.element_column,
            args.can_column,
            args.interface_column,
            args.dtype_column,
            args.header_row,
        ]
        if any(excel_options) and excel is None:
            raise argparse.ArgumentTypeError("Excel sheet/column options require --excel.")
        if args.header_row is not None and args.header_row < 1:
            raise argparse.ArgumentTypeError("--header-row must be at least 1.")
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    return SelectedPaths(
        excel=excel,
        dbc_folder=dbc_folder,
        blf_files=blf_files,
        schema_files=schema_files,
        output_folder=Path(args.output).expanduser().resolve()
        if args.output
        else (blf_source if blf_source.is_dir() else blf_source.parent) / "mat_output",
        mapping_config=mapping_config,
        matlab_exe=matlab_exe,
        output_format=output_format,
        input_sheets=tuple(args.input_sheet),
        output_sheets=tuple(args.output_sheet),
        element_column=args.element_column,
        can_column=args.can_column,
        interface_column=args.interface_column,
        dtype_column=args.dtype_column,
        header_row=args.header_row,
    )


def parse_cli_args(argv: list[str] | None = None) -> SelectedPaths:
    parser = build_arg_parser()
    return resolve_paths(parser.parse_args(argv), parser)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_arg_parser()
    args = parser.parse_args(arguments)
    try:
        if args.check:
            from .checks import check_environment

            return check_environment(
                args.matlab, require_matlab=args.output_format == "dataset" or bool(args.matlab)
            )
        if args.gui or not arguments:
            from .gui import launch

            return launch(args)
        return convert(resolve_paths(args, parser))
    except KeyboardInterrupt:
        print("Cancelled by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return 1
