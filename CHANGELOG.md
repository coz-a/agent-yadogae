# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until 1.0, a minor version may change
behaviour.

## [Unreleased]

### Added

- This changelog.
- A Japanese README, `README.ja.md`.

### Changed

- The README is now in English.
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
- Every refusal happens before the first change, among them: a Claude Code history folder name shared
  with another project, a merge with conflicting files, a symbolic link as the source, a destination
  inside the source, a source containing the home directory or agent data, a move across filesystems,
  and any platform other than Linux.
- Stops with exit code 2 while a Claude Code, Codex or agy session is running in the project.
- Asks for confirmation after showing the plan when run from a terminal; `--yes` skips it and is
  required otherwise. `--dry-run` prints the plan only.
- Backs up the config, history and SQLite files it edits, never with a wider mode than the original.
- A failed step exits with code 1 and says how to finish with `--state-only`; running the tool in the
  other direction undoes a move.
- `--merge` folds the project into an existing destination; `--ignore-running` skips the running-session
  check.
- Python 3.8 or later, no dependencies, a single module.

[Unreleased]: https://github.com/coz-a/agent-yadogae/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/coz-a/agent-yadogae/releases/tag/v0.1.0
