from __future__ import annotations

import argparse
import sys

from app.ai_report import generate_report
from app.config import get_tickers
from app.db import database_status, initialize_database, load_history
from app.indicators import build_summary
from app.market_data import sync_ticker


def command_sync(args: argparse.Namespace) -> int:
    initialize_database()
    tickers = [item.upper() for item in args.tickers] if args.tickers else get_tickers()
    errors = 0
    for ticker in tickers:
        try:
            sync_ticker(ticker, period=args.period)
        except Exception as exc:  # Keep syncing other tickers when one provider call fails.
            errors += 1
            print(f"[失败] {ticker}: {exc}")
    return 1 if errors == len(tickers) else 0


def command_status(_: argparse.Namespace) -> int:
    rows = database_status()
    if not rows:
        print("数据库中还没有行情。先执行：python main.py sync --period 5y")
        return 0
    print("本地行情数据库状态：")
    for row in rows:
        print(
            f"{row['ticker']:6} | {row['rows_count']:5} 条 | "
            f"{row['first_date']} -> {row['last_date']} | "
            f"最近同步：{row['last_fetched_at']}"
        )
    return 0


def command_analyze(args: argparse.Namespace) -> int:
    ticker = args.ticker.upper()
    history = load_history(ticker)
    summary = build_summary(ticker, history)
    print(f"行情最新日期：{summary['latest_date']}")
    print(f"最新收盘价：{summary['metrics']['close']}")
    print(f"5 日收益率：{summary['metrics']['return_5d_pct']}%")
    print(f"20 日收益率：{summary['metrics']['return_20d_pct']}%")
    print(f"RSI(14)：{summary['metrics']['rsi_14']}")
    if args.no_ai:
        print("已完成指标摘要。由于指定 --no-ai，本次不调用 DeepSeek。")
        return 0
    try:
        path = generate_report(ticker, summary)
    except Exception as exc:
        print(f"[AI 报告失败] {exc}")
        return 1
    print(f"[完成] AI 研究报告已保存：{path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="QQQM 个人投资研究助手：历史行情、SQLite、技术指标与 DeepSeek 分析。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="下载并更新历史日线")
    sync_parser.add_argument("--period", default="5y", help="行情范围，例如 1y、5y、max")
    sync_parser.add_argument("--tickers", nargs="+", help="可选标的列表，例如 QQQM QQQ SPY TLT")
    sync_parser.set_defaults(func=command_sync)

    status_parser = subparsers.add_parser("status", help="查看本地数据库里的行情覆盖范围")
    status_parser.set_defaults(func=command_status)

    analyze_parser = subparsers.add_parser("analyze", help="计算指标并生成 AI 研究报告")
    analyze_parser.add_argument("--ticker", default="QQQM", help="默认 QQQM")
    analyze_parser.add_argument("--no-ai", action="store_true", help="只显示技术指标，不调用 API")
    analyze_parser.set_defaults(func=command_analyze)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
