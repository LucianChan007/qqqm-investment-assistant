r"""Streamlit Dashboard for QQQM Investment Assistant.

Run from project root:
    .\.venv\Scripts\python.exe -m streamlit run gui/dashboard.py

The clock updates once per second without re-running the rest of the dashboard
when the installed Streamlit version supports st.fragment(). This page reads
local reports only; it does not call market APIs or DeepSeek on each refresh.
"""
from __future__ import annotations

import json
import sys
from html import escape
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.market_clock import get_market_clock  # noqa: E402
from app.services.portfolio import calculate_position  # noqa: E402
from app.services.daily_review import (  # noqa: E402
    build_daily_review_context,
    load_recent_human_feedback,
    save_human_feedback,
)
from gui.components.chart import render_intraday_chart  # noqa: E402

FORECAST_PATH = ROOT / "reports" / "intraday" / "QQQM_intraday_forecast_latest.json"
SUMMARY_PATH = ROOT / "reports" / "intraday" / "QQQM_intraday_forecast_vs_actual_summary_latest.json"
CONTEXT_REPORT_PATH = ROOT / "reports" / "context_agent" / "QQQM_context_analysis_latest.md"

st.set_page_config(
    page_title="QQQM Investment Assistant",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _money(value: Any, digits: int = 2) -> str:
    try:
        return f"${float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _number(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _utc_to_local(value: Any, timezone_name: str = "Asia/Hong_Kong") -> str:
    if not isinstance(value, str) or not value.strip():
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, KeyError):
        return value


