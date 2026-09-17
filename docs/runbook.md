# Runbook：investment-ai 运维手册

> 一页纸原则：日常操作、部署升级、故障排查、数据运维。所有命令在项目根 `/Users/bjhl/IdeaProjects/learn-project/investment-ai` 下执行（`.venv/bin/python`）。

---

## 1. 系统概览

```text
每天 09:00 / 22:00（launchd）
  → 采集财联社+东财快讯（26h 回看窗口）
  → L0 关键词过滤 → 去重入库（MySQL: investment_ai）
  → L1 分类分级（deepseek-flash）→ P0/P1 深度分析（deepseek-chat）
  → 日报写入 vault → 晚间运行将日报刷新为全天版
```

| 资产 | 位置 |
|------|------|
| 代码 | `/Users/bjhl/IdeaProjects/learn-project/investment-ai`（git 管理，一 TASK 一提交） |
| 生产库 | 阿里云 RDS 实例 · `investment_ai` 库（7 表，Alembic 管理） |
| 测试库 | 同实例 · `investment_ai_test` 库（pytest 自动使用，可随时 DROP 重建） |
| 凭证 | 项目根 `.env`（DB_* + LLM_API_KEY/LLM_BASE_URL，不入 git） |
| Obsidian vault | `/Users/bjhl/GitRepository/Investment-KB`（可 git 管理） |
| 日志 | `logs/YYYY-MM-DD.jsonl`（结构化，run_id 贯穿）+ `logs/daily-launchd.log`（调度输出） |
| 调度 | launchd `com.investment-ai.daily`（每天 09:00/22:00，带 --force） |

## 2. 日常操作

```bash
# 查看最近运行（状态/成本/事件数）
.venv/bin/python main.py status --days 7

# 看某条事件的完整分析（含溯源与 JSON 结果）
.venv/bin/python main.py event <event_id>

# 手动补跑（当天已成功会 skip；--force 穿透，靠 UNIQUE 缓存零重复）
.venv/bin/python main.py daily --force

# Thesis 一览 / 种子导入
.venv/bin/python main.py thesis list

# 今晚的日报
open /Users/bjhl/GitRepository/Investment-KB/Daily/$(date +%F).md
```

## 3. 部署与升级

**首次部署**（已在 2026-09-17 完成，此处留档）：

```bash
uv venv && uv pip install -e ".[dev]"
cp .env.example .env          # 填 DB_* 与 LLM_API_KEY
DB_NAME=investment_ai .venv/bin/alembic upgrade head   # 建表
.venv/bin/python main.py thesis seed                    # 导入 4 条 Thesis 种子
bash scripts/install_launchd.sh                         # 安装调度
```

**拉取代码更新后**：

```bash
uv pip install -e ".[dev]"                              # 依赖变更时
DB_NAME=investment_ai .venv/bin/alembic upgrade head    # 有新迁移时
.venv/bin/pytest                                        # 回归（134 个，约 95s，需可达测试库）
bash scripts/install_launchd.sh                         # plist 变更时重装（幂等）
```

**配置调整**（不重启任何服务，CLI 进程每次冷启动读最新配置）：

| 要改什么 | 改哪里 |
|---------|--------|
| 行业关键词（L0 过滤） | `config/sectors.yaml` |
| 模型/温度/max_tokens/价格 | `config/settings.yaml`（`llm.tiers` / `llm.prices`） |
| 日成本熔断线（默认 ¥10） | `config/settings.yaml`（`llm.daily_budget_cny`） |
| 采集窗口/分类批量 | `config/settings.yaml`（`pipeline.*`） |
| API Key / DB 凭证 | `.env` |

**回滚**：`git log` 找上一个提交 → `git checkout <hash> -- app/ config/` → 重装 launchd（若 plist 变更）。数据库迁移回滚用 `alembic downgrade -1`（谨慎：V0.1 只有初始迁移，downgrade 会删表）。

