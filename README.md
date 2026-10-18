# BLF to MAT

[Tiếng Việt](README.vi.md)

Convert CAN BLF logs to MAT files using a graphical interface or the command line.
**Only a BLF file or folder is required.** Add other inputs when your project needs them.

## Features

- Export raw CAN/CAN-FD frames with BLF alone.
- Choose a DBC file or folder to decode signals automatically.
- Optionally use Excel, TXT or YAML to map signals, set datatypes, apply formulas
  or hold inputs at constant values.
- Choose your own Excel input/output sheets, columns and header row.
- Export ordinary MAT without MATLAB, or native Datasets for Signal Editor with MATLAB.

## Install and open

Use Python **3.11-3.14**. Place the `.pyz` and its accompanying `requirements.txt`
in the same folder, open a terminal there, and run:

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.0.pyz --gui
```

Use the same Python for installation and running the tool. If SciPy is reported
missing, check the environment with:

```powershell
python .\blf_to_mat-0.1.0.pyz --check
```

## Convert

In the GUI, select a BLF file or folder, add any optional inputs, choose the output
format and click **Convert**. Use **Select sheets...** to customize Excel mapping;
blank fields use automatic detection. Conversion runs in the background with logs.

For the command line:

```powershell
python .\blf_to_mat-0.1.0.pyz --blf .\capture.blf
python .\blf_to_mat-0.1.0.pyz --blf .\capture.blf --dbc .\network.dbc
python .\blf_to_mat-0.1.0.pyz --blf .\Logs --dbc .\DBC
```

Output goes to `mat_output` beside the BLF file or inside the selected BLF folder.
Use `--output` to choose another folder. BLF-only creates `<name>.mat` with frames;
DBC-only creates `<name>_signals.mat`. Custom mappings produce input/output files
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
