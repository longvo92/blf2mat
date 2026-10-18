from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile

import pytest

from blf_to_mat import __version__, checks, cli
from scripts.build_pyz import build, validate_release


@pytest.mark.parametrize("flag", ["--version", "--help"])
def test_archive_help_without_dependencies(tmp_path, flag):
    archive = build(tmp_path)
    process = subprocess.run(
        [sys.executable, "-S", str(archive), flag], cwd=tmp_path, capture_output=True, text=True
    )
    assert process.returncode == 0, process.stderr
    assert (__version__ if flag == "--version" else "--gui") in process.stdout


def test_archive_is_reproducible_and_contains_only_app(tmp_path):
    first = build(tmp_path / "a")
    second = build(tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
    assert (
        first.with_suffix(".pyz.sha256").read_text().split()[0]
        == hashlib.sha256(first.read_bytes()).hexdigest()
    )
    with zipfile.ZipFile(first) as package:
        assert "__main__.py" in package.namelist()
        assert not any(
            name.endswith((".blf", ".dbc", ".xlsx", ".pyc")) for name in package.namelist()
        )
        assert "scipy" in package.read("requirements.txt").decode()


def test_release_requires_matching_version():
    validate_release(f"v{__version__}")
    with pytest.raises(ValueError, match="must match"):
        validate_release("v9.9.9")


def test_missing_cli_inputs_have_exit_code_two():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--cli"])
    assert exc.value.code == 2


def test_check_reports_missing_matlab(monkeypatch, capsys):
    def missing(*args):
        raise RuntimeError("MATLAB not installed")

    monkeypatch.setattr(checks, "find_matlab_executable", missing)
    assert cli.main(["--check"]) == 0
    assert cli.main(["--check", "--format", "dataset"]) == 1
    assert "MATLAB not installed" in capsys.readouterr().out


def test_check_success_and_dependency_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "find_matlab_executable", lambda *args: tmp_path / "matlab")
    assert checks.check_environment(emit=lambda _: None) == 0
    original = checks.importlib.import_module

    def fail(name):
        if name == "scipy.io":
            raise ImportError("missing scipy")
        return original(name)

    monkeypatch.setattr(checks.importlib, "import_module", fail)
    lines = []
    assert checks.check_environment(emit=lines.append) == 1
    assert any("missing scipy" in line for line in lines)


def test_config_is_found_next_to_archive(tmp_path):
    archive = build(tmp_path / "app")
    config = archive.parent / "signal_mapping.yaml"
    config.write_text("{}")
    script = "import sys; sys.path.insert(0, sys.argv[1]); from blf_to_mat.cli import application_directory; sys.argv[0] = sys.argv[1]; print(application_directory())"
    process = subprocess.run(
        [sys.executable, "-S", "-c", script, str(archive)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == str(archive.parent)


def test_archive_missing_dependencies_has_actionable_error(tmp_path):
    archive = build(tmp_path)
    process = subprocess.run(
        [sys.executable, "-S", str(archive), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 1
    assert "pip install -r requirements.txt" in process.stdout


def test_archive_conversion_uses_packaged_engine(tmp_path, sample):
    archive = build(tmp_path / "release")
    # Exercise CLI dispatch, parsing, decoding and raw MAT serialization from zip imports.
    # The MATLAB boundary is replaced because hosted CI has no MATLAB license.
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from blf_to_mat import cli, converter
from scipy.io import loadmat, savemat
assert ".pyz" in converter.__file__
output = Path(sys.argv[sys.argv.index("--output") + 1])
def package(matlab, script, cwd):
    raw = loadmat(next(cwd.glob("raw_*.mat")), simplify_cells=True)
    assert raw["RawInputScenario"]["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]
    for side in ("input", "output"):
        savemat(output / ("sample_" + side + ".mat"), {"mock": 1})
converter.run_matlab_batch = package
raise SystemExit(cli.main(sys.argv[2:]))
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(archive), *sample["argv"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert "[SUMMARY]" in process.stdout


@pytest.mark.gui
def test_archive_gui_can_launch(tmp_path):
    archive = build(tmp_path)
    script = """
import sys
sys.path.insert(0, sys.argv[1])
try:
    import tkinter
    root = tkinter.Tk()
except Exception as exc:
    print(exc)
    raise SystemExit(5)
from blf_to_mat import gui, cli
gui.Tk = lambda: root
root.after(200, root.destroy)
raise SystemExit(cli.main(["--gui"]))
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(archive)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode == 5 and os.environ.get("BLF_REQUIRE_GUI") != "1":
        pytest.skip("Graphical display/Tcl/Tk unavailable: " + process.stdout)
    assert process.returncode == 0, process.stdout + process.stderr
