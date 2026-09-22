# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until 1.0, a minor version may change
behaviour.

## [Unreleased]

### Added

- Support for OpenCode: repoints `project.worktree`, `project_directory.directory`,
  `worktree.directory`, and `session`/`session_v2` `directory`/`path` in `~/.local/share/opencode/opencode.db`
  (default location follows `XDG_DATA_HOME` when set), so `opencode --continue`/`-c` still finds the old
  sessions. Unlike the other three agents, OpenCode keeps everything in one SQLite database keyed by a
  project id that has nothing to do with the path, so nothing on disk needs renaming.
- An `opencode` process running under the source or destination is now detected the same way Codex and
  agy are, and stops the move with exit code 2.
- `~/.local/share/opencode` is now included in the agent-data guard that refuses to move into, out of,
  or over an agent's own data.

## [0.1.1] - 2026-09-13

Documentation only; the tool behaves exactly as in 0.1.0.

### Added

- This changelog.
- A Japanese README, `README.ja.md`.
- README: a quick start with a sample session, running it without installing (`uvx`, or piped straight
  from GitHub), uninstalling, where backups are kept and how to find them, and the environment
  variables it honours.
- The source distribution now includes `README.ja.md` and `CHANGELOG.md`, and the PyPI page links to
  the changelog.

### Changed

- The README is now in English.
- README: the list of refusals now matches the checks the tool makes, and the descriptions of undo,
  backups and file writes say exactly what they cover.
- Publishing to PyPI now waits for approval through the `pypi` GitHub environment.

## [0.1.0] - 2026-09-13

First release.

### Added

- Move a project directory and repoint what Claude Code, Codex and the Antigravity CLI (`agy`) index
  by its path, so `claude --continue`, `codex resume` and `agy -c` still find the old conversations.
  - Claude Code: the history folder under `~/.claude/projects/`, `projects` in `~/.claude.json`, and
    `~/.claude/history.jsonl`.
  - Codex: the `cwd` in rollout files, `threads.cwd` and `project_roots.path` in `state_<n>.sqlite`,
    and `[projects."<path>"]` in `config.toml`.
  - agy: `cache/last_conversations.json`, `trustedWorkspaces` in `settings.json`, and `history.jsonl`.
- Sessions started in a subdirectory of the project, Claude Code worktrees included, move with it.
- Checks that run before any change and refuse, among others: a symbolic link as source or destination,
  one side inside the other, either side containing the home directory or agent data, a move across
  filesystems, a merge with conflicting files, a Claude Code history folder name shared with another
  project, and any platform other than Linux.
- Stops with exit code 2 while a Claude Code, Codex or agy session is running under the source or the
  destination.
- Asks for confirmation after showing the plan when run from a terminal; `--yes` skips it and is
  required otherwise. `--dry-run` prints the plan only.
- Backs up the config, history and SQLite files it edits, never with a wider mode than the original.
- A failed step exits with code 1 and says how to finish with `--state-only`; a move into a new
  destination can be reversed by running the tool in the other direction.
- `--merge` folds the project into an existing destination; `--ignore-running` skips the running-session
  check.
- Python 3.8 or later, no dependencies, a single module.

[Unreleased]: https://github.com/coz-a/agent-yadogae/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/coz-a/agent-yadogae/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/coz-a/agent-yadogae/releases/tag/v0.1.0
