<div align="center">

# BLF → MAT

**From CAN logs to MATLAB data, through a GUI or the command line.**

[![Checks](https://github.com/longvo92/blf2mat/actions/workflows/checks.yml/badge.svg?branch=main)](https://github.com/longvo92/blf2mat/actions/workflows/checks.yml)
[![Python 3.11–3.14](https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-22A699.svg)](LICENSE)

[Get started](#install-and-open) · [Usage](#convert) · [CLI flags](#cli-flags) · [Mapping example](examples/signal_mapping.example.yaml) · [Changelog](CHANGELOG.md)

</div>

Convert CAN/CAN-FD BLF logs to MAT files for analysis and simulation.
**Only a BLF file or folder is required.** Add a DBC or project mappings when needed.

## Features

| Your inputs | Your result |
| --- | --- |
| BLF file or folder | Raw CAN/CAN-FD frames in MAT |
| BLF + DBC file or folder | Decoded signals in MAT |
| BLF + optional Excel, TXT or YAML mappings | Signals organized for your project |

- Map signals, set datatypes, apply formulas or hold inputs at constant values.
- Choose Excel input/output sheets, columns and header row.
- Export ordinary MAT without MATLAB, or native Signal Editor Datasets with MATLAB.

## Install and open

Use Python **3.11–3.14**. From a downloaded or cloned copy of this repository:

```powershell
python -m pip install .
blf-to-mat --gui
```

Packaged build:

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.3.pyz --gui
```

Use the same Python to install and run. Add `--check` to diagnose dependencies.

## Convert

In the GUI, select BLF, optional inputs and output format, then click **Convert**.
**Select sheets...** customizes Excel mapping; blank fields use automatic detection.

CLI:

```powershell
blf-to-mat --blf .\capture.blf
blf-to-mat --blf .\capture.blf --dbc .\network.dbc
```

With a packaged build, replace `blf-to-mat` with `python .\blf_to_mat-0.1.3.pyz`.

### TXT without Excel

Leave **Excel workbook** blank and select **Input TXT schema** and **Output TXT schema**,
or run:

```powershell
blf-to-mat --blf .\capture.blf --dbc .\network.dbc --input-schema .\inputs.txt --output-schema .\outputs.txt
```

TXT lines declare scalar signals:

```text
VehicleInputs.VehicleSpeed : single
VehicleInputs.Enable : boolean
```

Element names match DBC signals.
Input TXT exports `<name>_input.mat`; output TXT exports `<name>_output.mat`.
Sides are optional. `--schema INPUT.txt OUTPUT.txt` uses that order;
one TXT means input only. Do not mix legacy and explicit flags.
YAML can map different input CAN names.
Without DBC, TXT signals use defaults. BLF remains required.

To skip Excel rows, select a YAML config containing:

```yaml
excel_skip_keywords: ["ignore", "obsolete"]
```

Keywords match substrings in any cell, case-insensitively, on both sides.

Output defaults to `mat_output` beside BLF; change it with `--output`.
BLF-only creates `<name>.mat`; BLF + DBC creates `<name>_signals.mat`.
Mappings produce input/output files for configured sides.
See `--help` and the [YAML example](examples/signal_mapping.example.yaml).

## CLI flags

Aliases in the same row are interchangeable. Quote paths and sheet/header names
containing spaces. Only `--blf` is required for conversion.

| Flag | Value and behavior |
| --- | --- |
| `-b`, `--blf` | BLF file or folder; folders are searched recursively. |
| `-d`, `--dbc`, `--dbc-folder` | Optional DBC file or recursively searched folder. Omit for raw frames or mapping defaults. |
| `-e`, `--excel` | Optional `.xlsx` or `.xlsm` mapping workbook. |
| `--input-schema` | Input TXT schema; produces `<name>_input.mat`. |
| `--output-schema` | Output TXT schema; produces `<name>_output.mat`. |
| `-s`, `--schema` | Legacy space-separated TXT paths. Without Excel: `INPUT.txt [OUTPUT.txt]` (maximum two). With Excel, sheets select sides. Cannot combine with explicit schema flags. |
| `-c`, `--config` | YAML mappings, transforms, forced inputs and `excel_skip_keywords`. If omitted, auto-loads `signal_mapping.yaml` beside the `.pyz`, or in the working directory for source runs, when present. |
| `-o`, `--output` | Output directory; default: `mat_output` beside the BLF file or inside the selected BLF folder. |
| `--format` | `mat` (default, no MATLAB) or `dataset` (native Signal Editor Dataset). |
| `--matlab` | MATLAB executable path; implies `dataset` unless `--format` is explicit. Otherwise MATLAB is discovered on PATH or in common Windows installation folders. |
| `--gui` | Open GUI; also the default with no arguments. |
| `--cli` | Run conversion in the terminal; also the default when conversion arguments are supplied. |
| `--check` | Diagnose Python dependencies, Tcl/Tk and MATLAB discovery without launching MATLAB. Add `--format dataset` to require MATLAB discovery. |
| `--debug` | Print the full Python traceback on failure. |
| `--version` | Print version and exit. |
| `-h`, `--help` | Print usage and exit. |

`--gui`, `--cli` and `--check` are mutually exclusive.

Excel options require `--excel`. Columns accept a header name or **1-based**
column number; omitted columns are detected automatically.

| Flag | Value and behavior |
| --- | --- |
| `--input-sheet` | Input sheet name; repeat for multiple sheets. |
| `--output-sheet` | Output sheet name; repeat for multiple sheets. If either sheet flag is supplied, only explicitly selected sheets are used. Otherwise mapping sheets are detected. |
| `--element-column` | Element name column. |
| `--can-column` | CAN signal name column. |
| `--interface-column` | Interface name column. |
| `--dtype-column` | Datatype column. |
| `--header-row` | Header row number, starting at 1; default: detect within the first 20 rows. |

Example with explicit Excel selection:

```powershell
blf-to-mat --blf .\logs --dbc .\DBC --excel .\Interface.xlsx `
  --input-sheet "Inputs" --input-sheet "Extra Inputs" --output-sheet "Outputs" `
  --element-column "Element" --can-column "CAN Signal" `
  --interface-column "Interface" --dtype-column "Datatype" --header-row 2 `
  --config .\signal_mapping.yaml --output .\results --format mat
```

## Before using the result

For native Signal Editor Datasets, choose `dataset` or pass `--format dataset`;
MATLAB/Simulink R2024b+ and a license are required.

Missing signals use defaults with warnings; review the log.
**Existing output files are overwritten.** Native
Dataset export still needs validation with a live MATLAB/Signal Editor session.

## License

[MIT](LICENSE).