## 4. 故障排查（对照已实现的失败语义）

| 现象 | 含义与处置 |
|------|-----------|
| run 状态 `skipped` | 当天已成功且非 force——正常幂等行为，非故障 |
| run 状态 `partial` + `degraded_sources` 非空 | 某数据源失败已降级（如财联社接口变更）。看 `logs/*.jsonl` 中该 provider 的 warning；接口失效去修对应 `app/providers/news/*.py`（参照本机 a-stock-data skill 的最新实现） |
| run 状态 `db_unreachable` | RDS 不可达（维护窗口/网络）。无需处理，下次触发自动重跑，幂等保证零重复 |
| 日报缺失 + `report_error` in stats | vault 写入失败（目录被占用/iCloud 锁）。DB 数据完好，修复目录后 `main.py daily --force` 或次日自动补 |
| `budget_hit: true` | 当日 LLM 成本超熔断线，深度分析顺延次日。频繁触发则调高 `daily_budget_cny` 或检查是否有异常重复输入 |
| `parse_errors` > 0 | LLM 输出两次未过 Schema，事件终态 `parse_error` 留档。偶发可忽略；批量出现通常是 prompt/模型变更，修 `prompts/*.md` 后 bump 版本号（`_v2.md`）即可重分析（UNIQUE 键含 prompt_version） |
| launchd 没跑 | `launchctl list \| grep investment-ai` 查退出码；`log show --last 1h --predicate 'process == "launchd"'`；Mac 睡眠错过会在唤醒后补跑 |
| 进程 hang | watchdog 30 分钟强退（exit 99），launchd 60s 后重启一次；连续出现查 `logs/daily-launchd.log` 尾部 |
| 通知弹窗"partial/failed" | 对应上表逐项排查，`main.py status` 看详情 |

**重刷历史分析**：分析结果缓存的幂等键是 `(event, strategy, prompt_version)`——改完 Prompt 存为新版本文件（如 `event_analysis_v2.md`）并更新 `strategies.py` 引用，旧分析保留可对比，新事件自动用新版，重跑 `daily --force` 后未分析事件走新版。

## 5. 数据库运维

```bash
# 迁移状态
DB_NAME=investment_ai .venv/bin/alembic current

# 重建测试库（测试异常时）
.venv/bin/python -c "import pymysql, os; from dotenv import dotenv_values; e=dotenv_values('.env'); \
c=pymysql.connect(host=e['DB_HOST'],port=int(e['DB_PORT']),user=e['DB_USER'],password=e['DB_PASSWORD']); \
cur=c.cursor(); cur.execute('DROP DATABASE IF EXISTS investment_ai_test'); \
cur.execute('CREATE DATABASE investment_ai_test CHARACTER SET utf8mb4'); print('OK')"

# 备份：RDS 云快照（运维层承接，应用不管）；自留冷备可 mysqldump investment_ai > backup.sql

# 清理：events 按 published_at 滚动（V0.1 无自动清理，量级 ~150 条/天，一年 5 万行，暂不需要）
```

## 6. 成本监控

- 单次运行成本在执行报告 `estimated_cost_cny`（正常 ~¥0.5~1.5/天，两次运行翻倍但共享缓存）
- 月度汇总：`SELECT DATE(started_at) d, SUM(JSON_EXTRACT(stats_json,'$.estimated_cost_cny')) c FROM runs GROUP BY d ORDER BY d DESC LIMIT 30;`
- 熔断线 ¥10/天在 `settings.yaml`；分析行级成本在 `analyses.cost_cny`

## 7. 观察期验收（进行中）

- [ ] 2026-09-17 晚 22:00 首次双时段运行
- [ ] 连续 3 天（至 2026-09-20）09:00/22:00 全部 success（degraded 可接受但须出现在报告中）
- [ ] 通过后：V0.1 正式验收，V0.2（Thesis Review 闭环）立项
