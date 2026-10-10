
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.config import REPORTS_DIR


SYSTEM_PROMPT = """
你是一个面向投资新手的金融教育与市场研究助手，不是持牌投资顾问。

你的任务是根据用户提供的历史行情和技术指标，生成一份简体中文研究报告。

必须遵守以下规则：
1. 只使用输入中真实提供的数据，不得编造行情、新闻、宏观事件或数据来源。
2. 当前版本没有联网搜索新闻，也没有接入 FRED、美联储公告和最新经济数据。
   不得声称自己已经搜索了新闻或核实了当前宏观经济情况。
3. 明确区分数据事实、可能的解释和未知因素。
4. 均线、RSI、历史收益率和历史波动率都不能可靠地保证未来涨跌。
5. 不得给出确定性的买入、卖出指令。
6. 不要捏造目标价、上涨概率或预测准确率。
7. 如果某个指标为 null，明确说明数据不足，不得猜测数值。
8. 用通俗中文解释金融概念，尽量帮助投资新手理解原因及局限。
9. 明确指出分析局限和仍需观察的因素。
10. 必须输出一个完整、有效的 JSON 对象，不要使用 Markdown 代码围栏。

JSON 必须包含以下字段：
{
  "title": "报告标题",
  "data_cutoff": "行情数据截止日期",
  "plain_language_summary": "面向新手的总结",
  "observations": ["有数据支持的观察"],
  "possible_bullish_factors": ["可能的积极因素及局限"],
  "possible_bearish_factors": ["可能的风险因素及局限"],
  "what_to_watch": ["后续值得关注的指标或事件"],
  "limitations": ["数据与分析局限"],
  "education_note": "这不是个性化投资建议"
}

列表类型的字段必须返回 JSON 数组，即使没有内容也返回 []。
所有内容使用简体中文。
""".strip()


def _clean_json_text(text: str) -> str:
    """清理模型返回内容，兼容意外出现的 Markdown 代码围栏。"""
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
    """尝试解析完整 JSON，必要时从模型返回文本中提取 JSON 对象。"""
    if not content or not content.strip():
        return None

    cleaned = _clean_json_text(content)

    # 优先解析完整内容。
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 兼容模型在 JSON 对象前后附带解释文字的情况。
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        candidate = cleaned[start:end + 1]

        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def _as_list(value: Any) -> list[str]:
    """保证报告列表字段格式稳定，避免字符串被拆成单个字符。"""
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]

    if isinstance(value, str) and value.strip():
        return [value.strip()]

    return []


def _get_data_source(summary: dict[str, Any]) -> str:
    """从行情摘要读取数据来源，避免将 EODHD 错写成 Yahoo Finance。"""
    sources = summary.get("data_sources", [])

    if isinstance(sources, str) and sources.strip():
        return sources.strip()

    if isinstance(sources, (list, tuple, set)):
        values = [str(item) for item in sources if item]
        if values:
            return ", ".join(values)

    return os.getenv("MARKET_DATA_PROVIDER", "unknown").strip().lower()


def _build_user_prompt(
    ticker: str,
    summary: dict[str, Any],
) -> str:
    """构建发送给模型的分析任务。"""
    return (
        "请为标的 "
        + ticker.upper()
        + " 生成一份面向投资新手的中文市场研究报告。\n\n"
        + "请只输出一个完整、有效的 JSON 对象。\n"
        + "输出内容必须遵守系统提示中的字段定义。\n"
        + "不要输出 Markdown 代码围栏、JSON 以外的解释文字或虚构数据。\n"
        + "不能根据历史行情擅自推断当前新闻或美联储政策。\n"
        + "如果没有足够数据支持某个判断，请明确说明不确定性。\n\n"
        + "以下是程序计算的行情摘要，请以这些数据为依据：\n\n"
        + json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    )


