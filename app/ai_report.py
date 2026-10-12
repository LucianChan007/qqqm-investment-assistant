
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.config import REPORTS_DIR


SYSTEM_PROMPT = """
你是一名面向投资新手的金融教育与市场研究助手，不是持牌投资顾问。

你的任务是根据用户提供的历史行情、技术指标，以及（如果存在）
FRED 宏观经济观测数据，生成一份简体中文研究报告。

必须遵守以下规则：
1. 只能使用输入中真实提供的数据，不得编造行情、新闻、宏观事件或数值。
2. 当前版本没有联网搜索新闻。不得声称已经搜索最新新闻、
   核实最新美联储公告或访问输入中不存在的数据。
3. 只有输入中实际包含 macro 数据时，才能分析其中的 FRED 观测值。
4. 每次提及宏观数据时，应尽可能注明观测日期和单位。
5. 必须区分已知事实、可能的经济机制解释和未知因素。
6. 利率、CPI 与 QQQM 同时变化，并不能证明存在直接因果关系。
7. 降息不必然意味着科技股上涨，升息也不必然意味着科技股下跌。
   市场预期、企业盈利、估值和经济增长都可能影响结果。
8. 均线、RSI、历史收益率和波动率不能保证未来走势。
9. 不得捏造目标价、上涨概率、预测准确率或没有数据支持的结论。
10. 不得输出确定性的买入或卖出指令。
11. 如果某项数据缺失，明确说明，不得猜测。
12. 使用通俗中文解释金融概念，帮助新手理解指标及其局限。
13. 输出一个完整、有效的 JSON 对象，不得使用 Markdown 代码围栏。

JSON 必须包含以下字段：
{
  "title": "报告标题",
  "plain_language_summary": "面向投资新手的总结",
  "observations": ["基于真实行情数据的观察"],
  "macro_context": ["基于实际 FRED 数据的宏观环境观察"],
  "possible_bullish_factors": ["可能的积极因素及其局限"],
  "possible_bearish_factors": ["可能的风险因素及其局限"],
  "what_to_watch": ["后续值得关注的指标或事件"],
  "limitations": ["数据与分析局限"],
  "education_note": "金融教育说明及投资风险提示"
}

所有列表字段都必须返回 JSON 数组，即使没有内容也返回 []。
所有报告内容使用简体中文。
""".strip()


REPORT_LIST_FIELDS = [
    ("数据观察", "observations"),
    ("宏观环境观察", "macro_context"),
    ("可能的积极因素", "possible_bullish_factors"),
    ("可能的风险因素", "possible_bearish_factors"),
    ("后续值得关注", "what_to_watch"),
    ("局限与不确定性", "limitations"),
]


