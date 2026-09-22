"""Tests for agent-yadogae.

Everything here runs against a throwaway HOME, CLAUDE_CONFIG_DIR and
CODEX_HOME, a fake /proc and throwaway project directories. Nothing touches
the real agent state and nothing calls an API: the question these answer is
whether the right bytes end up in the right places, which is a filesystem
question.

    python3 -m unittest discover -s test -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import agent_yadogae as ay  # noqa: E402

try:
    import tomllib
except ImportError:
    tomllib = None

needs_tomllib = unittest.skipIf(tomllib is None, "reading TOML back needs Python 3.11+")


def write_session(index_dir: Path, cwd: str, token: str) -> str:
    """A minimal two-turn transcript of the shape Claude Code writes."""
    index_dir.mkdir(parents=True, exist_ok=True)
    sid = str(uuid.uuid4())
    u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
    base = dict(
        isSidechain=False, userType="external", entrypoint="cli",
        cwd=cwd, sessionId=sid, version="2.1.270", gitBranch="main",
    )
    lines = [
        {**base, "parentUuid": None, "type": "user", "uuid": u1,
         "timestamp": "2026-09-13T00:00:00.000Z",
         "message": {"role": "user", "content": f"Remember {token}."}},
        {**base, "parentUuid": u1, "type": "assistant", "uuid": u2,
         "timestamp": "2026-09-13T00:00:01.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": f"Noted {token}."}]}},
    ]
    (index_dir / f"{sid}.jsonl").write_text(
        "".join(json.dumps(l, separators=(",", ":")) + "\n" for l in lines), encoding="utf-8"
    )
    return sid


def compact(obj) -> str:
    """JSONL the way the agents write it (JSON.stringify / encoding/json)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class Fixture(unittest.TestCase):
    """A fake home with one project that has history, memory and settings."""

    ENV = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_DATA_HOME", "HOME")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.root = Path(self.tmp.name).resolve()
        # HOME, CODEX_HOME and XDG_DATA_HOME too: the Codex, agy and OpenCode
        # carriers run on every migration, and must never see the real
        # ~/.codex, ~/.gemini or ~/.local/share/opencode.
        saved = {k: os.environ.get(k) for k in self.ENV}
        self.addCleanup(self._restore_env, saved)
        os.environ["HOME"] = str(root)
        os.environ["CODEX_HOME"] = str(root / ".codex")
        os.environ["XDG_DATA_HOME"] = str(root / ".local" / "share")
        (root / "proc").mkdir()
        for patch in (
            mock.patch.object(ay, "PROC_ROOT", root / "proc"),
            mock.patch.object(ay, "platform_supported", lambda: True),
            mock.patch.object(ay, "interactive", lambda: False),
        ):
            patch.start()
            self.addCleanup(patch.stop)

        self.home = root / ".claude"
        self.projects = self.home / "projects"
        self.projects.mkdir(parents=True)
        (self.home / "sessions").mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home)

        self.src = root / "work" / "oldname"
        self.dst = root / "work" / "newname"
        self.src.mkdir(parents=True)
        (self.src / "README.md").write_text("hello", encoding="utf-8")

        self.index = self.projects / ay.encode(str(self.src))
        self.sid = write_session(self.index, str(self.src), "XYZZY-7391")
        (self.index / "memory").mkdir()
        (self.index / "memory" / "MEMORY.md").write_text("- a memory", encoding="utf-8")
        (self.index / self.sid).mkdir()
        (self.index / self.sid / "tool-results").mkdir()

        self.config = ay.config_path(self.home)
        self.config.write_text(json.dumps({
            "numStartups": 3,
            "projects": {str(self.src): {"hasTrustDialogAccepted": True, "allowedTools": ["Bash"]}},
        }, indent=2), encoding="utf-8")

        self.history = self.home / "history.jsonl"
        self.history.write_text(
            compact({"display": "hi", "project": str(self.src), "sessionId": self.sid}) + "\n"
            + compact({"display": "other", "project": "/somewhere/else", "sessionId": "x"}) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _restore_env(saved):
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_cli(self, *args: str, argv: list[str] | None = None) -> int:
        if argv is None:
            argv = [str(self.src), str(self.dst), "-q", "--yes", *args]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ay.main(argv)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code


# Produced by running the path sanitizer extracted from Claude Code 2.1.270
# under node; see TestEncoding.test_matches_the_original_function_under_node.
VECTORS = [
    ("/home/you/work/my_proj", "-home-you-work-my-proj"),
    ("/home/you/.config/app.v2", "-home-you--config-app-v2"),
    ("/home/you/日本語 フォルダ", "-home-you---------"),
    ("/home/you/emoji😀x", "-home-you-emoji--x"),
    ("/w/" + "a_b/" * 60, ("-w-" + "a-b-" * 60)[:200] + "-mhgl"),
    ("/x/" + "日本" * 150, ("-x-" + "-" * 300)[:200] + "-3h411c"),
    ("/p/" + "z" * 197, "-p-" + "z" * 197),
    ("/p/" + "z" * 198, ("-p-" + "z" * 198)[:200] + "-n7dswi"),
]

CLAUDE_SANITIZER_JS = """
const V6=t=>{let e=0;for(let r=0;r<t.length;r++)e=(e<<5)-e+t.charCodeAt(r)|0;return e};
const _=t=>{let e=t.replace(/[^a-zA-Z0-9]/g,"-");if(e.length<=200)return e;return `${e.slice(0,200)}-${Math.abs(V6(t)).toString(36)}`};
console.log(JSON.stringify(JSON.parse(require("fs").readFileSync(0,"utf8")).map(_)));
"""


class TestEncoding(unittest.TestCase):
    def test_matches_claude_code_on_recorded_vectors(self):
        for path, expected in VECTORS:
            with self.subTest(path=path[:40]):
                self.assertEqual(ay.encode(path), expected)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_matches_the_original_function_under_node(self):
        cases = [p for p, _ in VECTORS] + [
            "/tmp/a b/c.d_e~f+g@h", "/😀/x", "/" + "é" * 250, "/p/" + "q" * 197 + "😀",
            "/" + "Ab9" * 70, "/w/" + "\U0001F600" * 120,
        ]
        out = subprocess.run(["node", "-e", CLAUDE_SANITIZER_JS], input=json.dumps(cases),
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual([ay.encode(c) for c in cases], json.loads(out))

    def test_names_are_lossy_which_is_why_collisions_are_checked(self):
        self.assertEqual(ay.encode("/w/a_b"), ay.encode("/w/a-b"))


class TestVerifyEncoding(Fixture):
    def test_clean_machine_reports_no_mismatch(self):
        self.assertEqual(ay.verify_encoding(self.projects), [])

    def test_a_directory_that_contradicts_the_rule_is_reported(self):
        rogue = self.projects / "not-the-encoded-name"
        write_session(rogue, "/some/real/path", "T")
        bad = ay.verify_encoding(self.projects)
        self.assertEqual([b[0] for b in bad], ["not-the-encoded-name"])

    def test_a_worktree_session_is_not_a_violation(self):
        """Regression: a session that starts in the project root and then enters
        a worktree records both cwds and is filed under the worktree's name.
        Judging it by the first cwd alone wrongly blocked every migration."""
        root = "/home/u/proj"
        tree = "/home/u/proj/.claude/worktrees/wt"
        d = self.projects / ay.encode(tree)
        sid = write_session(d, root, "ROOT")  # the pre-switch lines
        with (d / f"{sid}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(compact({"type": "user", "cwd": tree, "sessionId": sid}) + "\n")
        self.assertEqual(ay.verify_encoding(self.projects), [])

    def test_paths_with_underscores_and_spaces_vouch_for_their_names(self):
        for path in ("/w/my_proj", "/w/with space", "/w/日本語"):
            write_session(self.projects / ay.encode(path), path, "T")
        self.assertEqual(ay.verify_encoding(self.projects), [])

    def test_declared_cwds_collects_every_one(self):
        d = self.projects / "whatever"
        sid = write_session(d, "/a", "T")
        with (d / f"{sid}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(compact({"type": "user", "cwd": "/b"}) + "\n")
        self.assertEqual(ay.declared_cwds(d), {"/a", "/b"})

    def test_main_refuses_to_guess_when_the_rule_is_contradicted(self):
        write_session(self.projects / "not-the-encoded-name", "/some/real/path", "T")
        self.assertEqual(self.run_cli(), 1)
        self.assertTrue(self.src.is_dir(), "must not move anything when it cannot trust the rule")

    def test_a_carried_folder_still_vouches_for_its_new_name(self):
        """Regression: carried transcripts keep the old cwd, and the next run
        took that for a broken rule and refused every later migration."""
        self.assertEqual(self.run_cli(), 0, self.err)
        new_index = self.projects / ay.encode(str(self.dst))
        self.assertEqual(ay.sidecar_paths(new_index), {str(self.dst)})
        self.assertEqual(ay.verify_encoding(self.projects), [])


class TestMigration(Fixture):
    def test_moves_the_directory_and_the_whole_index(self):
        self.assertEqual(self.run_cli(), 0, self.err)

        self.assertFalse(self.src.exists())
        self.assertEqual((self.dst / "README.md").read_text(encoding="utf-8"), "hello")

        new_index = self.projects / ay.encode(str(self.dst))
        self.assertFalse(self.index.exists(), "the old index key must not linger")
        self.assertTrue((new_index / f"{self.sid}.jsonl").is_file())
        self.assertEqual((new_index / "memory" / "MEMORY.md").read_text(encoding="utf-8"), "- a memory")
        self.assertTrue((new_index / self.sid / "tool-results").is_dir())

    def test_rekeys_the_project_settings(self):
        self.run_cli()
        data = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertNotIn(str(self.src), data["projects"])
        self.assertEqual(data["projects"][str(self.dst)]["allowedTools"], ["Bash"])
        self.assertEqual(data["numStartups"], 3)

    def test_repoints_only_this_projects_prompt_history(self):
        self.run_cli()
        entries = [json.loads(l) for l in self.history.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(entries[0]["project"], str(self.dst))
        self.assertEqual(entries[1]["project"], "/somewhere/else")

    def test_leaves_the_transcript_cwd_alone(self):
        """Rewriting it was verified unnecessary; not rewriting it is the contract."""
        self.run_cli()
        new_index = self.projects / ay.encode(str(self.dst))
        line = json.loads((new_index / f"{self.sid}.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(line["cwd"], str(self.src))

    def test_backs_up_both_files_it_edits(self):
        self.run_cli()
        self.assertTrue(list(self.config.parent.glob(".claude.json.agent-yadogae-*")))
        self.assertTrue(list(self.home.glob("history.jsonl.agent-yadogae-*")))

    def test_malformed_history_lines_are_preserved_byte_for_byte(self):
        self.history.write_text(
            "not json at all\n" + compact({"display": "hi", "project": str(self.src)}) + "\n",
            encoding="utf-8",
        )
        self.run_cli()
        lines = self.history.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "not json at all")
        self.assertEqual(json.loads(lines[1])["project"], str(self.dst))

    def test_prints_how_to_undo(self):
        self.assertEqual(self.run_cli(argv=[str(self.src), str(self.dst), "--yes"]), 0)
        self.assertIn(f"to undo: agent-yadogae {self.dst} {self.src}", self.out)


class TestClaudeIndexes(Fixture):
    def test_a_worktree_folder_moves_with_its_project(self):
        tree = str(self.src / ".claude" / "worktrees" / "wt")
        folder = self.projects / ay.encode(tree)
        sid = write_session(folder, str(self.src), "ROOT")
        with (folder / f"{sid}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(compact({"type": "user", "cwd": tree, "sessionId": sid}) + "\n")

        self.assertEqual(self.run_cli(), 0, self.err)
        moved = self.projects / ay.encode(str(self.dst / ".claude" / "worktrees" / "wt"))
        self.assertTrue((moved / f"{sid}.jsonl").is_file())
        self.assertFalse(folder.exists())
        self.assertEqual(ay.verify_encoding(self.projects), [])

    def test_subdirectory_settings_and_history_follow(self):
        sub = str(self.src / "pkg")
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["projects"][sub] = {"allowedTools": ["Read"]}
        self.config.write_text(json.dumps(data, indent=2), encoding="utf-8")
        with self.history.open("a", encoding="utf-8") as fh:
            fh.write(compact({"display": "sub", "project": sub}) + "\n")

        self.run_cli()
        self.assertIn(str(self.dst / "pkg"), json.loads(self.config.read_text(encoding="utf-8"))["projects"])
        last = json.loads(self.history.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["project"], str(self.dst / "pkg"))

    def test_a_destination_name_that_belongs_to_another_project_is_refused(self):
        """Regression: /w/a_b and /w/a-b share a folder name, and the history of
        the project moving in was silently merged into the other one's."""
        other = self.root / "work" / "a-b"
        other_folder = self.projects / ay.encode(str(other))
        write_session(other_folder, str(other), "OTHER")
        self.dst = self.root / "work" / "a_b"

        self.assertEqual(self.run_cli(), 1)
        self.assertIn("belongs to", self.err)
        self.assertTrue(self.src.is_dir())
        self.assertTrue(self.index.is_dir())
        self.assertEqual(len(list(other_folder.glob("*.jsonl"))), 1)

    def test_history_already_at_the_destination_is_merged(self):
        """Opening Claude in the new directory first must not block the carry-over."""
        new_index = self.projects / ay.encode(str(self.dst))
        fresh = write_session(new_index, str(self.dst), "NEWER")
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertTrue((new_index / f"{self.sid}.jsonl").is_file(), "the carried session")
        self.assertTrue((new_index / f"{fresh}.jsonl").is_file(), "the one already there")
        self.assertFalse(self.index.exists())

    def test_identical_memory_on_both_sides_collapses(self):
        new_index = self.projects / ay.encode(str(self.dst))
        write_session(new_index, str(self.dst), "NEWER")
        shutil.copytree(self.index / "memory", new_index / "memory")
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertFalse(self.index.exists())

    def test_different_memory_on_both_sides_is_refused_before_anything_moves(self):
        new_index = self.projects / ay.encode(str(self.dst))
        write_session(new_index, str(self.dst), "NEWER")
        (new_index / "memory").mkdir()
        (new_index / "memory" / "MEMORY.md").write_text("- another memory", encoding="utf-8")
        self.assertEqual(self.run_cli(), 1)
        self.assertIn("memory/MEMORY.md", self.err)
        self.assertTrue(self.src.is_dir())
        self.assertTrue(self.index.is_dir())

    def test_a_rename_that_keeps_the_folder_name_keeps_the_folder(self):
        src = self.root / "work" / "my-proj"
        dst = self.root / "work" / "my_proj"
        src.mkdir()
        folder = self.projects / ay.encode(str(src))
        sid = write_session(folder, str(src), "T")

        self.assertEqual(self.run_cli(argv=[str(src), str(dst), "-q", "--yes"]), 0, self.err)
        self.assertTrue((folder / f"{sid}.jsonl").is_file())
        self.assertEqual(ay.sidecar_paths(folder), {str(dst)})
        self.assertEqual(ay.verify_encoding(self.projects), [])

    def test_a_folder_that_only_shares_the_sources_name_is_left_alone(self):
        """Regression: moving /w/a_b took /w/a-b's history, because the folder
        name matched even though its transcripts named the other project."""
        src = self.root / "work" / "a_b"
        src.mkdir()
        other = self.root / "work" / "a-b"
        folder = self.projects / ay.encode(str(other))
        sid = write_session(folder, str(other), "OTHER")

        self.assertEqual(self.run_cli(argv=[str(src), str(self.root / "work" / "elsewhere"), "-q", "--yes"]), 0, self.err)
        self.assertTrue((folder / f"{sid}.jsonl").is_file())
        self.assertEqual(ay.sidecar_paths(folder), set())

    def test_a_folder_shared_with_a_project_outside_the_move_is_refused(self):
        inner = str(self.src / "b")
        outer = str(self.root / "work" / "oldname-b")  # same folder name as src/b
        folder = self.projects / ay.encode(inner)
        write_session(folder, inner, "IN")
        write_session(folder, outer, "OUT")

        self.assertEqual(self.run_cli(), 1)
        self.assertIn("cannot be split", self.err)
        self.assertTrue(self.src.is_dir())
        self.assertEqual(len(list(folder.glob("*.jsonl"))), 2)

    def test_a_folder_with_no_transcripts_left_moves_by_its_name(self):
        for f in self.index.glob("*.jsonl"):
            f.unlink()
        self.assertEqual(self.run_cli(), 0, self.err)
        new_index = self.projects / ay.encode(str(self.dst))
        self.assertEqual((new_index / "memory" / "MEMORY.md").read_text(encoding="utf-8"), "- a memory")

    def test_a_folder_with_no_transcripts_is_refused_when_another_project_shares_its_name(self):
        for f in self.index.glob("*.jsonl"):
            f.unlink()
        src = self.root / "work" / "x_y"
        src.mkdir()
        folder = self.projects / ay.encode(str(src))
        (folder / "memory").mkdir(parents=True)
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["projects"][str(self.root / "work" / "x-y")] = {}
        self.config.write_text(json.dumps(data, indent=2), encoding="utf-8")

        code = self.run_cli(argv=[str(src), str(self.root / "work" / "z"), "-q", "--yes"])
        self.assertEqual(code, 1)
        self.assertIn("no transcript", self.err)
        self.assertTrue(src.is_dir())
        self.assertTrue(folder.is_dir())

    def add_recorded_project(self, path: str) -> None:
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["projects"][path] = {}
        self.config.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_a_folder_another_recorded_project_also_uses_is_refused(self):
        """Regression: the other project's transcripts had been pruned, so only
        the memory/ the two share was left -- and it went with this move."""
        self.add_recorded_project(str(self.root / "work.oldname"))  # same folder name as src
        self.assertEqual(self.run_cli(), 1)
        self.assertIn("not part of this move", self.err)
        self.assertTrue(self.src.is_dir())
        self.assertTrue((self.index / "memory" / "MEMORY.md").is_file())

    def test_a_subdirectory_folder_another_recorded_project_also_uses_is_refused(self):
        inner = str(self.src / "x")
        folder = self.projects / ay.encode(inner)
        write_session(folder, inner, "IN")
        self.add_recorded_project(str(self.root / "work" / "oldname-x"))  # same folder name as src/x
        self.assertEqual(self.run_cli(), 1)
        self.assertIn("not part of this move", self.err)
        self.assertTrue(folder.is_dir())

    def test_an_unreadable_claude_config_is_refused_not_ignored(self):
        self.config.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_cli(), 1)
        self.assertIn("tell projects apart", self.err)
        self.assertTrue(self.src.is_dir())

    def test_a_folder_with_no_transcripts_needs_claude_codes_record_of_the_project(self):
        for f in self.index.glob("*.jsonl"):
            f.unlink()
        self.config.write_text(json.dumps({"projects": {}}, indent=2), encoding="utf-8")
        self.history.write_text("", encoding="utf-8")
        self.assertEqual(self.run_cli(), 1)
        self.assertIn("no record", self.err)
        self.assertTrue(self.index.is_dir())

    def test_a_subdirectory_folder_with_no_transcripts_is_reported_as_left_behind(self):
        folder = self.projects / ay.encode(str(self.src / "sub"))
        (folder / "memory").mkdir(parents=True)
        self.assertEqual(self.run_cli(argv=[str(self.src), str(self.dst), "--yes"]), 0, self.err)
        self.assertIn(f"left {folder.name} where it is", self.out)
        self.assertTrue(folder.is_dir())

    def test_an_existing_settings_entry_at_the_destination_is_kept(self):
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["projects"][str(self.dst)] = {"allowedTools": []}
        self.config.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.run_cli()
        projects = json.loads(self.config.read_text(encoding="utf-8"))["projects"]
        self.assertEqual(projects[str(self.dst)], {"allowedTools": []})
        self.assertIn(str(self.src), projects)


class TestDryRun(Fixture):
    def test_changes_nothing(self):
        before = self.config.read_text(encoding="utf-8")
        self.assertEqual(self.run_cli("--dry-run"), 0, self.err)
        self.assertTrue(self.src.is_dir())
        self.assertFalse(self.dst.exists())
        self.assertTrue(self.index.is_dir())
        self.assertFalse((self.index / ay.SIDECAR).exists())
        self.assertEqual(self.config.read_text(encoding="utf-8"), before)
        self.assertEqual(list(self.home.glob("history.jsonl.agent-yadogae-*")), [])


class TestGuards(Fixture):
    def assertRefusedUntouched(self, code: int, needle: str = "") -> None:
        self.assertEqual(code, 1, self.err)
        self.assertIn(needle, self.err)
        self.assertTrue(self.src.is_dir(), "a refusal must leave the project where it was")
        self.assertTrue(self.index.is_dir())

    def test_refuses_an_existing_destination_without_merge(self):
        self.dst.mkdir()
        self.assertRefusedUntouched(self.run_cli(), "--merge")

    def test_merge_folds_the_project_into_an_existing_destination(self):
        self.dst.mkdir()
        (self.dst / "NOTES.md").write_text("notes", encoding="utf-8")
        self.assertEqual(self.run_cli("--merge"), 0, self.err)
        self.assertEqual(sorted(p.name for p in self.dst.iterdir()), ["NOTES.md", "README.md"])
        self.assertFalse(self.src.exists())

    def test_merge_refuses_files_that_differ_on_the_two_sides(self):
        self.dst.mkdir()
        (self.dst / "README.md").write_text("a different readme", encoding="utf-8")
        self.assertRefusedUntouched(self.run_cli("--merge"), "README.md")

    def test_refuses_while_a_session_is_live_in_the_project(self):
        (self.home / "sessions" / "1.json").write_text(
            json.dumps({"pid": os.getpid(), "cwd": str(self.src / "sub"), "sessionId": "live"}),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli(), 2)
        self.assertTrue(self.src.is_dir(), "a live session must stop the move, not just warn")

    def test_a_dead_pid_is_not_a_live_session(self):
        (self.home / "sessions" / "1.json").write_text(
            json.dumps({"pid": 2 ** 30, "cwd": str(self.src), "sessionId": "stale"}),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli(), 0, self.err)

    def test_identical_paths_are_refused(self):
        self.assertRefusedUntouched(self.run_cli(argv=[str(self.src), str(self.src), "--yes"]), "same path")

    def test_missing_source_is_refused(self):
        self.assertEqual(self.run_cli(argv=[str(self.root / "no-such-dir"), str(self.dst), "--yes"]), 1)

    def test_a_symlinked_source_is_refused(self):
        link = self.root / "link"
        link.symlink_to(self.src)
        self.assertRefusedUntouched(self.run_cli(argv=[str(link), str(self.dst), "--yes"]), "symbolic link")
        self.assertTrue(link.is_symlink())

    def test_a_destination_inside_the_source_is_refused(self):
        self.assertRefusedUntouched(self.run_cli(argv=[str(self.src), str(self.src / "sub"), "--yes"]), "inside")

    def test_a_source_containing_the_home_directory_is_refused(self):
        code = self.run_cli(argv=[str(self.root), str(self.root.parent / "elsewhere"), "--yes"])
        self.assertRefusedUntouched(code, "home directory")

    def test_moving_into_agent_data_is_refused(self):
        code = self.run_cli(argv=[str(self.src), str(self.root / ".codex" / "proj"), "--yes"])
        self.assertRefusedUntouched(code, "agent data")

    def test_moving_into_opencode_data_is_refused(self):
        code = self.run_cli(
            argv=[str(self.src), str(self.root / ".local" / "share" / "opencode" / "proj"), "--yes"])
        self.assertRefusedUntouched(code, "agent data")

    def test_a_move_across_filesystems_is_refused(self):
        with mock.patch.object(ay, "same_filesystem", lambda a, b: False):
            self.assertRefusedUntouched(self.run_cli(), "--state-only")

    def test_merging_into_an_existing_mount_is_judged_by_the_mount_itself(self):
        self.dst.mkdir()
        dst = self.dst
        with mock.patch.object(ay, "same_filesystem", lambda a, b: Path(b) != dst):
            self.assertRefusedUntouched(self.run_cli("--merge"), "different filesystems")

    def test_a_destination_that_contains_agent_data_is_refused(self):
        other = self.root / "other"
        (other / ".gemini" / "antigravity-cli").mkdir(parents=True)
        with mock.patch.object(ay, "agy_home", lambda: other / ".gemini" / "antigravity-cli"):
            code = self.run_cli(argv=[str(self.src), str(other), "--merge", "--yes"])
        self.assertRefusedUntouched(code, "agent data")

    def test_a_missing_destination_parent_is_refused(self):
        self.dst = self.root / "nowhere" / "newname"
        self.assertRefusedUntouched(self.run_cli(), "create it first")

    def test_other_platforms_are_refused(self):
        with mock.patch.object(ay, "platform_supported", lambda: False):
            self.assertRefusedUntouched(self.run_cli(), "only Linux")

    def test_without_a_terminal_it_needs_yes(self):
        code = self.run_cli(argv=[str(self.src), str(self.dst)])
        self.assertRefusedUntouched(code, "--yes")

    def test_in_a_terminal_it_asks_and_no_means_no(self):
        with mock.patch.object(ay, "interactive", lambda: True), \
                mock.patch("builtins.input", lambda prompt: "n"):
            code = self.run_cli(argv=[str(self.src), str(self.dst)])
        self.assertRefusedUntouched(code)
        self.assertIn("move", self.out, "the plan is shown before the question")

    def test_in_a_terminal_yes_proceeds(self):
        with mock.patch.object(ay, "interactive", lambda: True), \
                mock.patch("builtins.input", lambda prompt: "y"):
            self.assertEqual(self.run_cli(argv=[str(self.src), str(self.dst)]), 0, self.err)
        self.assertTrue(self.dst.is_dir())

    def test_state_only_refuses_while_the_source_still_exists(self):
        self.dst.mkdir()
        self.assertRefusedUntouched(self.run_cli("--state-only"), "still exists")


class TestStateOnly(Fixture):
    def test_carries_state_for_a_directory_already_moved(self):
        self.src.rename(self.dst)  # as if the user had already run mv
        self.assertEqual(self.run_cli("--state-only"), 0, self.err)
        self.assertTrue((self.projects / ay.encode(str(self.dst)) / f"{self.sid}.jsonl").is_file())
        self.assertIn(str(self.dst), json.loads(self.config.read_text(encoding="utf-8"))["projects"])


class TestNoHistory(Fixture):
    def test_a_project_claude_never_saw_still_moves(self):
        shutil.rmtree(self.index)
        self.config.write_text(json.dumps({"projects": {}}), encoding="utf-8")
        self.history.write_text("", encoding="utf-8")
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertTrue((self.dst / "README.md").is_file())


class TestRebase(unittest.TestCase):
    def test_the_path_itself_and_its_subdirectories_move(self):
        self.assertEqual(ay.rebase("/w/old", "/w/old", "/w/new"), "/w/new")
        self.assertEqual(ay.rebase("/w/old/sub/x", "/w/old", "/w/new"), "/w/new/sub/x")

    def test_a_sibling_sharing_the_prefix_does_not(self):
        self.assertIsNone(ay.rebase("/w/old-other", "/w/old", "/w/new"))
        self.assertIsNone(ay.rebase("/w", "/w/old", "/w/new"))


class TestFileSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def mode(self, p: Path) -> int:
        return stat.S_IMODE(p.stat().st_mode)

    def test_write_atomic_keeps_a_private_file_private(self):
        f = self.dir / "config.toml"
        f.write_text("old", encoding="utf-8")
        os.chmod(f, 0o600)
        ay.write_atomic(f, "new")
        self.assertEqual((f.read_text(encoding="utf-8"), self.mode(f)), ("new", 0o600))
        self.assertEqual([p.name for p in self.dir.iterdir()], ["config.toml"])

    def test_write_atomic_keeps_a_shared_file_shared(self):
        f = self.dir / "history.jsonl"
        f.write_text("old", encoding="utf-8")
        os.chmod(f, 0o664)
        ay.write_atomic(f, "new")
        self.assertEqual(self.mode(f), 0o664)

    def test_create_private_never_reuses_a_name(self):
        first = ay.create_private(self.dir / "b")
        second = ay.create_private(self.dir / "b")
        self.assertNotEqual(first, second)
        self.assertEqual(self.mode(second), 0o600)


class CodexFixture(Fixture):
    """A fake ~/.codex of the shape codex-cli 0.153 writes."""

    def setUp(self):
        super().setUp()
        self.codex = self.root / ".codex"
        day = self.codex / "sessions" / "2026" / "09" / "13"
        day.mkdir(parents=True)
        self.rollout = self.write_rollout(day, "t1", str(self.src))
        self.other_rollout = self.write_rollout(day, "t2", "/somewhere/else")

        self.db = self.codex / "state_5.sqlite"
        con = sqlite3.connect(str(self.db))
        con.executescript("""
            CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, cwd TEXT NOT NULL);
            CREATE TABLE project_roots (project_id TEXT, position INTEGER, path TEXT,
                                        PRIMARY KEY (project_id, position));
        """)
        con.executemany("INSERT INTO threads VALUES (?, ?, ?)", [
            ("t1", str(self.rollout), str(self.src)),
            ("t2", str(self.other_rollout), "/somewhere/else"),
            ("t3", "", str(self.src) + "/sub"),
            ("t4", "", str(self.src) + "-sibling"),
        ])
        con.execute("INSERT INTO project_roots VALUES ('p', 0, ?)", (str(self.src),))
        con.commit()
        con.close()

        self.toml = self.codex / "config.toml"
        self.toml.write_text(
            'model = "gpt-6"\n\n'
            f'[projects.{json.dumps(str(self.src))}]\ntrust_level = "trusted"\n\n'
            '[projects."/somewhere/else"]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )

    def write_rollout(self, day: Path, tid: str, cwd: str) -> Path:
        f = day / f"rollout-2026-09-13T00-00-00-{tid}.jsonl"
        f.write_text(
            compact({"type": "session_meta", "payload": {"id": tid, "cwd": cwd,
                                                         "base_instructions": {"text": "日本語"}}}) + "\n"
            + '{"type": "response_item", "payload": {"text": "the word \\"cwd\\" in prose"}}\n'
            + compact({"type": "turn_context", "payload": {"cwd": cwd, "model": "m"}}) + "\n",
            encoding="utf-8",
        )
        return f

    def thread_cwds(self, db: Path | None = None) -> dict:
        con = sqlite3.connect(str(db or self.db))
        try:
            return dict(con.execute("SELECT id, cwd FROM threads"))
        finally:
            con.close()

    def rollout_cwds(self, f: Path) -> list:
        return [json.loads(l)["payload"].get("cwd") for l in f.read_text(encoding="utf-8").splitlines()]


class TestCodex(CodexFixture):
    def test_the_rollout_cwd_the_resume_filter_reads_follows_the_move(self):
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertEqual(self.rollout_cwds(self.rollout), [str(self.dst), None, str(self.dst)])

    def test_other_rollout_lines_are_kept_byte_for_byte(self):
        before = self.rollout.read_text(encoding="utf-8").splitlines()
        self.run_cli()
        after = self.rollout.read_text(encoding="utf-8").splitlines()
        self.assertEqual(after[1], before[1])
        self.assertEqual(json.loads(after[0])["payload"]["base_instructions"]["text"], "日本語")

    def test_the_thread_index_follows_including_subdirectories(self):
        self.run_cli()
        self.assertEqual(self.thread_cwds(), {
            "t1": str(self.dst),
            "t2": "/somewhere/else",
            "t3": str(self.dst) + "/sub",
            "t4": str(self.src) + "-sibling",
        })
        con = sqlite3.connect(str(self.db))
        self.assertEqual(con.execute("SELECT path FROM project_roots").fetchone()[0], str(self.dst))
        con.close()

    def test_a_database_without_project_roots_still_gets_its_threads_repointed(self):
        """Regression: the UPDATE on the missing table rolled the thread update
        back with it, while the run still reported success."""
        con = sqlite3.connect(str(self.db))
        con.execute("DROP TABLE project_roots")
        con.close()
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertEqual(self.thread_cwds()["t1"], str(self.dst))

    def test_an_unknown_threads_schema_fails_the_run_but_not_the_rest(self):
        con = sqlite3.connect(str(self.db))
        con.executescript("DROP TABLE threads; CREATE TABLE threads (id TEXT, something_else TEXT);")
        con.close()
        self.assertEqual(self.run_cli(), 1)
        self.assertIn("threads table", self.err)
        self.assertEqual(self.rollout_cwds(self.rollout)[0], str(self.dst), "rollouts are still carried")

    def test_a_thread_whose_rollout_is_gone_does_not_fail_the_run(self):
        """A missing rollout used to fail every run, --state-only included."""
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO threads VALUES ('t5', ?, ?)",
                    (str(self.rollout.parent / "rollout-gone.jsonl"), str(self.src)))
        con.commit()
        con.close()
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertEqual(self.thread_cwds()["t5"], str(self.dst))

    def test_other_projects_rollouts_are_untouched(self):
        before = self.other_rollout.read_bytes()
        self.run_cli()
        self.assertEqual(self.other_rollout.read_bytes(), before)

    def test_a_rollout_the_index_never_saw_is_found_by_its_session_meta(self):
        con = sqlite3.connect(str(self.db))
        con.execute("DELETE FROM threads WHERE id = 't1'")
        con.commit()
        con.close()
        self.run_cli()
        self.assertEqual(self.rollout_cwds(self.rollout)[0], str(self.dst))

    @needs_tomllib
    def test_the_trust_entry_is_rekeyed_and_the_toml_stays_valid(self):
        self.run_cli()
        conf = tomllib.loads(self.toml.read_text(encoding="utf-8"))
        self.assertEqual(conf["projects"][str(self.dst)]["trust_level"], "trusted")
        self.assertNotIn(str(self.src), conf["projects"])
        self.assertIn("/somewhere/else", conf["projects"])
        self.assertEqual(conf["model"], "gpt-6")

    def test_the_trust_entry_is_rekeyed_on_any_python(self):
        self.run_cli()
        self.assertIn(f"[projects.{json.dumps(str(self.dst))}]", self.toml.read_text(encoding="utf-8"))

    @needs_tomllib
    def test_an_existing_trust_entry_for_the_destination_is_not_duplicated(self):
        with self.toml.open("a", encoding="utf-8") as fh:
            fh.write(f'\n[projects.{json.dumps(str(self.dst))}]\ntrust_level = "untrusted"\n')
        self.run_cli()
        conf = tomllib.loads(self.toml.read_text(encoding="utf-8"))  # must still parse
        self.assertEqual(conf["projects"][str(self.dst)]["trust_level"], "untrusted")

    def test_the_index_is_backed_up_before_it_is_edited(self):
        self.run_cli()
        backups = list(self.codex.glob("state_5.sqlite.agent-yadogae-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.thread_cwds(backups[0])["t1"], str(self.src))
        self.assertTrue(list(self.codex.glob("config.toml.agent-yadogae-*")))

    def test_backups_are_no_more_readable_than_the_originals(self):
        """Regression: the SQLite backup came out 0644 next to a 0600 original."""
        os.chmod(self.db, 0o600)
        os.chmod(self.toml, 0o600)
        self.run_cli()
        for pattern in ("state_5.sqlite.agent-yadogae-*", "config.toml.agent-yadogae-*"):
            (backup,) = self.codex.glob(pattern)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600, pattern)
        self.assertEqual(stat.S_IMODE(self.toml.stat().st_mode), 0o600)

    def test_a_second_run_changes_and_backs_up_nothing(self):
        self.run_cli()
        before = sorted(p.name for p in self.codex.iterdir())
        self.src.mkdir()  # something new at the old path, so the run is not refused
        self.assertEqual(self.run_cli(argv=[str(self.root / "work" / "unrelated"), str(self.dst / "x"), "-q", "--yes"]), 1)
        self.assertEqual(sorted(p.name for p in self.codex.iterdir()), before)

    def test_dry_run_changes_nothing(self):
        rollout, toml = self.rollout.read_bytes(), self.toml.read_bytes()
        self.assertEqual(self.run_cli("--dry-run"), 0, self.err)
        self.assertEqual(self.thread_cwds()["t1"], str(self.src))
        self.assertEqual(self.rollout.read_bytes(), rollout)
        self.assertEqual(self.toml.read_bytes(), toml)
        self.assertEqual(list(self.codex.glob("*.agent-yadogae-*")), [])


@unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores the permission this relies on")
class TestFailureRecovery(CodexFixture):
    def test_a_failed_step_fails_the_run_and_state_only_finishes_it(self):
        day = self.rollout.parent
        os.chmod(day, 0o555)
        self.addCleanup(os.chmod, day, 0o755)

        self.assertEqual(self.run_cli(), 1)
        self.assertIn("rollout", self.err)
        self.assertIn("--state-only", self.err)
        self.assertTrue(self.dst.is_dir(), "the project itself had already moved")
        self.assertEqual(self.rollout_cwds(self.rollout)[0], str(self.src))

        os.chmod(day, 0o755)
        self.assertEqual(self.run_cli("--state-only"), 0, self.err)
        self.assertEqual(self.rollout_cwds(self.rollout), [str(self.dst), None, str(self.dst)])
        self.assertEqual(self.thread_cwds()["t1"], str(self.dst))


class AgyFixture(Fixture):
    """A fake ~/.gemini/antigravity-cli of the shape agy 1.2 writes."""

    def setUp(self):
        super().setUp()
        self.agy = self.root / ".gemini" / "antigravity-cli"
        (self.agy / "cache").mkdir(parents=True)
        self.last = self.agy / "cache" / "last_conversations.json"
        self.last.write_text(json.dumps({str(self.src): "conv-1", "/somewhere/else": "conv-2"}, indent=2),
                             encoding="utf-8")
        self.settings = self.agy / "settings.json"
        self.settings.write_text(json.dumps({
            "colorScheme": "dark", "trustedWorkspaces": [str(self.src), "/somewhere/else"],
        }, indent=2), encoding="utf-8")
        self.agy_history = self.agy / "history.jsonl"
        self.agy_history.write_text(
            compact({"display": "hi", "workspace": str(self.src) + "/sub"}) + "\n"
            + compact({"display": "other", "workspace": "/somewhere/else"}) + "\n",
            encoding="utf-8",
        )

    def read(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))


class TestAntigravity(AgyFixture):
    def test_continue_pointer_follows_the_move(self):
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertEqual(self.read(self.last), {str(self.dst): "conv-1", "/somewhere/else": "conv-2"})

    def test_an_existing_pointer_at_the_destination_is_kept(self):
        self.last.write_text(json.dumps({str(self.src): "conv-1", str(self.dst): "conv-new"}), encoding="utf-8")
        self.run_cli()
        self.assertEqual(self.read(self.last), {str(self.src): "conv-1", str(self.dst): "conv-new"})

    def test_trust_follows_without_duplicates(self):
        data = self.read(self.settings)
        data["trustedWorkspaces"].append(str(self.dst))
        self.settings.write_text(json.dumps(data), encoding="utf-8")
        self.run_cli()
        data = self.read(self.settings)
        self.assertEqual(data["trustedWorkspaces"], [str(self.dst), "/somewhere/else"])
        self.assertEqual(data["colorScheme"], "dark")

    def test_prompt_history_follows_including_subdirectories(self):
        self.run_cli()
        entries = [json.loads(l) for l in self.agy_history.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["workspace"] for e in entries], [str(self.dst) + "/sub", "/somewhere/else"])

    def test_dry_run_changes_nothing(self):
        before = [p.read_bytes() for p in (self.last, self.settings, self.agy_history)]
        self.run_cli("--dry-run")
        self.assertEqual([p.read_bytes() for p in (self.last, self.settings, self.agy_history)], before)


class OpencodeFixture(Fixture):
    """A fake ~/.local/share/opencode of the shape opencode v2.0.11 writes."""

    def setUp(self):
        super().setUp()
        self.opencode = self.root / ".local" / "share" / "opencode"
        self.opencode.mkdir(parents=True)
        self.oc_db = self.opencode / "opencode.db"
        con = sqlite3.connect(str(self.oc_db))
        con.executescript("""
            CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL);
            CREATE TABLE project_directory (project_id TEXT NOT NULL, directory TEXT NOT NULL,
                                             type TEXT, strategy TEXT,
                                             PRIMARY KEY (project_id, directory));
            CREATE TABLE worktree (project_id TEXT NOT NULL, directory TEXT NOT NULL, strategy TEXT,
                                   PRIMARY KEY (project_id, directory));
            CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                                   directory TEXT NOT NULL, path TEXT);
            CREATE TABLE session_v2 (id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                                      directory TEXT NOT NULL, path TEXT);
        """)
        self.tree = str(self.src / ".claude" / "worktrees" / "wt")
        con.executemany("INSERT INTO project VALUES (?, ?)", [
            ("p1", str(self.src)),
            ("other", "/somewhere/else"),
        ])
        con.executemany("INSERT INTO project_directory VALUES (?, ?, ?, ?)", [
            ("p1", str(self.src), None, None),
            ("p1", self.tree, None, "git_worktree"),
            ("other", "/somewhere/else", None, None),
        ])
        con.executemany("INSERT INTO worktree VALUES (?, ?, ?)", [
            ("p1", str(self.src), None),
            ("other", "/somewhere/else", None),
        ])
        con.executemany("INSERT INTO session VALUES (?, ?, ?, ?)", [
            ("ses1", "p1", str(self.src), ""),
            ("ses2", "other", "/somewhere/else", ""),
        ])
        con.executemany("INSERT INTO session_v2 VALUES (?, ?, ?, ?)", [
            ("ses1v2", "p1", str(self.src / "sub"), ""),
            ("ses2v2", "other", "/somewhere/else", ""),
        ])
        con.commit()
        con.close()

    def rows(self, table: str, db: Path | None = None) -> list:
        con = sqlite3.connect(str(db or self.oc_db))
        try:
            return sorted(con.execute(f"SELECT * FROM {table}"))
        finally:
            con.close()


class TestOpencode(OpencodeFixture):
    def test_the_project_worktree_follows_the_move(self):
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertEqual(dict(self.rows("project")), {"p1": str(self.dst), "other": "/somewhere/else"})

    def test_project_directory_and_worktree_follow_including_subdirectories(self):
        self.run_cli()
        new_tree = str(self.dst) + self.tree[len(str(self.src)):]
        self.assertEqual(
            {(pid, d) for pid, d, *_ in self.rows("project_directory")},
            {("p1", str(self.dst)), ("p1", new_tree), ("other", "/somewhere/else")},
        )
        self.assertEqual(
            {(pid, d) for pid, d, *_ in self.rows("worktree")},
            {("p1", str(self.dst)), ("other", "/somewhere/else")},
        )

    def test_session_and_session_v2_directory_follow_including_subdirectories(self):
        self.run_cli()
        self.assertEqual(dict((i, d) for i, _, d, _ in self.rows("session")),
                         {"ses1": str(self.dst), "ses2": "/somewhere/else"})
        self.assertEqual(dict((i, d) for i, _, d, _ in self.rows("session_v2")),
                         {"ses1v2": str(self.dst / "sub"), "ses2v2": "/somewhere/else"})

    def test_an_existing_project_at_the_destination_is_kept(self):
        con = sqlite3.connect(str(self.oc_db))
        con.execute("INSERT INTO project VALUES ('p2', ?)", (str(self.dst),))
        con.commit()
        con.close()
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertEqual(dict(self.rows("project")),
                         {"p1": str(self.src), "p2": str(self.dst), "other": "/somewhere/else"})

    def test_an_existing_project_directory_at_the_destination_is_kept(self):
        con = sqlite3.connect(str(self.oc_db))
        con.execute("INSERT INTO project_directory VALUES ('p1', ?, NULL, NULL)", (str(self.dst),))
        con.commit()
        con.close()
        self.run_cli()
        self.assertIn(("p1", str(self.src)), [(pid, d) for pid, d, *_ in self.rows("project_directory")])

    def test_no_opencode_project_is_a_noop(self):
        con = sqlite3.connect(str(self.oc_db))
        con.execute("DELETE FROM project WHERE id = 'p1'")
        con.execute("DELETE FROM project_directory WHERE project_id = 'p1'")
        con.execute("DELETE FROM worktree WHERE project_id = 'p1'")
        con.execute("DELETE FROM session WHERE project_id = 'p1'")
        con.execute("DELETE FROM session_v2 WHERE project_id = 'p1'")
        con.commit()
        con.close()
        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertEqual(list(self.opencode.glob("opencode.db.agent-yadogae-*")), [])

    def test_the_database_is_backed_up_before_it_is_edited(self):
        self.run_cli()
        backups = list(self.opencode.glob("opencode.db.agent-yadogae-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(dict(self.rows("project", backups[0]))["p1"], str(self.src))

    def test_dry_run_changes_nothing(self):
        before = self.oc_db.read_bytes()
        self.assertEqual(self.run_cli("--dry-run"), 0, self.err)
        self.assertEqual(self.oc_db.read_bytes(), before)
        self.assertEqual(list(self.opencode.glob("opencode.db.agent-yadogae-*")), [])


class TestRoundTrip(CodexFixture, AgyFixture, OpencodeFixture):
    """Moving back is the undo, so it has to restore every store exactly."""

    def snapshot(self) -> dict:
        out = {}
        for f in sorted(self.root.rglob("*")):
            rel = str(f.relative_to(self.root))
            if rel.startswith("proc") or ".agent-yadogae-" in f.name:
                continue
            if f.is_dir():
                out[rel + "/"] = None
            elif f.suffix in (".sqlite", ".db"):
                con = sqlite3.connect(str(f))
                tables = [n for (n,) in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                out[rel] = {t: sorted(con.execute(f"SELECT * FROM {t}")) for t in tables}
                con.close()
            else:
                out[rel] = f.read_bytes()
        return out

    def test_moving_back_restores_every_store(self):
        tree = str(self.src / ".claude" / "worktrees" / "wt")
        write_session(self.projects / ay.encode(tree), tree, "TREE")
        before = self.snapshot()

        self.assertEqual(self.run_cli(), 0, self.err)
        self.assertNotEqual(self.snapshot(), before)
        self.assertEqual(self.run_cli(argv=[str(self.dst), str(self.src), "-q", "--yes"]), 0, self.err)
        self.assertEqual(self.snapshot(), before)


class TestLiveAgentProcesses(Fixture):
    def fake_process(self, pid: int, cwd: Path, exe: str, argv: list[str]) -> None:
        d = self.root / "proc" / str(pid)
        d.mkdir()
        (d / "cwd").symlink_to(cwd)
        (d / "exe").symlink_to(exe)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")

    def test_a_codex_process_inside_the_project_stops_the_move(self):
        (self.src / "sub").mkdir()
        self.fake_process(4242, self.src / "sub", "/opt/bin/codex", ["codex", "resume"])
        self.assertEqual(self.run_cli(), 2)
        self.assertTrue(self.src.is_dir())

    def test_agy_and_a_node_wrapped_codex_are_recognised(self):
        self.fake_process(1, self.src, "/usr/bin/node", ["node", "/usr/lib/codex/bin/codex.js"])
        self.fake_process(2, self.dst, "/home/u/.local/bin/agy", ["agy"])
        self.assertEqual(ay.live_agent_processes([str(self.src), str(self.dst)]),
                         [(1, "Codex"), (2, "Antigravity")])

    def test_an_opencode_process_inside_the_project_stops_the_move(self):
        (self.src / "sub").mkdir()
        self.fake_process(3, self.src / "sub", "/home/u/.opencode/bin/opencode", ["opencode", "--auto"])
        self.assertEqual(self.run_cli(), 2)
        self.assertTrue(self.src.is_dir())

    def test_unrelated_processes_do_not_count(self):
        self.fake_process(1, self.src, "/usr/bin/vim", ["vim"])
        self.fake_process(2, Path("/"), "/opt/bin/codex", ["codex"])
        self.assertEqual(ay.live_agent_processes([str(self.src)]), [])
        self.assertEqual(self.run_cli(), 0, self.err)

    def test_ignore_running_migrates_anyway(self):
        self.fake_process(1, self.src, "/opt/bin/agy", ["agy"])
        self.assertEqual(self.run_cli("--ignore-running"), 0, self.err)


if __name__ == "__main__":
    unittest.main()
