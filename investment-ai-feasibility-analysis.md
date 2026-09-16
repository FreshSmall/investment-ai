# AI 股票研究与投资知识系统：可行性分析与执行方案

## 1. 项目背景

希望建立一个长期运行的 AI 股票研究系统，将：

- 市场数据
- 新闻资讯
- 公司公告
- 财务数据
- 行业数据
- AI 分析
- 投资假设（Investment Thesis）
- 每日/每周复盘
- Obsidian 知识库

串成一个自动化闭环。

目标不是让 AI 直接“推荐股票”，而是建立一个**持续获取信息 → 结构化分析 → 更新研究结论 → 验证投资假设 → 沉淀知识**的研究系统。

核心研究方向暂定为：

1. AI / 半导体
2. 电力 / 电网 / 储能
3. 机器人 / 人形机器人

---

# 2. 核心目标

## 2.1 长期目标

形成如下闭环：

```text
外部信息
  ↓
数据采集
  ↓
清洗 / 去重 / 标准化
  ↓
重要性判断
  ↓
AI 分析
  ↓
行业 / 公司 / 催化剂 / 市场分析
  ↓
投资假设验证
  ↓
更新知识库
  ↓
每日 / 每周 / 每月复盘
  ↓
形成新的研究问题
  ↓
进入下一轮信息采集
```

最终希望系统能够回答：

- 最近市场发生了什么？
- 哪些变化与我的核心研究行业有关？
- 行业发生了什么变化？
- 这些变化如何传导到企业？
- 哪些公司可能受到影响？
- 这是短期情绪变化还是基本面变化？
- 当前信息支持还是削弱了哪些投资假设？
- 哪些观点已经被市场定价？
- 哪些关键指标需要继续跟踪？
- 我的研究结论是否需要修改？

---

# 3. 设计原则

## 3.1 AI 不负责“直接炒股”

系统不以：

> “今天买什么股票？”

作为核心目标。

而是建立：

```text
事实
 ↓
解释
 ↓
因果链
 ↓
假设
 ↓
证据
 ↓
反证
 ↓
验证条件
```

最终由人做投资决策。

---

## 3.2 区分 Fact / Interpretation / Hypothesis / Opinion

AI 输出中必须尽量区分：

### Fact

可以被外部来源验证的事实。

例如：

> 某公司公告新增产能 10 万片/月。

### Interpretation

基于事实进行的分析。

例如：

> 新增产能可能意味着公司正在判断未来需求增长。

### Hypothesis

需要未来验证的假设。

例如：

> AI 服务器需求持续增长可能推动相关 PCB 需求增加。

### Opinion

主观判断。

例如：

> 当前市场可能对该产业链存在过度乐观预期。

系统不能把 AI 推测包装成事实。

---

# 4. 核心因果链

所有行业和公司研究尽量围绕以下链条展开：

```text
产业变化
 ↓
需求
 ↓
供给
 ↓
价格
 ↓
订单
 ↓
收入
 ↓
利润
 ↓
业绩预期
 ↓
估值
 ↓
资金
 ↓
股价
```

研究时重点判断：

> 当前变化处于产业链的哪个环节？

以及：

> 这个变化能否继续向下游传导？

例如：

```text
AI 算力需求增长
 ↓
GPU / ASIC 需求
 ↓
服务器出货
 ↓
PCB / 光模块 / HBM / 封装需求
 ↓
相关企业订单增长
 ↓
收入增长
 ↓
利润增长
 ↓
市场上调盈利预期
 ↓
估值变化
 ↓
股价变化
```

---

# 5. 系统总体架构

建议采用：

