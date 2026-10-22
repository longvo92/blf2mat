from __future__ import annotations

import subprocess
import sys

import can
import pandas as pd
import pytest
from scipy.io import loadmat

from blf_to_mat import cli
from blf_to_mat import converter as core
from scripts.build_pyz import build


def basic_args(sample):
    return ["--blf", str(sample["blf"]), "--output", str(sample["output"])]


def dbc_args(sample):
    return [*basic_args(sample), "--dbc-folder", str(sample["root"] / "dbc")]


def test_blf_only_exports_frames_and_defaults_output(sample):
    assert cli.main(["--blf", str(sample["blf"])]) == 0
    content = loadmat(sample["root"] / "mat_output/sample.mat", simplify_cells=True)["Frames"]
    assert content["ID"].tolist() == [999, 256, 256]
    assert content["Time"].tolist() == [0, 0.5, 1]
    with can.BLFReader(sample["blf"]) as reader:
        expected_timestamps = [frame.timestamp for frame in reader]
    assert content["Timestamp"].tolist() == expected_timestamps
    assert content["Data"].shape == (3, 64)
    assert content["Data"][1, :2].tolist() == [10, 2]
    assert content["Length"].tolist() == [1, 2, 2]


def test_blf_plus_dbc_infers_messages_without_zero_insertion(sample):
    assert cli.main(dbc_args(sample)) == 0
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert scenario["Sample"]["SpeedCAN"]["Data"].tolist() == [10, 30]
    assert scenario["Sample"]["SpeedCAN"]["Time"].tolist() == [0.5, 1]
    assert scenario["Sample"]["RequestCAN"]["Data"].tolist() == [2, 3]


@pytest.mark.parametrize("flag", ["--dbc", "-d", "--dbc-folder"])
@pytest.mark.parametrize("single_file", [False, True])
def test_dbc_source_accepts_file_or_recursive_folder(sample, flag, single_file):
    folder = sample["root"] / "dbc"
    source = folder / "sample.dbc"
    nested = folder / "nested"
    nested.mkdir()
    source = source.rename(nested / "sample.DBC")
    assert cli.main([*basic_args(sample), flag, str(source if single_file else folder)]) == 0
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert scenario["Sample"]["SpeedCAN"]["Data"].tolist() == [10, 30]


def test_single_dbc_does_not_load_neighboring_files(sample):
    folder = sample["root"] / "dbc"
    source = folder / "sample.dbc"
    (folder / "other.dbc").write_text(
        source.read_text()
        .replace("Sample:", "Other:")
        .replace("SpeedCAN", "OtherSpeed")
        .replace("RequestCAN", "OtherRequest")
    )
    assert cli.main([*basic_args(sample), "--dbc", str(source)]) == 0
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert list(scenario) == ["Sample"]


@pytest.mark.parametrize("name", ["missing.dbc", "schema.txt"])
def test_invalid_dbc_source_is_rejected(sample, name):
    with pytest.raises(SystemExit) as exc:
        cli.main([*basic_args(sample), "--dbc", str(sample["root"] / name)])
    assert exc.value.code == 2


def test_schema_without_excel_maps_element_names(sample):
    sample["schema"].write_text("Vehicle.SpeedCAN : single\n", encoding="utf-8")
    assert cli.main([*dbc_args(sample), "--schema", str(sample["schema"])]) == 0
    signal = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"][
        "Vehicle"
    ]["SpeedCAN"]
    assert signal["Data"].dtype.name == "float32"
    assert signal["Data"].tolist() == [0, 10, 30]


def test_force_without_excel_schema_or_dbc(sample):
    sample["config"].write_text(
        "input_forces:\n- {interface: Inputs, element: Enable, value: 7}\n", encoding="utf-8"
    )
    assert cli.main([*basic_args(sample), "--config", str(sample["config"])]) == 0
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert scenario["Inputs"]["Enable"]["Data"].tolist() == [7, 7]
    assert (sample["output"] / "sample.mat").is_file()


def custom_excel(sample, rows=None):
    path = sample["root"] / "custom.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([["Notes only"]]).to_excel(
            writer, sheet_name="Notes", header=False, index=False
        )
        pd.DataFrame(
            rows
            or [
                ["Group", "Wire label", "Target name", "Storage"],
                ["Vehicle", "SpeedCAN", "Speed", "single"],
            ]
        ).to_excel(writer, sheet_name="Any Project", header=False, index=False, startrow=3)
    return path


