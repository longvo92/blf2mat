"""Tkinter front end with one worker and main-thread-only widget updates."""

from __future__ import annotations

import argparse
import queue
import threading
import traceback
from collections.abc import Callable
from tkinter import END, StringVar, Text, Tk, filedialog, messagebox, ttk

from . import __version__
from .checks import check_environment
from .cli import build_arg_parser, resolve_paths
from .converter import convert


class _GuiParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


class Application:
    def __init__(self, root: Tk, args: argparse.Namespace | None = None) -> None:
        self.root = root
        self.busy = False
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.schema_files = list(args.schema or []) if args else []
        self.fields = {
            key: StringVar(value=getattr(args, key, None) or "" if args else "")
            for key in ("excel", "dbc_folder", "blf", "output", "config", "matlab")
        }
        self.schema_label = StringVar(value="; ".join(self.schema_files))
        self.status = StringVar(value="Ready")
        self.debug = bool(args and args.debug)
        root.title(f"BLF to MAT {__version__}")
        root.minsize(780, 580)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame = ttk.Frame(root, padding=12)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        self.controls: list[ttk.Widget] = []
        rows = (
            ("Excel workbook", "excel", "excel"),
            ("DBC folder", "dbc_folder", "directory"),
            ("BLF file / folder", "blf", "blf"),
            ("TXT schemas", "schema", "schema"),
            ("Output folder", "output", "directory"),
            ("YAML config (optional)", "config", "config"),
            ("MATLAB executable (auto)", "matlab", "matlab"),
        )
        for row, (label, key, kind) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
            variable = self.schema_label if key == "schema" else self.fields[key]
            entry = ttk.Entry(frame, textvariable=variable, width=65)
            entry.grid(row=row, column=1, sticky="ew", padx=8)
            if key == "schema":
                entry.state(["readonly"])
            self.controls.append(entry)
            button = ttk.Button(
                frame, text="Browse...", command=lambda k=key, t=kind: self.browse(k, t)
            )
            button.grid(row=row, column=2)
            self.controls.append(button)
            if key == "blf":
                folder = ttk.Button(
                    frame, text="Folder...", command=lambda: self.browse("blf", "directory")
                )
                folder.grid(row=row, column=3, padx=4)
                self.controls.append(folder)
        ttk.Label(
            frame, text="Empty YAML uses signal_mapping.yaml beside the .pyz when present."
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(4, 8))
        actions = ttk.Frame(frame)
        actions.grid(row=8, column=0, columnspan=4, sticky="ew")
        for label, command in (
            ("Convert", self.start_conversion),
            ("Check environment", self.start_check),
        ):
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side="left", padx=(0, 8))
            self.controls.append(button)
        self.progress = ttk.Progressbar(actions, mode="indeterminate")
        self.progress.pack(side="right", fill="x", expand=True)
        ttk.Label(frame, textvariable=self.status).grid(
            row=9, column=0, columnspan=4, sticky="w", pady=6
        )
        self.output = Text(frame, wrap="word", state="disabled", height=16)
        self.output.grid(row=10, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=self.output.yview)
        scrollbar.grid(row=10, column=3, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)
        frame.rowconfigure(10, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(75, self.poll)

    def browse(self, key: str, kind: str) -> None:
        if kind == "directory":
            value = filedialog.askdirectory(parent=self.root, mustexist=key != "output")
        elif kind == "schema":
            files = filedialog.askopenfilenames(
                parent=self.root, filetypes=[("TXT schema", "*.txt")]
            )
            if files:
                self.schema_files = list(files)
                self.schema_label.set("; ".join(files))
            return
        else:
            filters = {
                "excel": [("Excel workbook", "*.xlsx *.xlsm")],
                "blf": [("CAN BLF log", "*.blf")],
                "config": [("YAML mapping", "*.yaml *.yml")],
                "matlab": [("MATLAB executable", "matlab.exe matlab"), ("All files", "*")],
            }
            value = filedialog.askopenfilename(parent=self.root, filetypes=filters[kind])
        if value:
            self.fields[key].set(value)

    def append_log(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert(END, text + "\n")
        self.output.see(END)
        self.output.configure(state="disabled")

    def start_conversion(self) -> None:
        if self.busy:
            return
        args = build_arg_parser().parse_args([])
        for name, variable in self.fields.items():
            setattr(args, name, variable.get().strip() or None)
        args.schema = list(self.schema_files)
        try:
            paths = resolve_paths(args, _GuiParser())
        except Exception as exc:
            self.status.set("Invalid inputs")
            messagebox.showerror("Invalid inputs", str(exc), parent=self.root)
            return
        self.start_job(lambda emit: convert(paths, log_callback=emit), "Converting...")

    def start_check(self) -> None:
        matlab = self.fields["matlab"].get().strip() or None
        self.start_job(lambda emit: check_environment(matlab, emit), "Checking environment...")

    def start_job(self, job: Callable[[Callable[[str], None]], int], label: str) -> None:
        if self.busy:
            return
        self.busy = True
        self.status.set(label)
        for control in self.controls:
            control.state(["disabled"])
        self.progress.start(12)

        def worker() -> None:
            try:
                code = job(lambda text: self.events.put(("log", text)))
                self.events.put(("done", code))
            except Exception as exc:
                self.events.put(("log", f"ERROR: {exc}"))
                if self.debug:
                    self.events.put(("log", traceback.format_exc()))
                self.events.put(("done", 1))

        threading.Thread(target=worker, name="blf-converter", daemon=False).start()

    def poll(self) -> None:
        # Bound each tick so a large conversion log cannot starve the UI.
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.append_log(str(value))
            else:
                self.busy = False
                self.progress.stop()
                self.progress.configure(value=0)
                for control in self.controls:
                    control.state(["!disabled"])
                self.status.set("Completed" if value == 0 else "Failed - see log")
        self.poll_id = self.root.after(75, self.poll)

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo(
                "Operation running",
                "Wait for the operation to finish before closing.",
                parent=self.root,
            )
            return
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def launch(args: argparse.Namespace | None = None) -> int:
    root = Tk()
    Application(root, args)
    root.mainloop()
    return 0