def _request_report(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """
    请求 DeepSeek 生成报告。

    第一种方式：普通输出模式，关闭思考模式。
    第二种方式：关闭思考模式，并启用 JSON 输出。
    第三种方式：普通输出模式，不显式指定思考模式。

    仅在响应为空、格式无效或请求方式不兼容时继续尝试。
    """

    attempts: list[tuple[str, dict[str, Any]]] = [
        (
            "普通输出模式（关闭思考）",
            {
                "extra_body": {
                    "thinking": {"type": "disabled"}
                }
            },
        ),
        (
            "JSON 输出模式（关闭思考）",
            {
                "response_format": {"type": "json_object"},
                "extra_body": {
                    "thinking": {"type": "disabled"}
                },
            },
        ),
        (
            "普通输出兼容模式",
            {},
        ),
    ]

    diagnostics: list[str] = []
    last_non_json_content: str | None = None

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
            message = f"{label}请求失败：{type(exc).__name__}: {exc}"
            diagnostics.append(message)
            print(f"[AI 诊断] {message}")
            continue

        if not response.choices:
            diagnostics.append(f"{label}没有返回 choices。")
            continue

        choice = response.choices[0]
        message = choice.message

        content = (message.content or "").strip()
        finish_reason = getattr(choice, "finish_reason", None)

        if not content:
            reasoning = getattr(message, "reasoning_content", None)
            reasoning_length = len(reasoning or "")

            diagnostics.append(
                f"{label}返回空 content；"
                f"finish_reason={finish_reason!r}；"
                f"reasoning_content长度={reasoning_length}。"
            )

            print(f"[AI 诊断] {diagnostics[-1]}")
            continue

        report_data = _parse_report_json(content)

        if report_data is not None:
            return report_data, None, diagnostics

        # 保存最后一份非空文本，必要时作为原始分析报告输出。
        last_non_json_content = content

        diagnostics.append(
            f"{label}返回了非空内容，但未能解析成有效 JSON；"
            f"finish_reason={finish_reason!r}。"
        )

        print(f"[AI 诊断] {diagnostics[-1]}")

    return None, last_non_json_content, diagnostics


def _write_report(
    ticker: str,
    summary: dict[str, Any],
    model: str,
    report_data: dict[str, Any] | None,
    raw_content: str | None,
) -> Path:
    """把结构化报告或模型原始文本写入 Markdown 文件。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()
    run_stamp = now.strftime("%Y%m%d_%H%M%S")

    output_path = REPORTS_DIR / f"{ticker.upper()}_{run_stamp}.md"

    data_source = _get_data_source(summary)
    data_cutoff = summary.get("latest_date", "未知")

    lines: list[str] = [
        f"# {ticker.upper()} 每日研究报告",
        "",
        f"- 标的：{ticker.upper()}",
        f"- 行情截止日期：{data_cutoff}",
        f"- 报告生成时间：{now.isoformat(timespec='seconds')}",
        f"- AI 模型：{model}",
        f"- 行情数据来源：{data_source}",
        "",
        (
            "> 本报告用于金融教育与市场研究，不构成个性化投资建议。"
            "本版本尚未接入联网新闻搜索、FRED 宏观数据或美联储实时公告。"
        ),
        "",
    ]

    if report_data is None:
        # 模型确实返回了文本但无法生成合法 JSON 时，不丢弃已有内容。
        lines.extend(
            [
                "## AI 原始分析",
                "",
                (
                    "模型未按预期返回有效 JSON。"
                    "以下保留模型返回的原始文字，尚未经过结构化校验。"
                ),
                "",
                raw_content or "模型没有返回可用的正文内容。",
                "",
                "## 说明",
                "",
                "请谨慎阅读原始分析，不要将其视为已验证的预测或投资建议。",
                "",
            ]
        )
    else:
        title = str(
            report_data.get(
                "title",
                f"{ticker.upper()} 每日研究报告",
            )
        )

        # 使用模型提供的标题，但保留程序生成的元数据。
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

        sections = [
            ("数据观察", "observations"),
            ("可能的积极因素", "possible_bullish_factors"),
            ("可能的风险因素", "possible_bearish_factors"),
            ("后续值得关注", "what_to_watch"),
            ("局限与不确定性", "limitations"),
        ]

        for section_title, key in sections:
            lines.extend([f"## {section_title}", ""])

            items = _as_list(report_data.get(key))

            if items:
                lines.extend([f"- {item}" for item in items])
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
                        "本报告仅用于金融教育和研究，不构成个性化投资建议。",
                    )
                ),
                "",
            ]
        )

    # 附上程序计算的原始数据备注，方便后续核查报告依据。
    data_notes = _as_list(summary.get("data_notes"))

    if data_notes:
        lines.extend(["## 行情数据备注", ""])
        lines.extend([f"- {note}" for note in data_notes])
        lines.append("")

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return output_path


def generate_report(
    ticker: str,
    summary: dict[str, Any],
) -> Path:
    """生成 QQQM 等标的的 AI 研究报告并保存为 Markdown。"""

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()

    if (
        not api_key
        or api_key == "replace_with_your_deepseek_api_key"
    ):
        raise RuntimeError(
            "未配置 DEEPSEEK_API_KEY。"
            "请在项目根目录的 .env 文件中填写自己的 DeepSeek API Key。"
        )

    base_url = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ).strip()

    model = os.getenv(
        "DEEPSEEK_MODEL",
        "deepseek-flash",
    ).strip()

    if not model:
        raise RuntimeError(
            "DEEPSEEK_MODEL 为空，请检查 .env 配置。"
        )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=90.0,
        max_retries=0,
    )

    user_prompt = _build_user_prompt(
        ticker=ticker,
        summary=summary,
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    report_data, raw_content, diagnostics = _request_report(
        client=client,
        model=model,
        messages=messages,
    )

    if report_data is None and not raw_content:
        details = "\n".join(
            f"- {item}" for item in diagnostics
        )

        raise RuntimeError(
            "DeepSeek 连续尝试后仍未返回可用的报告正文。\n"
            "请检查模型名称、API 账户额度和接口状态。\n"
            "请求诊断信息：\n"
            + (details or "- 没有可用的详细错误信息。")
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
            "[AI 提示] 已保存模型原始文本。"
            "由于返回内容不是有效 JSON，部分结构化字段未生成。"
        )

    return output_path

