from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st


# -----------------------------------------------------------------------------
# Paths and page configuration
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "market_data.db"
HISTORY_PATH = ROOT / "data" / "QQQM_tiingo_history.csv"
REPORT_DIR = ROOT / "reports"

st.set_page_config(
    page_title="QQQM Investment Assistant",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------
def latest_file(pattern: str) -> Path | None:
    """Return the most recently modified file matching a report pattern."""
    if not REPORT_DIR.exists():
        return None
    files = list(REPORT_DIR.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda item: item.stat().st_mtime)


def run_command(args: list[str], timeout: int = 600) -> dict[str, Any]:
    """Run an existing project CLI using the current Python interpreter."""
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "command": args,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": -1,
            "stdout": exc.stdout or "",
            "stderr": f"命令运行超过 {timeout} 秒，已停止等待。",
            "command": args,
        }
    except Exception as exc:  # Keep UI alive and surface the problem.
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "command": args,
        }


def render_command_result(result: dict[str, Any] | None) -> None:
    """Display the result of a command previously run by the dashboard."""
    if not result:
        return

    if result.get("returncode") == 0:
        st.success("命令执行完成。")
    else:
        st.error("命令执行失败，请查看输出和错误信息。")

    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    command = result.get("command", [])

    if command:
        with st.expander("查看运行命令"):
            st.code(subprocess.list2cmdline(command), language="powershell")

    if stdout:
        with st.expander("查看命令输出", expanded=result.get("returncode") != 0):
            st.code(stdout)

    if stderr:
        with st.expander("查看错误信息", expanded=True):
            st.code(stderr)


def read_text_file(path: Path) -> str:
    """Read a UTF-8 text file without allowing a rendering error to crash UI."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"读取文件失败：{exc}"


@st.cache_data(ttl=60, show_spinner=False)
def load_market_data() -> pd.DataFrame:
    """Read QQQM daily OHLCV data from the existing SQLite database."""
    if not DB_PATH.exists():
        return pd.DataFrame()

    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT trade_date, open, high, low, close, volume
            FROM market_daily
            WHERE ticker = ?
            ORDER BY trade_date
            """,
            conn,
            params=("QQQM",),
        )


@st.cache_data(ttl=60, show_spinner=False)
def load_fred_macro_data() -> pd.DataFrame:
    """Read existing FRED observations from the local database."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                "SELECT series_id, observation_date, value, retrieved_at "
                "FROM macro_observations ORDER BY observation_date",
                conn,
            )
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def load_bls_macro_data() -> pd.DataFrame:
    """Read existing BLS economic observations from the local database."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                "SELECT series_id, series_name, category, year, period, "
                "period_name, value, unit, footnotes, source_name, source_url, fetched_at "
                "FROM bls_macro_observations",
                conn,
            )
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def load_news_data() -> pd.DataFrame:
    """Read official news items stored locally."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                "SELECT news_id, source_id, source_name, category, title, summary, "
                "url, published_at, fetched_at FROM news_items "
                "ORDER BY published_at DESC",
                conn,
            )
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


def load_backtest_outputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load the most recent rolling-grid trade/equity CSVs and matching JSON."""
    equity_file = latest_file("QQQM_rolling_grid_backtest_*_equity.csv")
    trades_file = latest_file("QQQM_rolling_grid_backtest_*_trades.csv")
    equity_df = pd.DataFrame()
    trades_df = pd.DataFrame()
    summary: dict[str, Any] = {}

    if equity_file:
        try:
            equity_df = pd.read_csv(equity_file)
            if "date" in equity_df.columns:
                equity_df["date"] = pd.to_datetime(
                    equity_df["date"], errors="coerce"
                )
            equity_df = equity_df.dropna(subset=["date"]).sort_values("date")
            equity_df = equity_df.reset_index(drop=True)
        except Exception as exc:
            st.error(f"读取资金曲线失败：{exc}")
            equity_df = pd.DataFrame()

        json_file = equity_file.with_name(
            equity_file.name.removesuffix("_equity.csv") + ".json"
        )
        if json_file.exists():
            try:
                content = json.loads(json_file.read_text(encoding="utf-8"))
                summary = content.get("summary", {})
            except (OSError, json.JSONDecodeError, AttributeError):
                summary = {}

    if trades_file:
        try:
            trades_df = pd.read_csv(trades_file)
            if "date" in trades_df.columns:
                trades_df["date"] = pd.to_datetime(
                    trades_df["date"], errors="coerce"
                )
            if "side" in trades_df.columns:
                trades_df["side"] = (
                    trades_df["side"].astype(str).str.upper()
                )
            if "date" in trades_df.columns:
                trades_df = trades_df.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            st.error(f"读取交易记录失败：{exc}")
            trades_df = pd.DataFrame()

    return equity_df, trades_df, summary


def max_drawdown_pct(values: pd.Series | list[float]) -> float:
    """Maximum peak-to-trough drawdown as a positive percentage."""
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if series.empty:
        return 0.0
    peak = series.cummax()
    drawdown = series / peak - 1.0
    return abs(float(drawdown.min()) * 100.0)


