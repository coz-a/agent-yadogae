[English](https://github.com/coz-a/agent-yadogae/blob/main/README.md) | 日本語

# agent-yadogae

プロジェクトのディレクトリを移動し、Claude Code・Codex CLI・Antigravity CLI・OpenCode がそのプロジェクト
について残した記録を一緒に連れていきます。移動先でもそのまま会話を再開できます。

> **非公式ツールです。** Anthropic・OpenAI・Google・OpenCode プロジェクトとは関係がありません。
> Claude Code・Codex・Antigravity・OpenCode がそれぞれ内部で使っている、公開も保証もされていない保存形式
> に依存しており、エージェントの更新で動かなくなることがあります。MIT ライセンスのもと無保証で提供します。
> Claude Code・Codex・Antigravity・OpenCode は各社の商標です。

## クイックスタート

そのプロジェクトで開いている Claude Code・Codex・agy・OpenCode のセッションを閉じてから実行します。
[uv](https://docs.astral.sh/uv/) があればインストール不要です。

```bash
uvx agent-yadogae ~/workspace/oldname ~/workspace/newname
```

何をするかを表示し、変更の前に確認します。

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
== OpenCode: no ~/.local/share/opencode; skipped

move /home/you/workspace/oldname -> /home/you/workspace/newname and carry the above? [y/N] y
[... 同じ手順が実際に実行されます ...]

moved: /home/you/workspace/oldname -> /home/you/workspace/newname
open the new directory and run `claude --continue`, `codex resume`, `agy -c` or `opencode --continue` to confirm.
to undo: agent-yadogae /home/you/workspace/newname /home/you/workspace/oldname
```

確認なしで計画だけ見たいときは `--dry-run` を付けます。

## インストール

依存なしの Python 3.8 以上、Linux のみです。

```bash
pipx install agent-yadogae        # または: uv tool install agent-yadogae
```

単一ファイルなので、`PATH` の通った場所に置くだけでも動きます。

```bash
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/coz-a/agent-yadogae/main/agent_yadogae.py \
  -o ~/.local/bin/agent-yadogae && chmod +x ~/.local/bin/agent-yadogae
```

Python だけで GitHub から直接実行することもできます。この場合スクリプトを標準入力から読むので確認の
プロンプトは出せません。先に計画を確認し、問題なければ `--yes` を付けて実行してください。

```bash
curl -fsSL https://raw.githubusercontent.com/coz-a/agent-yadogae/main/agent_yadogae.py \
  | python3 - ~/workspace/oldname ~/workspace/newname --dry-run
```

アンインストールは `pipx uninstall agent-yadogae` か `uv tool uninstall agent-yadogae`、またはファイルを
削除します。ツールが作った `.agent-yadogae.json` は残しておいてください
（[パス変換の検算](#パス変換の検算)を参照）。

## 対応エージェント

| エージェント | 検証したバージョン | `mv` だけだと |
|---|---|---|
| Claude Code | 2.1.268〜2.1.270 | `claude --continue` と `/resume` の一覧に出ない |
| Codex CLI | 0.153.4 | `codex resume` の一覧と `--last` に出ない |
| Antigravity CLI (`agy`) | 1.2.2 | `agy -c` が前の会話を見つけられない |
| OpenCode | 2.0.11 | `opencode --continue`/`-c` が前のセッションを見つけられない |

Linux でのみ検証しています。Linux 以外では何も変更せず、終了コード 1 で拒否します。Gemini CLI は対象外です。

## なぜ要るのか

4つのエージェントはどれも、会話を**実行したディレクトリの絶対パス**で索引しています。たとえば
Claude Code はパスの英数字以外をすべて `-` に置換した名前のフォルダを `~/.claude/projects/` に作り、
transcript も自動メモリもそこに入れます（200文字を超える名前は切り詰めてハッシュを付けます）。

```
/home/you/workspace/oldname
  → ~/.claude/projects/-home-you-workspace-oldname/
```

フォルダ名を変えると索引キーが変わるので、移動先では通常の再開コマンドやセッション一覧から過去の会話が
見つからなくなります。**データは消えません。古いキーの下に取り残される**だけです。`mv` は何も言わずに
これをやります。

## 何を運ぶか

各エージェントの resume が実際に読んでいる記録を書き換えます。

| | 中身 |
|---|---|
| `~/.claude/projects/<encoded>/` | transcript、サブエージェントのログ、tool-results、`memory/`（自動メモリ） |
| `~/.claude.json` の `projects[パス]` | 信頼ダイアログの承認、`allowedTools`、MCP 設定 |
| `~/.claude/history.jsonl` の `"project"` | プロンプト履歴 |
| `~/.codex/sessions/**/rollout-*.jsonl` の `cwd` | **`codex resume` の絞り込みが見ているのはここ** |
| `~/.codex/state_<n>.sqlite` の `threads.cwd`, `project_roots.path` | スレッド索引 |
| `~/.codex/config.toml` の `[projects."<パス>"]` | 信頼設定 |
| `~/.gemini/antigravity-cli/cache/last_conversations.json` | パス → 会話 ID。**`agy -c` が見ているのはここ** |
| `~/.gemini/antigravity-cli/settings.json` の `trustedWorkspaces` | 信頼済みワークスペース |
| `~/.gemini/antigravity-cli/history.jsonl` の `"workspace"` | プロンプト履歴 |
| `~/.local/share/opencode/opencode.db` の `project.worktree` | **`opencode --continue` が見ているのはここ** |
| 同じデータベースの `project_directory.directory`、`worktree.directory` | worktree・git-worktree のルート |
| 同じデータベースの `session.directory`/`.path`、`session_v2.directory`/`.path` | セッションごとの作業ディレクトリ |

上の場所は既定値です。`CLAUDE_CONFIG_DIR` と `CODEX_HOME` が設定されていればそちらを使います。agy の
保存先は常に `~/.gemini/antigravity-cli` で、OpenCode の保存先は設定されていれば `XDG_DATA_HOME`
（既定は `~/.local/share`）に従います。

プロジェクトの**サブディレクトリで始めたセッションも一緒に移ります**。Claude Code の worktree
（`.claude/worktrees/…`）の履歴フォルダも含め、`SRC/sub` は `DST/sub` になります。ただしサブディレクトリの
履歴フォルダのうち、transcript が残っておらずプロジェクトのものと判断できないものは移さず、
`left <name> where it is` と表示します。

Codex は SQLite の `threads.cwd` を直すだけでは戻らず、rollout 側の `cwd` まで書き換えて初めて移動先の
`codex resume` がセッションを拾います。agy は `last_conversations.json` のキーを付け替えれば `agy -c` が
会話を復元します。

他の3つと違い、**OpenCode はすべてを1つの SQLite データベースにまとめて**おり、プロジェクト ID はパスと
無関係です。そのため `~/.local/share/opencode/` の下（`shell/`、`snapshot/`、`tool-output/`）は移動しても
何もリネームされず、変わるのは上記のパス値カラムだけです。

## 使い方

```
agent-yadogae SRC DST [-n] [-y] [--state-only] [--merge] [--ignore-running] [-q] [--version]

  -n, --dry-run       計画だけ表示して何も変更しない
  -y, --yes           確認せずに実行する
      --state-only    ディレクトリを自分で移動した後、エージェントの記録だけ更新する
                      （SRC が存在せず、DST がディレクトリである必要があります）
      --merge         既に存在する DST へプロジェクトを合流させる
      --ignore-running  エージェントが動いていても実行する
  -q, --quiet         問題だけ報告する
      --version       バージョンを表示して終了する
```

`--yes` なしの場合、標準入力と標準出力がどちらも端末なら計画を表示して `[y/N]` で確認します。それ以外
（スクリプト、CI、パイプ）では終了コード 1 で拒否します。`--dry-run` で計画を確認してから `--yes` を付けて
実行してください。

終了コードは、成功が 0、拒否・確認で中止・途中の失敗が 1、SRC か DST の下でエージェントのセッションが
動いているときが 2 です。

## 安全のしくみ

### 変更前の検査

以下の検査は変更を始める前に行います。ひとつでも引っかかれば終了コード 1 で終了し、何も変更しません。

パスと環境:

- Linux 以外
- SRC か DST がシンボリックリンク、SRC と DST が同じディレクトリ、または一方がもう一方の中にある
- SRC か DST がホームディレクトリを含む、またはエージェントのデータ（`~/.claude`、`~/.claude.json`、
  `~/.codex`、`~/.gemini`、`~/.local/share/opencode`）の中にある・それを含む
- SRC がディレクトリでない、DST の親ディレクトリが無い、または SRC と DST が**別のファイルシステム**にある
  （移動がコピーと削除になり、途中で止まると戻せないため）

移動先:

- DST が既にあり、`--merge` が指定されていない
- `--merge` のとき、両側に内容の違う同名ファイルがある
- `--state-only` のとき、SRC がまだ存在する、または DST がディレクトリでない

Claude Code の履歴:

- パス変換規則が既存の履歴フォルダ名を再現できない（[パス変換の検算](#パス変換の検算)を参照）
- 運ぶ履歴フォルダを、移動に含まれない別のプロジェクトも使っている。たとえば `/w/a_b` と `/w/a-b` は
  どちらも `-w-a-b` になり、`memory/` も共有されます。transcript が残っていないフォルダは Claude Code
  自身の記録（`~/.claude.json` とプロンプト履歴）で判断し、記録が読めなければ拒否します
- DST の履歴フォルダ名が既に別のプロジェクトのものである、またはそのフォルダが既にあってどのプロジェクトの
  ものか分からない
- 運ぶ2つのフォルダが同じ名前になる、移動先の名前が同じ移動で動く別のフォルダの名前と重なる、または
  内容の違うファイルを合流させる必要がある（`memory/MEMORY.md` など）

### 動いているセッション

**そのプロジェクトで Claude Code・Codex・agy・OpenCode を閉じてから実行してください。** 開いたままだと
セッションは古いパスの下に書き込み続け、その書き込みは古いパスに残ったり、移動と競合したりします。
Claude Code は `~/.claude/sessions/*.json` の `cwd` と生存 PID を突き合わせ、Codex・agy・OpenCode は
`/proc` から作業ディレクトリが SRC か DST の下にある `codex` / `agy` / `opencode` プロセスを探します。
見つかれば終了コード 2 で止まります（`opencode serve --service` のような、作業ディレクトリが SRC・DST の
下にないグローバルな OpenCode のバックグラウンドサービスはこの方法では検出できません）。

### バックアップとファイルの書き込み

`~/.claude.json`、`~/.claude/history.jsonl`、Codex の `config.toml` と `state_<n>.sqlite`、agy の JSON と
JSONL、OpenCode の `opencode.db` は、編集する前に元のファイルと同じ場所へ `<name>.agent-yadogae-<timestamp>`
として複製します。バックアップは所有者だけが読める状態で作成し、その後で元のファイルと同じ権限にします。
数百MBになり得る Codex の rollout ファイルはバックアップしません。

**バックアップをツールが削除することはなく**、実行するたびに新しい組が増えます。移動の結果に問題が
なければ、次のコマンドで探して不要なものを削除してください。

```bash
find ~ -maxdepth 2 -name '*.agent-yadogae-*'; find ~/.gemini/antigravity-cli -name '*.agent-yadogae-*'
find ~/.local/share/opencode -maxdepth 1 -name '*.agent-yadogae-*'
```

テキストファイルは一時ファイルに書いてから置き換え、Codex と OpenCode のデータベースはそれぞれ1つの
トランザクションで更新するので、書きかけのファイルが残ることはありません。ただし移行全体は複数の手順の
組み合わせで、1回の不可分な操作ではありません。

### 途中で失敗したとき

終了コード 1 で、何が失敗したかと次の手を表示します。プロジェクトのディレクトリの移動が済んでいれば、
原因を直して `agent-yadogae SRC DST --state-only` を実行すると残りを運びます。済んだ手順には何もしません。

### 元に戻す

**新しい移動先への移動は、逆向きに実行すれば元に戻せます。** 正確なコマンドは成功時の最後に表示されます。
`agent-yadogae DST SRC` はプロジェクトと記録を元の場所へ移し、通常と同じ検査を行います（Codex の rollout や
OpenCode のデータベースも含め、往復後にバイト単位で一致することをテストで確認しています）。
スナップショットからの復元ではなく逆向きの移動なので、その間に行った変更は残ります。

`--merge` を戻す用途には使わないでください。DST にあるものを、合流前からあったものも含めて SRC へ移します。

## やらないこと

**Claude Code の transcript の各行に埋め込まれた `"cwd"` は書き換えません。** 古いパスのまま残しても
`--continue` も `--resume` も正しく動くことを確認した上での判断です。直そうとすると数十MBの JSONL を
全部書き換えることになり、得るものがありません。

また、Gemini CLI と Linux 以外の環境には対応せず、Codex の rollout ファイルはバックアップせず、自分の
バックアップを片付けることもしません。

なお `claude --resume <session-id>` はプロジェクトに関係なく使えるので、移行しなくてもセッション ID
さえ分かればどこからでも復元できます。壊れるのは一覧のほうだけです。

## パス変換の検算

パス → フォルダ名の変換は Claude Code 本体の関数を移植したもので、Claude Code 2.1.270 と結果を照合して
います。それでも移動先の名前は計算するしかないので、実行前に**このマシン上のすべての履歴フォルダ名を規則で
再現できるか**を検算し、できなければ拒否します。Claude Code の更新で規則が変わっても、黙って間違った
フォルダを作らないためです。

フォルダは、transcript の `cwd` のうち少なくとも1つが自分の名前に変換されれば合格です（最初の1つだけを
見てはいけません。プロジェクト直下で始まって git worktree に入ったセッションは `cwd` を2つ記録し、
worktree 側の名前で保存されるためです）。

運んだ履歴フォルダには古いパスの `cwd` を持つ transcript が残るので、今どのパスのものかを記録した小さな
`.agent-yadogae.json` を置き、これも検算に使います。**このファイルは残しておいてください。** 無くなると、
フォルダ名と中身が合わなくなり次回の実行が拒否されます。逆向きに戻したときなど、フォルダの transcript
自身がそのパスを申告していれば、ツールがこのファイルを削除します。

## 名前について

宿替え＝住まいを替えること。替えるのは**エージェントの宿**で、そこに置いてある持ち物（会話の記録、
自動メモリ、そのプロジェクト用の設定）は当然ついてきます。`mv` との違いがそのまま名前になっています。

## テストと検証

```bash
python3 -m unittest discover -s test -v
```

テストは使い捨ての `HOME`・`CLAUDE_CONFIG_DIR`・`CODEX_HOME`・`XDG_DATA_HOME` と偽の `/proc` だけを使い、
実際のエージェントのデータには触れず、API も呼びません。`node` があれば、Claude Code から取り出した
パス変換関数を node で実行し、移植版と結果が一致することも確かめます。

実際のエージェントでの end-to-end 確認は 2026-09-13 に実施しています。目印のトークンを含むセッションを作り、
移動後に移動先で本物の `claude --continue`・`codex exec resume --last`・`agy -c` がトークンを復元すること、
逆向きに戻した後も Claude Code が復元することを確認しました。Codex は `mv` だけでも、SQLite の
`threads.cwd` を直すだけでも復元できず、rollout の `cwd` まで直すと復元しました。

OpenCode の対応は、実際に使われている `opencode.db` のコピー（本物のファイルは一切変更していません）に
対して付け替えロジックを実行し、クエリが実際のスキーマと合っていること、`worktree`/`directory` の
各カラムだけが正しく付け替わり他は変わらないことを確認する形で検証しました。他の3エージェントのような、
実際の `opencode --continue` を使った往復での確認はまだ行っていません。

## 変更履歴

[CHANGELOG.md](https://github.com/coz-a/agent-yadogae/blob/main/CHANGELOG.md)（英語）を参照してください。

## ライセンス

MIT。[LICENSE](https://github.com/coz-a/agent-yadogae/blob/main/LICENSE) を参照してください。
