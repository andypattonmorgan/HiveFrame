"""Measure what the context trim actually saved.

Both versions are reconstructed here from the same live board, so the
comparison is one board's real numbers rather than a guess. Characters are
counted exactly; tokens are the usual four-characters-per-token approximation
and are labelled as such, because no tokeniser is installed and a precise
looking number from a rule of thumb is worse than an honest estimate.
"""
import json
import urllib.request

BOARD = json.load(urllib.request.urlopen("http://127.0.0.1:8787/api/board"))
PID = "hiveframe"

p = next(x for x in BOARD["projects"] if x["id"] == PID)
open_tasks = [t for t in p["tasks"] if t["status"] in ("open", "doing")]
num = {t["id"]: i + 1 for i, t in enumerate(open_tasks)}


def live_blockers(t):
    ids = {x["id"] for x in open_tasks}
    return [b for b in (t.get("blocked_by") or []) if b in ids]


def before():
    b = []
    names = {"project": "the Project view"}
    b.append(f"Andy is looking at {names['project']} in HiveFrame.")
    b.append(f"Selected project: {p['name']} (id {p['id']}), {p['kind']}, "
             f"horizon {p['horizon'] or 'none'}, status {p['status']}, score {p['score']}.")
    b.append(f"This project is stored in {p['source_file']}. You can read and edit "
             "that file directly. Do not guess a path; use that one.")
    if p.get("folders"):
        b.append("Its content folders: " + "; ".join(f["path"] for f in p["folders"]) + ".")
    c = p.get("charter") or {}
    if c.get("problem"):
        b.append(f"Its problem: {c['problem']}")
    if c.get("kill_when"):
        b.append(f"It dies when: {c['kill_when']}")
    if p.get("next_move"):
        b.append(f"Next move: {p['next_move']['title']}.")
    b.append(f"Open tasks: {p['open_tasks']}. Why it ranks: {'; '.join(p.get('why') or [])}.")
    if open_tasks:
        b.append("Open moves, numbered as they appear on screen. "
                 "When Andy refers to a number, it means this task:")
        for t in open_tasks:
            parts = [t["title"]]
            if t.get("due"):
                parts.append("due " + t["due"])
            if t.get("effort_h"):
                parts.append(f"{t['effort_h']}h")
            if t.get("urgent"):
                parts.append("urgent")
            if live_blockers(t):
                parts.append("waiting on " + ", ".join("#" + str(num[x]) for x in live_blockers(t)))
            b.append(f"  {num[t['id']]}. {', '.join(parts)} [id {t['id']}]")
    b.append("You have file tools here. You can read and edit the project TOML files "
             "in the store and the files in the folders named above. Nothing outside "
             "those is reachable. If a change is asked for, make it, then say what you "
             "changed. Do not describe an edit for Andy to do by hand.")
    b.append(f"The store is {BOARD['store_root']}, one TOML per project.")
    return " ".join(b)


def after():
    L = [f"HiveFrame project view.",
         f"Project: {p['name']} [{p['id']}] {p['tier']}/{p['horizon'] or '-'}/"
         f"{p['status']} score {p['score']} {p['open_tasks']} open.",
         f"File: {p['source_file']}"]
    if p.get("folders"):
        L.append("Folders: " + " ".join(f["path"] for f in p["folders"]))
    if open_tasks:
        L.append("Open moves as numbered on screen:")
        for t in open_tasks:
            f = []
            if t.get("due"):
                f.append(t["due"])
            if t.get("effort_h"):
                f.append(f"{t['effort_h']}h")
            if t.get("urgent"):
                f.append("urgent")
            if live_blockers(t):
                f.append("blocked by " + "/".join("#" + str(num[x]) for x in live_blockers(t)))
            L.append(f"{num[t['id']]}. {t['title']} [{t['id']}]" + (f" ({', '.join(f)})" if f else ""))
    L.append(f"Store: {BOARD['store_root']} (one TOML per project).")
    L.append("You have file tools. Read and edit those paths directly; nothing else "
             "is reachable. Make requested changes yourself, then say what changed.")
    return "\n".join(L)


WRAP_BEFORE = ("Context from the HiveFrame UI, which the user did not type:\n"
               "\n\nAnswer this, using that context only where it is relevant:\n")
WRAP_AFTER = "[screen, not typed]\n\n\n[request]\n"

ASK_BEFORE = """Work on this move in {name}.

Move: {title}
Why it matters: {note}
Due: {due}
Estimated: {eff}h
Project problem: {problem}
What good looks like: {goal}
Project folders: {folders}

Before changing anything, tell me what you plan to do and what you will touch.
Do not touch anything outside this project's folders."""

ASK_AFTER = """Do move #{n}: {title}
Context: {note}
Project goal: {goal}
Plan first, in two or three lines, then wait."""


def row(label, a, b):
    d = b - a
    pct = (d / a * 100) if a else 0
    print(f"{label:<28} {a:>7,} {b:>7,} {d:>8,} {pct:>7.0f}%")


t = open_tasks[0] if open_tasks else None
c = p.get("charter") or {}
ab = ASK_BEFORE.format(name=p["name"], title=t["title"], note=t.get("note") or "",
                       due=t.get("due") or "", eff=t.get("effort_h") or 0,
                       problem=c.get("problem") or "", goal=c.get("goal") or "",
                       folders="; ".join(f["path"] for f in p.get("folders") or []))
aa = ASK_AFTER.format(n=num[t["id"]], title=t["title"],
                      note=t.get("note") or "", goal=c.get("goal") or "")

B, A = before(), after()
print(f"Project {p['id']}, {len(open_tasks)} open moves\n")
print(f"{'':<28} {'before':>7} {'after':>7} {'change':>8} {'':>7}")
row("Screen context, chars", len(B), len(A))
row("Turn wrapper, chars", len(WRAP_BEFORE), len(WRAP_AFTER))
row("Ask draft, chars", len(ab), len(aa))
print()
per_before = len(B) + len(WRAP_BEFORE)
per_after = len(A) + len(WRAP_AFTER)
row("Every turn, chars", per_before, per_after)
row("Every turn, ~tokens", per_before // 4, per_after // 4)
print()
print(f"Per 100 turns, roughly {(per_before - per_after) * 100 // 4:,} fewer input tokens.")
print("Token counts are chars/4, an approximation. Character counts are exact.")
