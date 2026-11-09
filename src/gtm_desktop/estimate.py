"""Best-guess model for AI processes that leave no OS evidence of what they loaded.

Why: several runtimes read the model file into memory and close it (CTranslate2 for
faster-whisper, PyTorch with torch.load / .bin checkpoints, ONNX Runtime), so neither
memory maps nor open handles name the model and gputaskman shows only "AI". This module
adds an explicitly labelled *estimate*, in our layer, without touching the vendored engine.

Runtimes, recognised by the GPU libraries loaded in the process (a CPU-only runtime does not
explain VRAM and is ignored):
  CTranslate2   ctranslate2.dll                                    format: folder with model.bin + config.json
  ONNX Runtime  onnxruntime_providers_cuda / _tensorrt, DirectML   format: *.onnx (+ external data)
  PyTorch       torch_cuda.dll / c10_cuda.dll                      format: folder with config.json + *.safetensors
                                                                           or pytorch_model*.bin; or *.pt/.pth/.ckpt

Candidates of those formats come from the process working directory (bounded walk) and the
HuggingFace hub cache named by the process environment (HF_HUB_CACHE, HF_HOME\\hub,
%USERPROFILE%\\.cache\\huggingface\\hub).

Decision tree, per process (sampler thread):
  engine already has evidence (LLM view, mapped/cmdline model, installed candidates) -> none
  not AI, other PID namespace, no VRAM figure, no GPU runtime library                -> none
  1. "in code": candidates whose id (hub "org/name", or folder/file name) appears in the
     process command line, environment values or entry-point source files
       one  -> that one;  several -> the largest that fits the VRAM, else the smallest
  2. "by size", only where size ranks a homogeneous set: the working directory's own models,
     and CTranslate2 models in the hub cache (in practice the faster-whisper sizes)
       -> the largest that fits the VRAM
  3. otherwise none: a general hub cache holds unrelated models, and picking one by size
     alone would be a guess presented as a fact.

Estimates are always shown as such, with the alternatives found. Environment values are used
only for matching, never stored or displayed.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

TTL_S = 300.0           # evidence per process, and hub listings, are refreshed at most this often
WALK_DEPTH = 4
WALK_BUDGET = 3000      # directory entries per working-directory walk
SOURCE_FILES = 200      # entry-point source files read per process
SOURCE_BYTES = 8 << 20  # and their total size
FIT_SLACK = 1.02        # weights may round slightly above the reported VRAM figure
SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "site-packages", ".mypy_cache",
             ".pytest_cache", "dist", "build"}
SOURCE_EXTS = {".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env"}

CT2, ONNX, TORCH = "CTranslate2", "ONNX RT", "PyTorch"  # same labels as gputaskman's runtime list
# runtime -> library names (lower case) that prove it runs on a GPU
GPU_LIBS = {
    CT2: ("ctranslate2.dll", "libctranslate2.so", "libctranslate2.dylib"),
    ONNX: ("onnxruntime_providers_cuda.dll", "onnxruntime_providers_tensorrt.dll", "directml.dll",
           "libonnxruntime_providers_cuda.so", "libonnxruntime_providers_tensorrt.so"),
    TORCH: ("torch_cuda.dll", "c10_cuda.dll", "libtorch_cuda.so", "libc10_cuda.so"),
}
TORCH_FILE_EXTS = (".pt", ".pth", ".ckpt")


@dataclass(frozen=True)
class Candidate:
    label: str    # "Systran/faster-whisper-large-v3", "BAAI/bge-m3/onnx/model.onnx", or a folder/file name
    path: str     # model folder or file
    size: int     # weight bytes
    runtime: str  # CT2 | ONNX | TORCH
    origin: str   # "hub" | "cwd"


@dataclass(frozen=True)
class Estimate:
    runtime: str
    model: Candidate
    vram: float
    alternatives: tuple[Candidate, ...]
    basis: str        # "code" | "size"
    where: str = ""   # with basis "code": "command line" | "environment" | "source"

    @property
    def family(self) -> str:
        return "Whisper" if "whisper" in self.model.label.lower() else ""


# ---------------------------------------------------------------- model formats

def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _ct2(folder: str, names: set[str], label: str, origin: str) -> list[Candidate]:
    if "model.bin" in names and "config.json" in names:
        size = _size(os.path.join(folder, "model.bin"))
        if size:
            return [Candidate(label, folder, size, CT2, origin)]
    return []


def _torch_dir(folder: str, names: set[str], label: str, origin: str) -> list[Candidate]:
    if "config.json" not in names or "model.bin" in names:  # model.bin + config.json is CTranslate2
        return []
    st = [n for n in names if n.endswith(".safetensors")]
    pt = [n for n in names if n.startswith("pytorch_model") and n.endswith(".bin")]
    weights = st or pt  # both present: the same weights twice, transformers prefers safetensors
    size = sum(_size(os.path.join(folder, n)) for n in weights)
    return [Candidate(label, folder, size, TORCH, origin)] if size else []


def _onnx_files(folder: str, names: set[str], label: str, origin: str) -> list[Candidate]:
    out = []
    for n in sorted(names):
        if n.endswith(".onnx"):
            size = _size(os.path.join(folder, n))
            for extra in (n + "_data", n + ".data", n[:-5] + ".onnx_data"):  # external weights
                if extra in names:
                    size += _size(os.path.join(folder, extra))
                    break
            if size:
                out.append(Candidate(f"{label}/{n}" if label else n, os.path.join(folder, n), size, ONNX, origin))
    return out


def _torch_files(folder: str, names: set[str], origin: str) -> list[Candidate]:
    out = []
    for n in sorted(names):
        if n.endswith(TORCH_FILE_EXTS):
            size = _size(os.path.join(folder, n))
            if size >= 1 << 20:
                out.append(Candidate(n, os.path.join(folder, n), size, TORCH, origin))
    return out


def _models_in(folder: str, label: str, origin: str, loose_files: bool) -> list[Candidate]:
    try:
        names = {e.name for e in os.scandir(folder) if e.is_file()}
    except OSError:
        return []
    found = _ct2(folder, names, label, origin) + _torch_dir(folder, names, label, origin)
    found += _onnx_files(folder, names, label, origin)
    if loose_files:
        found += _torch_files(folder, names, origin)
    return found


# ---------------------------------------------------------------- where models live

def _hub_roots(env: dict[str, str]) -> list[str]:
    roots = []
    if env.get("HF_HUB_CACHE"):
        roots.append(env["HF_HUB_CACHE"])
    if env.get("HF_HOME"):
        roots.append(os.path.join(env["HF_HOME"], "hub"))
    home = env.get("USERPROFILE") or env.get("HOME") or os.path.expanduser("~")
    roots.append(os.path.join(home, ".cache", "huggingface", "hub"))
    seen, out = set(), []
    for r in roots:
        key = os.path.normcase(os.path.abspath(r))
        if key not in seen and os.path.isdir(r):
            seen.add(key)
            out.append(r)
    return out


def hub_models(root: str) -> list[Candidate]:
    """Models in a HuggingFace hub cache: models--org--name/snapshots/<newest rev>/ (root and one level down)."""
    found: list[Candidate] = []
    try:
        repos = [e for e in os.scandir(root) if e.is_dir() and e.name.startswith("models--")]
    except OSError:
        return found
    for repo in repos:
        repo_id = repo.name[len("models--"):].replace("--", "/")
        try:
            revs = sorted((e for e in os.scandir(os.path.join(repo.path, "snapshots")) if e.is_dir()),
                          key=lambda e: e.stat().st_mtime, reverse=True)
        except OSError:
            continue
        if not revs:
            continue
        snap = revs[0].path
        found += _models_in(snap, repo_id, "hub", loose_files=False)
        try:
            subdirs = [e for e in os.scandir(snap) if e.is_dir()]
        except OSError:
            subdirs = []
        for sub in subdirs:  # onnx/, or one model per folder
            found += _models_in(sub.path, f"{repo_id}/{sub.name}", "hub", loose_files=False)
    return found


def tree_models(root: str) -> list[Candidate]:
    """Models under a working directory (bounded walk; skips virtualenvs, VCS and build output)."""
    found: list[Candidate] = []
    budget = [WALK_BUDGET]

    def walk(folder: str, depth: int) -> None:
        if depth < 0 or budget[0] <= 0:
            return
        found.extend(_models_in(folder, os.path.basename(folder.rstrip("\\/")), "cwd", loose_files=True))
        try:
            entries = [e for e in os.scandir(folder) if e.is_dir(follow_symlinks=False)]
        except OSError:
            return
        budget[0] -= len(entries) + 1
        for e in entries:
            if e.name not in SKIP_DIRS and not e.name.startswith("."):
                walk(e.path, depth - 1)

    walk(root, WALK_DEPTH)
    return found


# ---------------------------------------------------------------- what the process says about itself

def source_files(cmdline: list[str], cwd: str) -> list[str]:
    """Entry-point source of a Python process: the script (and its folder), or the -m module's package."""
    if not cmdline or not cwd:
        return []
    exe = os.path.basename(cmdline[0]).lower()
    if not exe.startswith(("python", "pythonw", "py.exe")):
        return []
    targets: list[str] = []
    args = cmdline[1:]
    for i, a in enumerate(args):
        if a == "-m" and i + 1 < len(args):
            mod = args[i + 1].replace(".", os.sep)
            for cand in (os.path.join(cwd, mod + ".py"), os.path.join(cwd, mod)):
                if os.path.exists(cand):
                    top = os.path.join(cwd, args[i + 1].split(".")[0])
                    targets.append(top if os.path.isdir(top) else cand)
                    break
            break
        if a.endswith(".py"):
            path = a if os.path.isabs(a) else os.path.join(cwd, a)
            if os.path.isfile(path):
                targets.append(os.path.dirname(path))
            break
        if a == "-c":
            break
    if targets:  # top-level config files of the app (.env, settings.json, ...)
        targets.append(cwd)
    files: list[str] = []
    for t in targets:
        if os.path.isfile(t):
            files.append(t)
            continue
        for dirpath, dirnames, filenames in os.walk(t):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            if dirpath != t and t == cwd:
                dirnames[:] = []  # cwd itself: top level only
                continue
            files += [os.path.join(dirpath, f) for f in filenames
                      if os.path.splitext(f)[1].lower() in SOURCE_EXTS or f == ".env"]
            if len(files) >= SOURCE_FILES:
                break
    return list(dict.fromkeys(files))[:SOURCE_FILES]


