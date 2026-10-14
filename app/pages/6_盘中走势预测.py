from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
FORECAST_PATH = ROOT / "reports" / "intraday" / "QQQM_intraday_forecast_latest.json"

st.set_page_config(page_title="QQQM 盘中走势预测", page_icon="📈", layout="wide")
st.title("📈 QQQM 下一交易日走势预测")
st.caption("先看预计开盘、盘中路径与预计收盘。曲线是模型估计，不是未来真实行情，也不保证预测准确。")

if not FORECAST_PATH.exists():
    st.warning("还没有盘中预测结果。请先运行 scripts/run_intraday_path_backtest.py 生成预测。")
    st.stop()

try:
    data: dict[str, Any] = json.loads(FORECAST_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    st.error(f"读取预测文件失败：{exc}")
    st.stop()

summary = data.get("backtest_summary", {})
quality = data.get("data_quality", {})
open_est = data.get("estimated_open", {})
close_est = data.get("estimated_close_from_path", {})
prev_close = float(data.get("previous_session_close") or 0)
forecast_date = data.get("forecast_date_weekday_estimate", "未知")

st.info(
    f"预测基准：美股 {data.get('as_of_date', '未知')} 收盘；下一交易日暂估为 {forecast_date}。"
    "此日期暂时只跳过周末，还未使用官方美股假日日历。"
)

if data.get("conditional_model_available"):
    st.success("当前显示：相似历史行情候选路径。模型会寻找过去市场状态较接近的交易日，再汇总这些交易日的盘中走势。")
else:
    st.warning("相似历史行情候选模型当前不可用，页面使用历史中位路径基线。")

st.warning(
    "当前只有约 60 个可用历史交易日，且使用 Alpaca IEX 单一交易所数据。"
    "这版是实验性统计候选模型，未证明能稳定优于简单基线；情景区间也不是经过校准的真实概率。"
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("上一交易日收盘", f"${prev_close:,.2f}" if prev_close else "暂无")
col2.metric("预计开盘中位情景", f"${float(open_est.get('p50_price') or 0):,.2f}" if open_est else "暂无")
col3.metric("预计收盘中位情景", f"${float(close_est.get('p50_price') or 0):,.2f}" if close_est else "暂无")
col4.metric("可用历史交易日", str(data.get("eligible_training_sessions", 0)))

curve = data.get("curve", [])
baseline_curve = data.get("baseline_curve", [])
if curve:
    df = pd.DataFrame(curve)
    base_df = pd.DataFrame(baseline_curve) if baseline_curve else pd.DataFrame()
    chart = pd.DataFrame({
        "时间（美东）": df["time_ny"],
        "偏弱情景": pd.to_numeric(df["low_price"], errors="coerce"),
        "相似行情中位预测": pd.to_numeric(df["median_price"], errors="coerce"),
        "偏强情景": pd.to_numeric(df["high_price"], errors="coerce"),
    })
    if not base_df.empty:
        baseline_by_time = base_df.set_index("time_ny")["median_price"].to_dict()
        chart["历史中位基线"] = chart["时间（美东）"].map(baseline_by_time)

    st.subheader("下一交易日：预计价格路径")
    st.line_chart(chart.set_index("时间（美东）"), width="stretch", height=420)
    st.caption(
        "蓝/中位线是相似历史交易日给出的候选路径；上下边界是所选历史样本的经验情景。"
        "灰/参考线（如存在）是旧的历史中位基线。我们不人为加波动：如果线条仍较平，代表现有数据没有提供稳定的盘中特征。"
    )

    # A change-from-open chart makes small intraday movements easier to see without exaggerating price levels.
    pct_chart = pd.DataFrame({
        "时间（美东）": df["time_ny"],
        "偏弱情景（%）": pd.to_numeric(df["p10_return_from_open_pct"], errors="coerce"),
        "中位路径（%）": pd.to_numeric(df["p50_return_from_open_pct"], errors="coerce"),
        "偏强情景（%）": pd.to_numeric(df["p90_return_from_open_pct"], errors="coerce"),
    })
    st.subheader("盘中累计涨跌幅（相对预计开盘）")
    st.line_chart(pct_chart.set_index("时间（美东）"), width="stretch", height=300)
    st.caption("这张图用百分比显示盘中变化，更容易看出小幅波动；它和上面的美元价格图来自同一条预测路径。")

    with st.expander("查看每个时间点的预测价格和样本数"):
        table = df.rename(columns={
            "time_ny": "美东时间",
            "low_price": "偏弱情景价格",
            "median_price": "中位预测价格",
            "high_price": "偏强情景价格",
            "historical_slot_samples": "该时间点可用历史样本数",
            "p10_return_from_open_pct": "偏弱累计涨跌幅（%）",
            "p50_return_from_open_pct": "中位累计涨跌幅（%）",
            "p90_return_from_open_pct": "偏强累计涨跌幅（%）",
        })
        st.dataframe(table, hide_index=True, width="stretch")

st.subheader("这条曲线过去测试得怎么样？")
if summary:
    c1, c2, c3 = st.columns(3)
    cond_mae = summary.get("path_mae_bps_conditional_neighbor")
    base_mae = summary.get("path_mae_bps_historical_profile")
    flat_mae = summary.get("path_mae_bps_flat_after_open_baseline")
    c1.metric("相似行情候选路径误差", f"{cond_mae:.1f} bps" if cond_mae is not None else "样本不足", help="数值越低越好，仅计实际存在的盘中 K 线点。")
    c2.metric("历史中位基线误差", f"{base_mae:.1f} bps" if base_mae is not None else "样本不足", help="旧版按各时段历史累计收益分位构建的曲线。")
    c3.metric("开盘后保持不变基线", f"{flat_mae:.1f} bps" if flat_mae is not None else "样本不足", help="简单对照：开盘后每个时点都预测为开盘价。")

    improvement = summary.get("conditional_improvement_pct_vs_flat_baseline")
    if improvement is not None:
        st.write(f"相对‘开盘后保持不变’基线，候选路径误差改善：**{improvement:+.2f}%**。")
    profile_improvement = summary.get("conditional_improvement_pct_vs_historical_profile")
    if profile_improvement is not None:
        st.write(f"相对旧版历史中位路径，候选路径误差改善：**{profile_improvement:+.2f}%**。")
    st.caption(
        f"滚动测试区间：{summary.get('first_test_date') or '暂无'} 至 {summary.get('last_test_date') or '暂无'}；"
        f"测试交易日 {summary.get('walk_forward_test_sessions', 0)} 天，"
        f"实际对比点 {summary.get('evaluated_intraday_points', 0)} 个。"
    )
    st.caption(summary.get("interpretation", "这是探索性回测，不是收益保证。"))

with st.expander("为什么之前看起来像直线？模型到底怎么预测？"):
    st.write(
        "旧版曲线是把所有历史交易日按同一时间点求中位数。每个时间点的涨跌中位数通常靠近 0%，"
        "互相平均后自然可能接近一条直线。这不一定是绘图 bug，而是简单基线没有找到强烈的可预测盘中模式。"
    )
    st.write(
        "新版增加了相似历史行情候选：先根据最近收益、20 日波动、上一交易日盘中表现和数据覆盖率寻找相似历史日，"
        "再汇总这些日期的盘中路径。它有可能更有曲线变化，但是否更准确必须看下方滚动回测；不会为了视觉效果人工制造波动。"
    )
    for note in data.get("caveats", []):
        st.write(f"- {note}")

st.caption(f"数据源：Alpaca IEX {data.get('timeframe', '15Min')} 数据。页面时间使用美东时间；项目其他模块可使用香港时间。覆盖率中位数：{quality.get('median_coverage_pct', '未知')}%。")
