[English](https://github.com/coz-a/agent-yadogae/blob/main/README.md) | 日本語

# agent-yadogae

エージェントの宿替え — プロジェクトフォルダを移動し、**コーディングエージェントがそのプロジェクトについて溜めた記録を連れていく**。

> **非公式ツールです。** Anthropic・OpenAI・Google とは関係がありません。Claude Code・Codex・Antigravity
> がそれぞれ内部で使っている、公開も保証もされていない保存形式に依存しており、エージェントの更新で
> 動かなくなることがあります。MIT ライセンスのもと無保証で提供します。Claude Code・Codex・Antigravity
> は各社の商標です。

```bash
agent-yadogae ~/workspace/oldname ~/workspace/newname
```

## インストール

依存なしの Python 3.8 以上、Linux のみです。

```bash
pipx install agent-yadogae        # または: uv tool install agent-yadogae
```

単一ファイルなので、そのまま置いても動きます。

```bash
curl -fsSL https://raw.githubusercontent.com/coz-a/agent-yadogae/main/agent_yadogae.py \
  -o ~/.local/bin/agent-yadogae && chmod +x ~/.local/bin/agent-yadogae
```

## 対応状況

| エージェント | 検証したバージョン | `mv` だけだと |
|---|---|---|
| Claude Code | 2.1.268〜2.1.270 | `claude --continue` と `/resume` の一覧に出ない |
| Codex CLI | 0.153.4 | `codex resume` の一覧と `--last` に出ない |
| Antigravity CLI (`agy`) | 1.2.2 | `agy -c` が前の会話を引けない |

Linux でのみ検証しています。macOS と Windows では何も変更せずに終了します。Gemini CLI は対象外です。

## なぜ要るのか

3つのエージェントはどれも、会話を**実行したディレクトリの絶対パス**で索引しています。たとえば
Claude Code はパスの英数字以外をすべて `-` に置換した名前のフォルダを `~/.claude/projects/` に作り、
transcript も自動メモリもそこに入れます（200文字を超える名前は切り詰めてハッシュを付けます）。

```
/home/you/workspace/oldname
  → ~/.claude/projects/-home-you-workspace-oldname/
```

フォルダ名を変えると索引キーが変わるので、どのエージェントも過去の会話を見つけられなくなります。
**データは消えません。古いキーの下に取り残される**だけです。`mv` は何も言わずにこれをやります。

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

プロジェクトの**サブディレクトリで始めたセッションも一緒に移ります**。Claude Code の worktree
（`.claude/worktrees/…`）の履歴フォルダも含め、`SRC/sub` は `DST/sub` になります。

Codex は SQLite の `threads.cwd` を直すだけでは戻らず、rollout 側の `cwd` まで書き換えて初めて
移動先の `codex resume` がセッションを拾うことを確認しています。agy は `last_conversations.json`
のキーを付け替えれば `agy -c` が会話を復元します。

## 使い方

```
agent-yadogae SRC DST [-n] [-y] [--state-only] [--merge] [--ignore-running] [-q]

  -n, --dry-run       計画だけ表示して何も変更しない
  -y, --yes           確認せずに実行する（端末以外から使うときは必須）
      --state-only    フォルダは移動済み。エージェントの記録だけ運ぶ
      --merge         既に存在する DST へプロジェクトを合流させる
      --ignore-running  エージェントが動いていても実行する
  -q, --quiet         問題だけ報告する
```

終了コードは、成功が 0、拒否・中止・途中の失敗が 1、エージェントが稼働中で止まったときが 2 です。

端末から実行すると、まず計画を表示してから `[y/N]` で確認します。

## 安全のための振る舞い

**変更を始める前に全部検査し、ひとつでも引っかかれば何も変えずに終了します。**

- 運ぶ Claude Code 履歴フォルダの名前を、**移動に含まれない別のプロジェクト**も使っているとき（`/w/a_b` と `/w/a-b` は同じ名前になり、`memory/` も共有されます）。transcript が残っていない場合は、Claude Code 自身の記録（`~/.claude.json` とプロンプト履歴）で見分け、記録が読めなければ拒否します
- DST の Claude Code 履歴フォルダ名が別のプロジェクトのものと重なるとき
- 合流する両側に、内容の違う同名ファイルがあるとき（`memory/MEMORY.md` など）
- SRC がシンボリックリンク、DST が SRC の中、SRC がホームディレクトリやエージェントのデータを含むとき
- SRC と DST が**別のファイルシステム**にあるとき（移動がコピーと削除になり、途中で止まると戻せないため）
- DST が既にある（`--merge` なし）、DST の親ディレクトリが無い
- Linux 以外

**そのプロジェクトで Claude Code・Codex・agy を閉じてから実行してください。** 開いたまま動かすと、
セッションが古い索引に書き足し続けて、その分が失われます。Claude Code は `~/.claude/sessions/*.json`
の `cwd` と生存 PID を突き合わせ、Codex と agy は `/proc` から作業ディレクトリが SRC か DST の下にある
`codex` / `agy` プロセスを探し、見つかれば終了コード 2 で止まります。

設定・履歴ファイルと Codex の SQLite は、触る前に `*.agent-yadogae-<timestamp>` としてバックアップします。
バックアップは作成の瞬間から所有者だけが読める状態で作り、元のファイルより広い権限にはしません。
ファイルは一時ファイルに書いてから置き換えるので、途中の状態が読まれることはありません。

**途中で失敗したとき**は終了コード 1 で、何が失敗したかと次の手を表示します。プロジェクト本体の移動が
済んでいれば、原因を直して `agent-yadogae SRC DST --state-only` を再実行すると残りを運びます
（済んだ部分には何もしません）。

**元に戻すには逆向きに実行します。** `agent-yadogae DST SRC` で、運んだ記録はすべて移動前と同じ内容に
戻ります（テストで往復後のバイト一致を確認しています）。Codex の rollout は数百MBになり得るので
バックアップしませんが、この往復で戻せます。

## やらないこと

**Claude Code の transcript の各行に埋め込まれた `"cwd"` は書き換えません。** 古いパスのまま残しても
`--continue` も `--resume` も正しく動くことを確認した上での判断です。直そうとすると数十MBの JSONL を
全部書き換えることになり、得るものがありません。

その代わり、運んだ履歴フォルダには `.agent-yadogae.json` を置き、そのフォルダが今どのパスのものかを
記録します。これが無いと、次に実行したとき「transcript の `cwd` とフォルダ名が合わない」ことを
パス変換規則の変化と見分けられません。逆向きに戻したときなど、フォルダの transcript 自身がそのパスを
申告していれば、`agent-yadogae` はこのファイルを置かない（あれば消す）ようにしています。

なお `claude --resume <session-id>` はプロジェクトに関係なく使えるので、移行しなくてもセッション ID
さえ分かればどこからでも復元できます。壊れるのは一覧のほうだけです。

## パス変換をなぜ検証するのか

Claude Code のパス → フォルダ名の変換は Claude Code 本体から取り出した実装をそのまま移植しています
（UTF-16 単位で置換するので、絵文字は `-` 2つになります）。それでも移動先の名前は計算するしかないので、
実行前に**このマシン上の全プロジェクトで規則が再現するかを検算**し、合わなければ何もせず終了します。
Claude Code の更新で規則が変わった場合に、黙って間違ったフォルダを作らないためです。

検算は「そのフォルダが申告する `cwd`（と `.agent-yadogae.json`）のうち少なくとも1つが自分の名前に
符号化されるか」で判定します。1つ目だけを見てはいけません — プロジェクト直下で始まって git worktree に
入ったセッションは `cwd` を2つ記録し、索引は worktree 側に付くからです。

## 名前について

宿替え＝住まいを替えること。替えるのは**エージェントの宿**で、そこに置いてある持ち物（会話の記録、
自動メモリ、そのプロジェクト用の設定）は当然ついてきます。`mv` との違いがそのまま名前になっています。

## テスト

```bash
python3 -m unittest discover -s test -v
```

使い捨ての `HOME`・`CLAUDE_CONFIG_DIR`・`CODEX_HOME` と偽の `/proc` だけを使い、実際のエージェントの
データには触れず、API も呼びません。`node` があれば、Claude Code から取り出したパス変換関数を node で
実行し、移植版と結果が一致することも確かめます。

実環境での end-to-end 確認は 2026-09-13 に実施しています。目印のトークンを含むセッションを作り、
移動後に移動先で本物の `claude --continue`・`codex exec resume --last`・`agy -c` がトークンを復元する
ことを確認しました。Codex は `mv` だけでも、SQLite の `threads.cwd` を直すだけでも復元できず、rollout の
`cwd` まで直すと復元しました。

## 変更履歴

[CHANGELOG.md](https://github.com/coz-a/agent-yadogae/blob/main/CHANGELOG.md)（英語）を参照してください。

## ライセンス

MIT。[LICENSE](https://github.com/coz-a/agent-yadogae/blob/main/LICENSE) を参照してください。