```text
                    ┌────────────────────┐
                    │     定时调度器      │
                    │ launchd / cron     │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │    Pipeline        │
                    │    Orchestrator    │
                    └─────────┬──────────┘
                              ↓
          ┌───────────────────┼───────────────────┐
          ↓                   ↓                   ↓
     新闻采集器           行情采集器           公告采集器
     News Collector       Market Collector     Announcement
          ↓                   ↓                   ↓
          └───────────────────┼───────────────────┘
                              ↓
                    ┌────────────────────┐
                    │ 清洗 / 去重 / 分类  │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │    AI Analysis     │
                    ├────────────────────┤
                    │ Industry Agent     │
                    │ Company Agent      │
                    │ Catalyst Agent     │
                    │ Market Agent       │
                    │ Devil Advocate     │
                    │ Thesis Agent       │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │ Knowledge Writer   │
                    │ Knowledge Updater  │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │     Obsidian       │
                    │    Knowledge Base  │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │ Daily / Weekly     │
                    │ Monthly Reports    │
                    └────────────────────┘
```

---

# 6. 技术职责划分

一个重要原则：

## Python 负责确定性工作

例如：

- 定时调度
- 数据采集
- API 调用
- 数据清洗
- 数据去重
- 数据结构化
- 状态管理
- 任务重试
- Markdown 文件写入
- 日志
- 缓存
- 数据库操作

## AI 负责非确定性工作

例如：

- 信息理解
- 新闻分类
- 行业影响分析
- 公司影响分析
- 因果链分析
- 催化剂分析
- 反方观点
- Investment Thesis 验证
- 研究问题生成

不要让定时任务每天直接运行一个超大的 Claude Prompt。

应该采用：

```text
Scheduler
    ↓
Python Pipeline
    ↓
Structured Data
    ↓
LLM
    ↓
Structured JSON
    ↓
Python
    ↓
Markdown
```

---

# 7. 项目目录建议

```text
investment-ai/
│
├── CLAUDE.md
│
├── config/
│   ├── settings.yaml
│   ├── sectors.yaml
│   └── companies.yaml
│
├── collectors/
│   ├── news.py
│   ├── market.py
│   ├── announcements.py
│   ├── financials.py
│   └── industry_data.py
│
├── pipeline/
│   ├── ingest.py
│   ├── clean.py
│   ├── dedup.py
│   ├── classify.py
│   ├── importance.py
│   └── pipeline.py
│
├── agents/
│   ├── industry.py
│   ├── company.py
│   ├── catalyst.py
│   ├── market.py
│   ├── devil_advocate.py
│   └── thesis.py
│
├── knowledge/
│   ├── writer.py
│   ├── linker.py
│   └── updater.py
│
├── reports/
│   ├── daily.py
│   ├── weekly.py
│   └── monthly.py
│
├── prompts/
│   ├── industry.md
│   ├── company.md
│   ├── market.md
│   ├── catalyst.md
│   ├── devil_advocate.md
│   └── thesis.md
│
├── models/
│   ├── event.py
│   ├── company.py
│   ├── industry.py
│   └── thesis.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── cache/
│
├── logs/
│
├── tests/
│
└── main.py
```

---

# 8. 研究行业配置

第一阶段重点研究：

```yaml
sectors:

  ai_semiconductor:
    name: AI / 半导体
    keywords:
      - AI
      - GPU
      - ASIC
      - HBM
      - 光模块
      - CPO
      - PCB
      - 先进封装
      - 半导体设备
      - 半导体材料
      - 数据中心

  power_energy:
    name: 电力 / 电网 / 储能
    keywords:
      - 数据中心电力
      - 电网
      - 变压器
      - 储能
      - UPS
      - 电力电子

  robotics:
    name: 机器人 / 人形机器人
    keywords:
      - 人形机器人
      - 具身智能
      - 减速器
      - 丝杠
      - 灵巧手
      - 传感器
```

---

# 9. 行业研究模型

每个行业建立一个长期研究对象。

例如：

```text
Industries/
├── AI-Semiconductor.md
├── Power-Energy.md
└── Robotics.md
```

每个行业研究至少包含：

