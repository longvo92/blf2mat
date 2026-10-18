# Project guidance

## User-facing documentation

- Write for people using the tool, not maintaining its implementation.
- Keep each user guide readable in 2-3 minutes; aim for about 250-450 words.
- Cover only purpose, useful features, required inputs, installation, basic usage,
  outputs and limitations that affect the user's decisions.
- Use plain language and a few copyable commands. Refer to `--help` for the full
  option list instead of documenting every flag in the README.
- Keep architecture, internal APIs, test counts, CI configuration and release
  maintenance out of user guides. Keep necessary maintainer guidance here.
- Apply the same style to `CHANGELOG.md`: a few short bullets per release about
  changes users notice. Group minor changes and omit internal cleanup/check details.
- Maintain one English `README.md`. Do not create or restore `README.vi.md` or
  other translated guides unless explicitly requested. Conversations are Vietnamese.
- Do not create unsolicited reports or summary documents.

## Development and verification

- Keep CLI and GUI behavior consistent through the shared conversion engine.
- BLF is the only required input. Preserve project-neutral defaults and optional
  DBC/Excel/TXT/YAML inputs, configurable Excel sheets/columns and both MAT formats.
- Ordinary MAT export must work without MATLAB. Native Dataset export requires a
  live MATLAB/Simulink R2024b+ session for actual runtime verification; mocked tests
  do not prove Dataset serialization or Signal Editor loading.
- Use the runtime and dependencies declared in `pyproject.toml`.
- Development setup: `python -m venv .venv`, then
  `.venv/Scripts/python -m pip install -e ".[dev]"`.
- Run `.venv/Scripts/python scripts/check.py` for code changes. This checks Ruff,
  formatting, tests and archive build. Set `BLF_REQUIRE_GUI=1` to require GUI tests;
  use Xvfb for Linux without a display. GUI tests share one Tcl/Tk interpreter.
- For documentation-only changes, check accuracy, links, example commands and the
  diff; do not run unrelated application tests.

## Packaging and delivery

- Version is defined in `src/blf_to_mat/__init__.py`. Maintain a dated changelog
  section matching it. Build with `python scripts/build_pyz.py --release-tag vVERSION`.
- The build produces a source-only `.pyz`, SHA-256 checksum and generated
  requirements in `dist/`. Python/native dependencies are installed separately.
- The project is MIT-licensed. Keep `LICENSE` in the repository and `.pyz` archive,
  and preserve the matching license metadata in `pyproject.toml`.
- Package only application code. Keep vehicle data, user configurations, generated
  output and the original standalone script out of Git and release assets.
- Preserve unrelated work; use the appropriate `Codex/...` branch and PR. Commit
  scoped changes only after relevant checks and diff review.
- Merge, tag publication and releases require the user's authorization. The tag
  workflow reruns checks, validates version/changelog and publishes GitHub assets.
