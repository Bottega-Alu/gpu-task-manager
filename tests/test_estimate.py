"""Model estimate for runtimes that leave no OS evidence (CTranslate2, PyTorch, ONNX Runtime)."""

import os
from types import SimpleNamespace

import pytest

from gtm_desktop import estimate
from gtm_desktop.estimate import (CT2, ONNX, TORCH, Candidate, Estimator, decide, hub_models, pick,
                                  source_files, tree_models)

GB = 1024 ** 3


SIZES: dict[str, int] = {}


@pytest.fixture(autouse=True)
def fake_sizes(monkeypatch):
    """Model files are empty on disk; their sizes come from SIZES. (NTFS has no implicit sparse files:
    writing multi-GB fixtures would really fill the disk.)"""
    SIZES.clear()
    monkeypatch.setattr(estimate, "_size", lambda path: SIZES.get(os.path.normcase(os.path.abspath(path)), 0))


def _file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    SIZES[os.path.normcase(os.path.abspath(path))] = size


def _repo(root, repo_id, files):
    snap = root / ("models--" + repo_id.replace("/", "--")) / "snapshots" / "rev1"
    for name, size in files.items():
        _file(snap / name, size)
    return snap


def test_hub_formats(tmp_path):
    _repo(tmp_path, "Systran/faster-whisper-large-v3", {"model.bin": 3 * GB, "config.json": 10})
    _repo(tmp_path, "BAAI/bge-reranker-v2-m3", {"model.safetensors": 2 * GB, "config.json": 10,
                                                "pytorch_model.bin": 2 * GB, "onnx/model.onnx": GB // 4,
                                                "onnx/model.onnx_data": 2 * GB})
    _repo(tmp_path, "org/sharded", {"config.json": 10, "model-00001-of-00002.safetensors": GB,
                                    "model-00002-of-00002.safetensors": GB})
    found = {(c.label, c.runtime): c.size for c in hub_models(str(tmp_path))}
    assert found == {
        ("Systran/faster-whisper-large-v3", CT2): 3 * GB,
        ("BAAI/bge-reranker-v2-m3", TORCH): 2 * GB,  # safetensors preferred, the .bin is the same weights
        ("BAAI/bge-reranker-v2-m3/onnx/model.onnx", ONNX): GB // 4 + 2 * GB,  # with external data
        ("org/sharded", TORCH): 2 * GB,
    }


def test_tree_walk_formats_and_skips(tmp_path):
    _file(tmp_path / "models" / "whisper-medium-ct2" / "model.bin", GB)
    _file(tmp_path / "models" / "whisper-medium-ct2" / "config.json", 10)
    _file(tmp_path / "weights" / "detector.onnx", GB // 2)
    _file(tmp_path / "checkpoints" / "unet_final.pth", GB)
    _file(tmp_path / ".venv" / "lib" / "bundled.onnx", GB)
    _file(tmp_path / "venv" / "x.pt", GB)
    got = sorted((c.label, c.runtime) for c in tree_models(str(tmp_path)))
    assert got == [("unet_final.pth", TORCH), ("weights/detector.onnx", ONNX), ("whisper-medium-ct2", CT2)]


def test_source_files_for_script_and_module(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "rerank_server.py").write_text('MODEL = "BAAI/bge-reranker-v2-m3"')
    (tmp_path / "server" / "util.py").write_text("")
    (tmp_path / "settings.json").write_text("{}")
    files = source_files(["python.exe", str(tmp_path / "server" / "rerank_server.py")], str(tmp_path))
    assert {p.split("\\")[-1].split("/")[-1] for p in files} == {"rerank_server.py", "util.py", "settings.json"}
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "app" / "__main__.py").write_text("")
    files = source_files(["pythonw.exe", "-m", "src.app", "--child"], str(tmp_path))
    assert any(f.endswith("__main__.py") for f in files)
    assert source_files(["node.exe", "x.js"], str(tmp_path)) == []


def _c(label, size, runtime=TORCH, origin="hub"):
    return Candidate(label, "/m/" + label, int(size), runtime, origin)


