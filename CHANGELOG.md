# Changelog

## [0.1.3] - 2026-10-23

- Select input and output TXT schemas separately in CLI and GUI to export two MAT files without Excel.
- Fix `--schema INPUT.txt OUTPUT.txt` so the second TXT supplies output signals instead of merging into input.

## [0.1.2] - 2026-10-23

- Clarify the TXT-without-Excel workflow in the GUI, command-line help and usage examples.

## [0.1.1] - 2026-10-22

- Skip Excel mapping rows containing configured keywords using `excel_skip_keywords` in YAML, in both CLI and GUI.

## [0.1.0] - 2026-10-18

- Convert BLF logs to MAT using either the GUI or command line.
- Choose a DBC file or folder; optionally add Excel, TXT or YAML with your own sheets and columns.
- Export MAT without MATLAB, or use MATLAB for Signal Editor Datasets.
- Check the environment with `--check` and run the tool from one `.pyz` file.
- Available under the MIT license.