def _read_sources(files: list[str]) -> str:
    chunks, total = [], 0
    for f in files:
        try:
            size = os.path.getsize(f)
        except OSError:
            continue
        if not size or size > (1 << 20) or total + size > SOURCE_BYTES:
            continue
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                chunks.append(fh.read())
            total += size
        except OSError:
            continue
    return "\n".join(chunks).lower()


def _ids(c: Candidate) -> list[str]:
    """Strings that name this candidate in code or configuration."""
    if c.origin == "hub":
        parts = c.label.split("/")
        return ["/".join(parts[:2])] if len(parts) >= 2 else [c.label]
    name = os.path.basename(c.path)
    return [name] if len(name) >= 6 else []  # very short names would match by accident


def referenced(cands: list[Candidate], texts: dict[str, str]) -> list[tuple[Candidate, str]]:
    """Candidates named in any of the texts (already lower case), with where the name was found."""
    out = []
    for c in cands:
        for where, text in texts.items():
            if text and any(i.lower() in text for i in _ids(c)):
                out.append((c, where))
                break
    return out


def pick(candidates: list[Candidate], vram: float) -> tuple[Candidate, tuple[Candidate, ...]] | None:
    """Largest candidate whose weights fit in the process VRAM; the others are returned as alternatives."""
    fitting = [c for c in candidates if c.size <= vram * FIT_SLACK]
    if not fitting:
        return None
    best = max(fitting, key=lambda c: c.size)
    return best, tuple(sorted((c for c in candidates if c is not best), key=lambda c: -c.size))