def annualized_volatility_pct(values: pd.Series | list[float]) -> float:
    """Annualized volatility based on daily account-equity returns."""
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    returns = series.pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * (252.0**0.5) * 100.0)


def render_latest_report(pattern: str, *, title: str) -> None:
    report = latest_file(pattern)
    if report is None:
        st.info("暂时没有找到报告。先运行相应分析任务即可生成。")
        return

    st.caption(f"{title}：{report.name}")
    st.markdown(read_text_file(report))


# -----------------------------------------------------------------------------
# Header and navigation
# -----------------------------------------------------------------------------
st.title("📈 QQQM Investment Assistant")
st.caption("个人投资研究平台 · 行情分析 · AI 报告 · 策略回测")
st.warning("本工具用于学习、研究和历史回测，不构成投资建议。历史表现不代表未来结果。")

market_tab, report_tab, backtest_tab, macro_tab, status_tab = st.tabs(
    ["📊 市场概览", "🧠 AI 分析", "⚙️ 策略回测", "🌎 宏观与新闻", "🗄️ 数据状态"]
)


# -----------------------------------------------------------------------------
# 1. Market overview
# -----------------------------------------------------------------------------
with market_tab:
    heading_col, refresh_col = st.columns([5, 1])
    with heading_col:
        st.subheader("QQQM 市场行情")
    with refresh_col:
        if st.button("刷新行情", key="refresh_market_data"):
            load_market_data.clear()
            st.rerun()

    if not DB_PATH.exists():
        st.warning(f"没有找到数据库文件：{DB_PATH}")
    else:
        try:
            market_df = load_market_data()
        except Exception as exc:
            market_df = pd.DataFrame()
            st.error(f"读取市场数据失败：{type(exc).__name__}: {exc}")

        if market_df.empty:
            st.warning("数据库中没有读到 QQQM 行情，请先同步行情数据。")
        else:
            market_df["trade_date"] = pd.to_datetime(
                market_df["trade_date"], errors="coerce"
            )
            market_df = (
                market_df.dropna(subset=["trade_date", "close"])
                .sort_values("trade_date")
                .reset_index(drop=True)
            )

            if market_df.empty:
                st.warning("行情记录没有有效的日期或收盘价。")
            else:
                latest = market_df.iloc[-1]
                latest_close = float(latest["close"])

                def period_return(trading_days_back: int) -> float | None:
                    index = len(market_df) - 1 - trading_days_back
                    if index < 0:
                        return None
                    previous_close = float(market_df.iloc[index]["close"])
                    if previous_close == 0:
                        return None
                    return (latest_close / previous_close - 1.0) * 100.0

                daily_return = period_return(1)
                return_5d = period_return(5)
                return_20d = period_return(20)

                metric_cols = st.columns(4)
                metric_cols[0].metric(
                    "最新收盘价",
                    f"${latest_close:,.2f}",
                    f"{daily_return:+.2f}%" if daily_return is not None else None,
                )
                metric_cols[1].metric(
                    "近 5 个交易日",
                    f"{return_5d:+.2f}%" if return_5d is not None else "数据不足",
                )
                metric_cols[2].metric(
                    "近 20 个交易日",
                    f"{return_20d:+.2f}%" if return_20d is not None else "数据不足",
                )
                metric_cols[3].metric("日线记录数", f"{len(market_df):,}")

                st.caption(
                    f"最新交易日：{latest['trade_date'].date()}。"
                    "收益率按收盘价计算，未计入分红和交易成本。"
                )

                st.subheader("历史收盘价")
                price_series = market_df.set_index("trade_date")["close"]
                st.line_chart(price_series, y_label="价格（美元）")

                st.subheader("最近 15 个交易日")
                recent = market_df.tail(15).sort_values(
                    "trade_date", ascending=False
                ).copy()
                recent["trade_date"] = recent["trade_date"].dt.strftime("%Y-%m-%d")
                st.dataframe(
                    recent,
                    use_container_width=True,
                    hide_index=True,
                )


# -----------------------------------------------------------------------------
# 2. AI analysis report
# -----------------------------------------------------------------------------
with report_tab:
    st.subheader("AI 市场分析")
    st.write(
        "调用项目现有分析流程，结合行情、宏观数据与新闻生成研究报告。"
    )

    if st.button("生成 / 刷新 AI 分析报告", type="primary", key="run_ai_analysis"):
        with st.spinner("正在运行分析程序，这可能需要一点时间……"):
            result = run_command(
                [
                    sys.executable,
                    "main.py",
                    "analyze",
                    "--ticker",
                    "QQQM",
                    "--with-macro",
                ],
                timeout=600,
            )
        st.session_state["ai_result"] = result

    render_command_result(st.session_state.get("ai_result"))

    st.divider()
    st.subheader("最近生成的投资报告")
    render_latest_report(
        "QQQM_investment_report_*.md",
        title="投资报告",
    )