```text
1. 行业定义
2. 产业链
3. 上游
4. 中游
5. 下游
6. 核心需求
7. 供给结构
8. 行业竞争格局
9. 价格变化
10. 订单变化
11. 景气度
12. 行业周期
13. 核心公司
14. 核心催化剂
15. 核心风险
16. 当前市场预期
17. 需要持续跟踪的指标
```

---

# 10. 公司研究模型

目录：

```text
Companies/
├── Company-A.md
├── Company-B.md
└── Company-C.md
```

研究维度：

```text
公司定位
 ↓
收入结构
 ↓
行业暴露
 ↓
核心产品
 ↓
竞争优势
 ↓
客户
 ↓
订单
 ↓
产能
 ↓
收入
 ↓
利润
 ↓
现金流
 ↓
估值
 ↓
市场预期
 ↓
风险
```

重点不是简单记录：

> “这家公司很好。”

而是回答：

> “什么变化会让这家公司的盈利预期发生变化？”

---

# 11. Investment Thesis

建立：

```text
Theses/
├── AI-demand-growth.md
├── HBM-cycle.md
├── Power-infrastructure.md
└── Humanoid-robot-growth.md
```

每个 Thesis 使用统一结构：

```markdown
# Investment Thesis

## Research Object

## Core Hypothesis

## Why

## Supporting Evidence

## Counter Evidence

## Falsification Conditions

## Key Metrics

## Current Status

## Latest Changes

## Next Research Questions
```

例如：

```text
核心假设：

AI 数据中心建设持续增长。

支持证据：

- 数据中心资本开支增长
- GPU 出货增长
- 服务器需求增长
- 光模块需求增长

反证：

- 云厂商资本开支下降
- GPU 需求低于预期
- 数据中心建设放缓

证伪条件：

如果未来多个季度核心需求指标持续下降，
则该假设需要重新评估。
```

---

# 12. Devil's Advocate

系统不能只有“支持观点”。

应该建立独立的反方分析 Agent：

```text
当前 Thesis
      ↓
寻找反证
      ↓
寻找数据矛盾
      ↓
寻找市场过度定价
      ↓
寻找逻辑断点
      ↓
寻找替代解释
      ↓
输出证伪条件
```

重点区分：

### 理论风险

> “可能存在需求下降。”

### 实际反证

> “最新季度订单同比下降 20%。”

后者才应该显著影响 Thesis 状态。

---

# 13. Daily Review

每日复盘建议拆成两个阶段。

## 13.1 上午研究

建议时间：

```text
07:30
```

处理过去 24 小时：

```text
海外市场
 ↓
行业新闻
 ↓
公司公告
 ↓
产业数据
 ↓
重要事件
 ↓
AI / 半导体
 ↓
电力 / 储能
 ↓
机器人
```

输出：

```text
Daily Morning Research
```

---

# 14. 晚间市场复盘

建议：

```text
18:00
```

采集：

```text
A 股指数
行业涨跌
成交额
涨停
跌停
炸板
连板
核心个股
板块强度
市场情绪
资金变化
```

重点分析：

```text
市场发生了什么？
 ↓
哪个行业发生变化？
 ↓
核心行业是否仍然强？
 ↓
市场是否出现分歧？
 ↓
分歧之后是否回流？
 ↓
是否发生主线切换？
 ↓
市场行为是否验证基本面逻辑？
```

---

# 15. Thesis Review

建议：

```text
21:00
```

不是重新分析全部市场。

而是回答：

```text
今天的信息
 ↓
是否影响长期 Thesis？
```

输出：

```text
支持
中性
削弱
```

并说明：

```text
为什么？
证据是什么？
是否需要修改假设？
下一步需要验证什么？
```

---

# 16. Weekly Review

每周日自动执行。

输入：

```text
过去 7 天 Daily Research
+
过去 7 天 Market Review
+
过去 7 天 Thesis Review
```

输出：

```text
本周行业变化
本周重要公司变化
本周市场变化
重要催化剂
重要反证
哪些 Thesis 发生变化
哪些研究结论被验证
哪些结论被证伪
下周重点跟踪指标
新的研究问题
```