def test_decide_named_in_code_wins():
    cands = [_c("BAAI/bge-reranker-v2-m3", 2.1 * GB), _c("Qwen/Qwen3-TTS-1.7B", 3.5 * GB),
             _c("intfloat/multilingual-e5-large-instruct", 2.2 * GB)]
    texts = {"command line": "", "environment": "", "source": 'model = "baai/bge-reranker-v2-m3"'}
    est = decide((TORCH,), cands, texts, 4.0 * GB)
    assert (est.model.label, est.basis, est.where) == ("BAAI/bge-reranker-v2-m3", "code", "source")
    # named but larger than VRAM (fp32 file loaded in fp16): still the named one
    est = decide((TORCH,), cands, texts, 1.2 * GB)
    assert est.model.label == "BAAI/bge-reranker-v2-m3"


def test_decide_no_size_guess_across_unrelated_hub_models():
    cands = [_c("BAAI/bge-m3", 2.2 * GB), _c("Qwen/Qwen3-TTS-1.7B", 3.5 * GB)]
    assert decide((TORCH,), cands, {"source": "nothing relevant"}, 4.0 * GB) is None


def test_decide_by_size_for_ct2_hub_and_cwd():
    sizes = [_c("Systran/faster-whisper-large-v3", 2.9 * GB, CT2), _c("Systran/faster-whisper-medium", 1.5 * GB, CT2)]
    est = decide((CT2,), sizes, {}, 4.0 * GB)
    assert (est.model.label, est.basis) == ("Systran/faster-whisper-large-v3", "size")
    local = [_c("detector.onnx", 0.5 * GB, ONNX, "cwd"), _c("big.onnx", 6 * GB, ONNX, "cwd")]
    assert decide((ONNX,), local, {}, 1.0 * GB).model.label == "detector.onnx"


def test_pick_largest_that_fits():
    cands = [_c("large", 2.9 * GB), _c("medium", 1.5 * GB), _c("small", GB / 2)]
    assert pick(cands, 4.0 * GB)[0].label == "large"
    assert pick(cands, 2.0 * GB)[0].label == "medium"
    assert pick(cands, 0.1 * GB) is None


def _row(**kw):
    detail = SimpleNamespace(models=[], candidates=[], is_ai=True)
    base = dict(pid=1, host=False, llm=None, detail=detail, gpu=SimpleNamespace(shown_vram=4.0 * GB))
    base.update(kw)
    return SimpleNamespace(**base)


def test_estimator_gates(monkeypatch):
    ev = estimate._Evidence(0.0, (CT2,), [_c("Systran/faster-whisper-large-v3", 2.9 * GB, CT2)], {})
    monkeypatch.setattr(Estimator, "_evidence", lambda self, pid: ev)
    e = Estimator()
    assert e.estimate(_row()).family == "Whisper"
    assert e.estimate(_row(llm=object())) is None  # engine evidence wins
    assert e.estimate(_row(detail=SimpleNamespace(models=["m"], candidates=[], is_ai=True))) is None
    assert e.estimate(_row(detail=SimpleNamespace(models=[], candidates=[], is_ai=False))) is None
    assert e.estimate(_row(host=True)) is None
    assert e.estimate(_row(gpu=SimpleNamespace(shown_vram=None))) is None
    monkeypatch.setattr(Estimator, "_evidence", lambda self, pid: estimate._Evidence(0.0, (), [], {}))
    assert e.estimate(_row()) is None  # no GPU runtime library


def test_estimator_never_raises(monkeypatch):
    def boom(self, pid):
        raise OSError("access denied")
    monkeypatch.setattr(Estimator, "_evidence", boom)
    assert Estimator().estimate(_row()) is None


def test_runtime_needs_gpu_library():
    maps = lambda *names: SimpleNamespace(memory_maps=lambda: [SimpleNamespace(path="C:\\x\\" + n) for n in names])  # noqa: E731
    assert Estimator._runtimes(maps("onnxruntime_providers_shared.dll", "onnxruntime.dll")) == ()  # CPU only
    assert Estimator._runtimes(maps("onnxruntime_providers_cuda.dll", "ctranslate2.dll")) == (CT2, ONNX)
    assert Estimator._runtimes(maps("torch_cuda.dll")) == (TORCH,)


def test_hub_roots_from_process_env(tmp_path):
    (tmp_path / "custom").mkdir()
    (tmp_path / "home" / "hub").mkdir(parents=True)
    roots = estimate._hub_roots({"HF_HUB_CACHE": str(tmp_path / "custom"), "HF_HOME": str(tmp_path / "home"),
                                 "USERPROFILE": str(tmp_path / "nobody")})
    assert roots == [str(tmp_path / "custom"), str(tmp_path / "home" / "hub")]
