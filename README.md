# QQQM Investment Research Assistant

一个面向个人学习与研究的 Python 项目。第一阶段包含：

- 使用 `yfinance` 获取 QQQM、QQQ、SPY、TLT 的历史日线数据；
- 将行情增量保存到本地 SQLite 数据库；
- 计算基础技术指标；
- 使用 DeepSeek API 基于已计算的数据生成中文研究报告。

> 注意：`yfinance` 是第三方开源工具，使用公开的 Yahoo Finance 接口，主要定位于研究和教育。请自行遵守数据源条款。本项目不是自动交易程序，不构成投资建议。第一版没有接入实时新闻或宏观经济数据，也不应将模型内容当作可靠的价格预测。

## 环境要求

建议 Python 3.12 或 3.13。Windows 11 + VS Code + PowerShell 可以按以下步骤运行。

### 1. 创建虚拟环境并安装依赖

```powershell
py -0p
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果电脑没有 Python 3.12，请安装它，或把命令中的 `-3.12` 改为电脑上已有且能正常安装依赖的版本。

### 2. 配置 DeepSeek API

```powershell
Copy-Item .env.example .env
```

用 VS Code 打开 `.env`，将 `DEEPSEEK_API_KEY` 替换成自己在 DeepSeek 平台创建的密钥。不要将 `.env` 上传到 GitHub，不要把密钥贴到聊天、截图或代码中。

默认配置：

```text
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

如果控制台返回模型不可用，请进入 DeepSeek 开放平台查看该 API Key 当前可用的模型名，并修改 `.env` 中的 `DEEPSEEK_MODEL`。

### 3. 首次下载历史行情

```powershell
python main.py sync --period 5y
```

默认同步 `QQQM,QQQ,SPY,TLT`。第一次下载需要网络连接；Yahoo 接口可能偶尔限流或不可用，可以过一会儿重试。

只想先试 QQQM：

```powershell
python main.py sync --period 5y --tickers QQQM
```

### 4. 检查数据库

```powershell
python main.py status
```

本地数据库位于 `data/market_data.db`，不会提交到 GitHub。

### 5. 先计算指标，不调用 AI

```powershell
python main.py analyze --ticker QQQM --no-ai
```

### 6. 生成 DeepSeek 报告

确保 `.env` 里的 API Key 已配置，然后执行：

```powershell
python main.py analyze --ticker QQQM
```

报告会写入 `reports/` 文件夹。第一版只分析已下载的历史行情，不会搜索最新新闻。

## GitHub 建仓建议

在 GitHub 新建一个 **Private** 仓库，例如 `qqqm-investment-assistant`。如果你已经用这个本地目录和 README，请创建空仓库，不要再勾选自动生成 README、`.gitignore` 或 License，以免首次推送时出现无关冲突。之后：

```powershell
git init
git add .
git commit -m "Initial project scaffold"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/qqqm-investment-assistant.git
git push -u origin main
```

请先检查 `git status`，并确认 `.env`、数据库文件和生成报告没有进入待提交列表。
