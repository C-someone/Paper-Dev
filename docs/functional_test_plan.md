# PaperWatcher 功能测试文档

生成日期：2026-07-16

本文档用于验证当前阶段的用户库、后台文件事件流、调试注入、伪 RSS、前台多种读取方式。

---

## 1. 测试目标

验证以下需求：

1. `debug_user` 是内置必备测试用户。
2. 测试不只支持 `debug_user`，也支持普通用户，例如 `default`。
3. 后台记录从后台启动/首次扫描时建立基线，首次扫描不推送太早的历史内容。
4. 独立调试程序可以触发专用 debug 端口。
5. 独立调试程序也可以触发其他流程，例如伪造 RSS。
6. 前台支持多种读取方式：
   - 正常读取并推进 cursor
   - `--peek` 只读不推进 cursor
   - `--limit` 限制返回条数
   - `--format json` 输出 JSON
   - `--source` 按来源过滤
   - `--since` 按时间读取
   - `foreground cursor --reset` 重置用户 cursor

---

## 2. 测试环境准备

为了不污染真实运行状态，功能测试应使用临时配置目录和临时 state 目录。

示例：

```bash
rm -rf /tmp/paperwatcher-functional-config /tmp/paperwatcher-functional-state
cp -r config /tmp/paperwatcher-functional-config
python3 - <<'PY'
from pathlib import Path
path = Path('/tmp/paperwatcher-functional-config/settings.yaml')
text = path.read_text(encoding='utf-8')
text = text.replace('state_dir: state', 'state_dir: /tmp/paperwatcher-functional-state')
path.write_text(text, encoding='utf-8')
PY
```

后续命令统一追加：

```bash
--config-dir /tmp/paperwatcher-functional-config
```

---

## 3. 配置校验测试

命令：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config validate-config
```

期望：

```text
Configuration is valid.
Sources: 16 total, 14 enabled
Venues: 2
Users: 3
```

验证点：

- `debug_user` 存在。
- `root` 存在，并订阅当前开发阶段的全量监听清单。
- `default` 也存在。
- `debug_fake_rss` 存在但默认禁用。

---

## 4. Debug 端口注入测试

启动后台调试端口：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config debug-server --port 8765
```

另一个终端发送事件到 `debug_fake_rss` 源。前台是否读到它由用户订阅决定：

```bash
python3 scripts/send_debug_update.py debug-event \
  --url http://127.0.0.1:8765/debug/update \
  --source-id debug_fake_rss \
  --title "Functional Debug Event" \
  --link "https://example.com/functional-debug" \
  --paper-id functional_debug_001
```

期望：

```json
{"ok": true, "event_id": "...", "source_id": "debug_fake_rss"}
```

拉取：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config foreground pull --user debug_user --source debug_fake_rss --limit 1
```

期望包含：

```text
Functional Debug Event
https://example.com/functional-debug
```

---

## 5. 非 debug_user 调试测试

发送事件到普通用户 `default` 已订阅的 `dblp_ccs` 源：

```bash
python3 scripts/send_debug_update.py debug-event \
  --url http://127.0.0.1:8765/debug/update \
  --source-id dblp_ccs \
  --title "Functional Default Event" \
  --link "https://example.com/functional-default" \
  --paper-id functional_default_001
```

拉取：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config foreground pull --user default --source dblp_ccs --limit 1
```

期望包含：

```text
Functional Default Event
```

验证点：

- 调试能力不只绑定 `debug_user`；只要事件 source_id 属于某用户订阅集合，该用户即可读取。

---

## 6. 前台读取方式测试

### 6.1 peek 不推进 cursor

命令连续执行两次：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config foreground pull --user debug_user --source debug_fake_rss --peek --limit 1
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config foreground pull --user debug_user --source debug_fake_rss --peek --limit 1
```

期望：

两次都能看到同一条未读事件。

### 6.2 JSON 输出

命令：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config foreground pull --user debug_user --source debug_fake_rss --peek --format json --limit 1
```

期望：

输出 JSON，并包含：

```json
"count": 1
```

### 6.3 reset cursor

命令：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config foreground cursor --user debug_user --reset
```

期望：

```text
Cursor reset for debug_user.
```

---

## 7. 伪 RSS 流程测试

启动伪 RSS，建立第一条历史内容：

```bash
python3 scripts/send_debug_update.py fake-rss \
  --port 8766 \
  --title "Functional Fake RSS Baseline" \
  --link "https://example.com/fake-baseline" \
  --guid fake-baseline-001
```

另一个终端运行后台：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config background --once --source debug_fake_rss --include-disabled
```

期望：

```text
Background scanned sources: 1
New events: 0
Errors: 0
```

验证点：

- 首次扫描只建立基线，不推送早于后台启动的历史内容。

停止伪 RSS，重新启动新内容：

```bash
python3 scripts/send_debug_update.py fake-rss \
  --port 8766 \
  --title "Functional Fake RSS New Paper" \
  --link "https://example.com/fake-new" \
  --guid fake-new-001
```

再次运行后台：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config background --once --source debug_fake_rss --include-disabled
```

期望：

```text
Background scanned sources: 1
New events: 1
Errors: 0
```

拉取：

```bash
python3 -m paper_watcher.main --config-dir /tmp/paperwatcher-functional-config foreground pull --user debug_user --source debug_fake_rss --limit 1
```

期望包含：

```text
Functional Fake RSS New Paper
https://example.com/fake-new
```

---

## 8. 单元测试

命令：

```bash
python3 -m pytest
```

期望：

全部通过。
