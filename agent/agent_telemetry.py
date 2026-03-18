import os
import time
import threading

try:
    import psutil
except ImportError:
    psutil = None

try:
    import GPUtil
except ImportError:
    GPUtil = None


# Keep a rolling average of CPU utilization to smooth out momentary spikes
_cpu_history = []

# Cache last successful GPU reading so heartbeat never blocks on nvidia-smi
_last_gpu_stats: list = []


def _get_gpus_with_timeout(timeout: float = 3.0) -> list:
    """Query GPUtil.getGPUs() with a hard timeout.

    nvidia-smi can hang for 30+ seconds when the GPU is under heavy render
    load, which would block the heartbeat thread and cause the watchdog to
    mark the agent offline.  If the call doesn't return in time we fall back
    to the last cached result.
    """
    global _last_gpu_stats
    if not GPUtil:
        return []

    result = [None]  # mutable container for thread result

    def _query():
        try:
            result[0] = GPUtil.getGPUs()
        except Exception:
            result[0] = None

    t = threading.Thread(target=_query, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive() or result[0] is None:
        # nvidia-smi hung or errored — return cached stats
        return _last_gpu_stats

    # Build serialisable list and cache it
    gpu_list = []
    for g in result[0]:
        gpu_list.append({
            "id": g.id,
            "name": g.name,
            "load_percent": round(g.load * 100, 1),
            "vram_total_mb": int(g.memoryTotal),
            "vram_used_mb": int(g.memoryUsed),
            "vram_percent": round((g.memoryUsed / max(1, g.memoryTotal)) * 100, 1),
            "temperature_c": int(g.temperature),
        })
    _last_gpu_stats = gpu_list
    return gpu_list


def get_system_telemetry(workspace_root: str) -> dict:
    """Safely collect system telemetry. Fails gracefully if libraries are missing.
    Returns:
        {
            "cpu_percent": float,
            "ram_total_mb": int,
            "ram_used_mb": int,
            "ram_percent": float,
            "disk_total_mb": int,
            "disk_free_mb": int,
            "disk_percent": float,
            "gpus": [
                {
                    "id": int,
                    "name": str,
                    "load_percent": float,
                    "vram_total_mb": int,
                    "vram_used_mb": int,
                    "vram_percent": float,
                    "temperature_c": float
                }
            ]
        }
    """
    stats = {}

    if psutil:
        try:
            # CPU
            # Use interval=None to get instant usage without blocking the heartbeat loop
            cpu = psutil.cpu_percent(interval=None)
            
            # Smooth out CPU jumping around wildly
            global _cpu_history
            _cpu_history.append(cpu)
            if len(_cpu_history) > 5:
                _cpu_history.pop(0)
            avg_cpu = sum(_cpu_history) / len(_cpu_history)
            
            stats["cpu_percent"] = round(avg_cpu, 1)

            # System RAM
            vm = psutil.virtual_memory()
            stats["ram_total_mb"] = int(vm.total / (1024 * 1024))
            stats["ram_used_mb"] = int(vm.used / (1024 * 1024))
            stats["ram_percent"] = round(vm.percent, 1)

            # Main render output Disk Space (with timeout — can block during heavy I/O)
            disk_result = [None]
            def _disk_query():
                try:
                    if workspace_root and os.path.exists(workspace_root):
                        disk_result[0] = psutil.disk_usage(workspace_root)
                    else:
                        disk_result[0] = psutil.disk_usage("/")
                except Exception:
                    pass
            dt = threading.Thread(target=_disk_query, daemon=True)
            dt.start()
            dt.join(timeout=2.0)
            usage = disk_result[0]
            if usage:
                stats["disk_total_mb"] = int(usage.total / (1024 * 1024))
                stats["disk_free_mb"] = int(usage.free / (1024 * 1024))
                stats["disk_percent"] = round(usage.percent, 1)

        except Exception as e:
            print(f"[telemetry] Failed to gather psutil stats: {e}")

    if GPUtil:
        try:
            stats["gpus"] = _get_gpus_with_timeout(timeout=3.0)
        except Exception as e:
            print(f"[telemetry] Failed to gather GPUtil stats: {e}")
            stats["gpus"] = _last_gpu_stats

    return stats
