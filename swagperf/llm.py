"""Local model sessions: the Claude Code and Codex CLIs the user is logged in to.

Both run with the user's own subscription, so nothing here needs an API key.
This module only finds the binaries; the Copilot and the PM agent decide what
to run through them.
"""
import os, shutil

# The ChatGPT desktop app bundles the Codex CLI without putting it on PATH.
CODEX_APP = "/Applications/ChatGPT.app/Contents/Resources/codex"


def _exe(path):
    return path if path and os.path.isfile(path) and os.access(path, os.X_OK) else None


def claude_bin():
    """The `claude` CLI: SWAGPERF_CLAUDE_BIN, else PATH. None if absent."""
    env = os.environ.get("SWAGPERF_CLAUDE_BIN")
    return _exe(env) if env else shutil.which("claude")


def codex_bin():
    """The `codex` CLI: SWAGPERF_CODEX_BIN, else PATH, else the ChatGPT app's copy."""
    env = os.environ.get("SWAGPERF_CODEX_BIN")
    if env:
        return _exe(env)
    return shutil.which("codex") or _exe(CODEX_APP)
