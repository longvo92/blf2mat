# BLF to MAT

[Tiếng Việt](README.vi.md)

A project-neutral CAN BLF converter with CLI and Tkinter GUI in one versioned
`.pyz`. **Only BLF is required.** DBC, Excel, TXT schema, YAML, output folder and
MATLAB are optional; add the inputs that match your workflow.

## Run

Python **3.11-3.14** is supported. Install `requirements.txt` supplied with the
archive into the same Python environment. Tcl/Tk is needed only for the GUI.
MATLAB/Simulink R2024b+ is needed only for native Dataset export.

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.0.pyz --blf .\capture.blf
python .\blf_to_mat-0.1.0.pyz --gui
python .\blf_to_mat-0.1.0.pyz --check
```

No arguments opens the GUI. Choose a BLF file or a folder (searched recursively).
Output defaults to `mat_output` beside a BLF file or inside the selected BLF
folder. Use `--output` to override. `--cli` is optional when conversion arguments
are supplied. `--help` and `--version` work without third-party packages.

| Setup | Result |
| --- | --- |
| BLF only | `<stem>.mat`, containing CAN/CAN-FD `Frames` |
| BLF + DBC | `<stem>_signals.mat`, decoded signals grouped by DBC message |
| BLF + DBC + TXT | Schema interfaces/types; element names map directly to CAN names |
| BLF + Excel, optionally DBC/TXT | Selected input/output mappings; infer targets when TXT is absent |
| BLF + YAML, optionally DBC/TXT | Configured CAN mappings/transforms or constant forced inputs |
| Any signal setup + `--format dataset` | Native Signal Editor Dataset, serialized by MATLAB |

Without DBC, CAN signals cannot be decoded: raw frames are exported, and supplied
signal definitions receive defaults/forces with warnings. YAML CAN overrides
require DBC definitions for their named source signals. A raw-frame-only setup
cannot produce a native Dataset; supply signal definitions or use ordinary MAT.

## Flexible Excel mappings

No project sheet names, column positions or bus order are required. The tool
scans the first 20 rows for headers and known schema/DBC values. Recognized
headers include `Data Element`/`Element`/`Target`, `CAN Signal`/`DBC Signal`/`Source`,
`Interface`/`Bus`/`Group` and `Datatype`/`Type`.

```powershell
python .\blf_to_mat-0.1.0.pyz --blf .\Logs --dbc-folder .\DBC `
  --excel .\Mapping.xlsx --input-sheet "Inputs" --output-sheet "Outputs" `
  --header-row 4 --element-column "Model name" --can-column "Network name" `
  --interface-column "Bus name" --dtype-column "Storage type"
```

- Repeat `--input-sheet`/`--output-sheet` for multiple sheets. Selecting only one
  side is supported. Without selections, mapping sheets become inputs and sheets
  that cannot be detected are skipped with a warning. A workbook containing both
  legacy `SWC_INF`/`SWC_OUTF` sheets keeps their input/output interpretation.
- Column options accept exact header names (case-insensitive) or **1-based**
  column numbers. `--header-row` is also 1-based. Explicit invalid selections fail.
- Without TXT, use `Bus.Element` targets or an interface column; otherwise the bus
  is `Signals`. Missing types default to double. A CAN-only mapping column uses
  the CAN name as the element name. Duplicate conflicting mappings fail.
- With TXT, targets are resolved against that schema; ambiguous element names
  require a qualified target or interface column. Bus order follows mapping rows
  or schema order, with no architecture-specific list.
- GUI: choose **Select sheets...**, select input/output sheets, then enter column
  names/numbers and the header row. Blank fields use automatic detection.

## Signal definitions and MAT formats

TXT files merge scalar `Interface.Element : datatype` definitions. Conflicting
types and invalid MATLAB names fail validation. DBC-only export infers unique
MATLAB-safe message/element names, keeps same-named signals from different messages
independent, preserves observed sample times, and stores physical values as double.