def _redact_secret(text: str) -> str:
    """避免意外将 API Key 写入错误日志。"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()

    if api_key:
        return text.replace(api_key, "***")

    return text


def _clean_json_text(text: str) -> str:
    """清理模型可能返回的 Markdown 代码围栏。"""
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return text


def _parse_report_json(content: str) -> dict[str, Any] | None:
    """将模型正文解析为 JSON 对象。"""
    if not content or not content.strip():
        return None

    cleaned = _clean_json_text(content)

    try:
        parsed = json.loads(cleaned)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    # 兼容 JSON 前后存在少量解释文字的情况。
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    return None


def _as_list(value: Any) -> list[str]:
    """确保报告列表字段始终是可迭代的字符串列表。"""
    if isinstance(value, list):
        return [
            str(item)
            for item in value
            if item is not None and str(item).strip()
        ]

    if isinstance(value, str) and value.strip():
        return [value.strip()]

    return []


def _get_data_source(summary: dict[str, Any]) -> str:
    """读取实际行情数据源。"""
    sources = summary.get("data_sources", [])

    if isinstance(sources, str) and sources.strip():
        return sources.strip()

    if isinstance(sources, (list, tuple, set)):
        values = [str(item) for item in sources if item]

        if values:
            return ", ".join(values)

    return os.getenv(
        "MARKET_DATA_PROVIDER",
        "unknown",
    ).strip().lower()


def _get_macro_series(
    summary: dict[str, Any],
) -> dict[str, Any]:
    """读取 FRED 宏观数据，兼容没有宏观数据的旧报告。"""
    macro = summary.get("macro", {})

    if not isinstance(macro, dict):
        return {}

    series = macro.get("series", {})

    if not isinstance(series, dict):
        return {}

    return {
        str(series_id): item
        for series_id, item in series.items()
        if isinstance(item, dict)
    }


def _has_macro_data(summary: dict[str, Any]) -> bool:
    """判断是否存在至少一项有效的宏观观测值。"""
    return any(
        item.get("latest_value") is not None
        for item in _get_macro_series(summary).values()
    )


def _build_user_prompt(
    ticker: str,
    summary: dict[str, Any],
) -> str:
    """构建包含技术指标和可选宏观数据的分析任务。"""
    ticker = ticker.upper()

    macro_present = _has_macro_data(summary)

    if macro_present:
        macro_instruction = (
            "输入包含真实的 FRED 宏观观测数据。"
            "请单独分析这些数据反映的宏观环境，"
            "注明实际观测日期与单位，"
            "并解释其可能影响成长股估值的经济机制。"
            "必须指出这些数据不能证明 QQQM 涨跌的直接原因。"
        )
    else:
        macro_instruction = (
            "输入不包含有效的 FRED 宏观观测数据。"
            "macro_context 必须返回空数组。"
            "不得编造利率、CPI 或其他宏观数值。"
        )

    return (
        f"请为标的 {ticker} 生成一份面向投资新手的中文研究报告。\n\n"
        "请严格输出一个完整、有效的 JSON 对象。\n"
        "不要输出 Markdown 代码围栏或 JSON 以外的解释文字。\n"
        "不要声称已经联网搜索新闻。\n"
        f"{macro_instruction}\n"
        "如果某项数据缺失，请在局限部分说明。\n\n"
        "以下是程序采集和计算的行情及宏观数据摘要：\n\n"
        + json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def _request_report(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
) -> tuple[
    dict[str, Any] | None,
    str | None,
    list[str],
]:
    """
    尝试不同的 DeepSeek 输出模式。

    先尝试普通输出，再尝试 JSON 模式，最后使用兼容模式。
    不读取或输出模型的隐藏推理内容。
    """

    attempts: list[tuple[str, dict[str, Any]]] = [
        (
            "普通输出模式",
            {},
        ),
        (
            "JSON 输出模式",
            {
                "response_format": {
                    "type": "json_object",
                },
                "extra_body": {
                    "thinking": {
                        "type": "disabled",
                    },
                },
            },
        ),
        (
            "关闭思考模式重试",
            {
                "extra_body": {
                    "thinking": {
                        "type": "disabled",
                    },
                },
            },
        ),
    ]

    diagnostics: list[str] = []
    raw_content: str | None = None

    for label, extra_params in attempts:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=3000,
                temperature=0.2,
                **extra_params,
            )

        except Exception as exc:
            message = _redact_secret(
                f"{label}请求失败：{type(exc).__name__}: {exc}"
            )

            diagnostics.append(message)
            print(f"[AI 诊断] {message}")
            continue

        if not response.choices:
            message = f"{label}没有返回 choices。"

            diagnostics.append(message)
            print(f"[AI 诊断] {message}")
            continue

        choice = response.choices[0]
        message = choice.message

        content = (message.content or "").strip()
        finish_reason = getattr(choice, "finish_reason", None)

        if not content:
            reasoning = getattr(
                message,
                "reasoning_content",
                None,
            )

            diagnostic = (
                f"{label}返回空正文；"
                f"finish_reason={finish_reason!r}；"
                f"推理字段长度={len(reasoning or '')}。"
            )

            diagnostics.append(diagnostic)
            print(f"[AI 诊断] {diagnostic}")
            continue

        parsed = _parse_report_json(content)

        if parsed is not None:
            return parsed, None, diagnostics

        raw_content = content

        diagnostic = (
            f"{label}返回了正文，但不是有效 JSON；"
            f"finish_reason={finish_reason!r}。"
        )

        diagnostics.append(diagnostic)
        print(f"[AI 诊断] {diagnostic}")

    return None, raw_content, diagnostics


def _format_value(value: Any) -> str:
    """格式化宏观数值，避免将缺失数据伪装成 0。"""
    if value is None:
        return "暂无数据"

    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")

    return str(value)


def _append_macro_evidence(
    lines: list[str],
    summary: dict[str, Any],
) -> None:
    """
    将实际 FRED 观测值写入报告。

    这是程序直接记录的数据证据，与模型的解释分开保存。
    """

    macro = summary.get("macro")

    if not isinstance(macro, dict):
        lines.extend(
            [
                "## FRED 宏观数据",
                "",
                "本次报告没有传入 FRED 宏观数据。",
                "",
            ]
        )
        return

    series = _get_macro_series(summary)

    if not series:
        lines.extend(
            [
                "## FRED 宏观数据",
                "",
                "本地摘要中没有可用的宏观观测值。",
                "",
            ]
        )
        return

    lines.extend(
        [
            "## FRED 宏观数据：实际观测值",
            "",
            (
                f"- 数据来源：{macro.get('source', 'FRED')}"
            ),
            (
                f"- 摘要生成时间："
                f"{macro.get('retrieved_at', '未知')}"
            ),
            "",
            "| 系列 | 指标 | 最新观测日期 | 最新值 | 单位 |",
            "|---|---|---|---:|---|",
        ]
    )

    for series_id, item in series.items():
        value = item.get("latest_value")

        if value is None:
            continue

        name = str(item.get("name", series_id))
        observation_date = str(
            item.get("latest_observation_date", "未知")
        )
        unit = str(item.get("unit", "未知"))

        lines.append(
            f"| {series_id} | {name} | {observation_date} "
            f"| {_format_value(value)} | {unit} |"
        )

    lines.extend(
        [
            "",
            "### 变化参考",
            "",
        ]
    )

    has_comparison = False

    for series_id, item in series.items():
        if item.get("change_vs_30_days_ago_pp") is not None:
            change = item["change_vs_30_days_ago_pp"]
            comparison_date = item.get(
                "comparison_date",
                "约30日前",
            )

            lines.append(
                f"- **{series_id}**：相较 {comparison_date} "
                f"变化 {_format_value(change)} 个百分点。"
            )

            has_comparison = True

        if item.get("year_over_year_pct") is not None:
            yoy = item["year_over_year_pct"]
            year_ago_date = item.get(
                "year_ago_date",
                "去年同期",
            )

            lines.append(
                f"- **{series_id}**：相较 {year_ago_date} "
                f"同比变化 {_format_value(yoy)}%。"
            )

            has_comparison = True

        if item.get("month_over_month_pct") is not None:
            mom = item["month_over_month_pct"]

            lines.append(
                f"- **{series_id}**：最新月度指数相较前一有效月度"
                f"观测变化 {_format_value(mom)}%。"
            )

            has_comparison = True

    if not has_comparison:
        lines.append("- 当前摘要没有可用的历史变化比较值。")

    lines.extend(
        [
            "",
            "> 以上数值来自程序保存的 FRED 观测记录。"
            "各系列发布时间和频率不同；最新观测日期不一定是今天。"
            "利率变化与股票表现之间的相关性不构成直接因果证明。",
            "",
        ]
    )


def _write_report(
    ticker: str,
    summary: dict[str, Any],
    model: str,
    report_data: dict[str, Any] | None,
    raw_content: str | None,
) -> Path:
    """将 AI 分析与真实数据证据写入 Markdown 报告。"""

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = datetime.now().astimezone()
    run_stamp = now.strftime("%Y%m%d_%H%M%S")

    output_path = REPORTS_DIR / (
        f"{ticker.upper()}_{run_stamp}.md"
    )

    data_source = _get_data_source(summary)
    data_cutoff = summary.get("latest_date", "未知")

    if _has_macro_data(summary):
        scope_note = (
            "> 本报告结合历史行情、技术指标及 FRED 宏观观测数据。"
            "当前版本未联网搜索新闻或自动核实最新美联储公告。"
            "宏观变化不代表已证明其导致 QQQM 涨跌。"
            "本报告不构成个性化投资建议。"
        )
    else:
        scope_note = (
            "> 本报告基于历史行情和技术指标。"
            "当前版本没有使用有效的 FRED 宏观观测数据，"
            "也未联网搜索新闻。"
            "本报告不构成个性化投资建议。"
        )

    lines: list[str] = [
        f"# {ticker.upper()} 市场研究报告",
        "",
        f"- 标的：{ticker.upper()}",
        f"- 行情截止日期：{data_cutoff}",
        (
            f"- 报告生成时间："
            f"{now.isoformat(timespec='seconds')}"
        ),
        f"- AI 模型：{model}",
        f"- 行情数据来源：{data_source}",
        "",
        scope_note,
        "",
    ]

    # 始终先保留程序实际读取的宏观数据，方便核对 AI 的解释。
    _append_macro_evidence(lines, summary)

    if report_data is None:
        lines.extend(
            [
                "## AI 原始分析",
                "",
                (
                    "模型没有返回可解析的 JSON。"
                    "以下保留收到的正文供排查，"
                    "该内容未经结构化字段校验。"
                ),
                "",
                raw_content or "模型没有返回可用正文。",
                "",
            ]
        )

    else:
        title = str(
            report_data.get(
                "title",
                f"{ticker.upper()} 市场研究报告",
            )
        )

        lines[0] = f"# {title}"

        lines.extend(
            [
                "## 通俗总结",
                "",
                str(
                    report_data.get(
                        "plain_language_summary",
                        "模型没有提供总结。",
                    )
                ),
                "",
            ]
        )

        for section_title, key in REPORT_LIST_FIELDS:
            lines.extend(
                [
                    f"## {section_title}",
                    "",
                ]
            )

            items = _as_list(report_data.get(key))

            if items:
                lines.extend(
                    f"- {item}"
                    for item in items
                )
            else:
                if key == "macro_context" and not _has_macro_data(summary):
                    lines.append(
                        "- 本次报告没有可用的 FRED 宏观数据，未进行宏观判断。"
                    )
                else:
                    lines.append("- 暂无")

            lines.append("")

        lines.extend(
            [
                "## 说明",
                "",
                str(
                    report_data.get(
                        "education_note",
                        (
                            "本报告仅用于金融教育和市场研究，"
                            "不构成个性化投资建议。"
                        ),
                    )
                ),
                "",
            ]
        )

    data_notes = _as_list(summary.get("data_notes"))

    if data_notes:
        lines.extend(
            [
                "## 行情数据备注",
                "",
            ]
        )

        lines.extend(
            f"- {note}"
            for note in data_notes
        )

        lines.append("")

    lines.extend(
        [
            "## 报告生成说明",
            "",
            "- 技术指标由程序根据本地行情数据计算。",
            "- FRED 观测值由程序独立读取并展示，宏观解释由 AI 生成。",
            "- 本版本尚未自动搜索最新新闻。",
            "- 历史数据、宏观相关性和 AI 解释均不能保证未来收益。",
            "",
        ]
    )

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return output_path


def generate_report(
    ticker: str,
    summary: dict[str, Any],
) -> Path:
    """生成中文研究报告并保存到 reports 目录。"""

    api_key = os.getenv(
        "DEEPSEEK_API_KEY",
        "",
    ).strip()

    if (
        not api_key
        or api_key == "replace_with_your_deepseek_api_key"
    ):
        raise RuntimeError(
            "未配置有效的 DEEPSEEK_API_KEY。"
            "请检查项目根目录 .env 文件。"
        )

    base_url = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ).strip()

    model = os.getenv(
        "DEEPSEEK_MODEL",
        "deepseek-flash",
    ).strip()

    if not base_url:
        raise RuntimeError(
            "DEEPSEEK_BASE_URL 为空，请检查 .env 文件。"
        )

    if not model:
        raise RuntimeError(
            "DEEPSEEK_MODEL 为空，请检查 .env 文件。"
        )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=90.0,
        max_retries=0,
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": _build_user_prompt(
                ticker=ticker,
                summary=summary,
            ),
        },
    ]

    report_data, raw_content, diagnostics = _request_report(
        client=client,
        model=model,
        messages=messages,
    )

    if report_data is None and not raw_content:
        details = "\n".join(
            f"- {_redact_secret(item)}"
            for item in diagnostics
        )

        raise RuntimeError(
            "DeepSeek 多次尝试后仍未返回可用正文。\n"
            "请检查模型名称、API 额度和接口状态。\n"
            "诊断信息：\n"
            + (
                details
                if details
                else "- 没有可用的详细诊断信息。"
            )
        )

    output_path = _write_report(
        ticker=ticker,
        summary=summary,
        model=model,
        report_data=report_data,
        raw_content=raw_content,
    )

    if report_data is None:
        print(
            "[AI 提示] 模型返回了正文，但无法解析为有效 JSON。"
            "已保存原始文本，部分结构化章节可能缺失。"
        )

    return output_path

