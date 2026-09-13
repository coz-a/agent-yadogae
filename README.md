English | [日本語](https://github.com/coz-a/agent-yadogae/blob/main/README.ja.md)

# agent-yadogae

Move a project directory and bring along what Claude Code, Codex CLI and Antigravity CLI remember about
it, so you can resume your conversations in the new location.

> **This is an unofficial tool**, not affiliated with Anthropic, OpenAI or Google. It relies on the
> undocumented, unguaranteed storage formats that Claude Code, Codex and Antigravity use internally,
> and an agent update can break it. It is provided under the MIT license with no warranty.
> Claude Code, Codex and Antigravity are trademarks of their respective owners.

## Quick start

Close any Claude Code, Codex or agy session in the project first, then run it — no install needed with
[uv](https://docs.astral.sh/uv/):

```bash
uvx agent-yadogae ~/workspace/oldname ~/workspace/newname
```

It shows what it will do and asks before changing anything:

```
== project /home/you/workspace/oldname -> /home/you/workspace/newname
  move
== Claude Code
  move -home-you-workspace-oldname -> -home-you-workspace-newname
  back up .claude.json -> .claude.json.agent-yadogae-20260913T111814
  rekey 1 ~/.claude.json project entry
  no history.jsonl
== Codex: no ~/.codex; skipped
== Antigravity: no ~/.gemini/antigravity-cli; skipped

move /home/you/workspace/oldname -> /home/you/workspace/newname and carry the above? [y/N] y
[... the same steps, now carried out ...]

moved: /home/you/workspace/oldname -> /home/you/workspace/newname
open the new directory and run `claude --continue`, `codex resume` or `agy -c` to confirm.
to undo: agent-yadogae /home/you/workspace/newname /home/you/workspace/oldname
```

Add `--dry-run` to see the plan without being asked.

## Install

Python 3.8 or later, no dependencies, Linux only.

```bash
pipx install agent-yadogae        # or: uv tool install agent-yadogae
```

It is a single file, so putting it on your `PATH` works too:

```bash
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/coz-a/agent-yadogae/main/agent_yadogae.py \
  -o ~/.local/bin/agent-yadogae && chmod +x ~/.local/bin/agent-yadogae
```

To run it straight from GitHub with nothing but Python, pipe it in. Python then reads the script from
standard input, so there is no confirmation prompt: look at the plan first, then pass `--yes`.

```bash
curl -fsSL https://raw.githubusercontent.com/coz-a/agent-yadogae/main/agent_yadogae.py \
  | python3 - ~/workspace/oldname ~/workspace/newname --dry-run
```

To uninstall, run `pipx uninstall agent-yadogae` or `uv tool uninstall agent-yadogae`, or delete the
file. Leave any `.agent-yadogae.json` files it created in place (see
[How the path encoding is checked](#how-the-path-encoding-is-checked)).

## Supported agents

| Agent | Verified versions | After a plain `mv` |
|---|---|---|
| Claude Code | 2.1.268–2.1.270 | `claude --continue` and the `/resume` list no longer show the sessions |
| Codex CLI | 0.153.4 | `codex resume` and `--last` no longer show them |
| Antigravity CLI (`agy`) | 1.2.2 | `agy -c` no longer finds the previous conversation |

Verified on Linux only. On any other platform it refuses with exit code 1 without changing anything.
Gemini CLI is not supported.

## Why you need it

All three agents index conversations by the **absolute path of the directory they ran in**. Claude
Code, for example, replaces every non-alphanumeric character in the path with `-` and uses the result
as a folder name under `~/.claude/projects/`, where the transcripts and the auto-memory live (names
longer than 200 characters are truncated and given a hash suffix).

```
/home/you/workspace/oldname
  → ~/.claude/projects/-home-you-workspace-oldname/
```

Rename the directory and the index key changes, so the usual resume commands and session lists no
longer find the old conversations from the new location. **Nothing is deleted — it is left behind
under the old key.** `mv` does this without a word.

## What it carries

It rewrites the records each agent's resume actually reads.

| | What it is |
|---|---|
| `~/.claude/projects/<encoded>/` | transcripts, subagent logs, tool results, `memory/` (auto-memory) |
| `projects[path]` in `~/.claude.json` | trust-dialog acceptance, `allowedTools`, MCP settings |
| `"project"` in `~/.claude/history.jsonl` | prompt history |
| `cwd` in `~/.codex/sessions/**/rollout-*.jsonl` | **what the `codex resume` filter looks at** |
| `threads.cwd`, `project_roots.path` in `~/.codex/state_<n>.sqlite` | thread index |
| `[projects."<path>"]` in `~/.codex/config.toml` | trust settings |
| `~/.gemini/antigravity-cli/cache/last_conversations.json` | path → conversation ID, **what `agy -c` looks at** |
| `trustedWorkspaces` in `~/.gemini/antigravity-cli/settings.json` | trusted workspaces |
| `"workspace"` in `~/.gemini/antigravity-cli/history.jsonl` | prompt history |

These are the default locations. `CLAUDE_CONFIG_DIR` and `CODEX_HOME` are honoured when set; the agy
location is always `~/.gemini/antigravity-cli`.

**Sessions started in a subdirectory of the project move with it** — Claude Code worktree history
folders (`.claude/worktrees/…`) included: `SRC/sub` becomes `DST/sub`. A subdirectory history folder
with no transcript left, which cannot be tied to the project, is not moved; the output says
`left <name> where it is`.

For Codex, fixing `threads.cwd` in SQLite is not enough: `codex resume` in the new location only picks
the session up once the `cwd` inside the rollout files is rewritten too. For agy, rekeying
`last_conversations.json` is enough for `agy -c` to restore the conversation.

## Usage

```
agent-yadogae SRC DST [-n] [-y] [--state-only] [--merge] [--ignore-running] [-q] [--version]

  -n, --dry-run       print the plan and change nothing
  -y, --yes           do not ask for confirmation
      --state-only    update the agent records after moving the directory yourself
                      (SRC must no longer exist and DST must be a directory)
      --merge         fold the project into a DST that already exists
      --ignore-running  migrate even while an agent session is running there
  -q, --quiet         only report problems
      --version       print the version and exit
```

Without `--yes`, it shows the plan and asks `[y/N]` when both standard input and standard output are a
terminal. Otherwise (a script, a CI job, a pipe) it refuses with exit code 1: run it with `--dry-run`
to check the plan, then with `--yes`.

Exit codes: 0 on success; 1 when refused, declined at the prompt, or a step failed; 2 when an agent
session is running under SRC or DST.

## Safety

### Checks before any change

These checks run before anything is changed. If one fails, it exits with code 1 and nothing has been
touched.

Paths and platform:

- the platform is not Linux
- SRC or DST is a symbolic link, they are the same directory, or one is inside the other
- SRC or DST contains your home directory, or is inside or contains agent data (`~/.claude`,
  `~/.claude.json`, `~/.codex`, `~/.gemini`)
- SRC is not a directory, DST's parent directory does not exist, or SRC and DST are on **different
  filesystems** (a move there is a copy and a delete that cannot be undone halfway)

Destination:

- DST already exists and `--merge` was not given
- with `--merge`, a file exists on both sides with different content
- with `--state-only`, SRC still exists or DST is not a directory

Claude Code history:

- the path-encoding rule does not reproduce the name of an existing history folder (see
  [How the path encoding is checked](#how-the-path-encoding-is-checked))
- a history folder it would carry is also used by a project outside the move. For example, `/w/a_b`
  and `/w/a-b` both map to `-w-a-b` and share its `memory/`. When the folder has no transcript left,
  Claude Code's own records (`~/.claude.json` and the prompt history) decide, and a record that cannot
  be read is a refusal
- the history folder name for DST already belongs to another project, or already exists with nothing
  in it that says which project it belongs to
- two folders being carried would end up with the same name, a folder's new name is taken by another
  folder in the same move, or conflicting files would have to be merged (`memory/MEMORY.md`, for
  example)

### Running sessions

**Close Claude Code, Codex and agy in the project before running it.** A session left open keeps
writing under the old path, and those later writes stay filed there or clash with the move. Claude
Code sessions are found by matching the `cwd` in `~/.claude/sessions/*.json` against live PIDs; Codex
and agy by looking in `/proc` for `codex` / `agy` processes whose working directory is under SRC or
DST. If one is found, it stops with exit code 2.

### Backups and how files are written

Before editing them, it copies `~/.claude.json`, `~/.claude/history.jsonl`, Codex's `config.toml` and
`state_<n>.sqlite`, and agy's JSON and JSONL files to `<name>.agent-yadogae-<timestamp>` beside the
original. A backup is created readable by the owner only and then given the original file's mode.
Codex rollout files, which can run to hundreds of megabytes, are not backed up.

**Backups are never deleted by the tool**, and each run adds a new set. Once you are happy with a move,
you can find them with

```bash
find ~ -maxdepth 2 -name '*.agent-yadogae-*'; find ~/.gemini/antigravity-cli -name '*.agent-yadogae-*'
```

and delete the ones you no longer need.

Text files are written to a temporary file and renamed into place, and the Codex database is updated in
a single transaction, so no file is ever left half-written. The migration as a whole, however, is a
sequence of steps, not one atomic operation.

### If a step fails

It exits with code 1 and says what failed and what to do next. If the project directory has already
moved, fix the cause and run `agent-yadogae SRC DST --state-only` to carry the rest; steps that already
completed are left as they are.

### Undo

**To undo a move into a new destination, run it the other way round.** The exact command is printed at
the end of a successful run: `agent-yadogae DST SRC` moves the project and its records back, subject to
the same checks (the tests check that such a round trip is byte-identical, Codex rollouts included).
It is a reverse move, not a snapshot restore, so changes made in between are kept.

Do not use it to undo `--merge`: it would move everything in DST back to SRC, including what was there
before the merge.

## What it does not do

**It does not rewrite the `"cwd"` recorded on every line of a Claude Code transcript.** Leaving the old
path there was verified to be harmless — `--continue` and `--resume` both work — and fixing it would
mean rewriting tens of megabytes of JSONL for no gain.

It also does not support Gemini CLI or platforms other than Linux, does not back up Codex rollout
files, and does not clean up its own backups.

Note that `claude --resume <session-id>` works regardless of the project, so with the session ID you
can restore a session from anywhere even without migrating. Only the listings break.

## How the path encoding is checked

The path → folder name conversion is a port of the function in Claude Code itself, checked against
Claude Code 2.1.270. The destination name still has to be computed, so before doing anything it checks
that the rule reproduces the name of every history folder on this machine, and refuses if it does not.
That way a change of rule in a Claude Code update cannot silently produce a wrong folder.

A folder passes when at least one `cwd` in its transcripts encodes to its name. (Checking only the first
would be wrong: a session that starts in the project root and then enters a git worktree records two
`cwd`s and is filed under the worktree's name.)

A carried history folder keeps transcripts whose `cwd` is the old path, so the tool leaves a small
`.agent-yadogae.json` in it recording the path it now belongs to, and counts that as well. **Leave
these files in place**: without one, the next run would refuse, because the folder no longer matches
its name. When the folder's own transcripts already declare its path — after moving back, for
example — the tool removes the file.

## About the name

*Yadogae* (宿替え) means moving house. What moves here is the **agents' lodging**, and the belongings
kept there — conversation history, auto-memory, per-project settings — naturally come along. The
difference from `mv` is the name.

## Tests and verification

```bash
python3 -m unittest discover -s test -v
```

The tests use only a throwaway `HOME`, `CLAUDE_CONFIG_DIR` and `CODEX_HOME` and a fake `/proc`; they
never touch real agent data and never call an API. If `node` is available, they also run the path
encoding function taken from Claude Code under node and check that the port gives the same results.

End-to-end verification with the real agents was done on 2026-09-13: sessions containing a marker token
were created, moved, and then real `claude --continue`, `codex exec resume --last` and `agy -c` in the
new location restored the token, and Claude Code did so again after moving back. Codex restored nothing
after a plain `mv`, nor after fixing only `threads.cwd` in SQLite; it did once the `cwd` in the rollouts
was fixed as well.

## Changelog

See [CHANGELOG.md](https://github.com/coz-a/agent-yadogae/blob/main/CHANGELOG.md).

## License

MIT. See [LICENSE](https://github.com/coz-a/agent-yadogae/blob/main/LICENSE).
