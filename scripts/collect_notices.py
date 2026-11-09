"""Put every third-party notice the distributed app needs next to the exe.

    python scripts/collect_notices.py DIST_DIR

DIST_DIR is the PyInstaller onedir output (the folder with GPUTaskManager.exe).
It writes:
  DIST_DIR/THIRD-PARTY-NOTICES.txt     component, version, licence, where the full text is
  DIST_DIR/licenses/<component>/...    full licence texts

Every bundled component is under a permissive licence; a copyleft one must not be added
without revisiting how it is shipped (the tray icon is native for that reason).

Fails loudly when a licence it must ship cannot be found: an installer without its
notices is not distributable.
"""

from __future__ import annotations

import shutil
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_desktop import brand  # noqa: E402

# Runtime packages bundled into the exe, with their licence as declared upstream.
RUNTIME = {
    "nvidia-ml-py": "BSD-3-Clause (NVIDIA Corporation)",
    "psutil": "BSD-3-Clause",
    "pillow": "MIT-CMU (HPND), plus bundled image libraries listed in its licence file",
}
LICENSE_PREFIXES = ("license", "licence", "copying", "notice")


def _licence_files(dist: metadata.Distribution) -> list[Path]:
    found = []
    for f in dist.files or ():
        name = f.name.lower()
        if name.startswith(LICENSE_PREFIXES) or ("licenses" in f.parts and "dist-info" in str(f)):
            found.append(Path(dist.locate_file(f)))
    return [p for p in found if p.is_file()]


def _nvml_license(dist: metadata.Distribution) -> str:
    source = Path(dist.locate_file("pynvml.py")).read_text(encoding="utf-8")
    header, boundary, _rest = source.partition("\n#####\n")
    if not boundary or "Redistribution and use" not in header:
        raise SystemExit("NVIDIA bindings: inline licence not found in pynvml.py")
    return header + boundary


def _python_license() -> Path:
    base = Path(sys.base_prefix)
    for p in (base / "LICENSE.txt", Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
              base / "share" / "doc" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE"):
        if p.is_file():
            return p
    raise SystemExit("Python licence not found")


def _tcl_tk_licenses() -> list[Path]:
    base = Path(sys.base_prefix)
    hits: list[Path] = []
    for root in (base / "tcl", base / "lib"):  # Windows python.org layout, then Unix layout
        if root.is_dir():
            for d in sorted(root.glob("t[ck]*")):
                if d.is_dir() and (d / "license.terms").is_file():
                    hits.append(d / "license.terms")
    return hits[:4]


def main(dist_dir: Path) -> None:
    if not dist_dir.is_dir():
        raise SystemExit(f"not a folder: {dist_dir}")
    out = dist_dir / "licenses"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    lines = [
        f"{brand.APP_NAME} {brand.APP_VERSION}",
        brand.COPYRIGHT,
        f"{brand.LICENSE_NAME}: see LICENSE and NOTICE. Source: {brand.REPO_URL}",
        "",
        "This product includes the third-party components listed below. Each is distributed",
        "under its own licence; the full texts are in the 'licenses' folder next to this file.",
        "",
    ]

    def entry(name: str, version: str, licence: str, folder: str, extra: str = "") -> None:
        lines.append(f"* {name} {version}".rstrip())
        lines.append(f"  Licence: {licence}")
        lines.append(f"  Full text: licenses\\{folder}")
        if extra:
            lines.append(f"  {extra}")
        lines.append("")

    # Measurement engine (vendored source, MIT)
    (out / "gputaskman").mkdir()
    shutil.copy2(ROOT / "licenses" / "gputaskman-LICENSE.txt", out / "gputaskman" / "LICENSE.txt")
    upstream = (ROOT / "UPSTREAM.md").read_text(encoding="utf-8") if (ROOT / "UPSTREAM.md").exists() else ""
    commit = next((ln.split("`")[1] for ln in upstream.splitlines() if ln.startswith("- Commit:")), "")
    entry(brand.ENGINE_NAME, f"(commit {commit[:12]})" if commit else "", "MIT, Copyright (c) 2026 Scott Hanselman",
          "gputaskman", f"Source: {brand.ENGINE_URL}")

    for pkg, licence in RUNTIME.items():
        dist = metadata.distribution(pkg)
        folder = out / pkg
        folder.mkdir()
        if pkg == "nvidia-ml-py":
            (folder / "LICENSE.txt").write_text(_nvml_license(dist), encoding="utf-8")
        files = _licence_files(dist)
        for f in files:
            shutil.copy2(f, folder / f.name)
        if not any(folder.iterdir()):
            raise SystemExit(f"{pkg}: no licence file found in its distribution")
        entry(pkg, dist.version, licence, pkg, "")

    # Python runtime, Tcl/Tk, PyInstaller bootloader
    (out / "python").mkdir()
    shutil.copy2(_python_license(), out / "python" / "LICENSE.txt")
    entry("Python", sys.version.split()[0], "PSF License Agreement", "python")

    tcl = _tcl_tk_licenses()
    if tcl:
        (out / "tcl-tk").mkdir()
        for i, p in enumerate(tcl):
            shutil.copy2(p, out / "tcl-tk" / f"license-{i + 1}.terms")
        entry("Tcl/Tk", "", "Tcl/Tk License (BSD-style)", "tcl-tk")
    elif "tcl" in _python_license().read_text(encoding="utf-8", errors="ignore").lower():
        entry("Tcl/Tk", "", "Tcl/Tk License (BSD-style), included in the Python licence file", "python")
    else:
        print("WARNING: Tcl/Tk licence.terms not found; add it to licenses\\tcl-tk by hand", file=sys.stderr)

    pyi = metadata.distribution("pyinstaller")
    (out / "pyinstaller").mkdir()
    for f in pyi.files or ():
        if f.name.lower() in {"copying.txt", "license", "license.txt"}:
            shutil.copy2(pyi.locate_file(f), out / "pyinstaller" / f.name)
    if not any((out / "pyinstaller").iterdir()):
        raise SystemExit("PyInstaller bootloader licence not found")
    entry("PyInstaller bootloader", pyi.version, "GPL-2.0-or-later with the bootloader exception "
          "(allows distributing the resulting executable under any licence)", "pyinstaller")

    lines += ["GPU vendor libraries (NVML, ADL, AMD SMI) are provided by the installed driver,",
              "system libraries by Windows. None of them is redistributed with this product."]
    (dist_dir / "THIRD-PARTY-NOTICES.txt").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    print(f"notices written: {dist_dir / 'THIRD-PARTY-NOTICES.txt'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
