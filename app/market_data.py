from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

from app.db import initialize_database, upsert_history


def _period_start(period: str) -> str:
    """Convert a small yfinance-like period string to an ISO start date."""
    value = period.strip().lower()
    today = date.today()
    if value == "max":
        # EODHD free plans only provide one year. Paid plans may provide more.
        return "2000-01-01"
    match = re.fullmatch(r"(\d+)(d|mo|y)", value)
    if not match:
        raise ValueError("period 仅支持例如 30d、6mo、1y、5y 或 max。")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        start = today - timedelta(days=amount)
    elif unit == "mo":
        start = today - timedelta(days=round(amount * 30.4375))
    else:
        start = today - timedelta(days=round(amount * 365.2425))
    return start.isoformat()


def _fetch_eodhd(ticker: str, period: str) -> pd.DataFrame:
    api_key = os.getenv("EODHD_API_KEY", "").strip()
    if not api_key or api_key == "replace_with_your_eodhd_api_key":
        raise RuntimeError(
            "未配置 EODHD_API_KEY。请在项目根目录的 .env 文件中填写 EODHD API Token。"
        )

    symbol = ticker.upper()
    if not symbol.endswith(".US"):
        symbol = f"{symbol}.US"
    params = {
        "api_token": api_key,
        "fmt": "json",
        "from": _period_start(period),
        "to": date.today().isoformat(),
        "period": "d",
    }
    url = f"https://eodhd.com/api/eod/{symbol}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "QQQM-Investment-Assistant/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"EODHD HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接 EODHD：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("EODHD 返回的内容不是有效 JSON。") from exc

    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error") or payload.get("detail") or str(payload)
        raise RuntimeError(f"EODHD 返回错误：{message}")
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(
            f"EODHD 没有返回 {symbol} 的日线数据。请检查标的代码、API Token 和套餐权限。"
        )

    df = pd.DataFrame(payload)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"EODHD 返回字段不完整：{list(df.columns)}")

    df["Date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "adjusted_close": "Adj Close",
            "volume": "Volume",
        }
    )
    if "Adj Close" not in df.columns:
        df["Adj Close"] = df["Close"]
    df["Dividends"] = 0.0
    df["Stock Splits"] = 0.0
    for column in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df[["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]]


def _fetch_yfinance(ticker: str, period: str) -> pd.DataFrame:
    instrument = yf.Ticker(ticker)
    return instrument.history(
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=True,
        repair=True,
        raise_errors=True,
    )


def sync_ticker(ticker: str, period: str = "1y") -> int:
    """Fetch daily OHLCV from the configured provider and upsert it into SQLite."""
    provider = os.getenv("MARKET_DATA_PROVIDER", "eodhd").strip().lower()
    ticker = ticker.upper()
    print(f"[行情同步] 数据源={provider}，正在下载 {ticker} 的 {period} 日线数据……")

    if provider == "eodhd":
        history = _fetch_eodhd(ticker, period)
        source = "eodhd"
    elif provider == "yfinance":
        history = _fetch_yfinance(ticker, period)
        source = "yfinance"
    else:
        raise ValueError("MARKET_DATA_PROVIDER 仅支持 eodhd 或 yfinance。")

    if history.empty:
        raise RuntimeError(
            f"{ticker} 没有返回行情。请检查网络、标的代码、数据源权限或请求限制。"
        )

    initialize_database()
    saved = upsert_history(ticker, history, source=source)
    latest_date = history.index[-1].date().isoformat()
    print(f"[完成] {ticker}: 本次写入/更新 {saved} 条记录，最新行情日期 {latest_date}，来源 {source}")
    if provider == "eodhd" and period.strip().lower() not in {"1y", "12mo", "365d"}:
        print("[提示] EODHD 免费方案历史范围为过去一年；请求更长范围可能需要付费权限，请检查实际返回记录的起止日期。")
    return saved
