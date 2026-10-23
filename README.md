<div align="center">

# BLF → MAT

**From CAN logs to MATLAB data, through a GUI or the command line.**

[![Checks](https://github.com/longvo92/blf2mat/actions/workflows/checks.yml/badge.svg?branch=main)](https://github.com/longvo92/blf2mat/actions/workflows/checks.yml)
[![Python 3.11–3.14](https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-22A699.svg)](LICENSE)

[Get started](#install-and-open) · [Usage](#convert) · [Mapping example](examples/signal_mapping.example.yaml) · [Changelog](CHANGELOG.md)

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

For a packaged build, use the accompanying requirements:

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.2.pyz --gui
```

Use the same Python to install and run. Add `--check` to diagnose dependencies.

## Convert

In the GUI, select BLF, optional inputs and output format, then click **Convert**.
**Select sheets...** customizes Excel mapping; blank fields use automatic detection.

For the command line:

```powershell
blf-to-mat --blf .\capture.blf
blf-to-mat --blf .\capture.blf --dbc .\network.dbc
```

With a packaged build, replace `blf-to-mat` with `python .\blf_to_mat-0.1.2.pyz`.

### TXT without Excel

Leave **Excel workbook** blank and select one or more **TXT schemas** in the GUI,
or run:

```powershell
blf-to-mat --blf .\capture.blf --dbc .\network.dbc --schema .\signals.txt
```

Each TXT line declares a scalar signal, for example:

```text
VehicleInputs.VehicleSpeed : single
VehicleInputs.Enable : boolean
```

Element names (`VehicleSpeed`, `Enable`) match DBC signal names automatically.
All TXT interfaces go to `<name>_input.mat`, regardless of file/interface names.
Use Excel to select input/output sides, or YAML to map different CAN names.
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

## Before using the result

For native Signal Editor Datasets, choose `dataset` or pass `--format dataset`;
MATLAB/Simulink R2024b+ and a license are required.

Missing signals use defaults with warnings; review the log.
**Existing output files are overwritten.** Native
Dataset export still needs validation with a live MATLAB/Signal Editor session.

## License

[MIT](LICENSE).
