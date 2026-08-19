"""Chat through the GitHub Copilot CLI.

HiveFrame does not implement an assistant. It shells out to `copilot`, which
already has tool access, an authenticated session, and a permission model. That
is the whole design: a chat box with no tool access is a worse version of the
terminal, and rebuilding tool access is weeks of work to duplicate something
already installed.

Posture. The CLI can edit files and run shell commands, so this module is the
one place in HiveFrame that reaches outside a store. Four controls bound it, and
one of them is weaker than it looks:

  1. Writes are allowed. Publishing and remote history rewriting are not:
     `git push`, `git reset` and every network verb are denied by name.
  2. `shell(rm)` is denied, but that is not a deletion guarantee. Tested: asked
     to delete a file, the CLI was refused `rm` and then deleted it through the
     allowed edit tool instead. Granting write grants delete. The denial removes
     the blunt instrument and the accidental `rm -rf`, not the capability.
     Recovery is git, not the allowlist, which is why the repo commits after
     every change.
  3. --add-dir names writable directories explicitly rather than
     --allow-all-paths. The protected shared libraries are never included.
  4. Every turn is logged to chat.jsonl with its prompt, model, session id,
     duration and cost. An assistant that acts without a record is the thing
     this whole tool exists to argue against.

Sessions. The CLI owns continuity. It returns a session id on first turn and
resumes with --resume, so HiveFrame stores the id and nothing else. Conversation
history is not duplicated here, because two copies of a transcript disagree.

Sessions are per project, not per store. Cost grows with conversation length
because resume re-sends the history, and a question about one project rarely
needs another project's thread. Switching projects therefore switches threads,
which is both cheaper and the same separation the rest of the tool enforces.

Cost. Measured on an identical one-word prompt, the cheapest model costs 1.5
credits and the heaviest 20.8. The default is the light one and the heavy one is
picked deliberately per turn, because a heavy model left as a default is a bill
nobody decided to run up.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

CHAT_LOG = "chat.jsonl"
SESSION_FILE = ".chat_session"
TRANSCRIPT_FILE = "transcript"

# The CLI marks a tool invocation with a glyph and indents its detail beneath.
# Splitting those out of the prose is what turns a wall of text into the step
# list VS Code shows: you can see it read a file before you read its conclusion.
# There is more than one glyph: a bullet for a completed step, a cross for a
# refused one, and a rotating spinner character for one still running. Matching
# only the bullet leaves the refusals in the prose, which reads as though the
# assistant said them.
_STEP_RE = re.compile(r"^\s*([●✓✗⚠◆•])\s*(.+?)\s*$")
_SPINNER_RE = re.compile(r"^\s*([/\\|_-])\s+(\S.*?)\s*$")
_STEP_DETAIL_RE = re.compile(r"^\s*[│└├]\s?(.*)$")

# Read verbs, always allowed without prompting.
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
    "write",
)

# Denied by name rather than left to the allowlist, because a tool added
# upstream arrives enabled otherwise. These are the verbs that destroy, move,
# or reach the network. Editing is allowed; deleting and publishing are not.
DENY_TOOLS = (
    "shell(rm)",
    "shell(mv)",
    "shell(chmod)",
    "shell(chown)",
    "shell(dd)",
    "shell(curl)",
    "shell(ssh)",
    "shell(scp)",
    "shell(rsync)",
    "shell(git push)",
    "shell(git reset)",
)

# Cost varies about fourteen-fold across these, measured on an identical
# one-word prompt. The default is the cheapest capable option, and the heavy
# ones are a deliberate choice rather than a setting nobody revisits.
MODELS = (
    ("gpt-5.4-mini", "light", 1.5),
    ("claude-sonnet-4.5", "standard", 2.8),
    ("gpt-5.4", "standard", 5.0),
    ("claude-opus-5", "heavy", 20.8),
)

DEFAULT_MODEL = os.environ.get("HIVEFRAME_CHAT_MODEL", "gpt-5.4-mini")
TIMEOUT_S = int(os.environ.get("HIVEFRAME_CHAT_TIMEOUT", "300"))

# The persona lives in one place and is composed there, so this points at it
# rather than restating it. AGENTS.md in the store root carries the compact
# brief; this directory is granted read access so a question that turns on
# posture, paths or capabilities can be answered from the source instead of
# from a summary of it.
BRAIN_DIR = Path(os.environ.get(
    "HIVEFRAME_BRAIN",
    "/Users/D112236/Library/CloudStorage/OneDrive-KaiserPermanente/KaiserKM",
))

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


def _session_path(root: Path, project: str = "") -> Path:
    """One thread per project.

    Resume re-sends the whole conversation, so cost grows with history. Keeping
    a separate thread per project means switching subject also drops the history
    that no longer applies, which is cheaper and matches the separation the rest
    of the tool enforces.
    """
    safe = re.sub(r"[^a-z0-9_-]", "", (project or "board").lower())[:60] or "board"
    return root / f"{SESSION_FILE}.{safe}"


def read_session(root: Path, project: str = "") -> str:
    p = _session_path(root, project)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _transcript_path(root: Path, project: str = "") -> Path:
    safe = re.sub(r"[^a-z0-9_-]", "", (project or "board").lower())[:60] or "board"
    return root / f"{TRANSCRIPT_FILE}.{safe}.jsonl"


def read_transcript(root: Path, project: str = "", limit: int = 60) -> list[dict]:
    """The conversation itself, so closing the tab does not lose it.

    chat.jsonl is an audit log: what was asked, what it cost, how long it took.
    It deliberately does not carry answers, because a cost log padded with prose
    stops being readable. This is the other half, kept per project alongside the
    session id, so reopening HiveFrame shows the thread the CLI is about to
    resume rather than an empty box above a live conversation.
    """
    p = _transcript_path(root, project)
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


def clear_session(root: Path, project: str = "") -> None:
    """Start a fresh conversation. The old CLI session is not deleted, only
    forgotten here, so it stays resumable from the terminal. The transcript is
    archived rather than removed, for the same reason: a decision trail that a
    button can erase is not a trail."""
    p = _session_path(root, project)
    if p.exists():
        p.unlink()
    t = _transcript_path(root, project)
    if t.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        t.rename(t.with_suffix(f".{stamp}.jsonl"))


def _split_steps(text: str) -> tuple[str, list[dict]]:
    """Separate tool activity from the answer.

    The CLI interleaves what it did with what it concluded. Read as one blob
    that is noise; read as a step list above the answer it is provenance, which
    is the whole argument for using an assistant on portfolio data at all. You
    can see which file the number came from.
    """
    steps: list[dict] = []
    prose: list[str] = []
    cur: dict | None = None
    lines = text.splitlines()
    for n, line in enumerate(lines):
        m = _STEP_RE.match(line)
        if m:
            cur = {"glyph": m.group(1), "title": m.group(2), "detail": []}
            steps.append(cur)
            continue
        # A spinner glyph is a single character that also appears in ordinary
        # prose, so it only counts as a step when the line beneath it is an
        # indented detail line. That structure is what makes it unambiguous.
        s = _SPINNER_RE.match(line)
        if s and n + 1 < len(lines) and _STEP_DETAIL_RE.match(lines[n + 1]):
            cur = {"glyph": "·", "title": s.group(2), "detail": []}
            steps.append(cur)
            continue
        d = _STEP_DETAIL_RE.match(line)
        if d and cur is not None:
            cur["detail"].append(d.group(1))
            continue
        if line.strip() and cur is not None:
            cur = None
        prose.append(line)
    for s in steps:
        s["detail"] = "\n".join(s["detail"]).strip()
    # Collapsing the blank runs the stripped steps leave behind, so the answer
    # does not open with a screenful of nothing.
    prose_text = re.sub(r"\n{3,}", "\n\n", "\n".join(prose)).strip()
    return prose_text, steps


def _strip_footer(text: str) -> str:
    """Remove the CLI's own summary block, which is UI, not answer."""
    for marker in ("\nChanges ", "\nAI Credits ", "\nResume  "):
        i = text.find(marker)
        if i > 0:
            text = text[:i]
    return text.strip()