@pytest.mark.parametrize(
    "columns", [["Target name", "Wire label", "Group", "Storage"], ["3", "2", "1", "4"]]
)
def test_custom_sheets_headers_and_columns_without_schema(sample, columns):
    excel = custom_excel(sample)
    argv = [
        *dbc_args(sample),
        "--excel",
        str(excel),
        "--input-sheet",
        "Any Project",
        "--header-row",
        "4",
    ]
    for name, value in zip(("element", "can", "interface", "dtype"), columns):
        argv += [f"--{name}-column", value]
    assert cli.main(argv) == 0
    signal = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"][
        "Vehicle"
    ]["Speed"]
    assert signal["Data"].dtype.name == "float32"
    assert signal["Data"].tolist() == [0, 10, 30]


def test_auto_detect_generic_sheets_skips_notes(sample):
    excel = custom_excel(
        sample,
        [["Bus", "CAN Signal", "Data Element", "Type"], ["Vehicle", "SpeedCAN", "Speed", "single"]],
    )
    assert cli.main([*dbc_args(sample), "--excel", str(excel)]) == 0
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert "Vehicle" in scenario
    assert not (sample["output"] / "sample_output.mat").exists()


def test_output_only_sheet_and_unknown_sheet_errors(sample):
    excel = custom_excel(
        sample,
        [["Interface", "CAN Signal", "Data Element"], ["Controller", "RequestCAN", "Request"]],
    )
    argv = [*dbc_args(sample), "--excel", str(excel), "--output-sheet", "Any Project"]
    assert cli.main(argv) == 0
    assert (sample["output"] / "sample_output.mat").is_file()
    assert not (sample["output"] / "sample_input.mat").exists()
    assert cli.main([*dbc_args(sample), "--excel", str(excel), "--input-sheet", "Missing"]) == 1


def test_multiple_input_sheets(sample):
    excel = sample["root"] / "multi.xlsx"
    with pd.ExcelWriter(excel) as writer:
        for sheet, bus, source in (("A", "Vehicle", "SpeedCAN"), ("B", "Controller", "RequestCAN")):
            pd.DataFrame({"Bus": [bus], "CAN Signal": [source]}).to_excel(
                writer, sheet_name=sheet, index=False
            )
    assert (
        cli.main(
            [*dbc_args(sample), "--excel", str(excel), "--input-sheet", "A", "--input-sheet", "B"]
        )
        == 0
    )
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert list(scenario) == ["Vehicle", "Controller"]


@pytest.mark.parametrize("explicit", [False, True])
def test_excel_keywords_filter_all_cells_on_both_sides(sample, explicit, capsys):
    excel = sample["root"] / "filtered.xlsx"
    with pd.ExcelWriter(excel) as writer:
        for sheet in ("SWC_INF", "SWC_OUTF"):
            pd.DataFrame(
                [
                    ["Vehicle", "Speed", "SpeedCAN", "single", ""],
                    ["", "Speed", "RequestCAN", "single", "Marked OBSOLETE today"],
                    ["", "Ignored", "SpeedCAN", "invalid", "literal [skip] marker"],
                    ["", "Kept", "RequestCAN", "uint8", "skipping is not a literal marker"],
                    ["", "ObsoleteTarget", "SpeedCAN", "single", ""],
                    ["", "BadSource", "ObsoleteCAN", "single", ""],
                    ["ObsoleteBus", "BadBus", "SpeedCAN", "single", ""],
                    ["Other", "BadType", "SpeedCAN", "obsolete_type", ""],
                    ["", "Inherited", "RequestCAN", "uint8", ""],
                ],
                columns=["Interface", "Data Element", "CAN Signal", "Type", "Notes"],
            ).to_excel(writer, sheet_name=sheet, index=False)
    sample["config"].write_text('excel_skip_keywords: [" ObSoLeTe ", "[skip]"]\n')
    argv = [*dbc_args(sample), "--excel", str(excel), "--config", str(sample["config"])]
    if explicit:
        argv += ["--input-sheet", "SWC_INF", "--output-sheet", "SWC_OUTF", "--header-row", "1"]
    assert cli.main(argv) == 0
    for side in ("input", "output"):
        scenario = loadmat(sample["output"] / f"sample_{side}.mat", simplify_cells=True)["Scenario"]
        assert set(scenario) == {"Vehicle", "Other"}
        assert set(scenario["Vehicle"]) == {"Speed", "Kept"}
        assert scenario["Vehicle"]["Speed"]["Data"].tolist() == (
            [0, 10, 30] if side == "input" else [10, 30]
        )
        # Blank interface cells keep the workbook's group even after an excluded row.
        assert set(scenario["Other"]) == {"Inherited"}
    assert capsys.readouterr().out.count("skipped 6 row(s) matching excel_skip_keywords") == 2