def _clock_styles() -> None:
    """Keep the live clock compact without changing the size of other metrics."""
    st.markdown(
        """
        <style>
        .qqqm-clock-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.55rem;
            width: 100%;
            margin: 0.25rem 0 0.45rem 0;
        }
        .qqqm-clock-card {
            min-width: 0;
            box-sizing: border-box;
            padding: 0.65rem 0.75rem;
            border: 1px solid rgba(128, 128, 128, 0.26);
            border-radius: 0.7rem;
            background: var(--secondary-background-color, rgba(128, 128, 128, 0.06));
        }
        .qqqm-clock-label {
            font-size: 0.76rem;
            line-height: 1.25;
            opacity: 0.78;
            margin-bottom: 0.35rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .qqqm-clock-value {
            font-size: clamp(0.95rem, 1.2vw, 1.18rem);
            font-weight: 650;
            line-height: 1.3;
            letter-spacing: -0.015em;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .qqqm-clock-meta {
            font-size: 0.70rem;
            line-height: 1.3;
            opacity: 0.68;
            margin-top: 0.18rem;
            min-height: 0.9rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        @media (max-width: 1000px) {
            .qqqm-clock-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 480px) {
            .qqqm-clock-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.4rem; }
            .qqqm-clock-card { padding: 0.55rem 0.6rem; }
            .qqqm-clock-value { font-size: 0.98rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _split_datetime(value: str) -> tuple[str, str, str]:
    """Return date, time and optional zone abbreviation for compact cards."""
    parts = str(value or "—").split()
    if len(parts) >= 2:
        zone = parts[2] if len(parts) >= 3 else ""
        return parts[0], parts[1], zone
    return "", str(value or "—"), ""


def _short_market_status(raw_status: str) -> tuple[str, str]:
    """Use a short headline while retaining the full explanation underneath."""
    raw = str(raw_status or "状态未知")
    if "正常交易中" in raw:
        return "🟢 交易中", "美股常规交易时段"
    if "盘前" in raw:
        return "🟡 盘前", "常规交易尚未开市"
    if "盘后" in raw:
        return "🟠 盘后", "常规交易已经收市"
    if "休市" in raw:
        if "非交易日" in raw:
            return "🔴 休市", "周末或交易所假日"
        return "🔴 休市", "当前不在常规交易时段"
    return "⚪ 未知", raw


def _short_countdown_label(raw_label: str) -> str:
    raw = str(raw_label or "市场倒计时")
    if "收盘" in raw:
        return "距常规收盘"
    if "开盘" in raw and "下次" in raw:
        return "距下次开盘"
    if "开盘" in raw:
        return "距常规开盘"
    return "市场倒计时"


def _render_clock_content() -> None:
    clock = get_market_clock()
    local_date, local_time, _ = _split_datetime(clock.get("local_time", "—"))
    ny_date, ny_time, ny_zone = _split_datetime(clock.get("new_york_time", "—"))
    local_zone = str(clock.get("local_timezone", "Asia/Hong_Kong"))
    zone_abbreviations = {
        "Asia/Hong_Kong": "HKT",
        "Asia/Tokyo": "JST",
        "Asia/Shanghai": "CST",
        "Asia/Singapore": "SGT",
        "Asia/Taipei": "Taipei",
    }
    local_zone_label = zone_abbreviations.get(local_zone, local_zone.rsplit("/", 1)[-1].replace("_", " "))
    status_value, status_detail = _short_market_status(clock.get("market_status", "状态未知"))
    countdown_label = _short_countdown_label(clock.get("countdown_label", "市场倒计时"))
    countdown = str(clock.get("countdown") or "—")

    cards = [
        (f"本地时间 · {local_zone_label}", local_time, local_date),
        (f"美东时间{(' · ' + ny_zone) if ny_zone else ''}", ny_time, ny_date),
        ("美股市场状态", status_value, status_detail),
        (countdown_label, countdown, "按交易日历计算"),
    ]
    card_html = []
    for label, value, meta in cards:
        card_html.append(
            '<div class="qqqm-clock-card">'
            f'<div class="qqqm-clock-label">{escape(str(label))}</div>'
            f'<div class="qqqm-clock-value" title="{escape(str(value))}">{escape(str(value))}</div>'
            f'<div class="qqqm-clock-meta" title="{escape(str(meta))}">{escape(str(meta))}</div>'
            '</div>'
        )

    st.markdown(
        '<div class="qqqm-clock-grid">' + "".join(card_html) + '</div>',
        unsafe_allow_html=True,
    )

    source = clock.get("calendar_source", "未知")
    note = clock.get("calendar_note", "")
    st.caption(f"时间按秒刷新 · 时区：{local_zone} · 状态依据：{source}。{note}")


if hasattr(st, "fragment"):
    @st.fragment(run_every="1s")
    def _live_market_clock() -> None:
        _render_clock_content()

    def _show_live_clock() -> None:
        _live_market_clock()
else:
    # Compatibility fallback for older Streamlit versions.
    try:
        from streamlit_autorefresh import st_autorefresh
    except ImportError:
        st_autorefresh = None

    def _show_live_clock() -> None:
        if st_autorefresh is not None:
            st_autorefresh(interval=1000, key="market_clock_autorefresh")
        _render_clock_content()
        if st_autorefresh is None:
            st.warning(
                "当前 Streamlit 版本不支持 st.fragment，且未安装 streamlit-autorefresh，"
                "所以时间不会自动跳秒。请升级 Streamlit，或安装兼容刷新组件。"
            )


_clock_styles()

st.title("📈 QQQM Investment Assistant")
st.caption("看懂市场时间、下一交易日预测和预测复盘 · 研究辅助工具，不自动下单")

with st.container(border=True):
    st.subheader("🕒 市场时间与交易状态")
    _show_live_clock()

forecast = _read_json(FORECAST_PATH)
summary = _read_json(SUMMARY_PATH) or {}

if forecast is None:
    st.error(
        "没有读取到最新盘中预测 JSON。请确认文件存在：\n\n"
        "reports/intraday/QQQM_intraday_forecast_latest.json"
    )
    st.stop()

open_data = forecast.get("estimated_open") or {}
close_data = forecast.get("estimated_close_from_path") or {}
target_date = forecast.get("forecast_date_weekday_estimate") or "待确认"
as_of_date = forecast.get("as_of_date") or "未知"
previous_close = forecast.get("previous_session_close")

main_path_obj = forecast.get("main_path") if isinstance(forecast.get("main_path"), dict) else {}
main_open = main_path_obj.get("predicted_open_price", summary.get("main_path_open_price"))
main_close = main_path_obj.get("predicted_close_price", summary.get("main_path_close_price"))
main_model_name = str(main_path_obj.get("model_name") or "主路径尚未生成")
main_news_applied = bool(main_path_obj.get("news_adjustment_applied", summary.get("news_adjustment_applied", False)))

st.divider()
st.subheader("📌 下一交易日主预测")
info_a, info_b, info_c, info_d = st.columns(4)
info_a.metric("最近可用收盘参考价", _money(previous_close))
info_b.metric("主路径预计开盘", _money(main_open))
info_c.metric("主路径预计收盘", _money(main_close))
info_d.metric("新闻实验调整", "已应用" if main_news_applied else "未应用")
main_is_independent = bool(main_path_obj.get("independent_of_quantile_curves", False))
if main_is_independent:
    st.info(
        f"预测依据：截至 {as_of_date} 的已同步数据；目标日期：{target_date}。"
        "粗线是系统独立算出的主预测，不是把 P50 当答案。它仍是实验预测，"
        "不保证实际价格会照着它走。顶部参考价是最近一次已同步收盘价，不是实时成交价。"
    )
else:
    st.warning(
        f"目标日期：{target_date}。当前没有可用的独立主预测模型结果，"
        "页面可能正在显示旧方法生成的参考路径。请先重新运行预测，再把这条线当作主模型结果查看。"
    )

# Position inputs are deliberately user-editable. They are not broker-linked.
with st.sidebar:
    st.header("💰 我的持仓")
    st.caption("手动输入的估算值，不会连接或同步众安银行账户。")
    shares = st.number_input("QQQM 持有股数", min_value=0.0, value=2.0, step=1.0, format="%.4f")
    avg_cost = st.number_input("平均买入成本（美元/股）", min_value=0.0, value=310.0, step=0.1, format="%.4f")
    fees_paid = st.number_input("额外计入成本的手续费（美元）", min_value=0.0, value=0.0, step=0.1, format="%.2f")
    st.caption("这里的平均成本需要你根据真实成交和手续费自行维护。")

try:
    position = calculate_position(
        shares=shares,
        avg_cost=avg_cost,
        current_price=float(previous_close or 0),
        fees_paid=fees_paid,
    )
except (ValueError, TypeError) as exc:
    position = None
    st.sidebar.error(str(exc))

st.subheader("💵 持仓估算")
if position:
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("持仓市值（按最近收盘）", _money(position["market_value"]))
    p2.metric("总成本估算", _money(position["total_cost"]))
    p3.metric("未实现盈亏估算", _money(position["profit"]))
    p4.metric("盈亏率估算", f'{position["profit_pct"]:+.2f}%')
    p5.metric("持仓股数", _number(position["shares"], 4))
    st.caption("盈亏为按最近可用收盘价计算的估算值，未自动同步成交、买卖价差、税费或分红。")

st.divider()
st.subheader(f"📊 {target_date} 盘中主预测路径")
show_scenarios = st.checkbox(
    "同时显示 P10 / P50 / P90 情景参考线",
    value=False,
    help="默认只突出显示独立主预测路径。勾选后，额外显示历史分位情景供比较。",
)
render_intraday_chart(st, ROOT, show_scenarios=show_scenarios)

with st.expander("P10 / P50 / P90 是什么？什么时候有用？"):
    st.markdown(
        """
        **它们是风险情景参考，不是三个候选的买卖指令，也不是三种未来概率。**

        - **P10：** 每个 15 分钟时间点上，历史候选价格分布较低一端的参考值，可帮助观察偏弱情景。
        - **P50：** 每个时间点历史候选价格的中位数，适合作为中心参考，但不代表主模型认为它就是最可能的完整走势。
        - **P90：** 每个时间点历史候选价格分布较高一端的参考值，可帮助观察偏强情景。

        这些分位数是逐时间点分别计算的。把它们连接成线，不代表那条完整曲线曾经真实发生过，也不保证未来落在这些线之间。主预测路径由独立模型直接生成，默认优先展示。
        """
    )
    st.subheader("开盘情景参考")
    o1, o2, o3 = st.columns(3)
    o1.metric("偏低参考 · P10", _money(open_data.get("p10_price")))
    o2.metric("中位参考 · P50", _money(open_data.get("p50_price")))
    o3.metric("偏高参考 · P90", _money(open_data.get("p90_price")))
    st.subheader("收盘情景参考")
    c1, c2, c3 = st.columns(3)
    c1.metric("偏低参考 · P10", _money(close_data.get("p10_price")))
    c2.metric("中位参考 · P50", _money(close_data.get("p50_price")))
    c3.metric("偏高参考 · P90", _money(close_data.get("p90_price")))

if main_path_obj:
    with st.expander("查看主预测是怎么生成的（进阶说明）"):
        st.write("模型名称：", main_model_name)
        st.write("用于训练的历史记录数：", main_path_obj.get("training_rows", "—"))
        st.write("是否独立于 P10/P50/P90：", "是" if main_path_obj.get("independent_of_quantile_curves") else "否，可能使用旧方法回退")
        if main_path_obj.get("news_adjustment_note"):
            st.write(str(main_path_obj["news_adjustment_note"]))

st.divider()
st.subheader("📰 新闻有没有改变这次预测？")
path_diagnostics = forecast.get("path_selection_diagnostics") or {}
news = path_diagnostics.get("news_signal") or summary.get("news_signal") or {}
forecast_news_context = forecast.get("news_context") or {}
news_count = forecast_news_context.get("included_article_count", summary.get("news_article_count_at_forecast_cutoff"))
qualified_news = news.get("qualified_directional_articles", 0)
news_applied = bool(path_diagnostics.get("news_adjustment_applied", summary.get("news_adjustment_applied", False)))
news_signal = news.get("signal", 0)

n1, n2, n3 = st.columns(3)
n1.metric("预测时系统看到的新闻", str(news_count if news_count is not None else "—"))
n2.metric("方向较明确的新闻", str(qualified_news))
n3.metric("新闻调整这次主预测了吗？", "有（实验）" if news_applied else "没有")
if not news_applied:
    st.info(
        "这次没有足够可靠、方向明确的新闻，因此系统没有因为新闻去改变主预测线。"
        "这比硬把新闻解释成利好或利空更稳妥。"
    )
else:
    st.warning(
        "这次主预测线做了小幅新闻实验调整，但还没有足够的历史实测结果证明这样会更准。"
    )
with st.expander("查看新闻判断的技术细节"):
    st.write(f"方向性新闻计数：{qualified_news}")
    st.write(f"实验信号数值：{_number(news_signal, 2)}")
    st.write("提醒：这个信号不是上涨概率，也不是已经验证的因果关系。")

btest = forecast.get("backtest_summary") or {}
if not btest:
    btest = (forecast.get("backtest") or {}) if isinstance(forecast.get("backtest"), dict) else {}

st.subheader("🧪 过去的预测表现怎么样？")

# 用普通语言解释模型历史验证，不让缩写成为页面主角。
test_days = btest.get("walk_forward_test_sessions")
ridge_mae = btest.get("ridge_ml_path_mae_bps")
cluster_mae = btest.get("path_mae_bps_conditional_neighbor")
flat_mae = btest.get("path_mae_bps_flat_after_open_baseline")
ridge_open_mae = btest.get("ridge_ml_opening_mae_bps")

valid_a, valid_b, valid_c, valid_d = st.columns(4)
valid_a.metric("过去模拟检查了多少个交易日", str(test_days if test_days is not None else "—"))
valid_b.metric("主预测线平均偏差", f"{float(ridge_mae) / 100:.2f}%" if ridge_mae is not None else "暂时没有数据")
valid_c.metric("简单参考方法平均偏差", f"{float(flat_mae) / 100:.2f}%" if flat_mae is not None else "暂时没有数据")
valid_d.metric("主预测开盘价平均偏差", f"{float(ridge_open_mae) / 100:.2f}%" if ridge_open_mae is not None else "暂时没有数据")

if ridge_mae is not None and flat_mae is not None:
    delta_pct = (float(flat_mae) - float(ridge_mae)) / float(flat_mae) * 100 if float(flat_mae) else None
    if delta_pct is not None and delta_pct > 0:
        st.success(f"在这组历史模拟中，主预测线的平均偏差比简单参考方法低 {delta_pct:.1f}%。这只是当前样本的结果，不保证未来继续如此。")
    elif delta_pct is not None and delta_pct < 0:
        st.warning(f"在这组历史模拟中，主预测线的平均偏差比简单参考方法高 {abs(delta_pct):.1f}%。目前还看不出复杂模型有优势。")
    else:
        st.info("在这组历史模拟中，主预测线和简单参考方法的平均偏差相同。")

if test_days is not None:
    if int(test_days) < 30:
        st.warning("目前用于历史模拟检查的交易日较少，结果容易受个别行情影响，暂时不能判断模型是否稳定。")
    else:
        st.caption("这里是过去交易日的模拟检验，不是未来准确率。测试数量继续增加、并覆盖不同市场环境后，结论才会更有参考价值。")

with st.expander("“过去模拟检查”是什么意思？（新手版）"):
    st.markdown(
        """
        可以把它理解成**用过去的交易日做模拟考试**：

        1. 先选一个过去的交易日，只让模型看到那一天之前已经知道的资料。
        2. 让模型预测接下来的开盘和盘中走势。
        3. 再把预测与后来真实发生的价格比较，计算平均偏差。
        4. 把这个过程在多个交易日重复进行，观察模型有没有持续表现得更好。

        **“平均偏差”不是准确率。** 它表示预测价格平均离真实价格有多远，百分比越小通常越好。简单参考方法例如“开盘之后假设价格基本不变”，有时候也会胜过复杂模型。

        这种检查能减少“偷看未来数据”的问题，但不能保证模型未来继续有效。当前历史数据不多，结果只能作为观察依据。
        """
    )
    detail_a, detail_b, detail_c = st.columns(3)
    detail_a.metric("相似历史走势方法的平均偏差", f"{float(cluster_mae) / 100:.2f}%" if cluster_mae is not None else "暂时没有数据")
    detail_b.metric("简单参考方法的平均偏差", f"{float(flat_mae) / 100:.2f}%" if flat_mae is not None else "暂时没有数据")
    detail_c.metric("主预测线的平均偏差", f"{float(ridge_mae) / 100:.2f}%" if ridge_mae is not None else "暂时没有数据")
    if btest.get("first_test_date") or btest.get("last_test_date"):
        st.caption(f"这次模拟覆盖的日期：{btest.get('first_test_date', '—')} 至 {btest.get('last_test_date', '—')}。")

daily_review_ctx = build_daily_review_context(forecast, summary)
matched_summary = daily_review_ctx["matched_summary"]
actual_points = daily_review_ctx["actual_points_found"]
main_path_mae = matched_summary.get("main_path_curve_mae_bps_vs_actual")
p50_path_mae = matched_summary.get("p50_curve_mae_bps_vs_actual")
if int(actual_points or 0) > 0:
    st.markdown("**最近一次预测与真实走势的对照**")
    a1, a2, a3 = st.columns(3)
    a1.metric("已匹配的真实盘中价格点", str(actual_points))
    a2.metric("主预测线与实际价格的平均偏差", f"{float(main_path_mae) / 100:.2f}%" if main_path_mae is not None else "等待完整结算")
    a3.metric("中位参考线与实际价格的平均偏差", f"{float(p50_path_mae) / 100:.2f}%" if p50_path_mae is not None else "等待完整结算")
    st.caption("只有预测日期与实际数据日期相同，以上价格和误差才会对应起来；数据未完整同步时，不宜急着判断模型好坏。")
else:
    st.info(daily_review_ctx["explanation"])

with st.container(border=True):
    st.subheader("📝 每日预测复盘")
    st.caption("先看实际结果，再记录你的观察。人工反馈会单独保存，不会自动加入机器学习训练。")
    st.info(daily_review_ctx["explanation"])

    if daily_review_ctx["summary_matches_target"] and actual_points > 0:
        point_ratio = actual_points / max(1, daily_review_ctx["expected_points"])
        review_a, review_b, review_c, review_d = st.columns(4)
        review_a.metric("目标交易日", daily_review_ctx["target_date"] or "—")
        review_b.metric("实际价格点", f'{actual_points}/{daily_review_ctx["expected_points"]}')
        review_c.metric("实际开盘价", _money(daily_review_ctx["actual_open_price"]))
        review_d.metric("最后可用收盘价", _money(daily_review_ctx["actual_close_price"]))

        price_a, price_b = st.columns(2)
        open_err = daily_review_ctx["open_error_usd_actual_minus_predicted"]
        close_err = daily_review_ctx["close_error_usd_actual_minus_predicted"]
        with price_a:
            st.markdown("**开盘：预测 vs 实际**")
            st.write(f'预测：{_money(daily_review_ctx["predicted_open_price"])}')
            st.write(f'实际：{_money(daily_review_ctx["actual_open_price"])}')
            if open_err is not None:
                st.write(f'实际比预测：{open_err:+.2f} 美元')
        with price_b:
            st.markdown("**收盘：预测 vs 实际**")
            st.write(f'预测：{_money(daily_review_ctx["predicted_close_price"])}')
            st.write(f'最后可用实际价：{_money(daily_review_ctx["actual_close_price"])}')
            if close_err is not None:
                st.write(f'实际比预测：{close_err:+.2f} 美元')

        if point_ratio < 0.90:
            st.warning("这次还有部分 15 分钟价格点没匹配到。先把它当作初步复盘，数据同步完整后再比较模型。")
        if daily_review_ctx["main_path_mae_pct"] is not None:
            st.metric("这次主预测线的平均偏差", f'{daily_review_ctx["main_path_mae_pct"]:.2f}%')
            st.caption("这个百分比描述预测线和真实盘中价格平均相差多少，不是准确率，也不能单独代表长期水平。")
    elif daily_review_ctx["previous_completed_summary"]:
        previous = daily_review_ctx["previous_completed_summary"]
        st.caption(
            f'最近一次已有真实结果的交易日是 {previous["target_date"]}，'
            f'匹配到 {previous["actual_points_found"]} 个价格点。它属于旧预测，不能拿来评价当前目标日。'
        )

    with st.expander("记录我的观察（会保存到本地，方便以后改进）", expanded=True):
        with st.form(key=f'human_review_{daily_review_ctx["target_date"] or "unknown"}'):
            overall_match = st.selectbox(
                "看完实际走势后，你觉得这次主预测整体怎么样？",
                ["还没有实际结果，暂不判断", "走势比较接近", "有些地方接近", "走势差异较大"],
                index=0 if actual_points <= 0 else 1,
            )
            biggest_miss = st.selectbox(
                "你觉得最值得改进的部分是？",
                ["暂时看不出来", "开盘价偏差", "上午走势", "午后走势", "收盘方向或价格", "全天波动幅度", "新闻影响判断", "数据缺失或时间对不齐"],
            )
            news_helpfulness = st.selectbox(
                "这次新闻信息对理解预测有没有帮助？",
                ["暂时无法判断", "有帮助", "帮助不明显", "可能造成误导", "当时没有足够明确的新闻"],
            )
            notes = st.text_area(
                "补充观察（选填）",
                placeholder="例如：开盘比预测低，但午后反弹幅度没有被主路径体现。",
                max_chars=4000,
            )
            submitted = st.form_submit_button("保存本次复盘意见", type="primary")

        if submitted:
            try:
                feedback_path = save_human_feedback(
                    ROOT,
                    daily_review_ctx,
                    {
                        "overall_match": overall_match,
                        "biggest_miss": biggest_miss,
                        "news_helpfulness": news_helpfulness,
                        "notes": notes,
                    },
                )
                st.success(f"已保存到 {feedback_path.relative_to(ROOT)}。这条意见目前只作为人工复盘资料，不会自动训练模型。")
            except OSError as exc:
                st.error(f"保存失败：{exc}")

    recent_feedback = load_recent_human_feedback(ROOT, limit=5)
    if recent_feedback:
        with st.expander("查看最近保存的复盘意见"):
            for item in recent_feedback:
                st.markdown(f'**{item.get("target_date") or "日期未知"} · {item.get("user_overall_match") or "未填写"}**')
                st.caption(
                    f'重点：{item.get("user_biggest_miss") or "未填写"}；'
                    f'新闻帮助：{item.get("user_news_helpfulness") or "未填写"}'
                )
                if item.get("user_notes"):
                    st.write(item["user_notes"])
                st.divider()

with st.expander("查看数据来源、模型细节和注意事项（进阶）"):
    generated_at = forecast.get("generated_at_utc")
    st.write("预测生成时间（香港时间）：", _utc_to_local(generated_at, "Asia/Hong_Kong"))
    st.write("数据源：", f"{forecast.get('feed', '—')} / {forecast.get('timeframe', '—')}")
    st.write("相似历史交易日数量：", forecast.get("similar_session_count", "—"))
    st.write("主路径模型名称（技术字段）：", main_model_name)
    st.write("主路径训练记录数（技术字段）：", main_path_obj.get("training_rows", "—"))
    st.write("主路径是否独立于 P10/P50/P90：", "是" if main_path_obj.get("independent_of_quantile_curves") else "否，可能使用旧方法回退")
    st.write("当前历史训练是否把新闻当作训练输入：没有。因为还缺少足够完整的历史记录，无法确认每条新闻当时是否已经发布并完成分类。当前新闻只在条件满足时做可检查的实验性调整。")
    caveats = forecast.get("caveats", [])
    if caveats:
        st.markdown("**模型局限性**")
        for caveat in caveats:
            st.write(f"- {caveat}")

if CONTEXT_REPORT_PATH.exists():
    with st.expander("查看最新 AI 市场上下文报告"):
        try:
            report_text = CONTEXT_REPORT_PATH.read_text(encoding="utf-8-sig")
            st.markdown(report_text)
        except OSError as exc:
            st.warning(f"读取 AI 报告失败：{exc}")

st.caption("本页面仅用于研究和复盘，不构成投资建议，也不会自动下单。")