---

# 17. Monthly Review

每月进行一次更高层级的复盘。

重点：

```text
行业景气度变化
盈利预期变化
市场风格变化
核心 Thesis 演化
研究错误
认知盲点
新的研究方向
```

目标是形成长期研究能力，而不是每天产生大量 Markdown。

---

# 18. Obsidian 知识库

建议：

```text
Investment-KB/
│
├── Industries/
│   ├── AI-Semiconductor.md
│   ├── Power-Energy.md
│   └── Robotics.md
│
├── Companies/
│
├── Theses/
│
├── Daily/
│
├── Weekly/
│
├── Monthly/
│
└── Reports/
```

推荐通过 Obsidian Wiki Link 建立关系：

```text
AI
  ↓
半导体
  ↓
HBM
  ↓
先进封装
  ↓
相关公司
  ↓
相关 Thesis
  ↓
Daily Research
```

让知识库逐渐形成：

```text
Industry
    ↕
Company
    ↕
Event
    ↕
Thesis
    ↕
Market
```

---

# 19. 数据模型

不要直接让 AI 输出 Markdown。

推荐：

```text
数据采集
 ↓
标准化 Event
 ↓
LLM 输出 JSON
 ↓
Python 校验
 ↓
Markdown Renderer
```

例如事件：

```json
{
  "event_id": "xxx",
  "source": "source_name",
  "source_url": "https://...",
  "published_at": "2026-09-16T10:00:00",
  "title": "xxx",
  "content": "xxx",
  "sector": ["ai_semiconductor"],
  "companies": ["company_a"],
  "event_type": "capacity_expansion",
  "importance": "high"
}
```

---

# 20. 数据去重

必须考虑幂等性。

同一新闻可能来自：

```text
媒体 A
媒体 B
媒体 C
```

需要：

```text
source
+
source_id
+
content_hash
```

进行去重。

避免每天重复分析同一事件。

---

# 21. 增量处理

系统应该记录：

```text
last_run_at
watermark
processed_event_id
```

例如：

```text
第一次运行
↓
处理 1000 条

第二次运行
↓
只处理新增 50 条
```

而不是每天重新处理全部历史数据。

---

# 22. 失败处理

需要具备：

```text
Timeout
Retry
Error Log
Dead Letter
任务状态
```

例如：

```text
采集失败
 ↓
Retry 3 次
 ↓
仍然失败
 ↓
记录 Error
 ↓
继续执行其他数据源
```

不能因为某个数据源失败导致整个 Pipeline 停止。

---

# 23. AI 成本控制

不能把所有新闻都交给高级模型深度分析。

推荐：

```text
10000 条信息
      ↓
规则 / Embedding / 轻量模型
      ↓
1000 条相关信息
      ↓
重要性分类
      ↓
100 条重要信息
      ↓
高级 LLM 深度分析
```

形成：

```text
Cheap Filter
      ↓
Important Events
      ↓
Deep Analysis
```

---

# 24. 信息来源优先级

建议：

```text
第一优先级
公司公告
交易所
监管机构
政府部门
官方统计

第二优先级
行业协会
权威产业数据

第三优先级
海外公司财报
海外官方资料

第四优先级
主流财经媒体

第五优先级
券商研究

第六优先级
社交媒体
论坛
```

社交媒体主要用于：

```text
发现线索
```

而不是作为核心事实来源。

---

# 25. 数据源需要重点评估的问题

ZCode 需要重点调查：

### A 股行情

需要：

- 实时 / 延迟行情
- 日线
- 分钟线
- 行业分类
- 涨跌停
- 成交额
- 资金数据

### 公司公告

需要：

- 公告
- 财报
- 业绩预告
- 重大合同
- 产能
- 股权变化

### 财务数据

需要：

- 营收
- 净利润
- 毛利率
- 净利率
- ROE
- 现金流
- 资产负债率
- 估值

### 行业数据

需要：

