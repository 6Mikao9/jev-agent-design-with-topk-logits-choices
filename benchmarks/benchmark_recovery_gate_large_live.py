"""Large live Jev recovery matrix with twelve semantically similar pages.

LEGACY TARGET-CONDITIONED CONTROL: expected page/tool labels drive resolve,
gate and materialization branches even though gold labels are not marked in
the model prompt. Its monitor request contains two actions but has one gold
tool, so that row's exact-match failure is not a reliable model error.
Retained to reproduce historical diagnostics, not to claim answer-blind
missing detection. See benchmark_jev_bounded_paging.py for that evaluation.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceOption
from jev_agent.virtual_option import OptionFault, StaleVirtualOption, VirtualOption, VirtualOptionManager

PAGES = {
    "source_files": ("read_source", "list_sources"),
    "project_files": ("read_project", "list_project_files"),
    "docs_search": ("search_docs", "open_doc"),
    "web_search": ("search_web", "open_result"),
    "calendar_events": ("create_event", "list_events"),
    "task_schedule": ("schedule_task", "list_tasks"),
    "db_accounts": ("query_accounts", "update_account"),
    "db_orders": ("query_orders", "update_order"),
    "deploy_service": ("deploy_service", "rollout_status"),
    "monitor_service": ("inspect_metrics", "ack_alert"),
    "recent_memory": ("retrieve_recent", "summarize_recent"),
    "archive_memory": ("retrieve_archive", "summarize_archive"),
}
SUMMARIES = {
    "source_files":"source code file reading and source listing",
    "project_files":"project file browsing and project listing",
    "docs_search":"documentation search and document opening",
    "web_search":"web search and opening a search result",
    "calendar_events":"calendar event creation and event listing",
    "task_schedule":"scheduled task creation and task listing",
    "db_accounts":"account record queries and account updates",
    "db_orders":"order record queries and order updates",
    "deploy_service":"service deployment and rollout status",
    "monitor_service":"service metrics inspection and alert acknowledgement",
    "recent_memory":"recent conversation memory retrieval and summarization",
    "archive_memory":"archived conversation memory retrieval and summarization",
}
QUERIES = {
    "source_files":"read the source code file named parser.py",
    "project_files":"read the project file named README.md",
    "docs_search":"find the API authentication section in the documentation",
    "web_search":"search the web for the current API release note",
    "calendar_events":"create a calendar event for tomorrow's review",
    "task_schedule":"schedule a recurring background task for tomorrow",
    "db_accounts":"query the account records for the billing owner",
    "db_orders":"query the order records for the latest invoice",
    "deploy_service":"deploy the staging service and inspect its rollout",
    "monitor_service":"inspect service latency metrics and acknowledge an alert",
    "recent_memory":"retrieve the decision from the recent conversation",
    "archive_memory":"retrieve the decision from an archived conversation",
}
STATES = ("empty", "wrong_page", "stale", "correct_resident")

def build_manager():
    m = VirtualOptionManager(max_resident=2, max_pages=len(PAGES))
    for page, tools in PAGES.items():
        m.register_page(page, [VirtualOption(f"{page}:{t}", f"Use the {SUMMARIES[page]} operation {t}", page_id=page, kind="tool") for t in tools])
    return m

def directory_options():
    return [ChoiceOption(f"PAGE:{p}", f"Materialize a page for {SUMMARIES[p]}") for p in PAGES] + [ChoiceOption("CLARIFY", "Ask for clarification"), ChoiceOption("STOP", "Stop safely")]

def tool_options(m, page):
    return [ChoiceOption(x.option_id, x.description) for x in m.resident_options() if x.page_id == page] + [ChoiceOption("CLARIFY", "Ask for clarification"), ChoiceOption("STOP", "Stop safely")]

def run_case(chooser, target_page, state):
    m = build_manager(); target_tool = PAGES[target_page][0]; target_id = f"{target_page}:{target_tool}"
    if state == "wrong_page": m.page_in(next(p for p in PAGES if p != target_page))
    elif state in ("stale", "correct_resident"):
        m.page_in(target_page)
        if state == "stale": m.invalidate_page(target_page)
    started = time.perf_counter(); blocked = 0; gate = "unknown"
    try: m.resolve(target_id); gate = "resident_ok"
    except StaleVirtualOption: blocked, gate = 1, "stale_option"
    except OptionFault: blocked, gate = 1, "missing_option"
    page_choice = None; materialized = None
    if gate != "resident_ok":
        result = chooser.choose(state=f"User request: {QUERIES[target_page]}\nChoose a virtual page from the directory.", instructions="Choose exactly one PAGE:<page_id>, CLARIFY, or STOP.", options=directory_options())
        page_choice = result.choice; materialized = page_choice.removeprefix("PAGE:") if page_choice.startswith("PAGE:") else None
        if materialized == target_page:
            if state == "stale":
                tools = PAGES[target_page]
                m.register_page(target_page, [VirtualOption(f"{target_page}:{t}", f"Use the {SUMMARIES[target_page]} operation {t}", page_id=target_page, kind="tool", revision=2) for t in tools], revision=2)
            m.page_in(target_page, limit=2)
    active = target_page if gate == "resident_ok" or materialized == target_page else None
    tool_choice = None; tool_ok = False
    if active:
        result = chooser.choose(state=f"User request: {QUERIES[target_page]}\nChoose only an operation from the materialized page.", instructions="Choose exactly one listed operation, CLARIFY, or STOP.", options=tool_options(m, active))
        tool_choice, tool_ok = result.choice, result.choice == target_id
    return {"target_page":target_page,"state":state,"gate_trigger":gate,"page_choice":page_choice,"page_recovery":(state=="correct_resident" or materialized==target_page),"blocked_invalid_tool_calls":blocked,"in_page_selection":tool_ok,"end_to_end_success":tool_ok,"tool_choice":tool_choice,"latency_ms":round((time.perf_counter()-started)*1000,3),"resident_count":len(m.resident_options()),"resident_bound":2,"external_side_effects":0}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output", type=Path, default=Path(__file__).parent/"results"/"recovery-gate-large-live-latest.json"); args=ap.parse_args(); chooser=TypeSafeJevChooser(timeout_seconds=30)
    rows=[run_case(chooser,p,s) for p in PAGES for s in STATES]; nonresident=[r for r in rows if r["state"] != "correct_resident"]; times=sorted(r["latency_ms"] for r in rows)
    summary={"name":"recovery-gate-large-live","backend":"live Jev","pages":len(PAGES),"cases":len(rows),"states":list(STATES),"page_recovery_rate":round(sum(r["page_recovery"] for r in nonresident)/len(nonresident),3),"in_page_selection_rate":round(sum(r["in_page_selection"] for r in rows)/len(rows),3),"end_to_end_success_rate":round(sum(r["end_to_end_success"] for r in rows)/len(rows),3),"blocked_invalid_tool_calls":sum(r["blocked_invalid_tool_calls"] for r in rows),"p50_ms":times[len(times)//2],"p95_ms":times[min(len(times)-1,int(len(times)*.95)-1)],"resident_peak":max(r["resident_count"] for r in rows),"resident_bound":2,"external_side_effects":0}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps({**summary,"cases_detail":rows},ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__ == "__main__": main()
