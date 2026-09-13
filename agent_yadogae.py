#!/usr/bin/env python3
"""agent-yadogae -- move a project directory and take its coding-agent history with it.

Claude Code, Codex and the Antigravity CLI (agy) each index what they remember
about a project by its absolute path. Rename or move the project and those keys
stop matching: the transcripts, memories and settings are all still on disk,
but `claude --continue`, `codex resume` and `agy -c` no longer find them. `mv`
on its own silently orphans them.

This moves the directory and repoints what each agent's resume actually reads
(verified against Claude Code 2.1.268-2.1.270, codex-cli 0.153 and agy 1.2):

  Claude  ~/.claude/projects/<encoded>/          transcripts, subagent logs,
                                                 tool results, memory/
          ~/.claude.json  projects[path]         trust, allowed tools, MCP
          ~/.claude/history.jsonl  "project"     prompt history
  Codex   ~/.codex/sessions/**/rollout-*.jsonl   the cwd in session_meta and
                                                 turn_context -- what the
                                                 `codex resume` filter reads
          ~/.codex/state_<n>.sqlite              threads.cwd, project_roots.path
          ~/.codex/config.toml                   [projects."<path>"] trust
  agy     ~/.gemini/antigravity-cli/cache/last_conversations.json
          ~/.gemini/antigravity-cli/settings.json    trustedWorkspaces
          ~/.gemini/antigravity-cli/history.jsonl    "workspace" per prompt

Sessions started in a subdirectory of the project -- Claude Code worktrees
under .claude/worktrees/ included -- move with it: src/sub becomes dst/sub.

What it deliberately does NOT touch is the "cwd" recorded inside every Claude
Code transcript line. Leaving it stale was verified to be harmless, and
rewriting it would mean rewriting tens of megabytes of JSONL for no gain.
Instead the index directory it moves gets a small .agent-yadogae.json naming
the path it now belongs to, so the directory can still vouch for its name.

Files are edited through a temporary file renamed into place, and the small
ones are backed up first. Codex rollouts are not backed up -- they run to
hundreds of megabytes -- but only their cwd changes, and running the tool in
the other direction puts it back.

Unofficial: not affiliated with Anthropic, OpenAI or Google. It relies on
undocumented storage formats that can change without notice.

No dependencies beyond the standard library.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shlex
import shutil
import sqlite3
import stat
import sys
import time
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # Python < 3.11: config.toml is still rewritten, just not re-parsed
    tomllib = None

__version__ = "0.1.0"  # read by the build backend
VERSION = __version__


class Refused(Exception):
    """A precondition failed. Nothing has been changed."""


def rebase(path: str, src: str, dst: str) -> str | None:
    """path moved from under src to under dst, or None if it was not under src."""
    if path == src:
        return dst
    if path.startswith(src.rstrip("/") + "/"):
        return dst.rstrip("/") + path[len(src.rstrip("/")):]
    return None


def is_within(path: str, root: str) -> bool:
    return rebase(path, root, root) is not None


# --- Claude Code: the index name ----------------------------------------------
#
# Claude Code turns the absolute path into a folder name with
#
#   name = path.replace(/[^a-zA-Z0-9]/g, "-")
#   if (name.length > 200) name = name.slice(0, 200) + "-" + Math.abs(hash(path)).toString(36)
#
# where hash is the Java-style string hash wrapped to int32. Both the
# replacement and the hash walk UTF-16 code units, so a character outside the
# BMP becomes two hyphens; this port does the same. The mapping is lossy --
# "/a_b" and "/a-b" share a name -- which is why a destination whose name
# already belongs to another project is refused instead of merged.

CLAUDE_NAME_LIMIT = 200


def _utf16_units(s: str) -> list[int]:
    data = s.encode("utf-16-le", "surrogatepass")
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


def _js_string_hash(units: list[int]) -> int:
    h = 0
    for u in units:
        h = (h * 31 + u) & 0xFFFFFFFF
    return h - 0x100000000 if h & 0x80000000 else h


def _base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, rem = divmod(n, 36)
        out = digits[rem] + out
        if not n:
            return out


def encode(path: str) -> str:
    units = _utf16_units(path)
    name = "".join(
        chr(u) if 48 <= u <= 57 or 65 <= u <= 90 or 97 <= u <= 122 else "-" for u in units
    )
    if len(name) <= CLAUDE_NAME_LIMIT:
        return name
    return f"{name[:CLAUDE_NAME_LIMIT]}-{_base36(abs(_js_string_hash(units)))}"


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def config_path(home: Path) -> Path:
    """~/.claude.json sits beside ~/.claude/, not inside it.

    With CLAUDE_CONFIG_DIR pointing somewhere else there is no such convention,
    so keep the file with the directory it belongs to.
    """
    return home.parent / ".claude.json" if home.name == ".claude" else home / ".claude.json"


# A transcript can name more than one cwd: a session that starts in the project
# root and then enters a git worktree records both, and is filed under the
# worktree's encoded name. So a directory is identified by the set of cwds it
# declares, never by the first one -- reading only the first line mistakes such
# a session for a violation of the encoding rule.
HEAD_LINES = 3000
TAIL_BYTES = 256 * 1024


def declared_cwds(index_dir: Path) -> set[str]:
    """Every cwd the transcripts in this directory mention.

    Sampled rather than exhaustive: these files reach tens of megabytes, and a
    cwd change shows up either early (the session moved) or at the end (it
    moved last). Reading the head and the tail catches both.
    """
    found: set[str] = set()
    for jsonl in sorted(index_dir.glob("*.jsonl")):
        try:
            with jsonl.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i >= HEAD_LINES:
                        break
                    found.update(_cwds_in(line))
            size = jsonl.stat().st_size
            if size > TAIL_BYTES:
                with jsonl.open("rb") as fh:
                    fh.seek(-TAIL_BYTES, os.SEEK_END)
                    tail = fh.read().decode("utf-8", "replace")
                for line in tail.split("\n")[1:]:  # drop the partial first line
                    found.update(_cwds_in(line))
        except (OSError, UnicodeDecodeError):
            continue
    return found


def _cwds_in(line: str) -> set[str]:
    if '"cwd"' not in line:
        return set()
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return set()
    cwd = entry.get("cwd") if isinstance(entry, dict) else None
    return {cwd} if isinstance(cwd, str) and cwd else set()


# A carried index directory keeps transcripts whose cwd is the old path, so on
# its own it no longer vouches for its new name, and the next run would take
# it for a sign that the encoding rule has changed. The sidecar records the
# path it was moved to; it is dropped again once a transcript declares it.
SIDECAR = ".agent-yadogae.json"


def sidecar_paths(index_dir: Path) -> set[str]:
    try:
        data = json.loads((index_dir / SIDECAR).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    paths = data.get("paths") if isinstance(data, dict) else None
    return {p for p in paths if isinstance(p, str)} if isinstance(paths, list) else set()


def own_paths(index_dir: Path) -> set[str]:
    """The project paths this index directory is named after."""
    return {p for p in declared_cwds(index_dir) | sidecar_paths(index_dir) if encode(p) == index_dir.name}


def update_sidecar(index_dir: Path, new: str, inherited: set[str] | frozenset[str] = frozenset()) -> None:
    cwds = declared_cwds(index_dir)
    keep = {
        p for p in sidecar_paths(index_dir) | set(inherited) | {new}
        if encode(p) == index_dir.name and p not in cwds
    }
    f = index_dir / SIDECAR
    if keep:
        write_atomic(f, json.dumps({"paths": sorted(keep)}, indent=2) + "\n")
    elif f.exists():
        f.unlink()


def verify_encoding(projects: Path) -> list[tuple[str, list[str]]]:
    """Check encode() against every project directory that can vouch for itself.

    A directory vouches for itself when at least one path it declares encodes
    to its own name. Returns the ones that declare cwds but match none of them,
    as (directory name, declared cwds). An empty list means the rule reproduces
    every sample on this machine, which is the evidence that it can be trusted
    for a destination path that has no transcripts yet.
    """
    bad = []
    if not projects.is_dir():
        return bad
    for d in sorted(projects.iterdir()):
        if not d.is_dir():
            continue
        cwds = declared_cwds(d)
        if cwds and not own_paths(d):
            bad.append((d.name, sorted(cwds)))
    return bad


def merge_conflicts(src: Path, dst: Path, ignore: frozenset[str] = frozenset()) -> list[str]:
    """Entries present on both sides that a merge could not reconcile.

    Directories merge recursively and identical files collapse into one; any
    other overlap is a conflict, and a merge with conflicts is refused before
    anything moves.
    """
    out = []
    for item in sorted(src.iterdir()):
        if item.name in ignore:
            continue
        other = dst / item.name
        if not os.path.lexists(other):
            continue
        both_dirs = item.is_dir() and other.is_dir() and not item.is_symlink() and not other.is_symlink()
        both_files = item.is_file() and other.is_file() and not item.is_symlink() and not other.is_symlink()
        if both_dirs:
            out += [f"{item.name}/{c}" for c in merge_conflicts(item, other)]
        elif not (both_files and filecmp.cmp(item, other, shallow=False)):
            out.append(item.name)
    return out


def merge_into(src: Path, dst: Path, ignore: frozenset[str] = frozenset()) -> None:
    """Fold src into dst after merge_conflicts() came back empty."""
    for item in sorted(src.iterdir()):
        if item.name in ignore:
            item.unlink()
            continue
        other = dst / item.name
        if not os.path.lexists(other):
            os.rename(item, other)
        elif item.is_dir() and not item.is_symlink():
            merge_into(item, other)
        else:
            item.unlink()  # identical to the file already there
    src.rmdir()


def known_project_paths(home: Path) -> set[str]:
    """Every project path Claude Code has recorded, from ~/.claude.json and the prompt history.

    These records are what tells two projects with the same folder name apart,
    so a record that exists but cannot be read is a refusal, never an empty
    answer that would wave everything through.
    """
    paths: set[str] = set()
    config = config_path(home)
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Refused(f"cannot read {config} ({exc}); it is needed to tell projects apart")
        projects = data.get("projects") if isinstance(data, dict) else None
        if isinstance(projects, dict):
            paths.update(k for k in projects if isinstance(k, str))
    history = home / "history.jsonl"
    if history.exists():
        try:
            with history.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"project"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    project = entry.get("project") if isinstance(entry, dict) else None
                    if isinstance(project, str):
                        paths.add(project)
        except OSError as exc:
            raise Refused(f"cannot read {history} ({exc}); it is needed to tell projects apart")
    return paths


def plan_claude_indexes(
    projects: Path, src: str, dst: str, known: set[str]
) -> tuple[list[tuple[Path, Path, str]], list[str]]:
    """The folders to carry as (index dir, target dir, new path), and the names left behind.

    Folder names are lossy, so a folder is only taken when what it says about
    itself puts it under src and no other project Claude Code has recorded
    uses the same name, and a target is only used when nothing says it belongs
    elsewhere. Anything ambiguous raises Refused: one project's history -- its
    shared memory/ included -- must never be carried off with, or folded into,
    another's.
    """
    if not projects.is_dir():
        return [], []
    moves, left = [], []
    for d in sorted(projects.iterdir()):
        if not d.is_dir():
            continue
        owners = own_paths(d)
        inside = sorted(p for p in owners if is_within(p, src))
        outside = sorted(p for p in owners if not is_within(p, src))
        if inside and outside:
            raise Refused(
                f"the Claude Code history folder {d.name} holds sessions of both {inside[0]} and "
                f"{outside[0]}, which share that name; it cannot be split, so sort it out by hand first"
            )
        if not owners and d.name == encode(src):
            # No transcript left to vouch (Claude Code prunes old ones, memory/
            # stays), so the name is the only link. Take it only on Claude
            # Code's own record of src.
            if src not in known:
                raise Refused(
                    f"the Claude Code history folder {d.name} has no transcript left, and Claude Code "
                    f"has no record of {src} to tie it to; move it by hand"
                )
            inside = [src]
        if not inside:
            if not owners and d.name.startswith(encode(src) + "-"):
                left.append(d.name)
            continue
        rivals = sorted(
            p for p in known
            if encode(p) == d.name and not is_within(p, src) and not is_within(p, dst)
        )
        if rivals:
            raise Refused(
                f"the Claude Code history folder {d.name} is also the one Claude Code uses for "
                f"{rivals[0]}, which is not part of this move; what the two share (memory/ included) "
                "cannot be split, so sort it out by hand first"
            )
        old = src if src in inside else inside[0]
        new = dst + old[len(src):]  # every inside path is src or below it
        moves.append((d, projects / encode(new), new))

    sources = {d for d, _, _ in moves}
    claimed: dict[Path, str] = {}
    for d, target, new in moves:
        if target in claimed:
            raise Refused(
                f"{claimed[target]} and {new} would share the Claude Code history folder "
                f"{target.name}; move one of them out of the way first"
            )
        claimed[target] = new
    for d, target, new in moves:
        if target == d or not target.exists():
            continue
        if target in sources:
            raise Refused(
                f"the Claude Code history folder {target.name} for {new} is itself being moved; "
                "move the project in two steps"
            )
        theirs = own_paths(target)
        if new in theirs:
            conflicts = merge_conflicts(d, target, ignore=frozenset({SIDECAR}))
            if conflicts:
                raise Refused(
                    f"Claude Code already has history for {new} in {target.name}, and these entries "
                    f"differ on the two sides: {', '.join(conflicts[:10])}"
                )
            continue
        owners = sorted(theirs or declared_cwds(target))
        if owners:
            raise Refused(
                f"the Claude Code history folder {target.name} that {new} would use already belongs "
                f"to {', '.join(owners[:3])}; choose another destination name"
            )
        raise Refused(
            f"the Claude Code history folder {target.name} for {new} already exists and nothing "
            "in it says which project it belongs to; move it aside first"
        )
    return moves, left


def live_sessions(sessions_dir: Path, roots: list[str]) -> list[dict]:
    """Claude Code sessions still running inside any of roots.

    Migrating under a live session loses whatever it writes afterwards, because
    it keeps appending to the old index directory.
    """
    live = []
    if not sessions_dir.is_dir():
        return live
    for f in sessions_dir.glob("*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cwd = s.get("cwd") if isinstance(s, dict) else None
        if not isinstance(cwd, str) or not any(is_within(cwd, root) for root in roots):
            continue
        pid = s.get("pid")
        if not isinstance(pid, int):
            continue
        try:
            os.kill(pid, 0)  # signal 0 only tests for existence
        except OSError:
            continue
        live.append(s)
    return live


# Codex and agy keep no session registry to consult, so a running one is found
# by its process: an agent binary whose working directory is inside a root.
PROC_ROOT = Path("/proc")
AGENT_BINARIES = {"codex": "Codex", "agy": "Antigravity"}


def live_agent_processes(roots: list[str], proc: Path | None = None) -> list[tuple[int, str]]:
    """(pid, agent) for Codex and agy processes running inside any of roots."""
    proc = proc or PROC_ROOT
    live = []
    if not proc.is_dir():
        return live
    for p in proc.iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            cwd = os.readlink(p / "cwd")
            argv = (p / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        names = set()
        try:
            names.add(os.path.basename(os.readlink(p / "exe")))
        except OSError:
            pass
        # argv[1] covers `node .../codex.js`
        for arg in argv[:2]:
            names.add(os.path.splitext(os.path.basename(arg.decode("utf-8", "replace")))[0])
        hit = sorted(names & AGENT_BINARIES.keys())
        if hit and any(is_within(cwd, root) for root in roots):
            live.append((int(p.name), AGENT_BINARIES[hit[0]]))
    return sorted(live)


# --- running it -----------------------------------------------------------------

def create_private(path: Path) -> Path:
    """Create an empty file readable by the owner only, never over an existing one."""
    candidate, n = path, 0
    while True:
        try:
            os.close(os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            return candidate
        except FileExistsError:
            n += 1
            candidate = path.with_name(f"{path.name}.{n}")


def write_atomic(path: Path, text: str) -> None:
    """Replace path with text; no reader ever sees a partial file or a wider mode."""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    tmp = create_private(path.with_name(path.name + ".agent-yadogae-tmp"))
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink()
        raise


def dumps_like(original: str, data: object) -> str:
    """JSON in the two-space layout these agents write, keeping the final newline."""
    return json.dumps(data, indent=2, ensure_ascii=False) + ("\n" if original.endswith("\n") else "")


class Runner:
    def __init__(self, dry_run: bool, quiet: bool, prefix: str = "[dry-run] "):
        self.dry_run = dry_run
        self.quiet = quiet
        self.prefix = prefix
        self.stamp = time.strftime("%Y%m%dT%H%M%S")
        self.problems: list[str] = []
        self.project_moved = False

    def say(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def act(self, msg: str) -> bool:
        self.say(("  " + self.prefix if self.dry_run else "  ") + msg)
        return not self.dry_run

    def problem(self, msg: str) -> None:
        self.problems.append(msg)

    def step(self, label: str, fn, *args) -> Any:
        """Run one step; a failure is recorded and the remaining steps still run."""
        try:
            return fn(self, *args)
        except Exception as exc:  # one store's failure must not hide the others
            self.problem(f"{label}: {type(exc).__name__}: {exc}")
            return None

    def backup(self, path: Path) -> None:
        if not path.exists():
            return
        dest = path.with_name(f"{path.name}.agent-yadogae-{self.stamp}")
        if self.act(f"back up {path.name} -> {dest.name}"):
            dest = create_private(dest)
            shutil.copyfile(path, dest)
            shutil.copystat(path, dest)

    def backup_sqlite(self, con: sqlite3.Connection, path: Path) -> None:
        """Through the backup API, so pages still in the WAL are included."""
        dest = path.with_name(f"{path.name}.agent-yadogae-{self.stamp}")
        if self.act(f"back up {path.name} -> {dest.name}"):
            dest = create_private(dest)
            out = sqlite3.connect(str(dest))
            try:
                con.backup(out)
            finally:
                out.close()
            os.chmod(dest, stat.S_IMODE(path.stat().st_mode))


# --- Claude Code --------------------------------------------------------------

def carry_index(r: Runner, index: Path, target: Path, new: str) -> None:
    if target == index:
        if r.act(f"keep {index.name}; it is already the name for {new}"):
            update_sidecar(index, new)
    elif target.exists():
        if r.act(f"merge {index.name} into {target.name}"):
            inherited = sidecar_paths(index)
            merge_into(index, target, ignore=frozenset({SIDECAR}))
            update_sidecar(target, new, inherited)
    elif r.act(f"move {index.name} -> {target.name}"):
        os.rename(index, target)
        update_sidecar(target, new)


def rekey_config(r: Runner, config: Path, src: str, dst: str) -> None:
    if not config.exists():
        r.say("  no ~/.claude.json")
        return
    text = config.read_text(encoding="utf-8")
    data = json.loads(text)
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        r.say("  no project entries in ~/.claude.json")
        return
    out, moved = {}, 0
    for key, entry in projects.items():  # rebuilt in order, so a round trip restores the file
        new = rebase(key, src, dst)
        if new is not None and new != key and new in projects:
            r.say(f"  kept the existing ~/.claude.json entry for {new}; the one for {key} is left as is")
            new = None
        if new is None:
            out[key] = entry
            continue
        out[new] = entry
        moved += 1
    if not moved:
        r.say(f"  no ~/.claude.json entry for {src}")
        return
    r.backup(config)
    if r.act(f"rekey {moved} ~/.claude.json project entr{'y' if moved == 1 else 'ies'}"):
        data["projects"] = out
        write_atomic(config, dumps_like(text, data))


def rewrite_jsonl_field(r: Runner, history: Path, field: str, src: str, dst: str) -> None:
    """Repoint one path-valued field in every JSONL entry under src."""
    if not history.exists():
        r.say(f"  no {history.name}")
        return
    changed = 0
    out = []
    for line in history.read_text(encoding="utf-8").splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                out.append(line)  # keep anything unparseable byte for byte
                continue
            value = entry.get(field) if isinstance(entry, dict) else None
            new = rebase(value, src, dst) if isinstance(value, str) else None
            if new is not None:
                entry[field] = new
                ending = line[len(line.rstrip("\r\n")):]
                line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + ending
                changed += 1
        out.append(line)
    if not changed:
        r.say(f"  no {history.name} entries for {src}")
        return
    r.backup(history)
    if r.act(f"repoint {changed} {history.name} entr{'y' if changed == 1 else 'ies'}"):
        write_atomic(history, "".join(out))


def carry_claude(
    r: Runner, home: Path, moves: list[tuple[Path, Path, str]], left: list[str], src: str, dst: str
) -> None:
    r.say("== Claude Code")
    if not moves:
        r.say(f"  no history folder for {src}")
    for index, target, new in moves:
        r.step(f"Claude Code history folder {index.name}", carry_index, index, target, new)
    for name in left:
        r.say(f"  left {name} where it is: it has no transcript saying which project it belongs to")
    r.step("~/.claude.json", rekey_config, config_path(home), src, dst)
    r.step("~/.claude/history.jsonl", rewrite_jsonl_field, home / "history.jsonl", "project", src, dst)


# --- Codex -------------------------------------------------------------------
#
# `codex resume` filters by the cwd written into each rollout file. Rewriting
# only the SQLite thread index was tried and is not enough: the session stays
# invisible from the new directory until the rollout says so too.

def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_state_db(home: Path) -> Path | None:
    """The newest state_<n>.sqlite; the number is Codex's schema generation."""
    found = [(int(m.group(1)), p) for p in home.glob("state_*.sqlite")
             if (m := re.fullmatch(r"state_(\d+)\.sqlite", p.name))]
    return max(found)[1] if found else None


