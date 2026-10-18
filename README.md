# BLF to MAT

[Tiếng Việt](README.vi.md)

Convert CAN BLF logs, DBC definitions, an Excel mapping workbook and TXT schemas
into native Simulink Signal Editor Dataset MAT files. One versioned `.pyz` runs
both the CLI and the Tkinter GUI, using the same conversion engine.

## Requirements

- Python **3.11-3.14**, with Tcl/Tk for the GUI (included in standard Windows Python).
- Python packages listed in `requirements.txt` delivered alongside the `.pyz`.
- **MATLAB/Simulink R2024b+** with an available license for final Dataset serialization.
  MATLAB is invoked once per conversion batch with `-batch`; SLDD is not required.

The `.pyz` contains application source, not Python, MATLAB or native dependencies
such as NumPy/SciPy. Install dependencies once into the same Python environment.
The tool does not download or install anything at runtime. For an offline machine,
prepare a compatible wheel directory beforehand and install with
`python -m pip install --no-index --find-links wheels -r requirements.txt`.

## Run the release

Download `blf_to_mat-0.1.0.pyz` and `requirements.txt` from a release, then run:

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.0.pyz --version
python .\blf_to_mat-0.1.0.pyz --check
python .\blf_to_mat-0.1.0.pyz --gui
```

No arguments also opens the GUI. Select the Excel workbook, DBC folder, a BLF
file or folder, one or more TXT schemas and an output folder. YAML and the MATLAB
executable are optional selections. Conversion runs in a background worker with
live logs. Wait for it to finish before closing the window.

CLI conversion preserves the original flags:

```powershell
python .\blf_to_mat-0.1.0.pyz --cli `
  --excel .\Interface.xlsx --dbc-folder .\DBC --blf .\Logs `
  --schema .\InputSignals.txt .\OutputSignals.txt --output .\Output `
  --config .\signal_mapping.yaml `
  --matlab "C:\Program Files\MATLAB\R2024b\bin\matlab.exe"
```

`--cli` is optional when conversion flags are supplied. Use `--debug` for tracebacks.
`--help` and `--version` work without installing dependencies.

## Input and output contracts

- Excel `.xlsx`/`.xlsm`: `SWC_INF` and `SWC_OUTF` sheets; automatic detection of
  interface, Data Element and CAN Signal columns. Prefer qualified interface names
  when elements are repeated across buses.
- TXT: one scalar `Interface.Element : datatype` per line; multiple files merge.
  Conflicting datatypes fail validation. MATLAB identifiers must be valid.
- DBC: recursively loaded `.dbc` files. CAN ID and extended-frame flag identify
  decode requests; repeated signal names are selected by observed sample count,
  with ambiguity warnings.
- BLF: one `.blf` or a directory recursively containing BLFs.
- YAML: see [synthetic example](examples/signal_mapping.example.yaml).
  `input_mappings` override input CAN sources with optional `status_mapping` and
  arithmetic `formula`; order is decode → status mapping → formula → datatype.
  `input_forces` hold non-CAN inputs constant and bypass these transforms.
  Empty YAML selection loads `signal_mapping.yaml` beside the `.pyz`; source and
  installed-package runs look in the working directory. Explicit `--config` wins.
- Output: `<BLF_stem>_input.mat` and `<BLF_stem>_output.mat`. Repeated BLF stems
  in a batch receive suffixes (`_2`, `_3`). **Existing output files are overwritten.**
  Failures may leave partial output; rerun after correcting the reported problem.
- Each MAT contains `Scenario`, a `Simulink.SimulationData.Dataset` with top-level
  bus structs and `timeseries` leaves using zero-order hold. Missing samples default
  to zero/false with warnings. Inputs whose first sample is after zero receive an
  initial zero before configured transforms. Unsupported schema types fall back to
  double with a warning. Preserve warnings when reviewing generated test stimuli.

`--check` returns 0 when Python/dependency imports and MATLAB executable discovery
pass, otherwise 1. It does not start MATLAB or verify its release/license, Simulink
availability, GUI display or Dataset serialization. Conversion errors return 1,
invalid CLI arguments return 2 and keyboard interruption returns 130.

## Develop and verify

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python scripts/check.py
.\.venv\Scripts\python -m blf_to_mat --gui
```

The check runs Ruff, formatting, pytest and the `.pyz` build. Tests generate their
own synthetic BLF/DBC/Excel inputs, exercise the Python pipeline and GUI, and mock
the MATLAB process. They **do not prove native Dataset serialization**. GUI tests
skip without a display locally; `BLF_REQUIRE_GUI=1` makes missing GUI support fail.
GitHub checks require GUI tests on Windows and Linux (Xvfb), Python 3.11-3.14.

Before production use or release acceptance, run the archive against a known
reference dataset in a live MATLAB R2024b+ environment, load both MATs, confirm
`isa(Scenario,'Simulink.SimulationData.Dataset')`, bus ordering, types, timestamps
and expected signal values, then open them in Signal Editor. This manual gate is
not covered by the hosted CI workflow.

## Build and release

```powershell
python scripts/build_pyz.py
python scripts/build_pyz.py --release-tag v0.1.0
```

The build uses only the standard library and includes only `src/blf_to_mat/*.py`
and embedded requirements. `dist/` contains the `.pyz`, a SHA-256 checksum and
`requirements.txt` generated from `pyproject.toml`. No logs, vehicle data, user YAML,
test fixtures or original standalone script are packaged. Identical sources built
with the same Python/zlib produce identical archive bytes.

Version lives only in `src/blf_to_mat/__init__.py`; update it and add a dated
`CHANGELOG.md` section before a release. After checks and manual MATLAB acceptance,
merge the reviewed PR, then explicitly publish the matching tag:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

The release workflow reruns the checks, requires matching tag/version/changelog,
builds the archive, smoke-tests it without site packages, and publishes the three
assets as a GitHub release. No PyPI publication. Publishing a tag is a release
action; ordinary branch pushes and PRs produce checks/preview artifacts only.