- 产能
- 出货量
- 价格
- 库存
- 订单
- CAPEX
- 行业渗透率

必须评估：

```text
数据质量
API 稳定性
调用频率限制
商业授权
价格
历史数据完整度
```

---

# 26. 调度方案

第一阶段运行在个人 Mac。

不建议一开始引入：

```text
Airflow
Kafka
Kubernetes
Flink
```

系统规模没有必要。

可以使用：

```text
launchd
```

或者：

```text
cron
```

Mac 更推荐：

```text
launchd
```

调度：

```text
07:30 Morning Research

18:00 Market Review

21:00 Thesis Review

Sunday Weekly Review

Monthly Monthly Review
```

---

# 27. MVP 路线

## V0.1

目标：

```text
新闻
 ↓
AI
 ↓
Markdown
```

只解决：

- 数据采集
- 去重
- AI 摘要
- 行业分类
- Obsidian 写入

---

## V0.2

加入：

```text
行业研究
```

能够自动更新：

```text
AI / 半导体
电力 / 储能
机器人
```

---

## V0.3

加入：

```text
A 股行情
```

能够自动分析：

```text
指数
行业
涨跌
成交额
市场情绪
核心股票
```

---

## V0.4

加入：

```text
财务数据
```

---

## V0.5

加入：

```text
行业数据库
```

---

## V0.6

加入：

```text
Investment Thesis
```

---

## V0.7

加入：

```text
Devil's Advocate
```

---

## V0.8

加入：

```text
Weekly Review
Monthly Review
```

---

## V1.0

加入：

```text
Python Backtest
Factor Research
策略验证
```

注意：

> 回测系统应该独立于研究系统，不要把“AI 研究”和“自动交易”直接耦合。

---

# 28. 推荐的系统演进

最终可以形成：

```text
                ┌─────────────────────┐
                │    External Data    │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │   Data Platform     │
                │ Clean / Dedup       │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │     AI Research     │
                ├─────────────────────┤
                │ Industry            │
                │ Company             │
                │ Catalyst            │
                │ Market              │
                │ Devil Advocate      │
                │ Thesis              │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │ Knowledge Base      │
                │      Obsidian       │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │ Daily / Weekly      │
                │ Monthly Review      │
                └──────────┬──────────┘
                           ↓
                ┌─────────────────────┐
                │ Research Questions  │
                └──────────┬──────────┘
                           │
                           └──────→ 下一轮研究
```

---

# 29. ZCode 可行性分析任务

请不要直接开始写完整系统。

第一阶段请先对本方案进行技术可行性分析。

重点回答以下问题：

## 29.1 整体架构是否合理

分析：

- Python + LLM + Obsidian 架构是否合理
- 是否需要数据库
- 是否需要消息队列
- 是否需要 Agent Framework
- 是否需要 MCP
- 是否适合运行在个人 Mac
- 哪些设计存在过度设计

---

## 29.2 数据源分析

针对以下数据进行调研：

```text
A 股行情
公司公告
财务数据
行业数据
新闻
海外市场
```

请比较可选数据源：

```text
API
开源数据
商业数据
爬虫
```

并分析：

```text
数据质量
稳定性
成本
授权风险
API 限制
历史数据
实时数据
```

最终给出第一阶段建议的数据源组合。

---

## 29.3 LLM 方案

比较：

```text
Claude
GPT
Gemini
本地模型
```

从以下角度分析：

```text
中文能力
长上下文
结构化输出
分析能力
成本
API 稳定性
```

重点设计：

```text
轻量模型
      ↓
重要性筛选
      ↓
高级模型
      ↓
深度分析
```

---

## 29.4 Agent 是否必要

分析以下 Agent 是否应该独立：

```text
Industry Agent
Company Agent
Catalyst Agent
Market Agent
Devil Advocate Agent
Thesis Agent
```

判断：

- 是否需要多个 Agent
- 哪些应该合并
- 哪些应该拆分
- 是否应该使用 Workflow 替代 Agent
- 如何控制上下文
- 如何降低成本