def rekey_codex_threads(r: Runner, db: Path, src: str, dst: str) -> set[Path]:
    """Repoint threads.cwd and project_roots.path; return the threads' rollouts."""
    con = sqlite3.connect(str(db), timeout=10)
    try:
        tables = {n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {row[1] for row in con.execute("PRAGMA table_info(threads)")}
        if not {"id", "cwd", "rollout_path"} <= cols:
            r.problem(f"Codex: {db.name} has no threads table this tool understands; the thread index was left alone")
            return set()
        threads = [(new, tid, rp) for tid, cwd, rp in con.execute("SELECT id, cwd, rollout_path FROM threads")
                   if isinstance(cwd, str) and (new := rebase(cwd, src, dst)) is not None]
        roots = []
        if "project_roots" in tables:
            roots = [(new, pid, pos) for pid, pos, path in
                     con.execute("SELECT project_id, position, path FROM project_roots")
                     if isinstance(path, str) and (new := rebase(path, src, dst)) is not None]
        if not threads and not roots:
            r.say(f"  no threads for {src} in {db.name}")
            return set()
        r.backup_sqlite(con, db)
        if r.act(f"repoint {len(threads)} thread(s) and {len(roots)} project root(s) in {db.name}"):
            with con:
                if threads:
                    con.executemany("UPDATE threads SET cwd = ? WHERE id = ?", [t[:2] for t in threads])
                if roots:
                    con.executemany("UPDATE project_roots SET path = ? WHERE project_id = ? AND position = ?", roots)
        return {Path(rp) for _, _, rp in threads if rp}
    finally:
        con.close()


def codex_rollouts_started_in(home: Path, src: str) -> set[Path]:
    """Rollouts whose session_meta names src, for threads the index never saw."""
    found = set()
    for base in ("sessions", "archived_sessions"):
        for f in (home / base).rglob("rollout-*.jsonl"):
            try:
                with f.open(encoding="utf-8") as fh:
                    meta = json.loads(fh.readline())
            except (OSError, ValueError):
                continue
            payload = meta.get("payload") if isinstance(meta, dict) else None
            cwd = payload.get("cwd") if isinstance(payload, dict) else None
            if isinstance(cwd, str) and is_within(cwd, src):
                found.add(f)
    return found


def rewrite_rollout(f: Path, src: str, dst: str, write: bool) -> int:
    """Repoint payload.cwd lines; every other line is kept byte for byte."""
    out, changed = [], 0
    with f.open(encoding="utf-8", newline="") as fh:
        for line in fh:
            if '"cwd"' in line:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    entry = None
                payload = entry.get("payload") if isinstance(entry, dict) else None
                cwd = payload.get("cwd") if isinstance(payload, dict) else None
                new = rebase(cwd, src, dst) if isinstance(cwd, str) else None
                if isinstance(payload, dict) and new is not None:
                    payload["cwd"] = new
                    ending = line[len(line.rstrip("\r\n")):]
                    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + ending
                    changed += 1
            out.append(line)
    if changed and write:
        write_atomic(f, "".join(out))
    return changed


TOML_PROJECT_HEADER = re.compile(r'^(\s*)\[\s*projects\s*\.\s*("(?:[^"\\]|\\.)*"|\'[^\']*\')\s*\](.*)$')


def rekey_codex_config(r: Runner, config: Path, src: str, dst: str) -> None:
    """Rename [projects."<path>"] tables in place, leaving the rest of the text alone."""
    if not config.exists():
        r.say("  no config.toml")
        return
    lines = config.read_text(encoding="utf-8").splitlines(keepends=True)
    headers = []  # (line index, key, indent, trailer, line ending)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        m = TOML_PROJECT_HEADER.match(body)
        if not m:
            continue
        quoted = m.group(2)
        try:
            key = json.loads(quoted) if quoted.startswith('"') else quoted[1:-1]
        except json.JSONDecodeError:
            continue
        headers.append((i, key, m.group(1), m.group(3), line[len(body):]))
    keys = {h[1] for h in headers}
    moved = 0
    for i, key, indent, trailer, ending in headers:
        new = rebase(key, src, dst)
        if new is None:
            continue
        if new in keys:
            r.say(f"  kept the existing [projects] entry for {new}; the one for {key} is left as is")
            continue
        lines[i] = f"{indent}[projects.{json.dumps(new, ensure_ascii=False)}]{trailer}{ending}"
        keys.add(new)
        moved += 1
    if not moved:
        r.say(f"  no config.toml trust entry for {src}")
        return
    text = "".join(lines)
    if tomllib is not None:
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            r.problem(f"Codex config.toml: rekeying would make it invalid ({exc}); left alone")
            return
    r.backup(config)
    if r.act(f"rekey {moved} [projects] entr{'y' if moved == 1 else 'ies'} in config.toml"):
        write_atomic(config, text)


def carry_codex(r: Runner, home: Path, src: str, dst: str) -> None:
    if not home.is_dir():
        r.say("== Codex: no ~/.codex; skipped")
        return
    r.say("== Codex")
    rollouts = set()
    db = codex_state_db(home)
    if db is not None:
        rollouts |= r.step(f"Codex {db.name}", rekey_codex_threads, db, src, dst) or set()
    rollouts |= codex_rollouts_started_in(home, src)
    pending = []
    for f in sorted(rollouts):
        if not f.exists():
            # A thread can outlive its rollout; there is nothing left to carry,
            # and failing on it would make --state-only unable to ever finish.
            r.say(f"  {f.name} is listed in the thread index but no longer exists; skipped")
            continue
        try:
            if rewrite_rollout(f, src, dst, write=False):
                pending.append(f)
        except (OSError, ValueError) as exc:
            r.problem(f"Codex rollout {f.name}: {exc}")
    if not pending:
        r.say(f"  no rollouts for {src}")
    elif r.act(f"repoint the cwd in {len(pending)} rollout(s)"):
        for f in pending:
            try:
                rewrite_rollout(f, src, dst, write=True)
            except (OSError, ValueError) as exc:
                r.problem(f"Codex rollout {f.name}: {exc}")
    r.step("Codex config.toml", rekey_codex_config, home / "config.toml", src, dst)


# --- Antigravity CLI (agy) ----------------------------------------------------
#
# `agy -c` picks the conversation through cache/last_conversations.json, a
# map from workspace path to conversation id; rekeying that entry alone was
# verified to bring the conversation back. The conversation databases and the
# transcripts under brain/ are keyed by conversation id and are not touched.

def agy_home() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli"


def load_json_object(path: Path) -> tuple[dict, str] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return data, text


def rekey_last_conversations(r: Runner, path: Path, src: str, dst: str) -> None:
    loaded = load_json_object(path)
    if loaded is None:
        r.say("  no last_conversations.json")
        return
    data, text = loaded
    out, moved = {}, 0
    for key, conv in data.items():
        new = rebase(key, src, dst)
        if new is not None and new != key and new in data:
            r.say(f"  kept the existing conversation for {new}; the carried one is `agy --conversation {conv}`")
            new = None
        if new is None:
            out[key] = conv
            continue
        out[new] = conv
        moved += 1
    if not moved:
        r.say(f"  no last conversation for {src}")
        return
    r.backup(path)
    if r.act(f"rekey {moved} last-conversation entr{'y' if moved == 1 else 'ies'}"):
        write_atomic(path, dumps_like(text, out))


def rewrite_trusted_workspaces(r: Runner, path: Path, src: str, dst: str) -> None:
    loaded = load_json_object(path)
    if loaded is None or not isinstance(loaded[0].get("trustedWorkspaces"), list):
        r.say("  no trustedWorkspaces")
        return
    data, text = loaded
    trusted = data["trustedWorkspaces"]
    out, moved = [], 0
    for w in trusted:
        new = rebase(w, src, dst) if isinstance(w, str) else None
        if new is not None:
            moved += 1
            w = new
        if w not in out:
            out.append(w)
    if not moved:
        r.say(f"  {src} is not a trusted workspace")
        return
    r.backup(path)
    if r.act(f"repoint {moved} trusted workspace(s)"):
        data["trustedWorkspaces"] = out
        write_atomic(path, dumps_like(text, data))


def carry_antigravity(r: Runner, home: Path, src: str, dst: str) -> None:
    if not home.is_dir():
        r.say("== Antigravity: no ~/.gemini/antigravity-cli; skipped")
        return
    r.say("== Antigravity CLI")
    r.step("agy last_conversations.json", rekey_last_conversations, home / "cache" / "last_conversations.json", src, dst)
    r.step("agy settings.json", rewrite_trusted_workspaces, home / "settings.json", src, dst)
    r.step("agy history.jsonl", rewrite_jsonl_field, home / "history.jsonl", "workspace", src, dst)


# --- preconditions --------------------------------------------------------------
#
# Everything that can refuse runs before the first change, so a refusal always
# means nothing was touched. These three are functions so tests can stand in
# for another platform, a terminal, or a second filesystem.

def platform_supported() -> bool:
    return sys.platform.startswith("linux")


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def same_filesystem(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


class Plan:
    def __init__(self, args: argparse.Namespace):
        if not platform_supported():
            raise Refused(f"only Linux is supported for now (this is {sys.platform})")
        src_arg, dst_arg = Path(args.src).expanduser(), Path(args.dst).expanduser()
        for label, p in (("source", src_arg), ("destination", dst_arg)):
            if p.is_symlink():
                raise Refused(f"the {label} {p} is a symbolic link; pass the directory it points to")
        self.src = src = str(src_arg.resolve())
        self.dst = dst = str(dst_arg.resolve())
        self.state_only = args.state_only
        if src == dst:
            raise Refused("source and destination are the same path")
        if is_within(dst, src):
            raise Refused(f"the destination {dst} is inside the source {src}")
        if is_within(src, dst):
            raise Refused(f"the source {src} is inside the destination {dst}")

        self.home = claude_home()
        self.codex = codex_home()
        self.agy = agy_home()
        user_home = str(Path.home().resolve())
        for label, path in (("source", src), ("destination", dst)):
            if is_within(user_home, path):
                raise Refused(f"the {label} {path} contains the home directory {user_home}")
        for data_dir in (self.home, config_path(self.home), self.codex, self.agy.parent):
            d = str(data_dir.resolve())
            if any(is_within(a, b) for a, b in ((d, src), (src, d), (d, dst), (dst, d))):
                raise Refused(f"refusing to move into, out of or over the agent data at {d}")

        if self.state_only:
            if os.path.lexists(src):
                raise Refused(f"--state-only is for a project that has already moved, but {src} still exists")
            if not Path(dst).is_dir():
                raise Refused(f"--state-only expects the project at {dst}, which is not a directory")
        else:
            if not Path(src).is_dir():
                raise Refused(f"not a directory: {src}")
            parent = Path(dst).parent
            if not parent.is_dir():
                raise Refused(f"the destination's parent {parent} does not exist; create it first")
            landing = Path(dst) if os.path.lexists(dst) else parent  # an existing dst may be its own mount
            if not same_filesystem(Path(src), landing):
                raise Refused(
                    f"{src} and {landing} are on different filesystems, where a move is a copy and a "
                    "delete that cannot be undone halfway; copy the project yourself, check it, "
                    "remove the original, then run this again with --state-only"
                )
            if os.path.lexists(dst):
                if not args.merge:
                    raise Refused(f"{dst} already exists; pass --merge to fold the project into it")
                if not Path(dst).is_dir():
                    raise Refused(f"{dst} exists and is not a directory")
                conflicts = merge_conflicts(Path(src), Path(dst))
                if conflicts:
                    raise Refused(
                        f"cannot merge into {dst}: these differ on the two sides: {', '.join(conflicts[:10])}"
                    )

        projects = self.home / "projects"
        bad = verify_encoding(projects)
        if bad:
            lines = ["the Claude Code path-encoding rule does not match this machine:"]
            for name, cwds in bad[:5]:
                lines.append(f"  {name}")
                lines += [f"    declares cwd {c} -> {encode(c)}" for c in cwds[:3]]
            lines.append("refusing to guess the destination name; migrate by hand")
            raise Refused("\n".join(lines))
        self.index_moves, self.left_behind = plan_claude_indexes(projects, src, dst, known_project_paths(self.home))

    def execute(self, r: Runner) -> None:
        if not self.state_only:
            r.say(f"== project {self.src} -> {self.dst}")
            try:
                if os.path.lexists(self.dst):
                    if r.act("merge into the existing directory"):
                        merge_into(Path(self.src), Path(self.dst))
                elif r.act("move"):
                    os.rename(self.src, self.dst)
            except OSError as exc:
                r.problem(f"moving the project: {exc}")
                return
        r.project_moved = True
        carry_claude(r, self.home, self.index_moves, self.left_behind, self.src, self.dst)
        carry_codex(r, self.codex, self.src, self.dst)
        carry_antigravity(r, self.agy, self.src, self.dst)


def report_problems(plan: Plan, r: Runner) -> None:
    print(f"\n{len(r.problems)} problem(s):", file=sys.stderr)
    for p in r.problems:
        print(f"  - {p}", file=sys.stderr)
    if r.dry_run:
        return
    if not r.project_moved:
        print(
            f"the project directory was not moved -- or, when merging, only partly: check both "
            f"{plan.src} and {plan.dst}. No agent state was changed.",
            file=sys.stderr,
        )
        return
    print(
        f"the project is at {plan.dst}. Once the problems above are fixed, finish the move with:\n"
        f"  agent-yadogae {shlex.quote(plan.src)} {shlex.quote(plan.dst)} --state-only",
        file=sys.stderr,
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent-yadogae",
        description="Move a project directory and take its Claude Code, Codex and agy history with it.",
        epilog="Close every Claude Code, Codex and agy session in the project first. "
               "Unofficial; relies on undocumented storage formats.",
    )
    p.add_argument("src", help="the project directory as it is now")
    p.add_argument("dst", help="where it should live")
    p.add_argument("-n", "--dry-run", action="store_true", help="print the plan and change nothing")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--state-only", action="store_true", help="the directory is already moved; carry the state only")
    p.add_argument("--merge", action="store_true", help="fold the project into an existing destination directory")
    p.add_argument("--ignore-running", action="store_true", help="migrate even while an agent session is running there")
    p.add_argument("-q", "--quiet", action="store_true", help="only report problems")
    p.add_argument("--version", action="version", version=f"agent-yadogae {VERSION}")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = Plan(args)
    except Refused as exc:
        print(f"agent-yadogae: {exc}", file=sys.stderr)
        return 1

    roots = [plan.src, plan.dst]
    running = live_sessions(plan.home / "sessions", roots)
    others = live_agent_processes(roots)
    if (running or others) and not args.ignore_running:
        print(f"{len(running) + len(others)} agent session(s) still running there:", file=sys.stderr)
        for s in running:
            print(f"  Claude Code  pid {s.get('pid')}  session {s.get('sessionId')}", file=sys.stderr)
        for pid, agent in others:
            print(f"  {agent}  pid {pid}", file=sys.stderr)
        print("close them first, or pass --ignore-running to migrate anyway", file=sys.stderr)
        return 2

    if args.dry_run:
        r = Runner(dry_run=True, quiet=args.quiet)
        plan.execute(r)
        if r.problems:
            report_problems(plan, r)
            return 1
        r.say(f"\nwould move: {plan.src} -> {plan.dst}")
        return 0

    if not args.yes:
        if not interactive():
            print("agent-yadogae: not asking for confirmation without a terminal; "
                  "check the plan with --dry-run, then pass --yes", file=sys.stderr)
            return 1
        preview = Runner(dry_run=True, quiet=False, prefix="")
        plan.execute(preview)
        if preview.problems:
            report_problems(plan, preview)
            return 1
        try:
            answer = input(f"\nmove {plan.src} -> {plan.dst} and carry the above? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("nothing changed")
            return 1

    r = Runner(dry_run=False, quiet=args.quiet)
    try:
        plan.execute(r)
    except KeyboardInterrupt:
        r.problem("interrupted")
    if r.problems:
        report_problems(plan, r)
        return 1
    r.say(f"\nmoved: {plan.src} -> {plan.dst}")
    r.say("open the new directory and run `claude --continue`, `codex resume` or `agy -c` to confirm.")
    r.say(f"to undo: agent-yadogae {shlex.quote(plan.dst)} {shlex.quote(plan.src)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