@pytest.mark.parametrize("setting", ["{}", "excel_skip_keywords: []"])
def test_excel_keywords_disabled_by_default(sample, setting):
    excel = custom_excel(
        sample,
        [["Bus", "CAN Signal", "Data Element"], ["Vehicle", "SpeedCAN", "ObsoleteSpeed"]],
    )
    sample["config"].write_text(setting)
    assert (
        cli.main([*dbc_args(sample), "--excel", str(excel), "--config", str(sample["config"])]) == 0
    )
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert "ObsoleteSpeed" in scenario["Vehicle"]


def test_excel_keywords_all_rows_excluded_fail_clearly(sample, capsys):
    excel = custom_excel(
        sample,
        [["Bus", "CAN Signal", "Data Element"], ["Vehicle", "SpeedCAN", "ObsoleteSpeed"]],
    )
    sample["config"].write_text("excel_skip_keywords: [obsolete]\n")
    assert (
        cli.main([*dbc_args(sample), "--excel", str(excel), "--config", str(sample["config"])]) == 1
    )
    assert "No mapping rows were resolved" in capsys.readouterr().err
    assert not list(sample["output"].glob("*.mat"))


@pytest.mark.parametrize("value", ['"obsolete"', "null", "[1]", "[true]", '[""]', '["  "]', "{}"])
def test_invalid_excel_keywords_config_rejected(sample, value, capsys):
    sample["config"].write_text(f"excel_skip_keywords: {value}\n")
    assert cli.main([*basic_args(sample), "--config", str(sample["config"])]) == 1
    assert "'excel_skip_keywords' must" in capsys.readouterr().err
    assert not list(sample["output"].glob("*.mat"))


def test_same_signal_name_from_different_messages_is_independent(sample):
    dbc = sample["root"] / "dbc/sample.dbc"
    with dbc.open("a") as stream:
        stream.write('BO_ 257 Second: 1 ECU\n SG_ SpeedCAN : 0|8@1+ (1,0) [0|255] "" ECU\n')
    with can.BLFWriter(sample["blf"]) as writer:
        writer.on_message_received(
            can.Message(timestamp=1, arbitration_id=256, is_extended_id=False, data=[10, 2])
        )
        writer.on_message_received(
            can.Message(timestamp=2, arbitration_id=257, is_extended_id=False, data=[99])
        )
    assert cli.main(dbc_args(sample)) == 0
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert scenario["Sample"]["SpeedCAN"]["Data"] == 10
    assert scenario["Second"]["SpeedCAN"]["Data"] == 99


def test_missing_dbc_preserves_fd_and_extended_frame_metadata(sample):
    with can.BLFWriter(sample["blf"]) as writer:
        writer.on_message_received(
            can.Message(
                timestamp=1,
                arbitration_id=0x123456,
                is_extended_id=True,
                is_fd=True,
                bitrate_switch=True,
                data=list(range(64)),
            )
        )
    assert cli.main(basic_args(sample)) == 0
    frame = loadmat(sample["output"] / "sample.mat", simplify_cells=True)["Frames"]
    assert frame["Extended"] == 1 and frame["FD"] == 1 and frame["BRS"] == 1
    assert frame["Length"] == 64
    assert frame["Data"].tolist() == list(range(64))


def test_dataset_single_side_and_missing_matlab(sample, monkeypatch):
    argv = [*dbc_args(sample), "--format", "dataset", "--matlab", __file__]
    captured = []

    def package(executable, script, cwd):
        captured.append(script.read_text())
        (sample["output"] / "sample_signals.mat").touch()

    monkeypatch.setattr(core, "run_matlab_batch", package)
    assert cli.main(argv) == 0
    assert "if isempty(jobs{k,side}), continue; end" in captured[0]
    assert ", '';" in captured[0]

    def missing(*args):
        raise cli.argparse.ArgumentTypeError("MATLAB unavailable")

    monkeypatch.setattr(cli, "find_matlab_executable", missing)
    with pytest.raises(SystemExit) as exc:
        cli.main([*dbc_args(sample), "--format", "dataset"])
    assert exc.value.code == 2


def test_mapped_standard_mat_does_not_launch_matlab(sample, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("MATLAB should not run")

    monkeypatch.setattr(core, "run_matlab_batch", forbidden)
    assert cli.main([*sample["argv"], "--format", "mat"]) == 0
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert scenario["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]


@pytest.mark.parametrize(
    "extra", [["--header-row", "0"], ["--can-column", "2"], ["--input-sheet", "A"]]
)
def test_excel_options_need_workbook(sample, extra):
    with pytest.raises(SystemExit) as exc:
        cli.main([*basic_args(sample), *extra])
    assert exc.value.code == 2


def test_blf_only_from_built_archive(tmp_path, sample):
    archive = build(tmp_path / "release")
    result = subprocess.run(
        [sys.executable, str(archive), *basic_args(sample)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert loadmat(sample["output"] / "sample.mat", simplify_cells=True)["Frames"][
        "ID"
    ].tolist() == [999, 256, 256]
