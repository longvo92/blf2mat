from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from scipy.io import loadmat, savemat

from blf_to_mat import cli
from blf_to_mat import converter as core


def fake_packager(captured):
    def run(matlab_exe, script_path, cwd):
        captured.append(script_path.read_text(encoding="utf-8"))
        # MATLAB itself is deliberately mocked. Validate actual Python MAT output.
        for raw in cwd.glob("raw_*.mat"):
            content = loadmat(raw, simplify_cells=True)
            captured.append(content)
        import re

        for _, input_path, output_path in re.findall(
            r"    '([^']*)', '([^']*)', '([^']*)';", captured[0]
        ):
            savemat(input_path, {"mock": 1})
            savemat(output_path, {"mock": 1})

    return run


def test_cli_full_python_pipeline(sample, monkeypatch):
    captured = []
    monkeypatch.setattr(core, "run_matlab_batch", fake_packager(captured))
    assert cli.main(sample["argv"]) == 0
    assert len(captured) == 2
    raw = captured[1]
    assert raw["RawInputScenario"]["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]
    assert raw["RawInputScenario"]["BSW_CanInp"]["Speed"]["Time"].tolist() == [0, 0.5, 1]
    assert raw["RawInputScenario"]["BSW_CanInp"]["Enable"]["Data"].tolist() == [1, 1]
    assert raw["RawOutputScenario"]["BSW_CanOut"]["Request"]["Data"].tolist() == [2, 3]
    assert len(list(sample["output"].glob("*.mat"))) == 2
    assert "Simulink.SimulationData.Dataset" in captured[0]


def test_batch_duplicate_stems_one_matlab_launch(sample, monkeypatch):
    root = sample["root"] / "logs"
    for directory in (root / "a", root / "b"):
        directory.mkdir(parents=True)
        shutil.copy2(sample["blf"], directory / "same.blf")
    argv = list(sample["argv"])
    argv[argv.index("--blf") + 1] = str(root)
    captured = []
    monkeypatch.setattr(core, "run_matlab_batch", fake_packager(captured))
    assert cli.main(argv) == 0
    assert len(captured) == 3
    assert sorted(p.name for p in sample["output"].glob("*.mat")) == [
        "same_2_input.mat",
        "same_2_output.mat",
        "same_input.mat",
        "same_output.mat",
    ]


def test_matlab_failure_is_reported(sample, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("Simulink license unavailable")

    monkeypatch.setattr(core, "run_matlab_batch", fail)
    assert cli.main(sample["argv"]) == 1
    assert "Simulink license unavailable" in capsys.readouterr().err


def test_matlab_success_requires_both_outputs(sample, monkeypatch, capsys):
    monkeypatch.setattr(core, "run_matlab_batch", lambda *args, **kwargs: None)
    assert cli.main(sample["argv"]) == 1
    assert "did not create expected MAT files" in capsys.readouterr().err


def test_schema_conflict_rejected(sample):
    with sample["schema"].open("a") as stream:
        stream.write("BSW_CanInp.Speed : uint8\n")
    with pytest.raises(RuntimeError, match="Conflicting datatype"):
        core.load_signal_schema([sample["schema"]])


@pytest.mark.parametrize("formula", ["__import__('os')", "x.real", "x[0]", "sum(x)"])
def test_formula_cannot_execute_code(formula):
    with pytest.raises(RuntimeError, match="Invalid signal formula"):
        core.validate_signal_formula(formula)


def test_nonfinite_formula_rejected():
    with pytest.raises(RuntimeError, match="NaN/Inf"):
        core.apply_signal_formula([1], "x/0", "Bus.Value")


def test_status_then_formula_and_integer_saturation():
    mapped = core.apply_status_mapping([0, 4, 7], {0: 0, 4: 1, 7: 2}, "Bus.Value")
    values = core.apply_signal_formula(mapped, "x*200+0.5", "Bus.Value")
    assert core.cast_signal_data(values, "uint8").tolist() == [1, 201, 255]
    assert core.cast_signal_data([-1.5, 1.5], "int8").tolist() == [-2, 2]


def test_duplicate_timestamps_keep_last():
    times, data = core.collapse_duplicate_times(np.array([2, 1, 1]), np.array([30, 10, 20]))
    assert times.tolist() == [1, 2]
    assert data.tolist() == [20, 30]


def test_force_mapping_conflict_rejected(tmp_path):
    config = tmp_path / "bad.yaml"
    config.write_text(
        "input_mappings:\n- {interface: Bus, element: Value, can_signal: CAN}\ninput_forces:\n- {interface: Bus, element: Value, value: 1}\n"
    )
    with pytest.raises(RuntimeError, match="both input_mappings and input_forces"):
        core.load_input_mapping_config(config)


def test_matlab_command_and_quoting(tmp_path, monkeypatch):
    captured = []

    def run(command, **kwargs):
        captured.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "[PACKAGER] done\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    script = tmp_path / "owner's folder" / "package.m"
    core.run_matlab_batch(Path("matlab"), script, tmp_path)
    assert captured[0][0] == [
        "matlab",
        "-batch",
        f"run('{str(script).replace(chr(39), chr(39) * 2)}')",
    ]
    assert captured[0][1]["cwd"] == str(tmp_path)
