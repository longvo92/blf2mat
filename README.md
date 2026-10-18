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

For a packaged build, place the `.pyz` and accompanying `requirements.txt`
in the same folder and run:

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.0.pyz --gui
```

Use the same Python for installation and running the tool. Run `blf-to-mat --check`
or `python .\blf_to_mat-0.1.0.pyz --check` to diagnose missing dependencies.

## Convert

In the GUI, select a BLF file or folder, add any optional inputs, choose the output
format and click **Convert**. Use **Select sheets...** to customize Excel mapping;
blank fields use automatic detection. Conversion runs in the background with logs.

For the command line:

```powershell
blf-to-mat --blf .\capture.blf
blf-to-mat --blf .\capture.blf --dbc .\network.dbc
blf-to-mat --blf .\Logs --dbc .\DBC
```

With a packaged build, replace `blf-to-mat` with `python .\blf_to_mat-0.1.0.pyz`.

Output goes to `mat_output` beside the BLF file or inside the selected BLF folder.
Use `--output` to choose another folder. BLF-only creates `<name>.mat` with frames;
BLF with a DBC creates `<name>_signals.mat`. Custom mappings produce input/output files
for the configured sides. In the GUI, use **File...** or **Folder...** for DBC;
`--dbc-folder` remains supported in CLI. See `--help` for all options and the
[YAML example](examples/signal_mapping.example.yaml) for mapping syntax.

## Before using the result

Ordinary MAT files contain data structures, not native Signal Editor Datasets.
Choose `dataset` in the GUI or pass `--format dataset` for Signal Editor; this
requires MATLAB/Simulink R2024b+ and an available license.

Without DBC, CAN signals cannot be decoded. Missing mapped samples use defaults
with warnings, so review the log. **Existing output files are overwritten.** Native
Dataset export still needs validation with a live MATLAB/Signal Editor session.

## License

[MIT](LICENSE).
