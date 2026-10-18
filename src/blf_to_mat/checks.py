"""Non-destructive runtime diagnostics; never start MATLAB or install packages."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable

from . import __version__
from .cli import find_matlab_executable

MODULES = ("numpy", "pandas", "scipy.io", "can", "cantools", "openpyxl", "yaml")


def check_environment(
    matlab: str | None = None, emit: Callable[[str], None] = print, *, require_matlab: bool = False
) -> int:
    emit(f"blf-to-mat {__version__} | Python {sys.version.split()[0]}")
    failures = 0
    supported = (3, 11) <= sys.version_info[:2] < (3, 15)
    emit(f"[{'OK' if supported else 'FAIL'}] Python support: 3.11-3.14")
    failures += not supported
    for name in MODULES:
        try:
            module = importlib.import_module(name)
            emit(f"[OK] {name} {getattr(module, '__version__', '')}".rstrip())
        except Exception as exc:
            failures += 1
            emit(f"[FAIL] {name}: {exc}")
    try:
        emit(f"[OK] MATLAB executable: {find_matlab_executable(matlab)}")
    except Exception as exc:
        failures += require_matlab
        emit(f"[{'FAIL' if require_matlab else 'OPTIONAL'}] MATLAB: {exc}")
    try:
        importlib.import_module("tkinter")
        emit("[OK] tkinter (GUI support)")
    except Exception as exc:
        emit(f"[OPTIONAL] tkinter (CLI remains usable): {exc}")
    emit("MATLAB/Simulink version, license and Dataset serialization require an actual conversion.")
    emit("Tcl/Tk import does not verify display availability; opening the GUI verifies it.")
    if failures:
        emit("Install Python packages with: python -m pip install -r requirements.txt")
    return 1 if failures else 0
