"""What a training run ran on, and how fast: recorded with every training_run block.

The ledger records compute; it doesn't provide it. Training runs on this PC's CPU, a CUDA GPU when
PyTorch sees one, or any other machine that runs the same command (a cloud GPU or Colab) with the
exported dataset.
"""
from __future__ import annotations

import os
import platform
import time
from contextlib import contextmanager


def resolve_device(requested: str = "auto") -> str:
    """'auto' picks CUDA when PyTorch can use a GPU, else CPU. 'cuda' without a GPU is an error."""
    try:
        import torch
        cuda = torch.cuda.is_available()
    except ImportError:
        cuda = False
    if requested == "auto":
        return "cuda" if cuda else "cpu"
    if requested == "cuda" and not cuda:
        raise RuntimeError("no CUDA GPU is available to PyTorch on this machine (use --device cpu, or run the "
                           "training on a GPU machine with the exported dataset)")
    if requested not in ("cpu", "cuda"):
        raise ValueError(f"device is auto, cpu or cuda, not {requested!r}")
    return requested


def compute_info(device: str) -> dict:
    info = {"device": device, "host_os": f"{platform.system()} {platform.release()}", "cpu": platform.processor() or platform.machine(),
            "cpu_cores": os.cpu_count()}
    try:
        import torch
        info["torch"] = torch.__version__
        if device == "cuda":
            props = torch.cuda.get_device_properties(0)
            info.update(gpu=props.name, gpu_memory_gb=round(props.total_memory / 1e9, 1), cuda=torch.version.cuda)
    except ImportError:
        pass
    return info


@contextmanager
def measure(device: str, samples: int):
    """Times a block; the yielded dict gets seconds, samples_per_second and, on CUDA, peak GPU memory."""
    result: dict = {}
    torch = None
    if device == "cuda":
        import torch
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
    started = time.perf_counter()
    yield result
    if torch is not None:
        torch.cuda.synchronize()
        result["peak_gpu_memory_mb"] = round(torch.cuda.max_memory_allocated() / 1e6, 1)
    seconds = time.perf_counter() - started
    result.update(seconds=round(seconds, 4), samples_per_second=round(samples / seconds, 1) if seconds > 0 else None)
