English | [日本語](https://github.com/coz-a/agent-yadogae/blob/main/README.ja.md)

# agent-yadogae

Move a project directory and **take everything your coding agents remember about it along**.

> **This is an unofficial tool**, not affiliated with Anthropic, OpenAI or Google. It relies on the
> undocumented, unguaranteed storage formats that Claude Code, Codex and Antigravity use internally,
> and an agent update can break it. It is provided under the MIT license with no warranty.
> Claude Code, Codex and Antigravity are trademarks of their respective owners.

```bash
agent-yadogae ~/workspace/oldname ~/workspace/newname
```

## Install

Python 3.8 or later, no dependencies, Linux only.

```bash
pipx install agent-yadogae        # or: uv tool install agent-yadogae
```

It is a single file, so dropping it on your `PATH` works too.

```bash
curl -fsSL https://raw.githubusercontent.com/coz-a/agent-yadogae/main/agent_yadogae.py \
  -o ~/.local/bin/agent-yadogae && chmod +x ~/.local/bin/agent-yadogae
```

## Supported agents

| Agent | Verified versions | After a plain `mv` |
|---|---|---|
| Claude Code | 2.1.268–2.1.270 | `claude --continue` and the `/resume` list no longer show the sessions |
| Codex CLI | 0.153.4 | `codex resume` and `--last` no longer show them |
| Antigravity CLI (`agy`) | 1.2.2 | `agy -c` no longer finds the previous conversation |

Verified on Linux only. On macOS and Windows it exits without changing anything. Gemini CLI is not
supported.

## Why you need it

All three agents index conversations by the **absolute path of the directory they ran in**. Claude
Code, for example, replaces every non-alphanumeric character in the path with `-` and uses the result
as a folder name under `~/.claude/projects/`, where the transcripts and the auto-memory live (names
longer than 200 characters are truncated and given a hash suffix).

```
/home/you/workspace/oldname
  → ~/.claude/projects/-home-you-workspace-oldname/
```

Rename the directory and the index key changes, so none of the agents can find the old conversations.
**Nothing is deleted — it is left behind under the old key.** `mv` does this without a word.

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

**Sessions started in a subdirectory of the project move with it** — Claude Code worktree history
folders (`.claude/worktrees/…`) included: `SRC/sub` becomes `DST/sub`.

For Codex, fixing `threads.cwd` in SQLite is not enough: `codex resume` in the new location only picks
the session up once the `cwd` inside the rollout files is rewritten too. This was verified. For agy,
rekeying `last_conversations.json` is enough for `agy -c` to restore the conversation.

## Usage

```
agent-yadogae SRC DST [-n] [-y] [--state-only] [--merge] [--ignore-running] [-q]

  -n, --dry-run       print the plan and change nothing
  -y, --yes           do not ask for confirmation (required when not run from a terminal)
      --state-only    the directory is already moved; carry the agent records only
      --merge         fold the project into a DST that already exists
      --ignore-running  migrate even while an agent session is running there
  -q, --quiet         only report problems
```

Exit codes: 0 on success, 1 when refused, cancelled or a step failed, 2 when an agent session is still
running.

Run from a terminal, it prints the plan first and asks `[y/N]`.

## Safety

**Everything is checked before the first change. If any check fails, it exits without changing
anything.** It refuses when:

- a Claude Code history folder it would carry is **also used by another project that is not part of
  the move** (`/w/a_b` and `/w/a-b` map to the same folder and share its `memory/`). When no transcript
  is left in the folder, Claude Code's own records (`~/.claude.json` and the prompt history) decide,
  and a record that cannot be read is a refusal
- the Claude Code history folder name for DST already belongs to another project
- both sides of a merge contain a file with the same name but different content (`memory/MEMORY.md`,
  for example)
- SRC is a symbolic link, DST is inside SRC, or SRC contains the home directory or agent data
- SRC and DST are on **different filesystems** (the move would become a copy and a delete that cannot
  be undone halfway)
- DST already exists (without `--merge`), or DST's parent directory does not exist
- the platform is not Linux

**Close Claude Code, Codex and agy in the project before running it.** A session left open keeps
appending to the old index, and whatever it writes afterwards is lost. Claude Code sessions are found
by matching the `cwd` in `~/.claude/sessions/*.json` against live PIDs; Codex and agy by looking in
`/proc` for `codex` / `agy` processes whose working directory is under SRC or DST. If one is found, it
stops with exit code 2.

Config and history files and Codex's SQLite database are backed up as `*.agent-yadogae-<timestamp>`
before they are touched. Backups are readable by the owner only from the moment they are created, and
never get a wider mode than the original. Files are written to a temporary file and renamed into place,
so nothing ever reads a half-written file.

**If a step fails partway**, it exits with code 1 and says what failed and what to do next. If the
project directory itself has already moved, fix the cause and run `agent-yadogae SRC DST --state-only`
to carry the rest (steps that already completed are left as they are).

**To undo, run it the other way round.** `agent-yadogae DST SRC` restores every carried record to its
state before the move (the tests check that a round trip is byte-identical). Codex rollouts, which can
run to hundreds of megabytes, are not backed up, but this round trip restores them.

## What it does not do

**It does not rewrite the `"cwd"` recorded on every line of a Claude Code transcript.** Leaving the old
path there was verified to be harmless — `--continue` and `--resume` both work — and fixing it would
mean rewriting tens of megabytes of JSONL for no gain.

Instead, a carried history folder gets a `.agent-yadogae.json` recording which path it now belongs to.
Without it, the next run could not tell "the transcript `cwd` does not match the folder name" apart
from a change in the path-encoding rule. When the folder's own transcripts already declare that path —
after moving back, for example — `agent-yadogae` does not write the file (and removes it if present).

Note that `claude --resume <session-id>` works regardless of the project, so with the session ID you
can restore a session from anywhere even without migrating. Only the listings break.

## Why the path encoding is verified

The path → folder name conversion is a direct port of the implementation extracted from Claude Code
itself (it replaces UTF-16 code units, so an emoji becomes two `-`). The destination name still has to
be computed, though, so before doing anything it **checks that the rule reproduces every project folder
on this machine**, and exits without changes if it does not. That way a change of rule in a Claude Code
update cannot silently produce a wrong folder.

A folder passes the check when at least one of the `cwd`s it declares (plus `.agent-yadogae.json`)
encodes to its own name. Looking only at the first one is wrong: a session that starts in the project
root and then enters a git worktree records two `cwd`s, and is filed under the worktree's name.

## About the name

*Yadogae* (宿替え) means moving house. What moves here is the **agents' lodging**, and the belongings
kept there — conversation history, auto-memory, per-project settings — naturally come along. The
difference from `mv` is the name.

## Tests

```bash
python3 -m unittest discover -s test -v
```

They use only a throwaway `HOME`, `CLAUDE_CONFIG_DIR` and `CODEX_HOME` and a fake `/proc`; they never
touch real agent data and never call an API. If `node` is available, they also run the path encoding
function extracted from Claude Code under node and check that the port gives the same results.

End-to-end verification with the real agents was done on 2026-09-13: sessions containing a marker token
were created, moved, and then real `claude --continue`, `codex exec resume --last` and `agy -c` in the
new location restored the token. Codex restored nothing after a plain `mv`, nor after fixing only
`threads.cwd` in SQLite; it did once the `cwd` in the rollouts was fixed as well.

## Changelog

See [CHANGELOG.md](https://github.com/coz-a/agent-yadogae/blob/main/CHANGELOG.md).

## License

MIT. See [LICENSE](https://github.com/coz-a/agent-yadogae/blob/main/LICENSE).
