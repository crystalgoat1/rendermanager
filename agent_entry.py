import subprocess
import sys

if sys.platform == "win32":
    _original_popen = subprocess.Popen
    def _patched_popen(*args, **kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return _original_popen(*args, **kwargs)
    subprocess.Popen = _patched_popen

from agent.agent_main import main

if __name__ == "__main__":
    main()