---

# 30. ZCode 需要重点分析的数据流

请重点设计：

```text
Raw Event
 ↓
Normalized Event
 ↓
Classified Event
 ↓
Important Event
 ↓
Industry Analysis
 ↓
Company Impact
 ↓
Thesis Impact
 ↓
Knowledge Update
 ↓
Daily Report
```

每一步明确：

```text
Input
Output
数据结构
调用方
失败处理
幂等策略
```

---

# 31. AI 输出格式

不要让 AI 直接自由生成 Markdown。

优先考虑：

```text
JSON Schema
```

例如：

```json
{
  "summary": "",
  "facts": [],
  "interpretations": [],
  "hypotheses": [],
  "affected_industries": [],
  "affected_companies": [],
  "causal_chain": [],
  "supporting_evidence": [],
  "counter_evidence": [],
  "uncertainty": [],
  "follow_up_questions": []
}
```

然后由 Python：

```text
JSON
 ↓
Markdown Renderer
 ↓
Obsidian
```

---

# 32. 知识库更新策略

重点分析：

> AI 每天生成大量 Markdown 后，如何避免知识库变成垃圾场？

需要设计：

```text
事件层
 ↓
Daily
 ↓
Weekly
 ↓
Industry
 ↓
Company
 ↓
Thesis
```

不同层级承担不同职责。

推荐：

### Event

记录原始事件。

### Daily

记录当天变化。

### Weekly

提炼一周变化。

### Industry

长期行业知识。

### Company

长期公司知识。

### Thesis

记录核心投资假设及其验证状态。

---

# 33. 重要性分级

建议设计：

```text
P0
重大市场 / 公司事件

P1
重要行业变化

P2
一般行业信息

P3
低价值信息
```

不同等级使用不同 AI 分析深度。

例如：

```text
P0 → Deep Research
P1 → Standard Analysis
P2 → Summary
P3 → Archive
```

---

# 34. 系统稳定性要求

请重点设计：

## 幂等

重复运行不会产生重复结果。

## 可恢复

某个步骤失败后，可以从失败节点继续。

## 可观测

能够看到：

```text
本次运行时间
处理数据量
成功数量
失败数量
LLM 调用次数
Token
成本
耗时
```

## 可追溯

每个 AI 结论都能够找到：

```text
原始数据
来源
时间
URL
```

---

# 35. 需要避免的过度设计

第一阶段原则：

```text
能不用就不用：
Kafka
Redis
Kubernetes
Airflow
复杂 Agent Framework
向量数据库
复杂微服务
```

优先：

```text
Python
SQLite
YAML
Markdown
Obsidian
launchd
LLM API
```

如果未来数据量和任务复杂度增加，再演进。

---

# 36. 成本模型

请估算：

```text
每天新闻数量
每天行情数据量
每天 AI 调用次数
平均 Token
模型价格
每天成本
每月成本
```

并给出：

```text
低成本方案
平衡方案
高质量方案
```

重点分析：

> 如何通过缓存、去重、摘要、分层模型降低 LLM 成本。

---

# 37. 安全与数据合规

分析：

- API Key 如何保存
- 本地配置如何管理
- 日志是否可能泄露 Key
- 外部数据授权问题
- 新闻抓取是否合法合规
- 商业行情数据能否长期存储
- Obsidian 数据是否需要加密

---

# 38. 最终要求 ZCode 输出的内容

请在完成分析后，不直接开始全部编码。

先输出一份：

```text
investment-ai-feasibility.md
```

内容至少包含：

## 1. 总体可行性

```text
可行 / 有条件可行 / 不建议
```

并说明原因。

## 2. 架构调整建议

指出：

```text
保留什么
删除什么
新增什么
哪些是过度设计
```

## 3. 技术选型

给出：

```text
Python
数据库
调度
LLM
数据源
Obsidian
```

的具体建议及理由。

## 4. 数据源方案

列出候选方案并比较：

