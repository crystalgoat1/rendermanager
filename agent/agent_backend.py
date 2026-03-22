import os
import threading
import requests
from typing import Optional


class BackendSession:
    """A persistent session for all agent-to-server communication.

    Thread-safe via thread-local storage: each thread (heartbeat, job loop,
    preview, blend scan, preload) automatically gets its own requests.Session
    with its own TCP connection pool.  This means:
      - No thread can block another (heartbeat is never stuck behind a
        slow preview upload).
      - No shared-state corruption from concurrent access.
      - Each thread still benefits from connection keep-alive / reuse.
    """
    def __init__(self, backend_url: str, agent_token: str):
        self.backend_url = backend_url.rstrip("/")
        self.agent_token = agent_token
        self._local = threading.local()

    def _get_session(self) -> requests.Session:
        """Return a per-thread requests.Session, creating one on first call."""
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "X-Agent-Token": self.agent_token,
                "Accept": "application/json",
            })
            self._local.session = s
        return s

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.backend_url}/{path.lstrip('/')}"
        if "timeout" not in kwargs:
            kwargs["timeout"] = 15
        return self._get_session().request(method, url, **kwargs)

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)


def ping_server(session: BackendSession) -> dict:
    """Safe auth check — calls /auth/whoami."""
    r = session.get("/auth/whoami")
    if r.status_code != 200:
        try:
            j = r.json()
        except Exception:
            j = {"detail": r.text}
        raise RuntimeError(f"Server returned {r.status_code}: {j}")
    return r.json()


def verify_agent_token(backend_url: str, agent_token: str) -> dict:
    """Verify a provisioned agent token against the server (standalone check)."""
    res = requests.get(
        f"{backend_url}/auth/whoami",
        headers={"X-Agent-Token": agent_token},
        timeout=10,
    )
    if res.status_code != 200:
        raise RuntimeError("Unauthorized: agent token is invalid")
    return res.json()


def register_agent(session: BackendSession, agent_name: str) -> str:
    res = session.post("/agents/register", json={"name": agent_name})
    if res.status_code == 401 or res.status_code == 403:
        raise RuntimeError(f"Registration failed: Unauthorized (HTTP {res.status_code})")
    try:
        data = res.json()
    except Exception:
        raise RuntimeError(f"Registration failed: server returned non-JSON (HTTP {res.status_code})")
    if res.status_code != 200:
        raise RuntimeError(f"Registration failed: {data}")
    return data["agent_id"]


class AuthError(RuntimeError):
    """Raised when the server explicitly rejects the agent token (401/403)."""
    pass


def send_heartbeat(session: BackendSession, agent_id: str, boot_id: str, telemetry: Optional[dict] = None) -> dict:
    from agent.brand import AGENT_VERSION
    payload = {"boot_id": boot_id, "agent_version": AGENT_VERSION}
    if telemetry:
        payload["telemetry"] = telemetry

    res = session.post(f"/agents/{agent_id}/heartbeat", json=payload)
    if res.status_code in (401, 403):
        raise AuthError(f"Heartbeat failed: Unauthorized (HTTP {res.status_code})")
    try:
        data = res.json()
    except Exception:
        raise RuntimeError(f"Heartbeat failed: server returned non-JSON (HTTP {res.status_code})")
    if res.status_code != 200:
        raise RuntimeError(f"Heartbeat failed: {data}")
    return data


def get_next_job(session: BackendSession, agent_id: str) -> dict:
    res = session.post(f"/agents/{agent_id}/next-job", timeout=25)
    data = res.json()
    if res.status_code != 200:
        raise RuntimeError(f"Next-job failed: {data}")
    return data


def send_progress(session: BackendSession, job_id: str, agent_id: str, progress: int, message: str = "", current_frame: Optional[int] = None) -> dict:
    payload = {"agent_id": agent_id, "progress": progress, "message": message}
    if current_frame is not None:
        payload["current_frame"] = current_frame
    res = session.post(f"/jobs/{job_id}/progress", json=payload)
    return res.json()


def complete_job(session: BackendSession, job_id: str, agent_id: str, vram_recovery: Optional[dict] = None) -> dict:
    payload: dict = {"agent_id": agent_id}
    if vram_recovery:
        payload["vram_recovery"] = vram_recovery
    res = session.post(f"/jobs/{job_id}/complete", json=payload)
    return res.json()


def fail_job(session: BackendSession, job_id: str, agent_id: str, reason: str) -> dict:
    res = session.post(f"/jobs/{job_id}/fail", json={"agent_id": agent_id, "reason": reason})
    return res.json()


def get_rescan_status(session: BackendSession, agent_id: str) -> dict:
    res = session.get(f"/agents/{agent_id}/rescan-status")
    data = res.json()
    if res.status_code != 200:
        raise RuntimeError(f"Rescan status failed: {data}")
    return data


