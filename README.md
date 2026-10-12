# QQQM Investment Assistant

一个面向个人学习与研究的美股 ETF 投资分析工具。项目以 **QQQM（Invesco NASDAQ 100 ETF）** 为主要研究对象，整合历史行情、宏观经济数据、官方新闻、DeepSeek 研究报告和网格策略回测，并通过 Streamlit 提供本地 Web GUI。

> **风险提示：** 本项目用于编程学习、金融数据分析和历史回测，不构成投资建议，也不提供实盘交易执行。历史回测结果不代表未来收益。请在使用前核对数据来源、交易成本、策略规则和输出口径。

## 目录

- [功能概览](#功能概览)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [环境要求](#环境要求)
- [安装与配置](#安装与配置)
- [启动 GUI](#启动-gui)
- [命令行用法](#命令行用法)
- [回测说明](#回测说明)
- [数据与报告文件](#数据与报告文件)
- [常见问题](#常见问题)
- [后续计划](#后续计划)

## 功能概览

### 1. 市场概览

- 从本地 SQLite 数据库读取 QQQM 日线行情。
- 展示最新收盘价、近期收益率和历史收盘价曲线。
- 查看最近交易日数据及本地行情覆盖范围。

### 2. AI 市场分析

- 调用现有分析流程计算市场技术指标。
- 使用 DeepSeek 生成结构化研究报告。
- 报告保存在 `reports/` 目录，便于回看和留档。

### 3. 策略回测

- 支持基于滚动移动平均线偏离幅度的分层网格策略。
- 可以设置均线周期、网格步长、网格层数、每层资金以及初始账户资金（以当前 GUI 版本实际提供的参数为准）。
- 展示策略与买入持有基准的权益曲线、回撤曲线、收益与风险指标。
- 在价格曲线上标记实际买入和卖出成交点。
- 查看交易明细，并下载交易记录和资金曲线 CSV。
- 提供固定网格回测、参数扫描、仓位基准比较和滚动验证模块。

### 4. 宏观与新闻

- 从本地数据库查看 FRED 宏观观测数据，例如有效联邦基金利率、10 年期国债收益率、实际利率和 CPI 指数。
- 查看美国劳工统计局（BLS）的 CPI、失业率和非农就业等指标。
- 浏览本地保存的官方经济新闻，按来源、类别和关键词筛选。
- 查看数据同步状态与本地数据更新时间。

### 5. 数据状态

- 查看 SQLite 数据表以及各表的记录数量。
- 检查本地行情、宏观数据、新闻和回测报告是否可用。

## 技术栈

- **语言：** Python 3.11
- **GUI：** Streamlit
- **数据处理：** pandas、Altair
- **数据库：** SQLite
- **AI 报告：** DeepSeek API
- **行情与宏观数据：** EODHD、FRED、BLS 官方数据接口等
- **新闻：** 官方新闻源 / RSS 数据采集
- **回测输出：** Markdown、JSON、CSV

## 项目结构

```text
qqqm-investment-assistant/
├── app/
│   ├── config.py                  # 环境配置
│   ├── db.py                      # SQLite 数据库与行情查询
│   ├── market_data.py             # 行情同步
│   ├── indicators.py              # 技术指标与行情摘要
│   ├── macro_data.py              # 宏观数据同步与查询
│   ├── news_data.py               # 新闻数据处理与同步
│   ├── ai_report.py               # DeepSeek 研究报告生成
│   ├── dashboard.py               # Streamlit GUI
│   ├── backtest.py                # 固定网格回测
│   ├── parameter_scan.py          # 网格参数扫描
│   ├── exposure_benchmark.py      # 仓位基准比较
│   ├── rolling_backtest.py        # 滚动网格回测
│   ├── rolling_validation.py      # 训练区间选参与样本外验证
│   └── rolling_test_benchmark.py  # 测试区间与被动配置基准比较
├── data/
│   ├── market_data.db             # 本地 SQLite 数据库（本地生成）
│   └── QQQM_tiingo_history.csv    # Tiingo 历史数据（本地准备）
├── reports/                       # 分析、回测报告与 CSV（本地生成）
├── .env.example                   # 环境变量模板
├── .gitignore
├── main.py                        # 命令行入口
├── requirements.txt
└── README.md
```

说明：实际目录可能随开发迭代变化；未生成的数据文件或报告不会随源代码自动提供。`data/` 与 `reports/` 中的本地文件通常由用户自行同步或生成。

## 环境要求

- Windows 10/11，PowerShell（其他操作系统也可运行，但需调整路径与激活命令）。
- Python 3.11。
- `uv`（推荐）或可用的 Python 包安装工具。
- 网络连接，以及所需数据服务和 DeepSeek API 的访问权限。

## 安装与配置

以下命令以 Windows PowerShell 为例。请在项目根目录执行。

### 1. 创建虚拟环境

如果项目已有正常工作的 `.venv`，可以跳过创建步骤。

```powershell
uv venv --python 3.11 .venv
```

### 2. 安装依赖

建议使用 `uv` 向指定虚拟环境安装依赖，这也适用于虚拟环境中没有预装 `pip` 的情况。

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r .\requirements.txt
```

检查 Python 版本与依赖导入：

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m compileall -q .\main.py .\app
```

如果编译检查没有输出且没有报错，表示 Python 文件通过语法编译检查；这不等同于所有功能均已完成运行测试。

### 3. 配置环境变量

复制模板并编辑本地 `.env`：

```powershell
Copy-Item .\.env.example .\.env
notepad .\.env
```

根据 `.env.example` 的实际字段填写对应密钥。常见配置包括：

| 变量 | 用途 |
|---|---|
| `DEEPSEEK_API_KEY` | 调用 DeepSeek 生成 AI 报告 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址，模板通常使用 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 要调用的 DeepSeek 模型名称 |
| `MARKET_DATA_PROVIDER` | 行情数据提供方配置 |
| `EODHD_API_KEY` | EODHD 行情数据服务的 API Key |
| `TICKERS` | 默认研究标的列表 |
| `FRED_API_KEY` | 需要通过 FRED API 获取数据时使用 |
| `TIINGO_API_TOKEN` | 若本地数据获取脚本使用 Tiingo，可按相应脚本的配置要求填写 |

并非每个模块都必须使用以上全部变量。请以当前版本的 `.env.example` 和 `app/config.py` 为准。不要把真实 API Key 写入 README、源代码或截图。

**安全要求：** `.env` 应当被 `.gitignore` 忽略，严禁提交到公共仓库。公开前请检查 Git 暂存区中没有密钥、数据库、私人报告或不应发布的数据文件。

### 4. 准备历史数据

应用使用本地 SQLite 数据库 `data/market_data.db` 保存行情与宏观数据。可先通过 CLI 初始化并同步行情：

```powershell
.\.venv\Scripts\python.exe .\main.py sync --period max --tickers QQQM
.\.venv\Scripts\python.exe .\main.py status
```

行情供应商的免费套餐可能限制历史数据范围。滚动网格回测另外读取 `data/QQQM_tiingo_history.csv`。如果该文件不存在，需要根据项目所使用的 Tiingo 数据获取流程单独准备；仅同步 SQLite 行情不会自动保证这个 CSV 已经存在。

## 启动 GUI

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\app\dashboard.py
```

Streamlit 启动后，通常可以在浏览器访问：

```text
http://localhost:8501
```

GUI 当前包含「市场概览」「AI 分析」「策略回测」「宏观与新闻」「数据状态」等页面。

停止本地服务时，在运行 Streamlit 的终端按 `Ctrl + C` 即可。

## 命令行用法

以下命令均在项目根目录执行，并使用项目的虚拟环境 Python。

### 查看帮助

```powershell
.\.venv\Scripts\python.exe .\main.py --help
```

### 同步行情与查看状态

```powershell
.\.venv\Scripts\python.exe .\main.py sync --period max --tickers QQQM
.\.venv\Scripts\python.exe .\main.py status
```

`--period` 的可用格式以 `main.py --help` 为准；数据源可能限制可获取的历史范围。

### 生成分析报告

只计算指标、不调用 AI：

```powershell
.\.venv\Scripts\python.exe .\main.py analyze --ticker QQQM --with-macro --no-ai
```

生成 DeepSeek 报告：

```powershell
.\.venv\Scripts\python.exe .\main.py analyze --ticker QQQM --with-macro
```

### 同步宏观数据和新闻

```powershell
.\.venv\Scripts\python.exe .\main.py macro-sync
.\.venv\Scripts\python.exe .\main.py macro-status
.\.venv\Scripts\python.exe -m app.news_data sync
```

如果某条命令提示参数或子命令不存在，请先运行相应模块的 `--help`，以本地代码当前实现为准。

### 滚动网格回测

```powershell
.\.venv\Scripts\python.exe -m app.rolling_backtest --ticker QQQM --data-file .\data\QQQM_tiingo_history.csv --lookback 60 --step-pct 0.025 --levels 6 --cash-per-grid 1000
```

该模块的 `--step-pct` 使用小数表示百分比：例如 `0.025` 代表 2.5%。请不要将此模块的参数写法与 `rolling_test_benchmark` 混淆。

### 样本外滚动验证

例如，使用 2021 年及以前的数据选择参数，再测试 2022 年：

```powershell
.\.venv\Scripts\python.exe -m app.rolling_validation --ticker QQQM --data-file .\data\QQQM_tiingo_history.csv --train-end 2021-12-31 --test-start 2022-01-01 --test-end 2022-12-31
```

### 比较测试区间与被动配置基准

```powershell
.\.venv\Scripts\python.exe -m app.rolling_test_benchmark --ticker QQQM --data-file .\data\QQQM_tiingo_history.csv --start-date 2022-01-01 --end-date 2022-12-31 --lookback 60 --step-pct 2.5 --levels 6 --cash-per-grid 1000 --allocations 25 50 65 75 100
```

注意：在 `rolling_test_benchmark` 中，`--step-pct 2.5` 表示 2.5%；这与 `rolling_backtest` 使用 `0.025` 的参数约定不同。

其他模块包括固定网格回测、参数扫描以及仓位基准比较。具体参数请查看各模块的帮助信息，例如：

```powershell
.\.venv\Scripts\python.exe -m app.rolling_backtest --help
.\.venv\Scripts\python.exe -m app.rolling_validation --help
.\.venv\Scripts\python.exe -m app.rolling_test_benchmark --help
```

## 回测说明

当前滚动网格策略根据历史价格与过去一段时间的移动平均线偏离情况产生买入信号，并按策略规则在后续交易日执行。回测实现包含交易成本与滑点建模，并记录现金、持股、权益、成交价格和交易费用等信息。准确的触发规则与参数应以当前 `app/rolling_backtest.py` 的实现及生成的报告为准。

需要理解以下限制：

1. **样本区间会影响结论。** 趋势明显上涨、持续下跌与震荡市场中的策略表现可能差异很大。
2. **低仓位不等于策略能力更强。** 网格策略与被动持有的平均仓位可能不同，比较收益时也要看最大回撤、波动率、平均仓位、费用等指标。
3. **基准不一定严格风险匹配。** 不同初始配置比例的被动持有基准只能提供参考，不能直接证明某个策略在相同风险水平下更优。
4. **参数选择存在过拟合风险。** 不应根据已经观察过的测试区间反复挑选最佳参数，再把同一区间的结果当作独立验证。应事先冻结规则，采用时间顺序的训练与测试区间。
5. **历史模拟不是实盘复现。** 滑点、手续费、分红处理、成交条件、数据质量和实际可成交性都会影响真实结果。

## 数据与报告文件

常见本地文件：

- `data/market_data.db`：行情、宏观观测和新闻的 SQLite 数据库。
- `data/QQQM_tiingo_history.csv`：滚动回测使用的历史行情 CSV。
- `reports/`：AI 分析报告、回测 Markdown/JSON、交易记录 CSV 和权益曲线 CSV。

这些文件可能包含较大的历史数据或本地生成结果，默认不必全部提交到 Git。若需要发布演示数据，应先确认数据服务条款、数据许可和文件中是否包含私人信息。API 密钥和 `.env` 永远不应公开。

## 常见问题

### 1. `No module named pip`

虚拟环境可能没有预装 pip。可以使用 `uv` 安装依赖：

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r .\requirements.txt
```

### 2. Streamlit 提示找不到 `app/dashboard.py`

确认文件存在于项目根目录下的 `app/dashboard.py`，而不是 `reports/` 或其他目录。检查：

```powershell
Test-Path .\app\dashboard.py
```

### 3. 缺少 `data/QQQM_tiingo_history.csv`

该文件是滚动网格回测所需的本地历史数据文件。请按项目的数据准备流程获取文件并放入 `data/`；不要把它改名成数据库文件。

### 4. AI 报告生成失败

检查 `.env` 中的 DeepSeek 配置、API 额度、网络连接以及终端显示的错误信息。密钥应只保存在本地 `.env` 中，排查问题时不要粘贴真实密钥。

### 5. 宏观数据或新闻同步失败

检查网络访问、数据源可用性和模块输出。数据发布时间不固定，本地最后一条观测记录不一定代表数据源已经发布了最新一期数据。新闻同步也可能受到 RSS 或网站访问限制。

### 6. 回测模块参数不匹配

先执行对应模块的 `--help`。不同回测模块对百分比参数的输入格式可能不同，不能直接复制另一个模块的参数值。

### 7. PowerShell 中文显示成 `???`

这可能是终端编码或字体显示问题，不一定代表数据库内容损坏。可尝试在 PowerShell 中执行：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

## 后续计划

- 完善 GUI 的错误处理、数据新鲜度提示与同步状态展示。
- 继续核验回测指标、资金曲线、手续费和交易记录的一致性。
- 改进策略参数验证流程，保持时间顺序的样本外测试。
- 整理演示截图、开发说明和可复现的测试流程。
- 在数据许可允许的情况下，准备适合公开展示的示例数据。

## Disclaimer

This project is for educational and research purposes only. It is not financial advice and does not execute live trades. Historical backtest performance does not guarantee future results. Verify data sources, assumptions, transaction costs, and all outputs independently before using them for any decision.