# ---------------------------------------------------------------- per-process evidence

@dataclass
class _Evidence:
    at: float
    runtimes: tuple[str, ...]
    candidates: list[Candidate]
    texts: dict[str, str]


class Estimator:
    """Per-process cache of runtime libraries, candidate models and naming evidence. Sampler thread only."""

    def __init__(self) -> None:
        self._procs: dict[tuple[int, float], _Evidence] = {}
        self._hub: dict[str, tuple[float, list[Candidate]]] = {}

    def estimate(self, row) -> Estimate | None:
        try:
            if row.host or row.llm or row.detail.models or row.detail.candidates or not row.detail.is_ai:
                return None
            vram = row.gpu.shown_vram
            if not vram:
                return None
            ev = self._evidence(row.pid)
        except Exception:  # noqa: BLE001 - an estimate must never break sampling
            log.debug("model estimate failed for pid %s", getattr(row, "pid", "?"), exc_info=True)
            return None
        return decide(ev.runtimes, ev.candidates, ev.texts, vram)

    def prune(self, live_pids: set[int]) -> None:
        for key in [k for k in self._procs if k[0] not in live_pids]:
            del self._procs[key]

    def _hub_models(self, root: str) -> list[Candidate]:
        now = time.monotonic()
        hit = self._hub.get(root)
        if hit and now - hit[0] < TTL_S:
            return hit[1]
        models = hub_models(root)
        self._hub[root] = (now, models)
        return models

    def _evidence(self, pid: int) -> _Evidence:
        import psutil
        proc = psutil.Process(pid)
        key = (pid, proc.create_time())
        now = time.monotonic()
        hit = self._procs.get(key)
        if hit and now - hit.at < TTL_S:
            return hit
        runtimes = hit.runtimes if hit else self._runtimes(proc)
        candidates: list[Candidate] = []
        texts: dict[str, str] = {}
        if runtimes:
            env = _safe(proc.environ, {})
            cwd = _safe(proc.cwd, "")
            cmd = _safe(proc.cmdline, [])
            seen = set()
            pool = (tree_models(cwd) if cwd else []) + [c for r in _hub_roots(env) for c in self._hub_models(r)]
            for c in pool:
                k = (os.path.normcase(c.path), c.runtime)
                if c.runtime in runtimes and k not in seen:
                    seen.add(k)
                    candidates.append(c)
            texts = {"command line": " ".join(cmd).lower(),
                     "environment": "\n".join(env.values()).lower(),
                     "source": _read_sources(source_files(cmd, cwd))}
        ev = _Evidence(now, runtimes, candidates, texts)
        self._procs[key] = ev
        return ev

    @staticmethod
    def _runtimes(proc) -> tuple[str, ...]:
        maps = _safe(proc.memory_maps, [])
        names = {os.path.basename(m.path).lower() for m in maps}
        return tuple(rt for rt, libs in GPU_LIBS.items() if any(n in names for n in libs))


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - access denied, process gone
        return default


def decide(runtimes, candidates: list[Candidate], texts: dict[str, str], vram: float) -> Estimate | None:
    """The decision tree in the module docstring, on gathered evidence (pure: no I/O)."""
    if not runtimes or not candidates:
        return None
    named = referenced(candidates, texts)
    if named:
        cands = [c for c, _w in named]
        where = dict((c.path, w) for c, w in named)
        chosen = pick(cands, vram)
        best = chosen[0] if chosen else min(cands, key=lambda c: c.size)  # fp32 file run in fp16: bigger than VRAM
        others = tuple(c for c in sorted(cands, key=lambda c: -c.size) if c is not best)  # other named ones
        return Estimate(best.runtime, best, vram, others, "code", where[best.path])
    by_size = [c for c in candidates if c.origin == "cwd" or c.runtime == CT2]
    chosen = pick(by_size, vram)
    if not chosen:
        return None
    best, others = chosen
    return Estimate(best.runtime, best, vram, others, "size")
