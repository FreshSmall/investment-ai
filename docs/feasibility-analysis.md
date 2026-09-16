# AI 投资研究系统：可行性分析报告

> Phase 1 产出 | 基于 `investment-ai-feasibility-analysis.md`（原始需求）的技术评审
> 日期：2026-09-17 | 状态：待老板确认后进入 Phase 2
>
> **变更记录**：
> - 2026-09-17 存储层决策变更：**SQLite → MySQL（独立库 `investment_ai`）**，复用 stock-platform 的阿里云 RDS 实例与连接方式（实例共享、库级隔离）。涉及 §1/§3/§4/§8/§9/§11/§12/§13/附录 B，均已同步修订。

---

## 目录

1. [总体结论](#1-总体结论)
2. [Phase 0：项目现状与原方案理解](#2-phase-0项目现状与原方案理解)
3. [当前方案合理部分](#3-当前方案合理部分)
4. [当前方案问题与调整建议](#4-当前方案问题与调整建议)
5. [数据源方案](#5-数据源方案)
6. [LLM 方案](#6-llm-方案)
7. [Agent / Workflow 方案](#7-agent--workflow-方案)
8. [数据模型](#8-数据模型)
9. [知识库设计](#9-知识库设计)
10. [成本分析](#10-成本分析)
11. [稳定性分析](#11-稳定性分析)
12. [安全分析](#12-安全分析)
13. [风险清单](#13-风险清单)
14. [MVP 建议](#14-mvp-建议)
15. [待确认问题](#15-待确认问题)

---

## 1. 总体结论

**结论：可行，且是低成本可运行的个人系统。但有 5 处架构问题需要调整，核心调整是把"6 个独立 Agent"降级为"1 个 Analysis Engine + 多套 Prompt 策略"。**

可行性判断依据：

| 维度 | 判断 | 依据 |
|------|------|------|
| 数据源 | ✅ 可行 | 本机 `a-stock-data` 技能已实测验证 43 个免费 A 股数据端点（2026-07），覆盖行情/公告/新闻/研报/资金面，无需付费数据源即可启动 |
| LLM 成本 | ✅ 可行 | 国产模型分层方案下，每月 LLM 成本可控制在 ¥10~50；即使全用海外旗舰模型也 <¥150/月 |
| 技术栈 | ✅ 合理 | Python + MySQL（独立库）+ launchd + Obsidian 匹配个人系统规模，无需中间件；数据库托管在已有 RDS 实例上，零额外运维 |
| 工程量 | ⚠️ 可控 | MVP（新闻→分析→知识库→日报）约 3~5 个工作日；原方案全部功能（含月报、Thesis 全自动闭环）是 3 个月量级，必须分期 |
| 主要风险 | ⚠️ 需管理 | 爬虫类接口失效是长期风险（财联社/东财接口历史上多次变更）；LLM 结构化输出需要严格校验 |

**明确不需要的组件**（结论先行，详细论证见 §4）：

Redis、Kafka/MQ、Airflow、Kubernetes、向量数据库、Agent Framework（LangChain/LangGraph/AutoGen）、MCP。

---

## 2. Phase 0：项目现状与原方案理解

### 2.1 当前项目现状

```
/Users/bjhl/IdeaProjects/learn-project/investment-ai/
└── investment-ai-feasibility-analysis.md   # 唯一文件：需求文档（2046 行）
```

- **无任何代码、依赖、配置**。这是一个从零开始的项目，不存在历史包袱，也意味着"检查已有 Obsidian 集成 / AI 调用能力 / 采集能力"的结果全部为：无。
- 项目不在 git 管理下（建议 TASK-001 时 `git init`）。
- 运行环境：macOS（darwin 27.0, arm64），符合原方案的 Mac + launchd 假设。

### 2.2 本机已有资产（重要发现）

| 资产 | 对本项目的价值 |
|------|--------------|
| `~/.agents/skills/a-stock-data/`（V3.4.0，43 端点，2026-07 实测） | **直接决定数据源选型**。已验证：通达信 mootdx（TCP，不封 IP）、腾讯财经行情（不封 IP）、巨潮公告、财联社电报（v1 API + 本地签名）、新浪财报三表、东财数据中心（需 ≥1s 限流）、同花顺热点。含全部可运行代码和防封策略 |
| GLM Coding Plan（当前会话即由 GLM-5.3 驱动） | 说明老板已有智谱生态账号；但 **Coding Plan 订阅 ≠ API Key**，Pipeline 需要独立的 API Key（见 §15 待确认） |

### 2.3 原方案理解（一句话版）

> 每天定时采集新闻/公告/行情 → 清洗去重 → 分级 → LLM 结构化分析（区分事实/解释/假设）→ 更新行业/公司/Thesis 知识 → 写入 Obsidian → 生成 Daily/Weekly Review，形成"信息→认知→验证→修正"的研究闭环；AI 不做买卖建议，人做决策。

关键约束提炼：

- 输出必须区分 Fact / Interpretation / Hypothesis / Opinion，AI 推测不得包装成事实
- Thesis 只输出 Supporting / Neutral / Contradicting，**禁止评分制和买卖建议**
- 所有结论必须可溯源（source / url / time）
- LLM 输出 JSON → Schema 校验 → Python 渲染 Markdown，禁止 LLM 直出 Markdown
- 幂等：重复执行不产生重复数据

### 2.4 发现的关键问题（原方案 vs 现实）

1. **Agent 层过度设计**：6 个独立 Agent（Industry/Company/Catalyst/Market/DevilAdvocate/Thesis）本质是 6 套 Prompt + 不同上下文组装，不是自主决策实体。MVP 阶段做成独立 Agent 模块会显著增加代码量和维护成本（论证见 §7）。
2. **目录结构按"Agent"组织**（`agents/industry.py` 等），错误地把"Prompt 策略"当成了"模块边界"。应按 Pipeline 阶段组织。
3. **原方案 `collectors/` 直连数据源**，与指令八"必须设计 Adapter"矛盾（原方案自身在这点上不够彻底）。
4. **每日 3 次调度（07:30/18:00/21:00）对 MVP 过重**：3 个 Pipeline 入口意味着 3 套数据水位管理。MVP 应先 1 次/天跑通全链路，再拆分时段。
5. **知识库膨胀无机制**：原方案说"不要变成垃圾场"，但没给出 Event 层的存储策略——事件每天几百条，如果每条都写 Markdown 必然爆炸（解法见 §9）。
6. **LLM 未选型**：原方案列出 Claude/GPT/Gemini/本地模型，但未考虑国内网络可用性与中文金融语料效果。国产 API（GLM/DeepSeek/Qwen）在中文财经文本上不吃亏，价格低一个数量级，且无网络稳定性问题。
7. **未定义 Prompt 版本管理**：分析质量迭代依赖 Prompt 调整，`analyses` 表必须记录 prompt_version，否则无法做质量对比。

---

## 3. 当前方案合理部分

以下设计经评审后**保留**：

1. **总体技术栈**：Python + MySQL（独立库 `investment_ai`，复用 stock-platform 的 RDS 实例与连接规范）+ launchd + Obsidian + LLM API。规模匹配、零新增基础设施、单人可维护。
2. **职责划分原则**："Python 负责确定性工作，LLM 负责非确定性工作"。这是整个系统最重要的架构决策，正确。
3. **数据流主干**：Scheduler → Collect → Normalize → Dedup → Classify → Importance → Analyze → Knowledge → Report。顺序合理，每步职责单一。
4. **Fact / Interpretation / Hypothesis / Opinion 分离**：这是对抗 LLM 幻觉的核心机制，且直接体现在 JSON Schema 字段设计中。
5. **三级成本漏斗**：Cheap Filter → Important Events → Deep Analysis。必要且有效（成本估算见 §10）。
6. **来源优先级**（公告 > 官方 > 协会 > 海外财报 > 媒体 > 券商 > 社交媒体）：符合基本面研究纪律，应落入 `source_priority` 字段参与重要性打分。
7. **幂等三键**：`source + source_id + content_hash`。正确，可直接作为 UNIQUE 约束。
8. **重要性分级 P0~P3 对应不同分析深度**：合理，保留。
9. **回测系统独立于研究系统**：边界正确，第一阶段不做。
10. **因果链模型**（产业变化→需求→供给→…→股价）：作为 Prompt 中的分析框架保留，不做成代码逻辑。
11. **MVP 路线 V0.1→V1.0 分期**：方向正确（但建议重排优先级，见 §14）。

---

## 4. 当前方案问题与调整建议

### 4.1 "6 Agent 架构" → "1 个 Analysis Engine + Prompt 策略集"

**问题**：Agent 的定义是"自主规划 + 工具调用循环"。而原方案的 6 个 Agent：

- 输入输出都是确定的（结构化事件进，结构化 JSON 出）
- 不需要自主决定调用什么工具、调几次
- 差异只在 **Prompt 模板 + 组装的上下文**

这 6 个"Agent"实际是 6 个**分析策略（Analysis Strategy）**。做成独立 Agent 的代价：6 个模块文件、6 套调用约定、跨 Agent 的上下文传递复杂度、LangChain 类框架引入的抽象泄漏。

**调整**：

```
analysis/
├── engine.py          # 唯一的 Analysis Engine：组装上下文 → 调 LLM → 校验 Schema → 落库
├── strategies.py      # 策略注册表：industry / company / catalyst / market / devil_advocate / thesis
└── schemas.py         # 每个策略对应的 JSON Schema

prompts/
├── industry_v1.md
├── devil_advocate_v1.md
├── thesis_review_v1.md
└── ...
```

新增一个分析视角 = 新增一个 Prompt 文件 + Schema + 注册一行代码，**不改引擎**。

保留多阶段分析的能力：Thesis Review 的输入是"当天 P0/P1 分析结果 + Thesis 当前状态"，由 Orchestrator 编排调用顺序（先事件分析，后 Thesis 复盘），这是 **Workflow 编排**，不是 Agent 自治。

### 4.2 重设项目目录（按 Pipeline 阶段，不按 Agent）

原方案目录（`agents/`、`collectors/` 平铺）调整为：

```
investment-ai/
├── main.py                    # CLI: daily / market-review / thesis-review / weekly / backfill
├── config/                    # settings.yaml / sectors.yaml / companies.yaml / theses.yaml
├── app/
│   ├── domain/                # 纯 dataclass 领域模型（不依赖 DB）
│   ├── db/                    # MySQL 连接（复用 stock-platform 规范）+ SQLAlchemy 模型 + repository（幂等约束在这里）
│   ├── providers/             # 全部外部依赖的 Adapter
│   │   ├── base.py            # NewsProvider / MarketProvider / AnnouncementProvider / LLMProvider 抽象
│   │   ├── news/              # ClsNewsProvider / EastmoneyNewsProvider / MockNewsProvider
│   │   ├── market/            # TencentMarketProvider / MootdxMarketProvider / MockMarketProvider
│   │   ├── announcement/      # CninfoAnnouncementProvider / Mock...
│   │   └── llm/               # GlmProvider / DeepseekProvider / ClaudeProvider（OpenAI 兼容协议优先）
│   ├── pipeline/              # orchestrator + 各 step（normalize/dedup/classify/importance/analyze）
│   ├── analysis/              # Analysis Engine + strategies + schemas（见 4.1）
│   ├── knowledge/             # Obsidian Renderer + Writer（MySQL 为源，渲染为幂等重写）
│   └── report/                # daily / weekly 生成器
├── prompts/                   # Prompt 模板（文件名带版本号）
├── tests/                     # unit / integration / schema / idempotency / e2e
├── data/                      # raw 缓存（结构化数据存外部 MySQL：investment_ai 库）
├── logs/                      # 结构化日志（JSONL）
└── launchd/                   # com.investment-ai.daily.plist 等
```

要点：

- `providers/` 下每个真实 Provider 配一个同接口 Mock，满足"Mock First"
- `domain/` 与 `db/` 分离，未来换 Postgres 或加 Web UI 不动领域逻辑
- Obsidian 只是 `knowledge/` 的渲染目标，不是数据存储（符合指令十七）

### 4.3 调度：MVP 单入口，运行时段分步

原方案 07:30 / 18:00 / 21:00 三次独立运行的问题：三次水位管理、三次失败恢复路径、MVP 阶段调试成本 ×3。

**调整**：MVP 只做一个入口 `python main.py daily`（建议 20:00 运行，收盘后公告/新闻/行情齐全），内部按阶段产出 Morning 摘要 / Market Review / Thesis Review 三个 section。V0.3+ 再拆分为多个 launchd job——`main.py` 的子命令从一开始就预留（`market-review`、`thesis-review`、`weekly`），拆分时只加 plist 不改代码。

### 4.4 知识库：Event 不进 Obsidian（详见 §9）

原方案隐含"事件也写 Markdown"（§32 知识分层有 Event 层）。调整：**Event 只存 MySQL 事件表**，Obsidian 中 Daily Report 以表格 + 内部链接引用当日重要事件摘要；需要看事件全文时从 DB 查（或后续加一个极简查询命令 `python main.py event <id>`）。

### 4.5 逐项否决的组件

| 组件 | 否决理由 |
|------|---------|
| Redis | 无跨进程共享状态需求。Pipeline 单进程顺序执行；去重在 MySQL UNIQUE 索引；限流用进程内时间戳 |
| Kafka/MQ | 无多消费者。数据流是分钟级批处理，不是流处理 |
| Airflow | 每天 ≤4 个 job，launchd + `runs` 表的状态机足够；Airflow 本身需要常驻调度进程 + 学习成本 |
| Kubernetes/微服务 | 单机单用户单进程，任何分布式都是负资产 |
| 向量数据库 | 去重用 content_hash 精确匹配 + SimHash 近似；相关性检索 MVP 不需要。第二阶段若做"历史相似事件召回"，本地 FAISS 文件即可，仍然不需要独立服务 |
| Agent Framework | 见 4.1。固定流程 + 结构化 IO，框架只增加调试黑盒 |
| MCP | 系统是自包含定时任务，运行时无人交互。数据源封装用进程内 Adapter 更简单、可测试。（本机的 a-stock-data skill 是**开发期知识资产**，指导我们写 Provider 代码，不是运行时依赖） |
| Embedding 过滤层 | 原方案 §23 提到"规则/Embedding/轻量模型"。MVP 用关键词规则（sectors.yaml 已有）+ 便宜 Flash 模型分类，Embedding 是过早优化 |

---

## 5. 数据源方案

### 5.1 选型结论（第一版组合）

| 数据类别 | MVP 选择 | 协议/限制 | 备份源 | 替换成本 |
|---------|---------|----------|--------|---------|
| **新闻/快讯** | 财联社电报 `v1/roll/get_roll_list` + 本地 md5(sha1) 签名（零 key） | HTTP，2026-07 实测可用 | 东财全球资讯 `np-weblist`（7×24） | 低（统一 NewsProvider 接口） |
| **A 股行情/指数** | 腾讯财经 `qt.gtimg.cn` | HTTP GBK，不封 IP，批量 60+ 代码/次；含 PE/PB/市值/涨跌停价/换手 | mootdx（通达信 TCP 7709，不封 IP） | 低 |
| **行业板块涨跌** | 东财 `push2 clist`（m:90+t:2） | HTTP，**需 ≥1s 串行限流**（东财有风控：>5 QPS / 5min 300 次会封 IP） | 同花顺 | 低 |
| **公司公告** | 巨潮 `cninfo.com.cn` | HTTP，官方来源，含 PDF；需动态查 orgId | 深交所/上交所官方页 | 低 |
| **财报三表** | 新浪 `quotes.sina.cn` | HTTP，按报告期 | mootdx finance / Tushare | 低 |
| **研报**（观点参考） | 东财 `reportapi`（个股+行业，含一致预期 EPS） | HTTP，限流同东财 | 同花顺 worth.html | 低 |
| **海外市场** | 东财全球资讯（新闻）+ 腾讯行情（美股/港股指数，`usDJI`/`hkHSI` 前缀） | 同上 | — | 低 |

**全部免费、零 key**（除未来可选的 iwencai 语义搜索）。这是本机 a-stock-data 技能 2026-07 实测结论的直接复用。

### 5.2 为什么不选常见候选

| 候选 | 结论 | 理由 |
|------|------|------|
| **Tushare Pro** | 不作为 MVP 主源 | 积分墙：免费 120 积分仅基础日线，可用接口有限；2000 积分（¥200/年）起才实用，分钟数据另收 ~¥1000/月；且 2026 年有[突发停运前科](https://www.cls.cn/detail/2125736)。Adapter 接口预留，未来财务数据批量补数时可付费引入 |
| **AKShare** | 不依赖 | 本质是爬虫聚合库，接口随上游网站改版频繁失效（a-stock-data skill V3.0 正因此移除了 akshare 依赖），长期运行的系统不能建立在"每周可能坏"的依赖上。我们直连稳定的底层端点 |
| **baostock** | 备选 | 历史日线稳定免费，但只有日频历史数据，MVP 需要的实时/新闻/公告它都没有。作为历史 K 线补数的备选 |
| **Wind/同花顺 iFinD/聚宽** | 不选 | 商业授权万元级/年，个人研究系统第一阶段不值；且授权条款对"数据落地长期存储"有限制 |
| **自写爬虫抓财经网站正文** | 不做 | 版权与合规风险（见 §12），财联社/东财 API 已给结构化摘要，够用 |

### 5.3 数据质量与风控对策

- **东财系接口必须走统一限流客户端**（串行 ≥1s + 随机抖动 + Keep-Alive + 正常 UA），这是被封的头号原因；skill 中已有成熟实现可移植
- **mootdx 注意事项**：0.11.x 有 BESTIP 空串 bug（需显式传 server）；K 线为**不复权**价，跨除权计算需换腾讯前复权源；大量旧服务器 IP 已"连得上但返回空数据"，需数据级探测
- **接口失效是常态**：每个 Provider 实现健康检查（拉 1 条样例数据），失败即降级到备份源并在 run 报告中标记 `degraded_sources`，不让单源失败阻塞 Pipeline（符合指令"失败任务"要求）
- **财联社电报量级**：全天数千条，必须先过 sectors.yaml 关键词规则过滤（规则层零成本），预计过滤后 <500 条/天进入分类层

来源：[Tushare 积分与频次权限表](https://tushare.pro/document/1?doc_id=290)、[Tushare 平台积分](https://tushare.pro/document/1?doc_id=13)、[A 股量化数据接口对比（腾讯云）](https://developer.cloud.tencent.com/article/2738002)、[TusharePro 停运报道（财联社）](https://www.cls.cn/detail/2125736)、本机 a-stock-data skill V3.4 实测记录。

---

## 6. LLM 方案

### 6.1 选型结论

| 层 | 用途 | 首选 | 理由 | 备选 |
|----|------|------|------|------|
| **L0 规则层** | 关键词/来源优先级过滤 | 无 LLM（纯 Python 规则） | 零成本、零延迟、可解释 | — |
| **L1 Cheap 层** | 事件分类 + 重要性打分（P0~P3）+ 行业归属 | **GLM-4.7-Flash**（免费）或 **DeepSeek-V4-Flash**（约 ¥1/M 输入、¥2/M 输出） | 单条任务小（<1K token），Flash 级足够；两家 JSON 输出稳定、OpenAI 兼容协议 | Qwen-Flash |
| **L2 Standard 层** | P0/P1 事件深度分析、Daily Report 汇总 | **GLM-5 / DeepSeek-V4** 标准档 | 中文财经文本理解 + 因果链推理达标，长上下文（128K+）满足"当日事件 + Thesis 上下文"组装 | Qwen-Max |
| **L3 Deep 层**（可选，V0.6+） | Weekly/Monthly 复盘、Thesis 重大修订 | GLM-5 旗舰 或 Claude Sonnet 5（约 $2~3/M 输入） | 复盘质量对推理深度敏感；Claude 在反方论证（Devil Advocate）上表现强，但需海外网络+美元付费 | — |

**关键决策：国内 API 优先**。理由：

1. 网络稳定性：系统要每天无人值守运行，海外 API 的代理链路是单点故障
2. 中文能力：输入是中文财经文本，GLM/DeepSeek/Qwen 与海外模型无实质差距，价格低 10~30 倍
3. 结构化输出：GLM/DeepSeek 均支持 OpenAI 兼容的 `response_format/json_object` + function calling

### 6.2 模型分层与调用漏斗

```
每日原始信息（财联社+东财快讯）        ~2000-5000 条
    ↓ L0 关键词规则（sectors.yaml）      零成本
相关候选                            ~200-500 条
    ↓ L1 Flash 批量分类（单条 <1K token）  ~¥0.1-0.3/天
  分类 + P0~P3 分级 + 行业标签        全量落库
    ↓ 只取 P0/P1
重要事件                            ~10-30 条
    ↓ L2 标准模型逐条深度分析（含因果链 Schema）
结构化分析 JSON                      ~¥0.2-1/天
    ↓ 汇总上下文（当日分析 + Thesis 状态）
Daily Report + Thesis Review        1-2 次调用
```

### 6.3 结构化输出与防幻觉（落实指令九）

- LLM Gateway 统一封装：`complete(strategy, payload) -> validated_dict`，内部做 JSON 解析 → JSON Schema 校验（`jsonschema` 库）→ 失败自动带错误信息重试 1 次 → 仍失败则记录 `analysis_status=parse_error` 并跳过（不阻塞）
- Schema 必填字段含 `facts[]`（每条带 source_event_id 引用）、`uncertainty[]`——强制模型声明不确定性与证据来源
- 分析结果与原始事件的关联是 DB 外键（`analyses.event_id`），渲染到 Obsidian 时自动带来源链接——"这个结论根据哪些原始信息得到"可一键回查
- Prompt 模板文件名带版本（`industry_v1.md`），`analyses.prompt_version` 落库，支持质量回归对比
- 温度：分类层 0.0~0.2；分析层 ≤0.4；禁止高温度采样

来源：[DeepSeek API 定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)、[智谱 BigModel 定价](https://bigmodel.cn/pricing)、[2026 国产大模型 API 价格对比（CSDN）](https://blog.csdn.net/2601_96613114/article/details/163281568)、[LLM API Pricing 2026（Spheron）](https://www.spheron.network/blog/llm-api-pricing-comparison-gpt-claude-gemini-deepseek-2026/)、[Anthropic API Pricing（PE Collective）](https://pecollective.com/tools/anthropic-api-pricing/)。价格为 2026-09 快照，实施时以官方页为准。

---

## 7. Agent / Workflow 方案

### 7.1 决策矩阵

| 原方案角色 | 形态判定 | MVP 处理 |
|-----------|---------|---------|
| Industry Agent | Prompt 策略 | `industry` strategy：P0/P1 事件 → 行业影响分析（V0.2 启用） |
| Company Agent | Prompt 策略 | `company` strategy：命中自选股的事件 → 公司影响（V0.2，依赖 companies.yaml） |
| Catalyst Agent | Prompt 策略 | **并入 industry**：催化剂只是事件类型（event_type=catalyst）的一个分析维度，无独立上下文需求 |
| Market Agent | Prompt 策略 | `market_review` strategy：行情数据（指数/板块/涨停/成交额）→ 市场行为描述（V0.3） |
| Devil Advocate | Prompt 策略（**保留独立性**） | `devil_advocate` strategy：输入 = 当日支持性分析 + Thesis，任务 = 找反证/逻辑断点/替代解释。**必须独立调用**（不与正向分析混在同一 Prompt），否则反方观点会被正向上下文锚定——这是原方案中价值最高的设计，保留 |
| Thesis Agent | Workflow 编排 | `thesis_review`：取当日 P0/P1 分析 + theses 表当前状态 → 逐 Thesis 输出 supporting/neutral/contradicting + 证据引用 + 是否触发证伪条件（V0.6） |

### 7.2 结论

- **零个自治 Agent，一个 Engine，六个策略，两处 Workflow 编排**（Daily Pipeline 内部的调用顺序；Weekly 聚合 Daily）
- 每个 strategy = `prompt 模板 + 输出 Schema + 允许的模型档位`，在 `strategies.py` 注册
- 上下文控制：每类分析的输入由 Python 精确组装（事件正文 + 相关历史分析摘要 + Thesis 摘录），不让 LLM 自己决定读什么——成本可控、可复现
- 这个设计下"新增 Devil Advocate"和"新增一个新行业视角"是同一种操作，未来演进为真正的多 Agent（若第二阶段需要工具调用循环）也只是替换 Engine 内部实现，接口不变

---

## 8. 数据模型

### 8.0 存储与连接（2026-09-17 决策：MySQL 独立库）

**部署形态**：与 stock-platform 同一阿里云 RDS 实例，**新建独立库 `investment_ai`**——实例共享（零新增成本、统一备份与白名单），库级隔离（权限可单独授予；两系统互不影响，stock-platform 的库 `stock_analysis` 对本系统只读需求都无，MVP 完全不跨库）。

**连接方式（完全复用 stock-platform 的已验证模式，见其 `app/core/database.py`）**：

```python
# 配置：pydantic-settings 读环境变量（.env 加载，不入 git）
#   DB_HOST / DB_PORT=3306 / DB_USER / DB_PASSWORD / DB_NAME=investment_ai

DATABASE_URL = URL.create(                     # URL.create 自动转义密码特殊字符
    drivername="mysql+pymysql",
    username=settings.db_user, password=settings.db_password,
    host=settings.db_host, port=settings.db_port,
    database=settings.db_name,
    query={"charset": "utf8mb4"},
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, echo=False)
# 差异说明：pool_size 用 3（stock-platform 是 10）——本系统是 launchd 触发的
# 短时 CLI 进程，无并发流量；pool_pre_ping 保留（云 DB 空闲断连的标准对策）。
```

**技术选型**：SQLAlchemy 2.0（DeclarativeBase + sessionmaker(autoflush=False, expire_on_commit=False)）+ PyMySQL 驱动 + Alembic 迁移——与 stock-platform 完全一致，降低双项目维护心智成本。

**MySQL 下的关键工程约定**：

- 字符集/排序规则：`utf8mb4 / utf8mb4_0900_ai_ci`（RDS 8.0 默认），中文与 emoji 安全
- 主键与唯一键均为**短字符串**（`VARCHAR(16)`~`VARCHAR(64)` 的 hash/slug），避开 utf8mb4 长索引限制；正文大字段（title/content/result_json）用 `TEXT/MEDIUMTEXT` 且**不建索引**
- 事务与并发：单进程顺序 Pipeline，无并发写；repository 层用 `INSERT ... ON DUPLICATE KEY UPDATE` / `INSERT IGNORE` 表达幂等
- 迁移：Alembic 管理 schema（`alembic revision --autogenerate`），禁止手工改线上表
- 断连：`pool_pre_ping` + 调用层 tenacity 重试（网络抖动 1~2 次），DB 完全不可达时 Pipeline 以 `runs.status=db_unreachable` 快速失败退出（launchd 下次唤醒重跑，幂等保证不重复）

核心 8 张表：

### 8.1 ER 关系

```
events 1──N analyses
events N──N theses        （通过 thesis_evidence）
events N──1 industries    （sector_tag 逻辑关联，sector 字典放 sectors.yaml，MVP 不建表）
companies N──N theses     （theses.related_companies，JSON 字段）
reports 独立（按 type+date 唯一）
runs 独立（每次 Pipeline 执行一条）
```

### 8.2 表结构要点

**events**（原始+标准化事件，唯一事实来源）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | `sha1(source:source_id)` 前 16 位，天然幂等 |
| source / source_id / source_url | TEXT | 来源三件套；`UNIQUE(source, source_id)` |
| content_hash | TEXT | `sha1(normalized_title + normalized_body)`，正文级去重（跨媒体同一新闻） |
| title / content / published_at / collected_at | | 正文 + 双时间戳 |
| sectors | TEXT(JSON) | `["ai_semiconductor"]` |
| event_type | TEXT | capacity_expansion / policy / earnings / catalyst / ... |
| importance | TEXT | P0/P1/P2/P3（L1 层回填） |
| status | TEXT | raw → classified → analyzed / skipped / parse_error |

索引：`UNIQUE(source, source_id)`、`UNIQUE(content_hash)`、`INDEX(published_at)`、`INDEX(importance, status)`。

**analyses**（LLM 分析结果，版本化）

| 字段 | 说明 |
|------|------|
| id INTEGER PK | |
| event_id → events.id | FK；`UNIQUE(event_id, strategy, prompt_version)` |
| strategy | industry / company / market_review / devil_advocate / thesis_review / daily_summary |
| model / prompt_version | 可复现性 |
| result_json | Schema 校验后的完整结果 |
| input_tokens / output_tokens / cost_cny | 成本核算 |
| created_at | |

**theses**

| 字段 | 说明 |
|------|------|
| id TEXT PK | slug，如 `ai-demand-growth` |
| title / core_hypothesis / falsification_conditions(JSON) / key_metrics(JSON) | 结构化 Thesis 定义 |
| status | active / weakened / falsified / archived（**无评分字段**，落实指令十一） |
| version + updated_at | 每次修订 version+1，旧版进 `thesis_versions` |

**thesis_evidence**（证据关联表）

| 字段 | 说明 |
|------|------|
| thesis_id → theses.id, event_id → events.id | 联合主键，天然幂等 |
| direction | supporting / neutral / contradicting |
| note / created_at | 证据说明 |

**reports**

| 字段 | 说明 |
|------|------|
| id INTEGER PK | |
| type + date | `UNIQUE(type, date)`——同一天重跑覆盖（幂等） |
| obsidian_path | 渲染产物路径 |
| metrics_json | 当日统计（事件数/分析数/成本） |

**runs**（运行可观测性，落实指令十九）

| 字段 | 说明 |
|------|------|
| run_id TEXT PK | uuid |
| command / started_at / finished_at / status | running / success / partial / failed |
| stats_json | events_fetched / deduplicated / classified / analyzed / llm_calls / input_tokens / output_tokens / estimated_cost / success_count / failure_count / degraded_sources[] |

**daily_snapshots**（V0.3 行情层）：`UNIQUE(date)`，存指数/板块/涨停/成交额 JSON。

**companies**（V0.2）：code PK、name、sector、watch（bool）。MVP 阶段可仅由 `companies.yaml` 提供字典，入库推迟到需要记录公司级分析时。

### 8.3 幂等设计汇总

| 操作 | 幂等机制 |
|------|---------|
| 事件采集 | `INSERT IGNORE` + 两道 UNIQUE |
| 事件分析 | UNIQUE(event_id, strategy, prompt_version)，重跑跳过已完成 |
| Thesis 证据 | 联合主键 `INSERT IGNORE` |
| Obsidian 渲染 | Deterministic Renderer：同输入同输出，覆盖写；Industry/Company/Thesis 长文件按 section 幂等重写 |
| Daily Report | UNIQUE(type, date) `ON DUPLICATE KEY UPDATE` |
| 断点恢复 | events.status 状态机 + runs.stats_json；重跑只处理 `status < analyzed` 的事件 |

---

## 9. 知识库设计

### 9.1 反垃圾场核心策略：**分层存储，事件不入库（Obsidian）**

| 层 | 存储 | 生命周期 | 说明 |
|----|------|---------|------|
| Event | **仅 MySQL 事件表** | 永久（DB） | 每天几百条，只在 Daily Report 中以"标题+链接"出现。Obsidian 里没有事件文件，从源头杜绝膨胀 |
| Daily | Obsidian `Daily/2026-09-17.md` | 1 文件/天，约 200~400 行 | 当日 P0/P1 摘要、Thesis 变化、市场综述、明日关注。是**入口页**，链接到下层 |
| Weekly | Obsidian `Weekly/2026-W38.md` | 1 文件/周 | 聚合 7 天 Daily + Thesis 状态变化 |
| Industry | Obsidian `Industries/AI-Semiconductor.md` | **单一长文件，原地演进** | 结构化 section（产业链/供需/催化剂/风险/跟踪指标），Knowledge Updater 只重写有变化的 section + 追加 changelog 行 |
| Company | Obsidian `Companies/XXX.md` | 同上 | V0.2 引入 |
| Thesis | Obsidian `Theses/xxx.md` + MySQL theses 表 | 单文件 + DB 双源（DB 为准，渲染覆盖） | 状态徽章（🟢支持/⚪中性/🔴削弱）+ Latest Changes 滚动窗口（只保留最近 10 条变化，旧的进 DB 不展示） |

文件量估算：3 行业 + ~10 公司 + ~5 Thesis + 365 Daily + 52 Weekly ≈ **435 文件/年**，完全可控。

### 9.2 长文件的原地更新机制（关键工程点）

Industry/Company/Thesis 这类"活文档"不能靠追加（会无限膨胀），也不能让 LLM 全文重写（会漂移、丢内容）。机制：

1. 文件按标准注释分节：`<!-- SECTION:supply_demand START --> ... <!-- END -->`
2. `KnowledgeUpdater` 对某个 section 生成新内容（LLM 输出结构化 diff：`{section, new_content, based_on_event_ids}`）
3. Python 做节级替换，节外内容（人工补充的笔记）永不触碰
4. 文件尾部维护 `## Changelog` 表格，追加一行变化记录（含事件链接）

这样 AI 更新和**人工编辑可共存**——Obsidian 是个人知识库，老板手工写的洞察必须被保护。

### 9.3 链接结构

Daily Report 内用 Wiki Link 指向 Industry/Company/Thesis 与事件详情（`[[AI-Semiconductor]]`、`[[2026-09-17#P0-事件-x41f]]`）；事件标题锚点由 Renderer 生成确定性 slug。全链路：**Thesis 结论 ← 分析 JSON ← event_id ← source_url**，两端都可回查（落实指令十）。

---

## 10. 成本分析

### 10.1 每日成本模型（按 §6.2 漏斗估算）

| 项 | 数量 | Token 估算 | 低成本方案（GLM-4.7-Flash 免费 + DeepSeek-Flash） | 平衡方案（DeepSeek-V4 标准档为主） | 高质量方案（L3 用 Claude Sonnet） |
|----|------|-----------|----------|----------|----------|
| L1 分类 | 300 条 × (1K in + 0.1K out) | 330K | **¥0** | ~¥0.4 | ~¥0.4 |
| L2 深度分析 | 20 条 × (3K in + 1K out) | 80K | ~¥0.3（Flash） | ~¥1.5 | ~¥1.5 |
| Daily 汇总 + Thesis Review | 3 次 × (10K in + 2K out) | 36K | ~¥0.2 | ~¥0.6 | ~¥0.6 |
| L3 Weekly 复盘 | 摊薄到天（1 次/周 × 30K） | ~5K/天 | — | — | ~$0.3（≈¥2） |
| **每日合计** | | | **≈ ¥0.5** | **≈ ¥2.5** | **≈ ¥4.5** |
| **每月合计** | | | **≈ ¥15** | **≈ ¥75** | **≈ ¥135** |

### 10.2 成本控制手段（按优先级）

1. **L0 规则过滤**（拦截 80%+ 原始信息，零成本）
2. **content_hash 去重**（跨媒体重复新闻只分析一次，预计省 30~50%）
3. **Flash 免费档做分类**（GLM-4.7-Flash 当前免费）
4. **结果缓存**：`UNIQUE(event_id, strategy, prompt_version)` 即永久缓存，重跑零成本
5. **上下文瘦身**：送 L2 的历史上下文用"分析摘要"而非"原始事件全文"
6. **runs.stats_json 日成本落库**，超阈值（如 ¥10/天）告警日志

结论：**运行成本不是风险项**，每月 ¥15~135，选平衡方案即可。

---

## 11. 稳定性分析

| 要求 | 设计 |
|------|------|
| **幂等** | 见 §8.3：三道 UNIQUE + 状态机 + 确定性渲染 + upsert。`python main.py daily` 重复执行 = 跳过已完成 + 覆盖渲染 |
| **重试** | 两级：HTTP 层（指数退避 ×3，东财 403 不重试只降速）与 LLM 层（Schema 校验失败带错误重试 1 次） |
| **超时** | Provider 统一 15s（东财）/ 60s（LLM）；Pipeline 级总超时防 hang（launchd 依赖此退出） |
| **断点恢复** | 事件级状态机——任何一步崩溃，重跑从未完成处继续；`runs.status=partial` 记录断点 |
| **外部 DB 依赖** | MySQL 为云 RDS，比本地文件多一个网络依赖。对策：pool_pre_ping 防空闲断连；调用层重试 1~2 次抗抖动；DB 不可达时 `runs.status=db_unreachable` 快速失败退出，launchd 下次触发重跑（幂等保证零重复）。原始数据源响应可先落 raw 缓存文件再入库，降低"采集成功但入库失败"的浪费 |
| **失败隔离** | 单数据源失败 → 降级备份源/标记 degraded，绝不阻塞整条 Pipeline；单事件分析失败 → `parse_error` 状态留档 |
| **日志** | 结构化 JSONL（run_id 贯穿），logs/ 按天分文件；错误含 provider/endpoint/异常摘要 |
| **监控** | MVP：每次运行结束输出 Pipeline Execution Report（控制台 + 落 runs 表）+ 失败时 macOS 通知（`osascript display notification`）。不引入 Prometheus 等重型方案 |
| **成本统计** | 每次调用记录 token/cost，按 run/天/月聚合（一条 SQL） |

**launchd 特有问题**：Mac 合盖/睡眠会错过 20:00 触发 → plist 用 `StartCalendarInterval` + 程序入口幂等设计，错过的时间点在下次唤醒后由 launchd 补跑一次（launchd 对错过的 calendar interval 默认唤醒即执行）；Pipeline 入口再校验"今天是否已成功运行"（runs 表），避免重复分析。

---

## 12. 安全分析

| 项 | 方案 |
|----|------|
| API Key | 环境变量或 `~/.config/investment-ai/.env`（`python-dotenv` 加载）；**绝不入库、不进 git**（.gitignore 覆盖 config/local.yaml 与 .env）；settings.yaml 只放引用名不放值 |
| DB 凭证 | 与 stock-platform 同规范：`.env` 中 `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`，不入 git；URL 由 `URL.create()` 构造（密码特殊字符自动转义，不落日志）；建议在 RDS 上为本项目建独立账号并只授权 `investment_ai` 库，实现权限级隔离 |
| 日志泄密 | Logger 统一过滤器：脱敏 `sk-*`/`Bearer *` 模式；异常堆栈不含请求头 |
| 数据源授权 | 全部选用公开可访问端点，遵守 ToS：限速（东财 ≥1s）、不批量转售、不爬付费墙内容；单机个人研究用途，量级极小（<1 万请求/天） |
| 新闻版权 | 只存标题 + 摘要 + URL 引用，**不全文转载**到 Obsidian；财联社电报本就是短摘要形态，天然合规 |
| 商业行情数据 | MVP 不使用任何商业授权数据，无长期存储授权问题；未来若引入 Tushare 付费数据，落地数据需遵守其协议（仅自用） |
| Obsidian 数据 | 个人知识库，不含 Key。结构化数据在 RDS MySQL，备份由云快照承接（沿用 stock-platform spec-007 的结论：备份恢复由 RDS 运维层承接，不在应用层做）；Obsidian vault 本身可用 git/iCloud 自行备份。加密（FileVault）交给 macOS 系统级方案 |
| 网络安全 | 仅出站 HTTPS；无监听端口、无 Web 服务（MVP 无 Web UI） |

---

## 13. 风险清单

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| R1 | 爬虫类接口失效（财联社/东财改版） | **高**（历史上多次） | 中 | Provider Adapter + 备份源 + 健康检查降级；失效接口集中在 providers/ 可快速修补；本机 a-stock-data skill 持续维护可参考 |
| R2 | LLM 幻觉/虚构事实混入分析 | 高 | 高 | Schema 强制 facts 带 event_id 引用；Devil Advocate 独立 Prompt；`uncertainty` 必填；渲染时区分「事实（来源可查）」与「推断」字体标记 |
| R3 | LLM JSON 解析失败 | 中 | 中 | json_schema 校验 + 带错误重试 + parse_error 状态留档不阻塞 |
| R4 | 知识库膨胀 | 中 | 中 | §9 事件不入 Obsidian + 长文件节级更新 + changelog 滚动窗口 |
| R5 | 重复分析浪费成本 | 中 | 低 | 三道 UNIQUE；重跑跳过已完成 |
| R6 | 东财 IP 风控 | 中 | 低 | 串行限流 ≥1s + 抖动；能用腾讯/通达信的数据不碰东财 |
| R7 | Mac 睡眠错过调度 | 中 | 低 | launchd 唤醒补跑 + runs 表幂等校验 |
| R8 | Thesis 被单日噪音频繁翻转 | 中 | 中 | Thesis 状态变更需 P0 级证据或连续多日同向证据（规则在 thesis_review strategy 中）；状态只在新证据方向上标注，人最终裁决 |
| R9 | Prompt 质量不达预期（分析空洞/模板化） | 中 | 高 | prompt_version 落库可 A/B；输出含 follow_up_questions 强制生成研究问题；老板人工抽查 Daily Report 反馈迭代 |
| R10 | 分析错误累积进长文档 | 低 | 高 | Industry/Thesis section 重写基于事件引用，可追溯；changelog 保留历史；MySQL 是唯一事实源，Obsidian 可随时全量重建 |
| R11 | 海外 LLM 依赖（若选 L3 Claude） | 低 | 低 | L3 可选层，默认国产旗舰 |
| R12 | 云 MySQL 网络依赖（本机 ↔ RDS 链路故障/实例维护） | 低~中 | 中 | pool_pre_ping + 重试；DB 不可达时快速失败并留 run 记录，launchd 重跑补齐（幂等零重复）；raw 缓存先落本地再入库；极端情况 RDS 不可用不影响"昨天的知识已渲染到 Obsidian"——Obsidian 本身离线可读 |

---

## 14. MVP 建议

### 14.1 MVP 边界（= 指令十三，确认执行）

**做**：新闻采集（财联社+东财，规则过滤）→ 标准化 → 去重 → L1 分类+重要性 → L2 P0/P1 深度分析 → Obsidian（Daily/Industry 骨架）→ Daily Report → launchd 每日一次 → 幂等与运行报告。

**不做**：自动交易、量化策略、回测、Web UI、行情分析（V0.3）、公司级分析（V0.2）、Thesis 自动闭环（V0.6）、Weekly/Monthly（V0.8）、任何中间件。

### 14.2 版本路线（对原方案 V0.1~V1.0 的重排）

原路线基本合理，两处调整：

1. **Thesis 提前到 V0.2**（原方案 V0.6）：Thesis 是整个系统的灵魂——没有 Thesis，Daily Report 只是新闻摘要。V0.1 末就应在 Obsidian 建初始 Thesis 文件（人工撰写），V0.2 起自动做 thesis_review。理由：越早接入，知识积累飞轮越早转动
2. **行情（V0.3）后移于公司分析（V0.2）**：公司公告/自选股影响分析对 Thesis 验证的价值 > 市场情绪复盘

```
V0.1 (MVP, 3~5 天)   新闻→去重→分类→重要性→深度分析→Obsidian Daily→launchd
V0.2 (2~3 天)        自选股公司命中分析 + Thesis Review（supporting/neutral/contradicting）
V0.3 (2~3 天)        行情 Market Review（腾讯行情 + 东财板块/涨停池）+ Industry 长文档自动更新
V0.4 (2 天)          财务数据接入（财报三表）+ 公告采集强化（巨潮）
V0.5 (2~3 天)        Devil Advocate 独立策略 + Weekly Review
V0.6+               Monthly Review / 行业数据库 / 检索增强（FAISS 历史相似事件）
```

### 14.3 验收标准（V0.1）

- `python main.py daily` 完整跑通：采集→去重→分类→分析→Obsidian→Daily Report
- 连续执行两次：第二次 0 新增事件、0 重复分析、Daily Report 内容一致（幂等）
- 拔网线重试场景：数据源失败时 Pipeline 完成（degraded），恢复后重跑补齐
- launchd 连续 3 天自动运行成功，每天收到 Pipeline Execution Report

---

## 15. 待确认问题

进入 Phase 2 前，以下问题需要老板拍板（不影响 Phase 2 启动的有默认值）：

| # | 问题 | 默认方案（不回复则按此执行） |
|---|------|---------------------------|
| Q1 | **Obsidian vault 路径**：本机是否已装 Obsidian？知识库放独立 vault（如 `~/Investment-KB`）还是现有 vault 子目录？ | 新建独立 vault `~/Investment-KB` |
| Q2 | **LLM API Key**：已持有哪些？GLM（bigmodel.cn）/ DeepSeek / 其他？ | GLM API（免费 Flash 档起步 + 标准档付费），LLMProvider 抽象下随时切换 |
| Q3 | **自选股清单**：V0.2 的 companies.yaml 初始名单（三大行业各 3~5 只？） | V0.1 不需要，V0.2 前提供 |
| Q4 | **每日运行时间**：默认 20:00 一次（收盘后）？还是坚持 07:30/18:00/21:00 三次？ | 20:00 单次，V0.3 后拆分 |
| Q5 | **Thesis 初始内容**：4 个示例 Thesis（AI 需求增长/HBM 周期/电力基建/人形机器人）由老板人工撰写，还是 AI 起草+人工修订？ | V0.2 时 AI 起草框架 + 老板修订 |
| Q6 | Mac 夜间是否常开/不休眠（影响调度补跑策略）？ | 按"可能睡眠"设计（launchd 补跑 + 幂等） |

---

## 附录 B：项目形态决策——独立项目 vs 并入 stock-platform（2026-09-17 补充）

**决策：独立项目（本仓库），不并入 stock-platform。两者是上下游关系，不是包含关系。**

### B.1 stock-platform 现状（2026-09-17 调研）

`learn-project/stock-platform`：个人 A 股量化研究平台，FastAPI + MySQL（阿里云 RDS）+ Docker + React，256 源码文件，7 轮 spec 迭代，活跃（最近提交 2026-09-10）。已交付：34 因子 + IC、回测、模拟盘闭环、RAG + 5 Agent、新闻采集 + 情绪、APScheduler。其 ROADMAP 主线为"研究严谨化"（数据修复/复权/幸存者偏差），阶段五（2027 Q1 起）才是"AI 深度化/自主投研"。

### B.2 不并入的理由

1. **范式不同**：量化（因子/IC/回测/模拟盘）vs 定性（事件/因果链/Thesis 证伪）；核心实体（Factor/Backtest vs Thesis/Evidence/Event）无重叠，合并无复用只有耦合
2. **应用形态冲突**：stock-platform 是常驻 Web 服务（FastAPI + React 前端 + API 层），本系统是 launchd 触发的短时 CLI Pipeline——并入需按其形态重写（service/API/前端页面全套），MVP 从 3~5 天膨胀至数周，违反 §35。**数据层已于 2026-09-17 主动统一**（同一 RDS 实例 + 独立库 `investment_ai`，见 §8.0），应用层仍保持隔离
3. **知识呈现层冲突**：Web UI vs Obsidian 本地 vault（节级更新、与人工笔记共存），Obsidian 是本系统灵魂
4. **节奏冲突**：会打断 stock-platform 既定的"研究严谨化"主线
5. **失败隔离**：模拟盘生产运行中；新范式系统独立仓库自由试错

### B.3 复用损失评估

代码级复用是伪命题（Python 版本/ORM/配置/日志体系全不同，搬代码成本 > 重写薄 Adapter）。真正的复用资产是**数据源知识**（a-stock-data skill），已在本报告 §5 落地。

### B.4 集成点（数据层已共享实例，应用层保持松耦合）

1. **数据层（2026-09-17 起）**：同一 RDS 实例，独立库 `investment_ai` vs `stock_analysis`，库级隔离；独立 DB 账号，仅授权各自库。未来跨库查询（如 Thesis 引用行情历史）走 `库名.表名` 只读查询，不建跨库外键
2. 第三阶段（量化验证）：Thesis 产出可量化假设 → stock-platform 因子/回测验证 → 结论 URL 回链到 Obsidian Thesis 页——这正是需求文档三阶段规划（第三阶段"量化→回测→策略验证"）的自然落点
3. 应用层互不依赖对方存活：`python main.py daily` 只依赖 RDS 可达，不依赖 stock-platform 服务运行

---

## 附录 A：与原方案条款的对照索引

| 原方案章节 | 本报告结论 |
|-----------|-----------|
| §5 总体架构图 | 保留主干，Agent 盒子改为 Analysis Engine（§4.1/§7） |
| §7 项目目录 | 重设为按 Pipeline 阶段（§4.2） |
| §13-17 Daily/Thesis/Weekly/Monthly | 调度合并为单入口多 section（§4.3），路线重排（§14.2） |
| §18 Obsidian 结构 | Event 层移出 Obsidian（§9.1） |
| §19-22 数据模型/去重/增量/失败 | 全保留，落地为 §8 表结构与 §11 稳定性设计 |
| §23-24 成本控制/来源优先级 | 保留，L0 规则层明确不用 Embedding（§4.5/§10） |
| §25 数据源评估 | 选型结论 §5（复用本机实测资产，否决 Tushare/AKShare 为主源） |
| §26 调度 | launchd 单入口（§4.3/§11） |
| §27 MVP 路线 | 重排（§14.2） |
| §29.4 Agent 必要性 | 六策略一引擎（§7.1） |
| §32 知识更新策略 | 节级更新机制（§9.2） |
| §36 成本模型 | 三档方案（§10.1） |
| §37 安全合规 | §12 |