# -----------------------------------------------------------------------------
# 3. Rolling-grid backtest and visualization
# -----------------------------------------------------------------------------
with backtest_tab:
    st.subheader("滚动网格策略回测")
    st.caption(
        "使用本地 Tiingo 历史日线；策略按收盘信号、下一交易日开盘执行。"
        "参数用于历史研究，不代表建议采用的真实交易配置。"
    )

    if not HISTORY_PATH.exists():
        st.warning(
            f"没有找到历史行情 CSV：{HISTORY_PATH}\n\n"
            "请确认 data/QQQM_tiingo_history.csv 存在。"
        )
    else:
        with st.form("rolling_backtest_form"):
            left_col, right_col = st.columns(2)

            with left_col:
                lookback = st.number_input(
                    "移动平均线周期（交易日）",
                    min_value=20,
                    max_value=250,
                    value=60,
                    step=5,
                )
                step_pct_ui = st.select_slider(
                    "网格步长",
                    options=[1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
                    value=2.5,
                    format_func=lambda value: f"{value:.1f}%",
                )

            with right_col:
                levels = st.number_input(
                    "网格层数",
                    min_value=1,
                    max_value=10,
                    value=6,
                    step=1,
                )
                cash_per_grid = st.number_input(
                    "每层买入资金（美元）",
                    min_value=100,
                    max_value=10000,
                    value=1000,
                    step=100,
                )

            initial_cash = st.number_input(
                "初始账户资金（美元）",
                min_value=1000,
                max_value=1_000_000,
                value=10000,
                step=1000,
            )

            run_backtest = st.form_submit_button(
                "运行回测",
                type="primary",
            )

        if run_backtest:
            command = [
                sys.executable,
                "-m",
                "app.rolling_backtest",
                "--ticker",
                "QQQM",
                "--data-file",
                str(HISTORY_PATH),
                "--lookback",
                str(int(lookback)),
                "--step-pct",
                str(float(step_pct_ui) / 100.0),
                "--levels",
                str(int(levels)),
                "--cash-per-grid",
                str(float(cash_per_grid)),
                "--initial-cash",
                str(float(initial_cash)),
            ]

            with st.spinner("正在计算回测，请稍候……"):
                backtest_result = run_command(command, timeout=600)

            st.session_state["backtest_result"] = backtest_result
            st.session_state["backtest_params"] = {
                "lookback": int(lookback),
                "step_pct": float(step_pct_ui),
                "levels": int(levels),
                "cash_per_grid": float(cash_per_grid),
                "initial_cash": float(initial_cash),
            }

        render_command_result(st.session_state.get("backtest_result"))

        params = st.session_state.get("backtest_params")
        if params:
            st.caption(
                "最近一次回测参数："
                f"均线 {params['lookback']} 日 · "
                f"步长 {params['step_pct']:.1f}% · "
                f"层数 {params['levels']} · "
                f"每层 ${params['cash_per_grid']:,.0f} · "
                f"初始资金 ${params['initial_cash']:,.0f}"
            )

        # Load the latest outputs after a successful execution, or show the
        # latest existing backtest when the page is first opened.
        equity_df, trades_df, summary = load_backtest_outputs()
        equity_file = latest_file("QQQM_rolling_grid_backtest_*_equity.csv")
        trades_file = latest_file("QQQM_rolling_grid_backtest_*_trades.csv")
        report_file = latest_file("QQQM_rolling_grid_backtest_*.md")

        st.divider()
        st.subheader("回测绩效分析")

        if equity_df.empty:
            st.info("目前没有可展示的回测资金曲线，请先成功运行一次回测。")
        else:
            required_equity_cols = {
                "date", "close", "cash", "shares", "position_value", "equity",
                "buy_hold_position_value", "buy_hold_equity",
            }
            if not required_equity_cols.issubset(equity_df.columns):
                missing = sorted(required_equity_cols - set(equity_df.columns))
                st.error(f"资金曲线缺少必要字段：{', '.join(missing)}")
            else:
                grid_summary = summary.get("grid_strategy", {})
                bh_summary = summary.get("buy_and_hold", {})
                parameters = summary.get("parameters", {})

                # Prefer the metrics emitted by the backtest engine. Calculated
                # fallbacks keep old reports readable if their JSON is missing.
                starting_cash = float(
                    parameters.get("initial_cash", equity_df["equity"].iloc[0])
                )
                final_grid_equity = float(
                    grid_summary.get("final_equity", equity_df["equity"].iloc[-1])
                )
                final_bh_equity = float(
                    bh_summary.get("final_equity", equity_df["buy_hold_equity"].iloc[-1])
                )
                grid_return = float(
                    grid_summary.get(
                        "total_return_pct",
                        (final_grid_equity / starting_cash - 1.0) * 100.0,
                    )
                )
                bh_return = float(
                    bh_summary.get(
                        "total_return_pct",
                        (final_bh_equity / starting_cash - 1.0) * 100.0,
                    )
                )
                grid_mdd = float(
                    grid_summary.get("max_drawdown_pct", max_drawdown_pct(equity_df["equity"]))
                )
                bh_mdd_fallback = max_drawdown_pct(
                    pd.concat(
                        [pd.Series([starting_cash]), equity_df["buy_hold_equity"]],
                        ignore_index=True,
                    )
                )
                bh_mdd = float(
                    bh_summary.get("max_drawdown_pct", bh_mdd_fallback)
                )
                grid_vol = float(
                    grid_summary.get(
                        "annualized_volatility_pct",
                        annualized_volatility_pct(equity_df["equity"]),
                    )
                )
                bh_vol = float(
                    bh_summary.get(
                        "annualized_volatility_pct",
                        annualized_volatility_pct(
                            pd.concat(
                                [pd.Series([starting_cash]), equity_df["buy_hold_equity"]],
                                ignore_index=True,
                            )
                        ),
                    )
                )
                avg_exposure = float(
                    grid_summary.get(
                        "average_position_exposure_pct",
                        (
                            equity_df["position_value"]
                            / equity_df["equity"].where(equity_df["equity"] != 0)
                            * 100.0
                        ).mean(),
                    )
                )
                bh_avg_exposure = float(
                    bh_summary.get(
                        "average_position_exposure_pct",
                        (
                            equity_df["buy_hold_position_value"]
                            / equity_df["buy_hold_equity"].where(equity_df["buy_hold_equity"] != 0)
                            * 100.0
                        ).mean(),
                    )
                )
                total_fees = float(grid_summary.get("fees_paid", trades_df.get("fee", pd.Series(dtype=float)).sum()))
                buy_count = int(
                    grid_summary.get(
                        "buy_orders_filled",
                        int((trades_df.get("side", pd.Series(dtype=str)) == "BUY").sum()),
                    )
                )
                sell_count = int(
                    grid_summary.get(
                        "sell_orders_filled",
                        int((trades_df.get("side", pd.Series(dtype=str)) == "SELL").sum()),
                    )
                )
                dividends = float(grid_summary.get("dividends_received", 0.0))

                metric_cols = st.columns(5)
                metric_cols[0].metric("网格总收益率", f"{grid_return:+.2f}%")
                metric_cols[1].metric("买入持有收益率", f"{bh_return:+.2f}%")
                metric_cols[2].metric("网格最大回撤", f"{grid_mdd:.2f}%")
                metric_cols[3].metric("平均股票仓位", f"{avg_exposure:.2f}%")
                metric_cols[4].metric("网格手续费", f"${total_fees:,.2f}")

                metric_table = pd.DataFrame(
                    [
                        {
                            "指标": "最终账户权益",
                            "滚动网格": f"${final_grid_equity:,.2f}",
                            "买入持有": f"${final_bh_equity:,.2f}",
                        },
                        {
                            "指标": "总收益率",
                            "滚动网格": f"{grid_return:+.2f}%",
                            "买入持有": f"{bh_return:+.2f}%",
                        },
                        {
                            "指标": "最大回撤",
                            "滚动网格": f"{grid_mdd:.2f}%",
                            "买入持有": f"{bh_mdd:.2f}%",
                        },
                        {
                            "指标": "年化波动率",
                            "滚动网格": f"{grid_vol:.2f}%",
                            "买入持有": f"{bh_vol:.2f}%",
                        },
                        {
                            "指标": "平均股票仓位",
                            "滚动网格": f"{avg_exposure:.2f}%",
                            "买入持有": f"{bh_avg_exposure:.2f}%",
                        },
                        {
                            "指标": "已成交买入 / 卖出",
                            "滚动网格": f"{buy_count} / {sell_count}",
                            "买入持有": "不适用",
                        },
                        {
                            "指标": "交易手续费",
                            "滚动网格": f"${total_fees:,.2f}",
                            "买入持有": (
                                f"${float(bh_summary.get('entry_fee_paid', 0.0)):,.2f} 建仓费"
                                if bh_summary
                                else "见回测报告"
                            ),
                        },
                        {
                            "指标": "收到的现金分红",
                            "滚动网格": f"${dividends:,.2f}",
                            "买入持有": (
                                f"${float(bh_summary.get('dividends_received_in_cash', 0.0)):,.2f}"
                                if bh_summary
                                else "见回测报告"
                            ),
                        },
                    ]
                )
                st.dataframe(metric_table, use_container_width=True, hide_index=True)

                # Equity curves: grid and buy/hold share the same initial principal.
                st.subheader("账户权益曲线")
                curve_df = equity_df[["date", "equity", "buy_hold_equity"]].copy()
                curve_df = curve_df.rename(
                    columns={
                        "equity": "滚动网格",
                        "buy_hold_equity": "买入持有",
                    }
                ).set_index("date")
                st.line_chart(curve_df, y_label="账户权益（美元）")
                st.caption(
                    "买入持有基准包含初始建仓手续费与滑点估算；"
                    "两条策略的股票仓位不同，不能只按收益率判断优劣。"
                )

                # Drawdown series include the initial account capital in benchmark peak.
                st.subheader("账户回撤曲线")
                grid_equity = pd.to_numeric(equity_df["equity"], errors="coerce")
                bh_equity = pd.to_numeric(equity_df["buy_hold_equity"], errors="coerce")
                grid_peak = pd.concat(
                    [pd.Series([starting_cash]), grid_equity], ignore_index=True
                ).cummax().iloc[1:].reset_index(drop=True)
                bh_peak = pd.concat(
                    [pd.Series([starting_cash]), bh_equity], ignore_index=True
                ).cummax().iloc[1:].reset_index(drop=True)
                drawdown_df = pd.DataFrame(
                    {
                        "date": equity_df["date"],
                        "滚动网格": (grid_equity.reset_index(drop=True) / grid_peak - 1.0) * 100.0,
                        "买入持有": (bh_equity.reset_index(drop=True) / bh_peak - 1.0) * 100.0,
                    }
                ).set_index("date")
                st.line_chart(drawdown_df, y_label="回撤（%）")
                st.caption("回撤为负数；离 0 越远，表示较历史权益高点跌得越深。")

                # Price line with actual fills marked as green buys and red sells.
                st.subheader("QQQM 收盘价与策略买卖点")
                price_data = equity_df[["date", "close"]].dropna().copy()
                price_line = alt.Chart(price_data).mark_line().encode(
                    x=alt.X("date:T", title="交易日期"),
                    y=alt.Y("close:Q", title="QQQM 收盘价（美元）", scale=alt.Scale(zero=False)),
                    tooltip=[
                        alt.Tooltip("date:T", title="日期"),
                        alt.Tooltip("close:Q", title="收盘价", format=".2f"),
                    ],
                )
                price_chart = price_line

                trade_columns = {"date", "side", "fill_price"}
                if not trades_df.empty and trade_columns.issubset(trades_df.columns):
                    valid_trades = trades_df.dropna(subset=["date", "fill_price"]).copy()
                    points_tooltip = [
                        alt.Tooltip("date:T", title="交易日期"),
                        alt.Tooltip("side:N", title="方向"),
                        alt.Tooltip("fill_price:Q", title="成交价格", format=".2f"),
                    ]
                    if "shares" in valid_trades.columns:
                        points_tooltip.append(
                            alt.Tooltip("shares:Q", title="股数", format=".0f")
                        )
                    if "fee" in valid_trades.columns:
                        points_tooltip.append(
                            alt.Tooltip("fee:Q", title="手续费", format=".2f")
                        )

                    buy_rows = valid_trades[valid_trades["side"] == "BUY"]
                    sell_rows = valid_trades[valid_trades["side"] == "SELL"]

                    if not buy_rows.empty:
                        buy_points = alt.Chart(buy_rows).mark_point(
                            shape="triangle-up", size=85, color="#16a34a"
                        ).encode(
                            x=alt.X("date:T"),
                            y=alt.Y("fill_price:Q"),
                            tooltip=points_tooltip,
                        )
                        price_chart = price_chart + buy_points

                    if not sell_rows.empty:
                        sell_points = alt.Chart(sell_rows).mark_point(
                            shape="triangle-down", size=85, color="#dc2626"
                        ).encode(
                            x=alt.X("date:T"),
                            y=alt.Y("fill_price:Q"),
                            tooltip=points_tooltip,
                        )
                        price_chart = price_chart + sell_points

                st.altair_chart(price_chart.interactive(), use_container_width=True)
                st.caption("绿色上三角是买入成交，红色下三角是卖出成交。悬停可以查看价格和交易信息。")

                # Trade details, sortable and filterable.
                st.subheader("交易明细")
                if trades_df.empty:
                    st.info("这次回测没有生成交易记录。")
                else:
                    trade_view = trades_df.copy()
                    if "side" in trade_view.columns:
                        directions = sorted(trade_view["side"].dropna().unique().tolist())
                        selected_directions = st.multiselect(
                            "筛选交易方向",
                            options=directions,
                            default=directions,
                            key="trade_direction_filter",
                        )
                        trade_view = trade_view[
                            trade_view["side"].isin(selected_directions)
                        ]

                    if "date" in trade_view.columns:
                        trade_view = trade_view.sort_values("date", ascending=False)

                    visible_columns = [
                        column
                        for column in [
                            "date", "side", "tier", "trigger_price", "fill_price",
                            "target_sell_price", "shares", "notional", "fee",
                            "realized_pnl", "cash_after", "held_shares_after", "reason",
                        ]
                        if column in trade_view.columns
                    ]
                    display_df = trade_view[visible_columns].copy()
                    if "date" in display_df.columns:
                        display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True,
                    )

                # Downloads refer to the exact latest files shown above.
                dl1, dl2 = st.columns(2)
                if trades_file:
                    dl1.download_button(
                        "下载交易记录 CSV",
                        data=trades_file.read_bytes(),
                        file_name=trades_file.name,
                        mime="text/csv",
                        key="download_trades_csv",
                    )
                if equity_file:
                    dl2.download_button(
                        "下载资金曲线 CSV",
                        data=equity_file.read_bytes(),
                        file_name=equity_file.name,
                        mime="text/csv",
                        key="download_equity_csv",
                    )

                if report_file:
                    with st.expander("查看回测 Markdown 报告"):
                        st.caption(report_file.name)
                        st.markdown(read_text_file(report_file))

                if equity_file:
                    st.caption(f"当前展示的资金曲线文件：{equity_file.name}")
                if trades_file:
                    st.caption(f"当前展示的交易记录文件：{trades_file.name}")


