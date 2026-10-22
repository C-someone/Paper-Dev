# 可插拔本地 SQL 索引 / Pluggable Local SQL Index

生成日期：2026-07-17

本项目采用“文件为真、SQLite 为可插拔索引”的策略。

This project uses a "files are the source of truth, SQLite is a pluggable index" strategy.

---

## 1. 为什么不用外部 SQL 服务 / Why not an external SQL server

如果把后台索引直接绑定到 PostgreSQL、MySQL 或类似服务，目标设备在迁移时通常需要额外安装、部署、初始化和运维数据库。

If the backend index is bound directly to PostgreSQL, MySQL, or a similar service, the target device usually needs extra installation, deployment, initialization, and operational work.

本项目当前不需要这一层复杂度。

This project does not need that level of complexity right now.

更合适的方案是：

The better option is:

```text
核心状态仍然写文件。
The core state still lives in files.

SQLite 只作为本地索引层。
SQLite acts only as a local index layer.

索引可以随时从文件重建。
The index can be rebuilt from files at any time.
```

这里的 SQLite 是 Python 自带 `sqlite3` 模块使用的嵌入式数据库，不是需要单独安装和运行的数据库服务。

The SQLite used here is the embedded database exposed by Python's built-in `sqlite3` module. It is not a separate database service that must be installed and run.

---

## 2. 真相源与派生层 / Source of Truth and Derived Layer

文件后端继续保存真实状态：

The file backend continues to store the real state:

```text
state/events.jsonl
state/source_state.json
state/user_cursors.json
state/source_verification.json
```

SQLite 索引只保存这些文件的镜像视图，便于：

SQLite index only mirrors these files, which helps with:

```text
快速查询
Quick lookup

未来替换前端读取方式
Future replacement of foreground read paths

迁移到其他 SQL 方言
Potential migration to another SQL dialect
```

如果索引损坏、丢失或需要迁移，只要文件还在，就可以重新生成。

If the index is damaged, missing, or needs migration, it can be regenerated as long as the files remain.

---

## 3. 索引内容 / What the Index Stores

当前索引数据库默认使用 `config/settings.yaml` 中的 `database.path`。

The index database currently defaults to `database.path` in `config/settings.yaml`.

索引保存：

The index stores:

```text
事件镜像 / Event mirror
来源状态镜像 / Source-state mirror
用户 cursor 镜像 / User-cursor mirror
来源验证结果镜像 / Source-verification mirror
同步元数据 / Sync metadata
```

它不是业务真相源，也不替代后台文件写入。

It is not the business source of truth and does not replace the file writes in the background pipeline.

---

## 4. 同步方式 / Sync Method

通过命令将文件状态重建进 SQLite：

Rebuild the SQLite index from file state with:

```bash
python3 -m paper_watcher.main index sync
```

同步时会读取：

During sync, the system reads:

```text
state/events.jsonl
state/source_state.json
state/user_cursors.json
state/source_verification.json
```

然后覆盖写入索引表。

Then it overwrites the corresponding index tables.

这个操作可以：

This operation can:

```text
后台定时执行 / Run on a schedule
在部署后执行一次 / Run once after deployment
在迁移或故障恢复时执行 / Run during migration or recovery
```

---

## 5. 查询方式 / Query Method

可通过命令检查索引状态：

Check index status with:

```bash
python3 -m paper_watcher.main index status
```

未来若前端需要更快的读取路径，可以直接从 SQLite 索引读取，不必解析大体量 JSONL。

In the future, if the foreground needs faster reads, it can query the SQLite index directly instead of parsing large JSONL files.

---

## 6. 迁移边界 / Migration Boundary

当前实现承诺的是：

What the current implementation guarantees:

```text
不需要额外安装数据库服务。
No extra database service is required.

索引可重建。
The index is rebuildable.

文件状态始终可作为最终恢复来源。
File state always remains the final recovery source.
```

未来如果真的需要 PostgreSQL，只是把“索引实现”替换成另一种后端，不会改变文件真相源的原则。

If PostgreSQL is ever needed later, only the index implementation changes; the file-truth principle stays the same.
