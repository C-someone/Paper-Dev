# 监听清单热更新设计

生成日期：2026-07-16

目标：让 PaperWatcher 在后台长期运行时，可以发现 `config/sources.yaml`、`config/users.yaml`、`config/venues.yaml` 等监听清单变化，并在不中断进程或低成本重载的情况下应用变更。

---

## 1. 业务定位

PaperWatcher 的主监听对象是：

```text
CCF-A/B 期刊
CCF-A/B 会议
会议 accepted papers / program / proceedings 页面
DBLP / OpenReview / 出版社 RSS / TOC Alert
```

arXiv 类来源只作为早期线索和低等级记录源：

```text
arXiv 可以抓取、记录、检索。
arXiv 默认不进入前台推送。
arXiv 不作为高质量正式来源本身。
```

当前配置中通过字段表达：

```yaml
notification_policy: record_only
priority: 1
source_type: arxiv
```

TODO：arXiv 类来源后续按“发布者所属科研团队 / 实验室 / 企业研究组织”进行记录和分组。例如将论文作者单位或作者主页解析为：

```text
university_lab
company_research
security_vendor
independent
unknown
```

该信息只作为记录、检索、趋势观察和后续评分信号，不直接替代 CCF/venue 白名单。

---

## 2. 热更新范围

需要支持热更新的文件：

```text
config/sources.yaml
config/users.yaml
config/venues.yaml
config/keywords.yaml
config/scoring.yaml
config/report.yaml
config/settings.yaml 的非路径类运行参数
```

第一阶段重点：

```text
sources.yaml
users.yaml
```

原因：

```text
sources.yaml 决定监听哪些来源。
users.yaml 决定哪些用户订阅哪些来源。
```

---

## 3. 热更新基本策略

后台长期运行时维护一个 `ConfigSnapshot`：

```text
config_dir
loaded_at
fingerprint
AppConfig
source_id set
user_id set
```

每个后台循环开始前执行：

```text
1. 计算配置文件 fingerprint。
2. 如果 fingerprint 未变化，继续使用内存中的 AppConfig。
3. 如果 fingerprint 变化，重新 load_config。
4. 校验新配置。
5. 校验通过后原子替换内存中的 AppConfig。
6. 记录 config_reload 事件。
7. 校验失败则继续使用旧配置，并记录错误。
```

fingerprint 建议使用：

```text
每个 YAML 文件的 path + mtime_ns + size
```

后续如果需要更强一致性，再改为内容 hash。

---

## 4. 原子性和失败策略

热更新必须满足：

```text
坏配置不能破坏正在运行的后台。
坏配置不能清空已有 source_state。
坏配置不能导致用户 cursor 丢失。
```

因此采用“双缓冲”策略：

```text
old_config 正在服务
new_config 加载并校验
  成功 -> 替换 old_config
  失败 -> 保留 old_config
```

配置错误写入：

```text
state/config_reload_errors.jsonl
```

每条错误包含：

```json
{
  "seen_at": "...",
  "fingerprint": "...",
  "error": "..."
}
```

---

## 5. sources.yaml 变化处理

### 5.1 新增 source

新增 source 后：

```text
1. 后台下一轮发现 fingerprint 变化。
2. 加载新 source。
3. 如果有用户订阅该 source，后台开始扫描。
4. 对 RSS/arXiv 类 source，首次成功扫描只建立 baseline。
5. baseline 之后的新 item 才写入 events。
```

这样可以避免新增一个长期存在的 RSS feed 时，把历史条目一次性推给用户。

### 5.2 删除 source

删除 source 后：

```text
1. 后台不再扫描该 source。
2. source_state 保留，不立即删除。
3. events.jsonl 历史事件保留。
```

保留状态的原因：

```text
误删后重新加入时可以恢复增量状态。
历史事件仍可用于审计。
```

后续增加清理命令：

```bash
paperwatcher maintenance prune-source-state --source <id>
```

### 5.3 修改 source

修改 source 时按字段分类：

```text
name/priority/tags/notification_policy:
  立即生效，不重置 baseline。

feed_url/watch_url/venue_key/openreview_venue_id:
  视为来源身份变化，需要重建 baseline。
```

为此 source_state 中应保存：

```json
{
  "source_signature": "hash(source_type + feed_url + venue_key + watch_url + openreview_venue_id)"
}
```

如果 signature 变化：

```text
清空该 source 的 known_paper_ids 或另存旧状态
下一次成功扫描重新建立 baseline
```

---

## 6. users.yaml 变化处理

### 6.1 新增用户

新增用户后：

```text
1. 后台下一轮扫描会把该用户订阅的 source 纳入全局订阅并集。
2. 前台可以立刻用该 user_id pull。
3. 该用户首次 pull 时，只能看到其 cursor 之后、且 source_id 属于其订阅集合的事件。
```

为了避免新用户收到大量历史消息，建议新增用户时自动初始化 cursor：

```text
last_pulled_at = config reload time
```

也可以提供显式选项：

```yaml
initial_cursor: beginning | now
```

第一阶段默认：

```text
now
```

### 6.2 删除用户

删除用户后：

```text
1. 前台拒绝该 user_id。
2. user_cursors.json 中该用户 cursor 暂时保留。
3. 后续 maintenance 命令清理。
```

### 6.3 修改订阅

用户新增订阅：

```text
从下一轮后台扫描开始，新增事件会匹配该用户。
不回放该 source 的历史事件，除非显式请求。
```

用户取消订阅：

```text
新事件不再匹配该用户。
历史事件不删除。
```

---

## 7. notification_policy

每个 source 支持：

```yaml
notification_policy: notify       # 默认，写事件并匹配用户，前台可拉取
notification_policy: record_only  # 写事件但前台不推送
```

使用规则：

```text
CCF-A/B 期刊和会议：notify
debug_fake_rss：notify
arXiv：record_only
低质量或噪声较大的来源：record_only
```

`record_only` 的事件仍写入：

```text
state/events.jsonl
```

但前台按 source 配置过滤，不会把该 source 的事件返回给用户。兼容字段中通常保持：

```json
"matched_users": []
```

这保证“记录”和“推送”解耦。

---

## 8. 后台循环中的热更新伪代码

```python
snapshot = load_config_snapshot(config_dir)

while True:
    candidate = maybe_reload_config(config_dir, snapshot)
    if candidate.ok:
        snapshot = candidate.snapshot
    else:
        log_reload_error(candidate.error)

    run_background_once(snapshot.config)
    sleep(rss_interval)
```

对每日任务：

```python
if daily_window_reached:
    run_daily_non_rss_scan(snapshot.config)
```

---

## 9. 推荐 CLI

查看当前配置摘要：

```bash
paperwatcher config status
```

手动验证并热重载：

```bash
paperwatcher config reload
```

后台自动热更新：

```bash
paperwatcher background --loop --watch-config
```

测试新增源：

```bash
paperwatcher background --once --source <source_id>
```

---

## 10. 第一阶段实现任务

1. 增加 `notification_policy` 字段。
2. arXiv 配置设为 `record_only` 和低 priority。
3. 后台写事件时支持 record-only。
4. 增加 `ConfigSnapshot` 和 fingerprint。
5. 增加后台 loop 的 `--watch-config`。
6. 增加配置 reload 错误日志。
7. 增加用户新增时 cursor 初始化策略。
