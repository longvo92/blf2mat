"""Build a deterministic source-only zipapp and its runtime requirements/checksum."""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_version(root: Path = ROOT) -> str:
    tree = ast.parse((root / "src/blf_to_mat/__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            version = ast.literal_eval(node.value)
            if isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version):
                return version
    raise ValueError("__version__ must be a literal stable MAJOR.MINOR.PATCH string")


def validate_release(tag: str, root: Path = ROOT) -> None:
    version = project_version(root)
    if tag != f"v{version}":
        raise ValueError(f"Release tag {tag!r} must match v{version}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M):
        raise ValueError(f"CHANGELOG.md needs a dated section for {version}")


def build(output: Path, root: Path = ROOT) -> Path:
    version = project_version(root)
    output.mkdir(parents=True, exist_ok=True)
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = "\n".join(metadata["project"]["dependencies"]) + "\n"
    entries = {
        "__main__.py": b"from blf_to_mat.cli import main\nraise SystemExit(main())\n",
        "requirements.txt": requirements.encode("utf-8"),
        "LICENSE": (root / "LICENSE").read_text(encoding="utf-8").encode("utf-8"),
    }
    for source in sorted((root / "src/blf_to_mat").rglob("*.py")):
        entries[source.relative_to(root / "src").as_posix()] = source.read_text(
            encoding="utf-8"
        ).encode("utf-8")
    archive = output / f"blf_to_mat-{version}.pyz"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in sorted(entries.items()):
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, data)
    (output / "requirements.txt").write_text(requirements, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii", newline="\n"
    )
    print(archive)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--release-tag", help="Require tag/version/changelog consistency")
    args = parser.parse_args()
    if args.release_tag:
        validate_release(args.release_tag)
    build(args.output)


if __name__ == "__main__":
    main()
