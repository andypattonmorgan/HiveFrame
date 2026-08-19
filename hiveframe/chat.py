"""Chat through the GitHub Copilot CLI.

HiveFrame does not implement an assistant. It shells out to `copilot`, which
already has tool access, an authenticated session, and a permission model. That
is the whole design: a chat box with no tool access is a worse version of the
terminal, and rebuilding tool access is weeks of work to duplicate something
already installed.

Posture. The CLI can edit files and run shell commands, so this module is the
one place in HiveFrame that can reach outside a store. Three controls keep that
honest:

  1. --deny-tool on every write verb by default. Read verbs are allowlisted.
     --allow-all-tools is never passed; the CLI is invoked with an explicit
     allowlist so a prompt cannot talk it into a write it was not granted.
  2. --add-dir names the working directories explicitly rather than
     --allow-all-paths, so file access is bounded to the stores and the repo.
  3. Every turn is logged to chat.jsonl in the store with its prompt, session
     id, duration and exit code. An assistant that acts without a record is
     the thing this whole tool exists to argue against.

Sessions. The CLI owns continuity. It returns a session id on first turn and
resumes with --resume, so HiveFrame stores the id and nothing else. Conversation
history is not duplicated here, because two copies of a transcript disagree.

Cost. Every turn spends AI credits against the operator's allowance. The model
is pinned rather than left on auto, and turns are logged with their duration so
the spend is visible instead of inferred.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

CHAT_LOG = "chat.jsonl"
SESSION_FILE = ".chat_session"

# Read verbs only. The CLI prompts for anything not named here, and a prompt
# nobody is present to answer is a refusal, which is the safe failure.
ALLOW_TOOLS = (
    "shell(cat)",
    "shell(ls)",
    "shell(head)",
    "shell(tail)",
    "shell(wc)",
    "shell(grep)",
    "shell(find)",
    "shell(git status)",
    "shell(git log)",
    "shell(git diff)",
)

# Named explicitly. Relying on the allowlist alone means a tool added upstream
# arrives enabled; denying the write verbs means it arrives blocked.
DENY_TOOLS = (
    "shell(rm)",
    "shell(mv)",
    "shell(cp)",
    "shell(chmod)",
    "shell(chown)",
    "shell(dd)",
    "shell(curl)",
    "shell(ssh)",
    "shell(scp)",
    "shell(rsync)",
    "shell(git push)",
    "shell(git commit)",
    "shell(git reset)",
    "write",
)

DEFAULT_MODEL = os.environ.get("HIVEFRAME_CHAT_MODEL", "claude-sonnet-4.5")
TIMEOUT_S = int(os.environ.get("HIVEFRAME_CHAT_TIMEOUT", "180"))

_SESSION_RE = re.compile(r"--resume=([0-9a-fA-F-]{8,})")
_CREDITS_RE = re.compile(r"AI Credits\s+([0-9.]+)")


class ChatError(RuntimeError):
    """Raised when the CLI is missing, times out, or refuses."""


def available() -> dict:
    """Whether the CLI is installed and what version, without spending credits."""
    exe = shutil.which("copilot")
    if not exe:
        return {"ok": False, "reason": "copilot CLI not found on PATH"}
    try:
        out = subprocess.run([exe, "--version"], capture_output=True,
                             text=True, timeout=15)
    except (subprocess.SubprocessError, OSError) as e:
        return {"ok": False, "reason": f"copilot --version failed: {e}"}
    return {"ok": True, "path": exe, "version": (out.stdout or "").strip().split("\n")[0]}


def _session_path(root: Path) -> Path:
    return root / SESSION_FILE


def read_session(root: Path) -> str:
    p = _session_path(root)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def clear_session(root: Path) -> None:
    """Start a fresh conversation. The old CLI session is not deleted, only
    forgotten here, so it stays resumable from the terminal."""
    p = _session_path(root)
    if p.exists():
        p.unlink()


def _strip_footer(text: str) -> str:
    """Remove the CLI's own summary block, which is UI, not answer."""
    for marker in ("\nChanges ", "\nAI Credits ", "\nResume  "):
        i = text.find(marker)
        if i > 0:
            text = text[:i]
    return text.strip()


def ask(prompt: str, root: Path, dirs: tuple[Path, ...] = (),
        model: str = "", resume: bool = True) -> dict:
    """Run one turn and return the answer with its cost and provenance.

    root is the store directory: the session id and the turn log live there, so
    a work conversation and a personal one never share history.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ChatError("a prompt is required")

    state = available()
    if not state["ok"]:
        raise ChatError(state["reason"])

    argv = [state["path"], "-p", prompt, "--no-color", "--log-level", "none"]
    argv += ["--model", model or DEFAULT_MODEL]

    for t in ALLOW_TOOLS:
        argv += ["--allow-tool", t]
    for t in DENY_TOOLS:
        argv += ["--deny-tool", t]

    for d in dirs:
        argv += ["--add-dir", str(d)]

    session = read_session(root) if resume else ""
    if session:
        argv.append(f"--resume={session}")

    started = time.time()
    try:
        out = subprocess.run(argv, capture_output=True, text=True,
                             timeout=TIMEOUT_S, cwd=str(root))
    except subprocess.TimeoutExpired:
        raise ChatError(f"copilot did not answer within {TIMEOUT_S}s")
    except OSError as e:
        raise ChatError(f"could not run copilot: {e}")

    elapsed = round(time.time() - started, 1)

    # The CLI writes its answer to stdout and its summary block (session id,
    # credits, token counts) to stderr. Both are needed: the answer for the
    # reader, the summary for continuity and cost. Parsing only stdout loses
    # the session, which silently turns every turn into a new conversation.
    raw = (out.stdout or "") + "\n" + (out.stderr or "")

    if out.returncode != 0 and not (out.stdout or "").strip():
        raise ChatError(f"copilot exited {out.returncode}: {(out.stderr or '').strip()[:400]}")

    m = _SESSION_RE.search(raw)
    if m:
        _session_path(root).write_text(m.group(1), encoding="utf-8")
        session = m.group(1)

    credits = None
    c = _CREDITS_RE.search(raw)
    if c:
        try:
            credits = float(c.group(1))
        except ValueError:
            credits = None

    answer = _strip_footer(out.stdout or "")

    rec = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt": prompt,
        "answer_chars": len(answer),
        "session": session,
        "model": model or DEFAULT_MODEL,
        "seconds": elapsed,
        "credits": credits,
        "exit": out.returncode,
    }
    with (root / CHAT_LOG).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")

    return {"answer": answer, **rec}


def history(root: Path, limit: int = 40) -> list[dict]:
    """Turn log for this store. Prompts and cost, not full transcripts."""
    p = root / CHAT_LOG
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]
