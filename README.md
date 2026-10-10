
# QQQM Investment Research Assistant

一个面向个人投资学习与研究的 Python 项目。以 QQQM 为主要研究对象，结合历史行情、技术指标与大语言模型，帮助投资新手理解市场变化、交易成本和策略回测。

## 当前功能

- 使用 EODHD API 获取 QQQM 历史日线行情。
- 使用 SQLite 保存本地行情数据。
- 增量更新行情并查看数据库状态。
- 计算历史收益率、移动平均线、RSI 和波动率等指标。
- 使用 DeepSeek API 生成中文市场研究报告。
- 将研究报告保存为 Markdown 文件。

## 技术栈

- Python 3.11
- SQLite
- Pandas
- EODHD API
- DeepSeek API
- yfinance（早期数据源，当前默认使用 EODHD）

## 环境配置

建议使用 Windows、VS Code 和 Python 3.11。

在项目根目录创建虚拟环境：

    uv venv --python 3.11 .venv

安装依赖：

    uv pip install --python .venv\Scripts\python.exe -r requirements.txt

## API 配置

复制配置模板：

    Copy-Item .env.example .env

在本地 `.env` 文件中填写自己的 API Key：

    DEEPSEEK_API_KEY=your_deepseek_api_key
    DEEPSEEK_BASE_URL=https://api.deepseek.com
    DEEPSEEK_MODEL=deepseek-flash

    MARKET_DATA_PROVIDER=eodhd
    EODHD_API_KEY=your_eodhd_api_key

不要将 `.env` 上传到 GitHub，也不要在代码中硬编码 API Key。

## 运行方法

同步 QQQM 一年历史日线：

    .\.venv\Scripts\python.exe main.py sync --period 1y --tickers QQQM

检查本地行情数据库：

    .\.venv\Scripts\python.exe main.py status

计算指标，不调用 AI：

    .\.venv\Scripts\python.exe main.py analyze --ticker QQQM --no-ai

生成 DeepSeek 研究报告：

    .\.venv\Scripts\python.exe main.py analyze --ticker QQQM

行情数据库保存在本地 `data/` 目录，生成的报告保存在 `reports/` 目录。上述本地数据不应提交到公开仓库。

## 后续计划

- 接入 FRED 宏观经济数据。
- 获取美联储公告、通胀数据及可靠财经新闻。
- 建立个人交易记录和手续费核算模块。
- 完善网格交易回测、权益曲线和最大回撤计算。
- 使用严格的历史滚动测试评估预测模型。

## 免责声明

本项目仅用于金融教育、个人研究和软件开发学习，不构成投资建议。技术指标及 AI 输出不能保证未来市场走势。

历史回测结果不代表未来收益。使用者应自行核验数据来源、数据授权、交易费用及分析结论。

