"""Hardware and environment capture for eval runs: GPU memory sampling, Ollama state, host RAM.

Everything here shells out to tools that exist on the measurement machine (nvidia-smi, git,
PowerShell or /proc). Missing tools are recorded as null rather than guessed.
"""

import json
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def gpu_info() -> dict[str, Any] | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out:
        return None
    name, driver, total, used = (x.strip() for x in out.splitlines()[0].split(","))
    return {
        "name": name,
        "driver": driver,
        "memory_total_mib": int(total),
        "memory_used_mib": int(used),
    }


def host_memory() -> dict[str, float] | None:
    """Total and free physical memory in GiB."""
    if platform.system() == "Windows":
        out = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_OperatingSystem | "
                "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json",
            ]
        )
        if not out:
            return None
        data = json.loads(out)
        return {
            "total_gib": round(data["TotalVisibleMemorySize"] / 1024**2, 2),
            "free_gib": round(data["FreePhysicalMemory"] / 1024**2, 2),
        }
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {
            line.split(":")[0]: int(line.split()[1]) for line in meminfo.read_text().splitlines()
        }
        return {
            "total_gib": round(values["MemTotal"] / 1024**2, 2),
            "free_gib": round(values["MemAvailable"] / 1024**2, 2),
        }
    return None


class GpuSampler:
    """Samples GPU memory used every interval seconds in a background thread."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "GpuSampler":
        if shutil.which("nvidia-smi"):
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        # One long-lived nvidia-smi process with -lms is cheaper than spawning one per sample.
        proc = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
                f"-lms={int(self.interval * 1000)}",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert proc.stdout is not None
            while not self._stop.is_set():
                line = proc.stdout.readline()
                if not line:
                    break
                if line.strip().isdigit():
                    self.samples.append(int(line.strip()))
        finally:
            proc.terminate()

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def summary(self) -> dict[str, int] | None:
        if not self.samples:
            return None
        ordered = sorted(self.samples)
        return {
            "samples": len(ordered),
            "min_mib": ordered[0],
            "p50_mib": ordered[len(ordered) // 2],
            "peak_mib": ordered[-1],
        }


def ollama_state(base_url: str) -> dict[str, Any]:
    state: dict[str, Any] = {"base_url": base_url}
    try:
        with httpx.Client(base_url=base_url, timeout=10) as client:
            state["version"] = client.get("/api/version").json().get("version")
            state["models"] = {
                m["name"]: {
                    "digest": m.get("digest"),
                    "size": m.get("size"),
                    "quantization": m.get("details", {}).get("quantization_level"),
                    "parameter_size": m.get("details", {}).get("parameter_size"),
                }
                for m in client.get("/api/tags").json().get("models", [])
            }
            state["loaded"] = [
                {
                    "name": m["name"],
                    "size": m.get("size"),
                    "size_vram": m.get("size_vram"),
                    "context_length": m.get("context_length"),
                }
                for m in client.get("/api/ps").json().get("models", [])
            ]
    except (httpx.HTTPError, ValueError) as exc:
        state["error"] = str(exc)
    return state


def unload_models(base_url: str, names: list[str]) -> None:
    """Ask Ollama to unload models so the next call is a measured cold start."""
    with httpx.Client(base_url=base_url, timeout=60) as client:
        for name in names:
            endpoint = "/api/embed" if "embed" in name else "/api/generate"
            body: dict[str, Any] = {"model": name, "keep_alive": 0}
            if endpoint == "/api/embed":
                body["input"] = []
            try:
                client.post(endpoint, json=body)
            except httpx.HTTPError:
                pass
    time.sleep(2)


def git_state(root: Path) -> dict[str, Any]:
    sha = _run(["git", "-C", str(root), "rev-parse", "HEAD"])
    dirty = _run(["git", "-C", str(root), "status", "--porcelain", "--", "apps/api", "evals"])
    return {"sha": sha, "dirty_paths": dirty.splitlines() if dirty else []}