YAML [example](examples/signal_mapping.example.yaml): `input_mappings` can set
`can_signal`, `status_mapping` (CAN → model) and `formula` (e.g. `x/10+5`). Transform
order is CAN decode → status mapping → formula → datatype cast. `input_forces`
hold non-CAN inputs constant over the log duration. Without Excel/TXT, YAML targets
are inferred as double. With no `--config`, `signal_mapping.yaml` beside the `.pyz`
is loaded when present; source/installed runs look in the working directory.

Ordinary MAT is the default and requires no MATLAB. Signal files contain
`Scenario` structs with bus/element `Time` and `Data` fields; they are **not** native
Simulink Datasets. Input/output files are emitted only for configured sides.
Raw `Frames` contains relative `Time`, `Timestamp` as read from BLF, ID, channel,
DLC, payload length, an N×64 uint8 payload matrix and Extended/FD/Remote/Error/BRS/
ESI/Rx flags. `Length` distinguishes real payload from zero padding. Non-CAN BLF
objects are outside this export. Timestamps follow the BLF reader's time origin.

For Signal Editor, use `--format dataset [--matlab PATH]`. MATLAB is discovered
when the path is omitted. For CLI compatibility, an explicit `--matlab` implies
Dataset unless `--format` overrides it. MATLAB runs once for the entire batch;
each file contains native `Scenario`, with bus structs and ZOH timeseries.
SLDD is not required. Dataset serialization needs a live MATLAB/Simulink license.

Missing mapped samples default to zero/false with warnings. Excel/TXT input
setups retain the initial zero sample behavior before configured transforms;
DBC-only export does not insert artificial samples. Integer casts round and
saturate; unsupported schema types fall back to double with a warning. Inspect
warnings before using generated stimuli. Same-named source signals in explicit
Excel/TXT/YAML mappings retain sample-count-based DBC selection and ambiguity
warnings; CAN channel-specific DBC routing is not configured by these options.

**Existing output files are overwritten.** Duplicate stems within a batch receive
`_2`, `_3`, etc. Failed runs can leave partial output. GUI conversion runs in a
worker; wait for completion before closing. Use `--debug` for tracebacks.

`--check` verifies dependency imports and reports optional GUI/MATLAB availability.
Missing MATLAB does not fail the ordinary MAT check; `--check --format dataset`
requires it. Executable discovery does not verify MATLAB release/license or native
serialization; importing Tcl/Tk does not prove display availability. Exit codes:
0 success, 1 conversion/check failure, 2 invalid CLI arguments, 130 interruption.

## Develop, build and release

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python scripts/check.py
.\.venv\Scripts\python -m blf_to_mat --gui
python scripts/build_pyz.py --release-tag v0.1.0
```

Checks run Ruff, formatting, pytest and archive build. Tests use synthetic data,
verify real ordinary MAT serialization, optional setups, workbook selection and
GUI behavior. MATLAB calls are mocked: native Dataset serialization still needs
manual validation with MATLAB R2024b+ and Signal Editor. GUI tests may skip locally
without a display; `BLF_REQUIRE_GUI=1` requires them. CI requires GUI on Windows and
Linux (Xvfb), Python 3.11-3.14, using one Tcl/Tk interpreter per GUI test module.

Version lives in `src/blf_to_mat/__init__.py`; add a dated `CHANGELOG.md` section
for each version. `scripts/build_pyz.py` uses only the standard library and outputs
`.pyz`, SHA-256 checksum and requirements generated from `pyproject.toml` in `dist/`.
It packages application source only, normalizes newlines, and excludes user data,
YAML, fixtures, the original script and native dependencies. Same sources and
Python/zlib produce identical bytes. The tool never downloads anything at runtime;
for offline dependency installation, prepare compatible wheels and use
`python -m pip install --no-index --find-links wheels -r requirements.txt`.

After reviewed changes are merged and relevant runtime validation is complete,
explicitly push a matching tag (`git tag v0.1.0`, then `git push origin v0.1.0`).
The release workflow reruns checks, validates tag/version/changelog, smoke-tests
the archive without site packages, and publishes the three assets on GitHub.
Branch/PR checks publish preview artifacts only; there is no PyPI publication.