def ask(prompt: str, root: Path, dirs: tuple[Path, ...] = (),
        model: str = "", resume: bool = True, context: str = "",
        project: str = "") -> dict:
    """Run one turn and return the answer with its cost and provenance.

    root is the store directory: the session id and the turn log live there, so
    a work conversation and a personal one never share history. project splits
    that further, one thread per project.

    context is what the UI says is on screen. It is prepended rather than
    merged into the prompt, and labelled, so the assistant can tell the
    difference between what Andy asked and what the tool volunteered. The turn
    log records the question alone, because a log of prompts padded with state
    is unreadable a week later.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ChatError("a prompt is required")

    state = available()
    if not state["ok"]:
        raise ChatError(state["reason"])

    sent = prompt
    if context.strip():
        sent = (
            "Context from the HiveFrame UI, which the user did not type:\n"
            f"{context.strip()}\n\n"
            "Answer this, using that context only where it is relevant:\n"
            f"{prompt}"
        )

    argv = [state["path"], "-p", sent, "--no-color", "--log-level", "none"]
    argv += ["--model", model or DEFAULT_MODEL]

    for t in ALLOW_TOOLS:
        argv += ["--allow-tool", t]
    for t in DENY_TOOLS:
        argv += ["--deny-tool", t]

    for d in dirs:
        argv += ["--add-dir", str(d)]
    if BRAIN_DIR.exists():
        argv += ["--add-dir", str(BRAIN_DIR)]

    session = read_session(root, project) if resume else ""
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
        _session_path(root, project).write_text(m.group(1), encoding="utf-8")
        session = m.group(1)

    credits = None
    c = _CREDITS_RE.search(raw)
    if c:
        try:
            credits = float(c.group(1))
        except ValueError:
            credits = None

    answer = _strip_footer(out.stdout or "")
    answer, steps = _split_steps(answer)

    rec = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt": prompt,
        "project": project or "",
        "context_chars": len(context or ""),
        "answer_chars": len(answer),
        "session": session,
        "model": model or DEFAULT_MODEL,
        "seconds": elapsed,
        "credits": credits,
        "exit": out.returncode,
    }
    with (root / CHAT_LOG).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")

    # The audit log above answers "what did this cost". The transcript answers
    # "what did we decide", which is the one a portfolio conversation is for.
    with _transcript_path(root, project).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"role": "user", "at": rec["at"], "text": prompt}) + "\n")
        fh.write(json.dumps({
            "role": "assistant", "at": rec["at"], "text": answer, "steps": steps,
            "model": rec["model"], "credits": credits, "seconds": elapsed,
        }) + "\n")

    return {"answer": answer, "steps": steps, **rec}


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


# ---- streaming -----------------------------------------------------------
#
# ask() waits for the whole answer and returns it. That is correct for a script
# and wrong for a person: a research turn takes thirty seconds, and thirty
# seconds of a motionless box is indistinguishable from a hang. Streaming is not
# a cosmetic upgrade here, it is what makes the wait legible, and it is what
# makes stopping possible at all. You cannot cancel a turn you cannot see.

_RUNNING: dict[str, subprocess.Popen] = {}
_RUNNING_LOCK = threading.Lock()


def stop(turn_id: str) -> bool:
    """Kill a running turn. Returns whether there was one to kill.

    The whole process group, not just the CLI. Measured the difference: killing
    only the parent left the turn running for another 36 seconds, because the
    CLI spawns shells and language servers that inherit the stdout pipe and hold
    it open after their parent is gone. A stop button that takes half a minute
    is not a stop button. This is why the process is started in its own session.

    Terminate first, kill only if it ignores that, because the CLI writes its
    session id on the way out and a session id that was never written is a
    conversation that silently forks on the next turn.
    """
    with _RUNNING_LOCK:
        proc = _RUNNING.get(turn_id)
    if proc is None or proc.poll() is not None:
        return False

    def signal_group(sig) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            # Already gone, or not ours to signal. Fall back to the one
            # handle we definitely own.
            try:
                proc.send_signal(sig)
            except (ProcessLookupError, OSError):
                pass

    signal_group(signal.SIGTERM)
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        signal_group(signal.SIGKILL)
    return True


def _build_argv(state: dict, sent: str, dirs, model: str) -> list[str]:
    argv = [state["path"], "-p", sent, "--no-color", "--log-level", "none"]
    argv += ["--model", model or DEFAULT_MODEL]
    for t in ALLOW_TOOLS:
        argv += ["--allow-tool", t]
    for t in DENY_TOOLS:
        argv += ["--deny-tool", t]
    for d in dirs:
        argv += ["--add-dir", str(d)]
    if BRAIN_DIR.exists():
        argv += ["--add-dir", str(BRAIN_DIR)]
    return argv


def ask_stream(prompt: str, root: Path, dirs: tuple[Path, ...] = (),
               model: str = "", resume: bool = True, context: str = "",
               project: str = "", turn_id: str = ""):
    """Run one turn, yielding events as they arrive.

    Same contract as ask(): same permissions, same per-project session, same two
    logs written at the end. The difference is only in delivery. Events are
    dicts with a "type": turn, step, detail, text, done, error.

    Steps are emitted the moment their title line appears rather than when they
    complete, so a slow tool call shows as activity instead of silence. Detail
    lines follow and attach to the step already on screen.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        yield {"type": "error", "error": "a prompt is required"}
        return

    state = available()
    if not state["ok"]:
        yield {"type": "error", "error": state["reason"]}
        return

    turn_id = turn_id or uuid.uuid4().hex[:12]

    sent = prompt
    if context.strip():
        sent = (
            "Context from the HiveFrame UI, which the user did not type:\n"
            f"{context.strip()}\n\n"
            "Answer this, using that context only where it is relevant:\n"
            f"{prompt}"
        )

    argv = _build_argv(state, sent, dirs, model)
    session = read_session(root, project) if resume else ""
    if session:
        argv.append(f"--resume={session}")

    yield {"type": "turn", "id": turn_id, "model": model or DEFAULT_MODEL}

    # stderr carries the session id and cost and is drained to a temp file
    # rather than a pipe. Two pipes read from one thread deadlock the moment
    # either buffer fills, and this one fills on any turn that does real work.
    started = time.time()
    err = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=err,
                                text=True, bufsize=1, cwd=str(root),
                                start_new_session=True)
    except OSError as e:
        err.close()
        yield {"type": "error", "error": f"could not run copilot: {e}"}
        return

    with _RUNNING_LOCK:
        _RUNNING[turn_id] = proc

    steps: list[dict] = []
    prose: list[str] = []
    cur: dict | None = None
    stopped = False
    pending: str | None = None   # a spinner line is only a step if a detail follows

    def classify(line: str):
        """Emit for one line. Mirrors _split_steps, one line at a time."""
        nonlocal cur, pending
        m = _STEP_RE.match(line)
        if m:
            cur = {"glyph": m.group(1), "title": m.group(2), "detail": []}
            steps.append(cur)
            return {"type": "step", "glyph": cur["glyph"], "title": cur["title"]}
        d = _STEP_DETAIL_RE.match(line)
        if d:
            if pending is not None:
                cur = {"glyph": "·", "title": pending, "detail": []}
                steps.append(cur)
                pending = None
                out = {"type": "step", "glyph": "·", "title": cur["title"]}
                cur["detail"].append(d.group(1))
                return out
            if cur is not None:
                cur["detail"].append(d.group(1))
                return {"type": "detail", "text": d.group(1)}
        if pending is not None:
            prose.append(pending)
            pending = None
        s = _SPINNER_RE.match(line)
        if s:
            pending = s.group(2)
            return None
        if line.strip() and cur is not None:
            cur = None
        prose.append(line)
        return {"type": "text", "text": line} if line.strip() else None

    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            ev = classify(line)
            if ev:
                yield ev
        proc.wait(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        yield {"type": "error", "error": f"copilot did not answer within {TIMEOUT_S}s"}
    finally:
        with _RUNNING_LOCK:
            _RUNNING.pop(turn_id, None)
        stopped = proc.returncode is not None and proc.returncode < 0

    if pending is not None:
        prose.append(pending)

    elapsed = round(time.time() - started, 1)
    err.seek(0)
    tail = err.read()
    err.close()

    m = _SESSION_RE.search(tail)
    if m:
        _session_path(root, project).write_text(m.group(1), encoding="utf-8")
        session = m.group(1)

    credits = None
    c = _CREDITS_RE.search(tail)
    if c:
        try:
            credits = float(c.group(1))
        except ValueError:
            credits = None

    for s in steps:
        s["detail"] = "\n".join(s["detail"]).strip()
    answer = re.sub(r"\n{3,}", "\n\n", "\n".join(prose)).strip()
    answer = _strip_footer(answer)

    rec = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt": prompt,
        "project": project or "",
        "context_chars": len(context or ""),
        "answer_chars": len(answer),
        "session": session,
        "model": model or DEFAULT_MODEL,
        "seconds": elapsed,
        "credits": credits,
        "exit": proc.returncode,
        "stopped": stopped,
    }
    with (root / CHAT_LOG).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")

    # A stopped turn is still written. It was still asked, it still cost
    # something, and a transcript that quietly omits the turns you abandoned is
    # a flattering record rather than a true one.
    with _transcript_path(root, project).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"role": "user", "at": rec["at"], "text": prompt}) + "\n")
        fh.write(json.dumps({
            "role": "assistant", "at": rec["at"], "text": answer, "steps": steps,
            "model": rec["model"], "credits": credits, "seconds": elapsed,
            "stopped": stopped,
        }) + "\n")

    yield {"type": "done", "answer": answer, "steps": steps, **rec}
