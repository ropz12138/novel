#!/usr/bin/env python3
"""获取 LangSmith 最新一条 Supervisor 对话的完整 trace

用法:
    export LANGSMITH_API_KEY="lsv2_sk_xxx"
    python scripts/fetch_latest_trace.py

功能:
    1. 查询 Novel 项目中最新一条根 run（is_root=true）
    2. 获取该 trace 下所有子 run（包括 tool calls）
    3. 按执行顺序输出每一步的工具调用、输入、输出
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from langsmith import Client

BASE_URL = "https://api.smith.langchain.com"
PROJECT_NAME = "Novel"


def get_headers():
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            api_key = (config.get("observability") or {}).get("langsmith_api_key")
            if api_key:
                os.environ["LANGSMITH_API_KEY"] = api_key
        except Exception:
            api_key = None
    if not api_key:
        print("请设置 LANGSMITH_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)
    return {
        "x-api-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def query_root_runs(headers: dict) -> list[dict]:
    """查询最新的根 run（即一条完整对话的入口）"""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)  # 最近 24 小时

    # 使用官方 SDK 查询
    client = Client(api_key=os.environ.get("LANGSMITH_API_KEY"))
    runs = list(client.list_runs(
        project_name=PROJECT_NAME,
        is_root=True,
        start_time=start,
        limit=3,
    ))
    return [_run_to_dict(r) for r in runs]


def query_trace_runs(headers: dict, trace_id: str) -> list[dict]:
    """获取一条 trace 下的所有子 run"""
    client = Client(api_key=os.environ.get("LANGSMITH_API_KEY"))
    runs = list(client.list_runs(
        project_name=PROJECT_NAME,
        trace_id=trace_id,
        limit=100,
    ))
    return [_run_to_dict(r) for r in runs]


def _run_to_dict(run) -> dict:
    """把 LangSmith SDK Run 对象转成脚本原来的 dict 结构。"""
    return {
        "id": str(getattr(run, "id", "") or ""),
        "trace_id": str(getattr(run, "trace_id", "") or ""),
        "parent_run_id": str(getattr(run, "parent_run_id", "") or "") if getattr(run, "parent_run_id", None) else "",
        "name": getattr(run, "name", "") or "",
        "run_type": getattr(run, "run_type", "") or "",
        "start_time": getattr(run, "start_time", None).isoformat() if getattr(run, "start_time", None) else None,
        "end_time": getattr(run, "end_time", None).isoformat() if getattr(run, "end_time", None) else None,
        "status": getattr(run, "status", "") or ("error" if getattr(run, "error", None) else "success"),
        "inputs": getattr(run, "inputs", {}) or {},
        "outputs": getattr(run, "outputs", {}) or {},
    }


def format_time(ts: str | None) -> str:
    if not ts:
        return "?"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts[:19]


def print_trace(runs: list[dict]):
    """按时间顺序打印 trace"""
    # 按 start_time 排序
    sorted_runs = sorted(runs, key=lambda r: r.get("start_time") or "")

    print(f"\n{'='*80}")
    print(f"  LangSmith Trace — {PROJECT_NAME}")
    print(f"  共 {len(sorted_runs)} 个 run")
    print(f"{'='*80}\n")

    for run in sorted_runs:
        run_type = run.get("run_type", "?")
        name = run.get("name", "?")
        status = run.get("status", "?")
        start = format_time(run.get("start_time"))
        end = format_time(run.get("end_time"))
        parent = run.get("parent_run_id", "")

        indent = "  " if parent else ""

        print(f"{indent}[{run_type}] {name} ({start} → {end}) [{status}]")

        # 对于 tool 类型，显示输入和输出的关键信息
        if run_type == "tool":
            inputs = run.get("inputs", {})
            outputs = run.get("outputs", {})

            # 输入摘要
            if isinstance(inputs, dict):
                input_str = json.dumps(inputs, ensure_ascii=False, default=str)[:200]
                print(f"{indent}  输入: {input_str}")

            # 输出摘要
            if isinstance(outputs, dict):
                output_str = json.dumps(outputs, ensure_ascii=False, default=str)[:300]
                print(f"{indent}  输出: {output_str}")
            elif isinstance(outputs, str):
                print(f"{indent}  输出: {outputs[:300]}")

        elif run_type == "chat_model" or run_type == "llm":
            # LLM 调用：显示 tool_calls 和响应
            inputs = run.get("inputs", {})
            outputs = run.get("outputs", {})

            if isinstance(inputs, dict) and "messages" in inputs:
                msgs = inputs["messages"]
                if isinstance(msgs, list) and msgs:
                    last_msg = msgs[-1] if msgs else {}
                    content = ""
                    if isinstance(last_msg, dict):
                        content = str(last_msg.get("kwargs", {}).get("content", ""))[:100]
                    elif hasattr(last_msg, "content"):
                        content = str(last_msg.content)[:100]
                    print(f"{indent}  最后输入: {content}")

            if isinstance(outputs, dict):
                generations = outputs.get("generations", [])
                if generations and generations[0]:
                    gen = generations[0][0]
                    if isinstance(gen, dict):
                        msg = gen.get("message", {})
                        kwargs = msg.get("kwargs", {})
                        content = str(kwargs.get("content", ""))[:200]
                        tool_calls = kwargs.get("tool_calls", [])
                        print(f"{indent}  响应: {content}")
                        if tool_calls:
                            for tc in tool_calls:
                                tc_name = tc.get("name", "?")
                                tc_args = json.dumps(tc.get("args", {}), ensure_ascii=False)[:200]
                                print(f"{indent}  Tool Call: {tc_name}({tc_args})")

        print()


def save_full_trace(runs: list[dict], trace_id: str):
    """保存完整 trace 到 JSON 文件"""
    filename = f"/tmp/langsmith_trace_{trace_id[:8]}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(runs, f, ensure_ascii=False, indent=2, default=str)
    print(f"完整 trace 已保存到: {filename}")


def main():
    headers = get_headers()

    print(f"正在查询项目 {PROJECT_NAME} 的最新 trace...")

    # 1. 查询最新根 run
    root_runs = query_root_runs(headers)
    if not root_runs:
        print("未找到最近的 trace。尝试扩大时间范围到 24 小时...")
        # 扩大到 24 小时
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)
        resp = requests.post(
            f"{BASE_URL}/api/v1/runs/query",
            headers=headers,
            json={
                "project_name": PROJECT_NAME,
                "is_root": True,
                "start_time": start.isoformat(),
                "end_time": now.isoformat(),
                "limit": 3,
                "select": ["id", "trace_id", "name", "run_type", "start_time", "end_time", "status"],
                "order": "desc",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        root_runs = data.get("runs", []) if isinstance(data, dict) else data

    if not root_runs:
        print("未找到任何 trace。")
        sys.exit(1)

    root = root_runs[0]
    trace_id = root.get("trace_id", "")
    print(f"找到最新 trace: {trace_id}")
    print(f"  根 run: {root.get('name')} ({root.get('start_time')})")

    # 2. 获取完整 trace
    print("正在获取完整 trace 数据...")
    trace_runs = query_trace_runs(headers, trace_id)

    # 3. 打印
    print_trace(trace_runs)

    # 4. 保存
    save_full_trace(trace_runs, trace_id)


if __name__ == "__main__":
    main()