# -----------------------------------------------------------------------------
# 4. Macro data, news and sync status
# -----------------------------------------------------------------------------
with macro_tab:
    st.subheader("宏观经济与官方新闻")
    st.caption(
        "读取本地 SQLite 已保存的数据。宏观指标来自 FRED / BLS；新闻来自项目已配置的官方来源。"
    )

    sync_col1, sync_col2, sync_col3 = st.columns([1, 1, 1])
    with sync_col1:
        if st.button("同步 FRED 宏观数据", key="sync_fred_macro", type="primary"):
            with st.spinner("正在同步 FRED 数据……"):
                result = run_command(
                    [sys.executable, "main.py", "macro-sync"], timeout=600
                )
            st.session_state["macro_sync_fred_result"] = result
            load_fred_macro_data.clear()
    with sync_col2:
        if st.button("同步新闻与 BLS 数据", key="sync_news_bls"):
            with st.spinner("正在同步新闻与 BLS 指标……"):
                result = run_command(
                    [sys.executable, "-m", "app.news_data", "sync"], timeout=600
                )
            st.session_state["macro_sync_news_result"] = result
            load_news_data.clear()
            load_bls_macro_data.clear()
    with sync_col3:
        if st.button("刷新本地数据", key="refresh_macro_news"):
            load_fred_macro_data.clear()
            load_bls_macro_data.clear()
            load_news_data.clear()
            st.rerun()

    render_command_result(st.session_state.get("macro_sync_fred_result"))
    render_command_result(st.session_state.get("macro_sync_news_result"))

    fred_tab, bls_tab, news_tab, sync_tab = st.tabs(
        ["FRED 指标", "BLS 通胀与就业", "官方新闻", "同步状态"]
    )

    with fred_tab:
        st.markdown("#### 美国利率与宏观指标")
        fred_df = load_fred_macro_data()
        if fred_df.empty:
            st.info("本地没有读取到 FRED 数据。可点击上方“同步 FRED 宏观数据”尝试更新。")
        else:
            fred_df["observation_date"] = pd.to_datetime(
                fred_df["observation_date"], errors="coerce"
            )
            fred_df["value"] = pd.to_numeric(fred_df["value"], errors="coerce")
            fred_df = fred_df.dropna(subset=["observation_date", "value"])
            labels = {
                "EFFR": "联邦基金有效利率（EFFR）",
                "DGS10": "美国 10 年期国债收益率（DGS10）",
                "DFII10": "美国 10 年期实际利率（DFII10）",
                "CPIAUCSL": "美国 CPI 指数（CPIAUCSL）",
            }

            preferred_order = ["EFFR", "DGS10", "DFII10", "CPIAUCSL"]
            latest_by_series = (
                fred_df.sort_values("observation_date")
                .groupby("series_id", as_index=False)
                .tail(1)
            )
            existing_ids = set(fred_df["series_id"].astype(str))
            metric_ids = [sid for sid in preferred_order if sid in existing_ids]
            if metric_ids:
                metric_cols = st.columns(len(metric_ids))
                indexed_latest = latest_by_series.set_index("series_id")
                for idx, sid in enumerate(metric_ids):
                    row = indexed_latest.loc[sid]
                    label = labels.get(sid, sid)
                    value = float(row["value"])
                    value_text = f"{value:.3f}" if sid == "CPIAUCSL" else f"{value:.2f}%"
                    metric_cols[idx].metric(label, value_text)
                    metric_cols[idx].caption(
                        f"观测日期：{row['observation_date'].date()}"
                    )

            available_ids = sorted(existing_ids, key=lambda x: (preferred_order.index(x) if x in preferred_order else 999, x))
            selected_series = st.selectbox(
                "选择要查看的指标",
                options=available_ids,
                format_func=lambda value: f"{labels.get(value, value)} · {value}",
                key="fred_series_select",
            )
            selected_df = fred_df[fred_df["series_id"] == selected_series].copy()
            selected_df = selected_df.sort_values("observation_date")
            chart_title = labels.get(selected_series, selected_series)
            if selected_series == "CPIAUCSL":
                st.caption("CPIAUCSL 为消费者价格指数，不是同比通胀率；需要用指数序列自行计算同比或环比变化。")
            chart_df = selected_df.set_index("observation_date")["value"]
            st.line_chart(chart_df, y_label="指数值" if selected_series == "CPIAUCSL" else "百分比 / 数值")
            st.caption(f"当前图表：{chart_title}。缺失日期可能反映该指标本身的发布频率。")
            recent_fred = selected_df.sort_values("observation_date", ascending=False).head(30).copy()
            recent_fred["observation_date"] = recent_fred["observation_date"].dt.strftime("%Y-%m-%d")
            st.dataframe(
                recent_fred[["series_id", "observation_date", "value", "retrieved_at"]],
                use_container_width=True,
                hide_index=True,
            )

    with bls_tab:
        st.markdown("#### BLS 通胀与就业数据")
        bls_df = load_bls_macro_data()
        if bls_df.empty:
            st.info("本地没有读取到 BLS 宏观记录。可点击上方“同步新闻与 BLS 数据”尝试更新。")
        else:
            bls_df["value_numeric"] = pd.to_numeric(bls_df["value"], errors="coerce")
            bls_df["year"] = pd.to_numeric(bls_df["year"], errors="coerce")
            bls_df["period_number"] = pd.to_numeric(
                bls_df["period"].astype(str).str.extract(r"(\d+)", expand=False),
                errors="coerce",
            )
            # BLS monthly series use M01-M12; non-monthly periods remain visible in the table.
            month_text = bls_df["period_number"].where(
                bls_df["period"].astype(str).str.startswith("M")
                & bls_df["period_number"].between(1, 12)
            )
            bls_df["period_date"] = pd.to_datetime(
                bls_df["year"].astype("Int64").astype(str)
                + "-"
                + month_text.astype("Int64").astype(str).str.zfill(2)
                + "-01",
                errors="coerce",
            )

            categories = ["全部"] + sorted(
                bls_df["category"].dropna().astype(str).unique().tolist()
            )
            selected_category = st.selectbox(
                "按类别筛选",
                categories,
                key="bls_category_filter",
            )
            filtered_bls = bls_df.copy()
            if selected_category != "全部":
                filtered_bls = filtered_bls[
                    filtered_bls["category"] == selected_category
                ]

            if filtered_bls.empty:
                st.info("该类别暂时没有数据。")
            else:
                latest_bls = (
                    filtered_bls.sort_values(
                        ["year", "period_number"], ascending=[False, False]
                    )
                    .drop_duplicates(subset=["series_id"], keep="first")
                )
                metric_items = latest_bls.to_dict("records")
                metric_cols = st.columns(min(3, len(metric_items)))
                for idx, row in enumerate(metric_items[:3]):
                    numeric_value = row.get("value_numeric")
                    value_text = (
                        f"{numeric_value:,.3f} {row.get('unit') or ''}".strip()
                        if pd.notna(numeric_value)
                        else str(row.get("value", "暂无数据"))
                    )
                    metric_cols[idx].metric(
                        str(row.get("series_name") or row.get("series_id")),
                        value_text,
                    )
                    metric_cols[idx].caption(
                        f"{row.get('period_name') or row.get('period')} {row.get('year')}"
                    )

                series_options = (
                    filtered_bls[["series_id", "series_name"]]
                    .drop_duplicates()
                    .sort_values("series_name")
                )
                selected_bls_series = st.selectbox(
                    "选择趋势图指标",
                    options=series_options["series_id"].tolist(),
                    format_func=lambda sid: str(
                        series_options.loc[series_options["series_id"] == sid, "series_name"].iloc[0]
                    ),
                    key="bls_series_select",
                )
                series_df = filtered_bls[
                    filtered_bls["series_id"] == selected_bls_series
                ].copy()
                series_df = series_df.dropna(subset=["period_date", "value_numeric"])
                if not series_df.empty:
                    series_df = series_df.sort_values("period_date")
                    st.line_chart(
                        series_df.set_index("period_date")["value_numeric"],
                        y_label=str(series_df["unit"].dropna().iloc[0]) if series_df["unit"].notna().any() else "数值",
                    )
                else:
                    st.info("该指标没有可绘制的月度时间序列，可在下方表格查看原始记录。")

                display_bls = filtered_bls.sort_values(
                    ["year", "period_number"], ascending=[False, False]
                ).head(40).copy()
                display_columns = [
                    "series_name", "category", "year", "period", "period_name",
                    "value", "unit", "source_name", "source_url", "fetched_at",
                ]
                display_bls = display_bls[[c for c in display_columns if c in display_bls.columns]]
                st.dataframe(
                    display_bls,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "source_url": st.column_config.LinkColumn("官方数据来源", display_text="打开来源")
                    },
                )

    with news_tab:
        st.markdown("#### 官方经济新闻")
        news_df = load_news_data()
        if news_df.empty:
            st.info("本地新闻表没有记录。可点击上方“同步新闻与 BLS 数据”尝试更新。")
        else:
            news_df["published_at_dt"] = pd.to_datetime(
                news_df["published_at"], errors="coerce", utc=True
            )
            news_df = news_df.sort_values("published_at_dt", ascending=False)
            sources = ["全部"] + sorted(news_df["source_name"].dropna().astype(str).unique().tolist())
            categories = ["全部"] + sorted(news_df["category"].dropna().astype(str).unique().tolist())
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                selected_source = st.selectbox("新闻来源", sources, key="news_source_filter")
            with filter_col2:
                selected_news_category = st.selectbox("新闻类别", categories, key="news_category_filter")
            search = st.text_input("搜索标题或摘要", key="news_search_text", placeholder="例如 CPI、interest rate、employment")
            filtered_news = news_df.copy()
            if selected_source != "全部":
                filtered_news = filtered_news[filtered_news["source_name"] == selected_source]
            if selected_news_category != "全部":
                filtered_news = filtered_news[filtered_news["category"] == selected_news_category]
            if search.strip():
                pattern = search.strip()
                mask = (
                    filtered_news["title"].fillna("").str.contains(pattern, case=False, regex=False)
                    | filtered_news["summary"].fillna("").str.contains(pattern, case=False, regex=False)
                )
                filtered_news = filtered_news[mask]

            st.caption(f"找到 {len(filtered_news)} 条新闻，共 {len(news_df)} 条本地记录。")
            for _, item in filtered_news.head(30).iterrows():
                published = item.get("published_at_dt")
                published_text = published.strftime("%Y-%m-%d %H:%M UTC") if pd.notna(published) else "日期未知"
                source_label = str(item.get("source_name") or item.get("source_id") or "未知来源")
                category_label = str(item.get("category") or "未分类")
                title = str(item.get("title") or "（无标题）")
                summary_text = str(item.get("summary") or "暂无摘要")
                url = str(item.get("url") or "")
                with st.expander(f"{title}  ·  {source_label} / {category_label}  ·  {published_text}"):
                    st.write(summary_text)
                    if url.startswith(("https://", "http://")):
                        st.markdown(f"[阅读官方原文]({url})")
                    st.caption(f"抓取时间：{item.get('fetched_at') or '未知'}")

    with sync_tab:
        st.markdown("#### 同步状态与数据新鲜度")
        st.write("这些信息反映数据目前是否存储在本地，不代表数据源一定已经发布了最新一期数据。")

        if not DB_PATH.exists():
            st.warning("数据库文件不存在。")
        else:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    bls_state = pd.read_sql_query(
                        "SELECT series_id, series_name, category, source_url, "
                        "last_attempt_at, last_success_at, last_observation_count, last_error "
                        "FROM bls_macro_sync_state ORDER BY category, series_id",
                        conn,
                    )
                    if not bls_state.empty:
                        st.markdown("**BLS 同步记录**")
                        st.dataframe(
                            bls_state,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "source_url": st.column_config.LinkColumn("官方数据来源", display_text="打开来源")
                            },
                        )
                    else:
                        st.info("暂时没有 BLS 同步状态记录。")

                    fred_status = pd.read_sql_query(
                        "SELECT series_id, COUNT(*) AS observation_count, "
                        "MAX(observation_date) AS latest_observation, "
                        "MAX(retrieved_at) AS last_retrieved_at "
                        "FROM macro_observations GROUP BY series_id ORDER BY series_id",
                        conn,
                    )
                    if not fred_status.empty:
                        st.markdown("**FRED 数据覆盖情况**")
                        st.dataframe(
                            fred_status,
                            use_container_width=True,
                            hide_index=True,
                        )

                    news_counts = pd.read_sql_query(
                        "SELECT source_name, category, COUNT(*) AS item_count, "
                        "MAX(published_at) AS latest_published_at, "
                        "MAX(fetched_at) AS last_fetched_at "
                        "FROM news_items GROUP BY source_name, category "
                        "ORDER BY source_name, category",
                        conn,
                    )
                    if not news_counts.empty:
                        st.markdown("**本地新闻数量与更新时间**")
                        st.dataframe(news_counts, use_container_width=True, hide_index=True)

                    state_tables = pd.read_sql_query(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name LIKE '%sync_state%' ORDER BY name",
                        conn,
                    )["name"].tolist()
                    for table_name in state_tables:
                        if table_name in {"bls_macro_sync_state"}:
                            continue
                        escaped_name = table_name.replace('"', '""')
                        extra_state = pd.read_sql_query(
                            f'SELECT * FROM "{escaped_name}" LIMIT 100', conn
                        )
                        if not extra_state.empty:
                            st.markdown(f"**{table_name}**")
                            st.dataframe(extra_state, use_container_width=True, hide_index=True)
            except (sqlite3.Error, pd.errors.DatabaseError) as exc:
                st.error(f"读取同步状态失败：{type(exc).__name__}: {exc}")


