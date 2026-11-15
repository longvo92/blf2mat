# BLF to MAT

Convert CAN BLF logs to MATLAB MAT files or Simulink Datasets, with optional project mappings, through a CLI (`blf-to-mat`) and a Tkinter GUI.

## Layout
- `src/blf_to_mat/`: `converter.py` (shared conversion engine), `frames.py` (lossless frame export), `mapping.py` (workbook and schema mapping), `checks.py` (runtime diagnostics), `cli.py`, `gui.py`.
- `scripts/check.py` and `scripts/build_pyz.py`; `examples/`; `tests/`.

## Runtime
- Python >=3.11,<3.15 and dependencies as declared in `pyproject.toml`. MIT licensed: `LICENSE` stays in the repository and in the `.pyz`.

## Commands
- Setup: `python -m venv .venv`, then `.venv/Scripts/python -m pip install -e ".[dev]"`.
- Check: `.venv/Scripts/python scripts/check.py` (Ruff, formatting, tests, archive build). `BLF_REQUIRE_GUI=1` requires GUI tests; use Xvfb on Linux without a display.
- Build: `python scripts/build_pyz.py --release-tag vVERSION` writes a source-only `.pyz`, SHA-256 checksum and generated requirements to `dist/`.

## Invariants
- CLI and GUI behave the same through the shared conversion engine.
- BLF is the only required input. Keep project-neutral defaults, the optional DBC/Excel/TXT/YAML inputs, configurable Excel sheets and columns, and both MAT formats.
- Ordinary MAT export works without MATLAB. Native Dataset export needs a live MATLAB/Simulink R2024b+ session to verify; mocked tests do not prove Dataset serialization or Signal Editor loading.
- The version lives in `src/blf_to_mat/__init__.py` and matches a dated `CHANGELOG.md` section.
- Package application code only; keep vehicle data, user configurations, generated output and the original standalone script out of Git and release assets.

Working rules live in the owner's global instructions.
