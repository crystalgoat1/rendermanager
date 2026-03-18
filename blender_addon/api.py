# blender_addon/api.py
#
# HTTP client for the Render Manager server.
# Uses only urllib (stdlib) so the addon has zero pip dependencies.

from __future__ import annotations

import json
import urllib.request
import urllib.error


class ApiError(Exception):
    """Raised when a server request fails."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _request(
    method: str,
    url: str,
    *,
    token: str,
    body: dict | None = None,
    timeout: float = 15.0,
) -> dict:
    """Make an HTTP request and return the parsed JSON response."""
    headers = {"X-Agent-Token": token}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = f"HTTP {e.code}"
        try:
            body_bytes = e.read()
            body_json = json.loads(body_bytes)
            if "detail" in body_json:
                detail = str(body_json["detail"])
        except Exception:
            pass
        raise ApiError(detail, status=e.code) from e
    except urllib.error.URLError as e:
        raise ApiError(f"Server unreachable: {e.reason}") from e
    except Exception as e:
        raise ApiError(str(e)) from e


def get_active_jobs(
    backend_url: str,
    agent_id: str,
    token: str,
) -> dict:
    """Check if the user has any queued or in_progress jobs. Returns ``{"has_active": bool}``."""
    url = f"{backend_url}/agents/{agent_id}/jobs/active-check"
    return _request("GET", url, token=token)


# ── Public API ────────────────────────────────────────────────────────────


def submit_job(
    backend_url: str,
    agent_id: str,
    token: str,
    *,
    blend_relpath: str,
    frame_start: int,
    frame_end: int,
) -> dict:
    """Create a render job via the agent-token endpoint. Returns ``{"job": {...}}``."""
    url = f"{backend_url}/agents/{agent_id}/submit-job"
    return _request(
        "POST",
        url,
        token=token,
        body={
            "blend_relpath": blend_relpath,
            "frame_start": frame_start,
            "frame_end": frame_end,
        },
    )


def get_job_status(
    backend_url: str,
    agent_id: str,
    token: str,
    job_id: str,
) -> dict:
    """Poll job status. Returns ``{"job": {...}}``."""
    url = f"{backend_url}/agents/{agent_id}/jobs/{job_id}/status"
    return _request("GET", url, token=token)


def trigger_rescan(backend_url: str, agent_id: str, token: str) -> None:
    """Fire-and-forget: ask the agent to rescan blend files."""
    url = f"{backend_url}/agents/{agent_id}/request-rescan"
    try:
        _request("POST", url, token=token, body={})
    except Exception:
        pass  # best-effort


def pause_job(
    backend_url: str, agent_id: str, token: str, job_id: str
) -> dict:
    """Request to pause a running job."""
    url = f"{backend_url}/agents/{agent_id}/jobs/{job_id}/pause"
    return _request("POST", url, token=token, body={})


def resume_job(
    backend_url: str, agent_id: str, token: str, job_id: str
) -> dict:
    """Resume a paused job."""
    url = f"{backend_url}/agents/{agent_id}/jobs/{job_id}/resume"
    return _request("POST", url, token=token, body={})


def cancel_job(
    backend_url: str, agent_id: str, token: str, job_id: str
) -> dict:
    """Cancel a queued or running job."""
    url = f"{backend_url}/agents/{agent_id}/jobs/{job_id}/cancel"
    return _request("POST", url, token=token, body={})