# -----------------------------------------------------------------------------
# 5. Data status
# -----------------------------------------------------------------------------
with status_tab:
    st.subheader("本地数据库状态")
    st.write(f"数据库路径：`{DB_PATH}`")

    if not DB_PATH.exists():
        st.warning("数据库文件不存在。")
    else:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                table_names = pd.read_sql_query(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    ORDER BY name
                    """,
                    conn,
                )["name"].tolist()

                table_info = []
                for name in table_names:
                    safe_name = name.replace('"', '""')
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{safe_name}"'
                    ).fetchone()[0]
                    table_info.append({"数据表": name, "记录数": int(count)})

            if table_info:
                st.dataframe(
                    pd.DataFrame(table_info),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("数据库存在，但目前没有数据表。")
        except Exception as exc:
            st.error(f"读取数据库结构失败：{type(exc).__name__}: {exc}")

    st.divider()
    st.subheader("本地文件状态")
    status_rows = [
        {
            "项目文件": str(HISTORY_PATH.relative_to(ROOT)),
            "状态": "已找到" if HISTORY_PATH.exists() else "不存在",
        },
        {
            "项目文件": str(DB_PATH.relative_to(ROOT)),
            "状态": "已找到" if DB_PATH.exists() else "不存在",
        },
        {
            "项目文件": "reports/",
            "状态": "已找到" if REPORT_DIR.exists() else "不存在",
        },
    ]
    st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)

    if REPORT_DIR.exists():
        st.caption(f"报告目录内文件数量：{sum(1 for item in REPORT_DIR.iterdir() if item.is_file())}")
