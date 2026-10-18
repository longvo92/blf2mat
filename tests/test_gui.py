from __future__ import annotations

import os
import time

import pytest

from blf_to_mat import cli
from blf_to_mat import converter as core
from tests.test_conversion import fake_packager


@pytest.fixture(scope="module")
def tk_root():
    try:
        import tkinter

        root = tkinter.Tk()
    except Exception as exc:
        if os.environ.get("BLF_REQUIRE_GUI") == "1":
            pytest.fail(f"Required GUI runtime unavailable: {exc}")
        pytest.skip(f"Graphical display/Tcl/Tk unavailable: {exc}")
    root.withdraw()
    # Keep a single Tcl/Tk interpreter for this test module, as in the real app.
    # Recreating interpreters between threaded tests is unstable on Windows Tk.
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root):
    from blf_to_mat.gui import Application

    application = Application(tk_root)
    yield application
    tk_root.after_cancel(application.poll_id)
    for widget in tk_root.winfo_children():
        widget.destroy()
    tk_root.update_idletasks()


def wait_for_job(app):
    deadline = time.monotonic() + 15
    while app.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not app.busy
    assert not app.progress.instate(["disabled"])
    assert float(app.progress["value"]) == 0


@pytest.mark.gui
def test_gui_conversion_uses_shared_pipeline(app, sample, monkeypatch):
    args = cli.build_arg_parser().parse_args(sample["argv"])
    for key, variable in app.fields.items():
        variable.set(getattr(args, key, None) or "")
    app.schema_files = args.schema
    captured = []
    monkeypatch.setattr(core, "run_matlab_batch", fake_packager(captured))
    app.start_conversion()
    assert app.busy
    assert all(widget.instate(["disabled"]) for widget in app.controls)
    wait_for_job(app)
    assert app.status.get() == "Completed"
    assert len(captured) == 2
    assert "[SUMMARY]" in app.output.get("1.0", "end")
    assert all(not widget.instate(["disabled"]) for widget in app.controls)


@pytest.mark.gui
def test_gui_failure_recovers_controls(app):
    def fail(emit):
        raise RuntimeError("Synthetic failure")

    app.start_job(fail, "Working")
    wait_for_job(app)
    assert app.status.get().startswith("Failed")
    assert "Synthetic failure" in app.output.get("1.0", "end")
    assert all(not widget.instate(["disabled"]) for widget in app.controls)


@pytest.mark.gui
def test_gui_invalid_inputs_do_not_start_worker(app, monkeypatch):
    from blf_to_mat import gui

    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    app.start_conversion()
    assert not app.busy
    assert app.status.get() == "Invalid inputs"
    assert errors


@pytest.mark.gui
def test_gui_blf_only(app, sample):
    app.fields["blf"].set(str(sample["blf"]))
    app.start_conversion()
    wait_for_job(app)
    assert app.status.get() == "Completed"
    assert (sample["root"] / "mat_output/sample.mat").is_file()


@pytest.mark.gui
@pytest.mark.parametrize("single_file", [False, True])
def test_gui_dbc_file_and_folder_buttons(app, sample, monkeypatch, single_file):
    from tkinter import ttk

    from blf_to_mat import gui

    source = sample["root"] / "dbc"
    if single_file:
        source = source / "sample.dbc"
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kwargs: str(source))
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **kwargs: str(source))
    frame = app.root.winfo_children()[0]
    button = next(
        widget
        for widget in app.controls
        if isinstance(widget, ttk.Button)
        and widget.master is frame
        and int(widget.grid_info()["row"]) == 1
        and int(widget.grid_info()["column"]) == (2 if single_file else 3)
    )
    button.invoke()
    assert app.fields["dbc_folder"].get() == str(source)
    app.fields["blf"].set(str(sample["blf"]))
    app.start_conversion()
    wait_for_job(app)
    assert app.status.get() == "Completed"
    assert (sample["root"] / "mat_output/sample_signals.mat").is_file()


@pytest.mark.gui
def test_gui_custom_excel_options_share_cli_validation(app, sample):
    import pandas as pd

    excel = sample["root"] / "gui.xlsx"
    with pd.ExcelWriter(excel) as writer:
        pd.DataFrame({"Target": ["Vehicle.Speed"], "Source": ["SpeedCAN"]}).to_excel(
            writer, sheet_name="Custom", index=False
        )
    for name, value in {
        "blf": str(sample["blf"]),
        "dbc_folder": str(sample["root"] / "dbc"),
        "excel": str(excel),
        "element_column": "Target",
        "can_column": "Source",
        "header_row": "1",
    }.items():
        app.fields[name].set(value)
    from tkinter import Listbox, Toplevel, ttk

    app.select_sheets()
    window = next(widget for widget in app.root.winfo_children() if isinstance(widget, Toplevel))
    lists = [widget for widget in window.winfo_children() if isinstance(widget, Listbox)]
    lists[0].selection_set(0)
    apply = next(widget for widget in window.winfo_children() if isinstance(widget, ttk.Button))
    apply.invoke()
    assert app.sheets["input"] == ["Custom"]
    app.start_conversion()
    wait_for_job(app)
    assert app.status.get() == "Completed"
    assert (sample["root"] / "mat_output/sample_input.mat").is_file()