def publish_blend_files(session: BackendSession, agent_id: str, payload: dict) -> dict:
    res = session.post(f"/agents/{agent_id}/blend-files", json=payload, timeout=45)
    data = res.json()
    if res.status_code != 200:
        raise RuntimeError(f"Publish blend files failed: {data}")
    return data


def get_job_control(session: BackendSession, job_id: str, agent_id: str):
    res = session.get(f"/jobs/{job_id}/control", params={"agent_id": agent_id})
    data = res.json()
    if res.status_code != 200:
        raise RuntimeError(f"Control check failed: {data}")
    return data


def notify_paused(session: BackendSession, job_id: str, agent_id: str):
    res = session.post(f"/jobs/{job_id}/paused", json={"agent_id": agent_id})
    return res.json()


def notify_canceled(session: BackendSession, job_id: str, agent_id: str):
    res = session.post(f"/jobs/{job_id}/canceled", json={"agent_id": agent_id})
    return res.json()


def request_job_pause(session: BackendSession, job_id: str, agent_id: str):
    res = session.post(f"/agents/{agent_id}/jobs/{job_id}/pause")
    return res.json()


def request_job_resume(session: BackendSession, job_id: str, agent_id: str):
    res = session.post(f"/agents/{agent_id}/jobs/{job_id}/resume")
    return res.json()


def request_job_cancel(session: BackendSession, job_id: str, agent_id: str):
    res = session.post(f"/agents/{agent_id}/jobs/{job_id}/cancel")
    return res.json()


def get_preview_tasks(session: BackendSession, agent_id: str):
    """Poll the server for pending preview/compile requests."""
    res = session.get(f"/agents/{agent_id}/preview-tasks")
    if res.status_code != 200:
        return {"tasks": [], "tier": "free"}
    try:
        data = res.json()
    except Exception:
        return {"tasks": [], "tier": "free"}
    return data


def report_available_passes(session: BackendSession, agent_id: str, job_id: str, passes: list):
    """Report discovered render passes for a job."""
    try:
        res = session.post(f"/agents/{agent_id}/jobs/{job_id}/available-passes", json={"passes": passes})
        if res.status_code != 200:
            print(f"[preview] Failed to report passes: {res.text}")
    except Exception as e:
        print(f"[preview] Failed to report passes: {e}")


def report_preview_failure(session: BackendSession, agent_id: str, request_id: str, reason: str = ""):
    """Tell the server that a preview request could not be fulfilled."""
    res = session.post(f"/agents/{agent_id}/preview-fail", json={"request_id": request_id, "reason": reason})
    if res.status_code != 200:
        print(f"[preview] Failed to report preview failure: {res.text}")


def upload_preview_result(session: BackendSession, agent_id: str, request_id: str, file_path: str):
    """Upload a completed preview file (JPEG or MP4) to the server."""
    with open(file_path, "rb") as f:
        ct = "video/mp4" if file_path.endswith(".mp4") else "image/jpeg"
        files = {"file": (os.path.basename(file_path), f, ct)}
        data = {"request_id": request_id}
        res = session.post(f"/agents/{agent_id}/preview-upload", files=files, data=data, timeout=120)
    j = res.json()
    if res.status_code != 200:
        raise RuntimeError(f"Preview upload failed: {j}")
    return j


def preload_preview_pass(
    session: BackendSession, agent_id: str,
    job_id: str, frame: int, pass_name: str, file_path: str,
):
    """Proactively upload a pass JPEG."""
    try:
        with open(file_path, "rb") as f:
            res = session.post(
                f"/agents/{agent_id}/preview-preload",
                files={"file": (os.path.basename(file_path), f, "image/jpeg")},
                data={"job_id": job_id, "frame": str(frame), "pass_name": pass_name},
                timeout=60,
            )
        if res.status_code == 200 or "already_ready" in res.text:
            return True
        print(f"[preview] Preload failed for pass '{pass_name}': {res.text}")
    except Exception as e:
        print(f"[preview] Preload failed for pass '{pass_name}': {e}")
    return False


def upload_latest_preview(
    session: BackendSession, job_id: str, agent_id: str,
    file_path: str, frame: int, pass_name: str = "Combined",
):
    """Upload a JPEG as the job's latest preview (shown on the dashboard card)."""
    try:
        with open(file_path, "rb") as f:
            res = session.post(
                f"/jobs/{job_id}/preview/latest",
                files={"file": (os.path.basename(file_path), f, "image/jpeg")},
                data={"agent_id": agent_id, "frame": str(frame), "pass_name": pass_name},
                timeout=60,
            )
        if res.status_code == 200:
            return True
        # 429 = rate limited, not an error worth logging loudly
        if res.status_code != 429:
            print(f"[preview] Latest preview upload failed: {res.text}")
    except Exception as e:
        print(f"[preview] Latest preview upload failed: {e}")
    return False
