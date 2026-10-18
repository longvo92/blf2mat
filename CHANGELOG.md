# Changelog

## [0.1.0] - 2026-10-18

- Package the BLF converter as one versioned `.pyz` with CLI and Tkinter GUI.
- Run with BLF alone to export CAN/CAN-FD frames; optionally decode DBC signals without Excel, schema or MATLAB.
- Select arbitrary Excel input/output sheets and columns, infer optional signal definitions, and preserve legacy mapping flags and transforms.
- Export ordinary MAT by default or native Signal Editor Datasets through MATLAB; remove project-specific interface names and bus ordering.
- Add environment diagnostics, automated checks and tag-based GitHub releases with SHA-256 checksums.