```text
价格
稳定性
数据范围
实时性
授权
开发成本
```

## 5. AI Workflow

明确：

```text
哪些步骤使用代码
哪些步骤使用 LLM
哪些步骤需要 Agent
哪些步骤使用 Workflow
```

## 6. 数据模型

设计：

```text
Event
Industry
Company
Thesis
DailyReport
WeeklyReport
```

的数据结构。

## 7. Pipeline

给出完整执行流程：

```text
Scheduler
 ↓
Collector
 ↓
Normalize
 ↓
Dedup
 ↓
Classify
 ↓
Importance
 ↓
AI Analysis
 ↓
Knowledge Update
 ↓
Report
```

## 8. MVP

明确 V0.1 应该做什么。

要求：

> V0.1 必须能够真正每天自动运行，而不是只完成 Demo。

## 9. 详细执行计划

按照：

```text
Phase 1
Phase 2
Phase 3
...
```

拆解。

每个阶段说明：

```text
目标
任务
代码模块
输入
输出
验收标准
```

## 10. 风险清单

至少分析：

```text
数据源风险
AI 幻觉
数据授权
成本
系统稳定性
知识库膨胀
错误分析
重复分析
```

## 11. 测试方案

至少包含：

```text
Unit Test
Integration Test
Pipeline Test
LLM Output Validation
Idempotency Test
Failure Recovery Test
```

## 12. 最终目录结构

根据实际分析结果重新设计项目目录。

不要机械采用本文目录。

---

# 39. 第二阶段：生成实施 Plan

完成可行性分析后，再生成：

```text
implementation-plan.md
```

要求：

```text
按 MVP 优先级拆解
每个任务可以独立执行
明确依赖关系
明确输入输出
明确验收标准
```

例如：

```text
TASK-001
初始化 Python 项目

TASK-002
建立 SQLite 数据模型

TASK-003
实现 Event Collector

TASK-004
实现 Dedup

TASK-005
实现 LLM Gateway

TASK-006
实现 News Analysis

TASK-007
实现 Obsidian Writer

TASK-008
实现 Daily Pipeline

TASK-009
实现 launchd

TASK-010
端到端测试
```

---

# 40. 第三阶段：再开始编码

只有完成：

```text
feasibility analysis
        ↓
architecture adjustment
        ↓
implementation plan
        ↓
review
```

之后再进入编码。

编码要求：

1. 优先 MVP。
2. 不提前实现未来功能。
3. 每个模块保持清晰边界。
4. 所有外部数据源通过 Adapter 抽象。
5. LLM 通过统一 Gateway 抽象。
6. AI 输出必须进行 Schema 校验。
7. Pipeline 必须支持重试和幂等。
8. 所有关键 AI 结论保留来源。
9. 不把 AI 生成的判断直接当成事实。
10. 不实现自动交易，第一阶段只做研究和分析。

---

# 41. 最终系统目标

最终希望形成：

```text
              ┌───────────────┐
              │   外部世界     │
              │ 新闻/公告/行情 │
              └───────┬───────┘
                      ↓
              ┌───────────────┐
              │   Data Layer  │
              └───────┬───────┘
                      ↓
              ┌───────────────┐
              │   AI Research │
              └───────┬───────┘
                      ↓
              ┌───────────────┐
              │ Knowledge Base│
              └───────┬───────┘
                      ↓
              ┌───────────────┐
              │ Thesis System │
              └───────┬───────┘
                      ↓
              ┌───────────────┐
              │ Daily Review  │
              └───────┬───────┘
                      ↓
              ┌───────────────┐
              │ Research Loop │
              └───────┬───────┘
                      │
                      └──────────────→ 下一轮研究
```

核心目标不是：

> AI 替我决定买什么。

而是：

> AI 帮我持续建立、验证和更新对行业、公司和市场的认知。

系统最终应该成为一个：

**“持续运行的 AI 投资研究员 + 个人投资知识库 + Thesis 验证系统”**。
