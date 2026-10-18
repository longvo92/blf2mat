from __future__ import annotations

import os
import time

import pytest

from blf_to_mat import cli
from blf_to_mat import converter as core
from tests.test_conversion import fake_packager


@pytest.fixture
def app():
    try:
        import tkinter

        root = tkinter.Tk()
    except Exception as exc:
        if os.environ.get("BLF_REQUIRE_GUI") == "1":
            pytest.fail(f"Required GUI runtime unavailable: {exc}")
        pytest.skip(f"Graphical display/Tcl/Tk unavailable: {exc}")
    from blf_to_mat.gui import Application

    root.withdraw()
    application = Application(root)
    yield application
    if root.winfo_exists():
        root.after_cancel(application.poll_id)
        root.destroy()


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
