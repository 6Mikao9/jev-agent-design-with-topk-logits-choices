"""Live Jev recovery-gate matrix (no tool side effects).

LEGACY TARGET-CONDITIONED CONTROL: labels are not marked in the model prompt,
but target IDs drive resolve, recovery gating and materialization. This
script measures a supplied-target control, not autonomous missing detection.
See benchmark_jev_bounded_paging.py for answer-blind runtime evaluation.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceOption
from jev_agent.virtual_option import OptionFault, StaleVirtualOption, VirtualOption, VirtualOptionManager

PAGES = {"files": ("read_file", "list_files"), "calendar": ("create_event", "list_events"), "database": ("query_rows", "update_row"), "browser": ("open_url", "find_text")}
SUMMARY = {"files":"workspace file operations", "calendar":"calendar event scheduling", "database":"database row queries and updates", "browser":"web browsing and page retrieval"}
QUERIES = {"files":"read a source file", "calendar":"schedule a review meeting", "database":"query account rows", "browser":"open the documentation url"}
STATES = ("empty", "wrong_page", "stale", "correct_resident")

def manager():
    m = VirtualOptionManager(max_resident=2, max_pages=4)
    for p, tools in PAGES.items():
        m.register_page(p, [VirtualOption(f"{p}:{t}", f"Use {t}", page_id=p, kind="tool") for t in tools])
    return m

def page_options():
    return [ChoiceOption(f"PAGE:{p}", f"Materialize the {SUMMARY[p]} page") for p in PAGES] + [ChoiceOption("CLARIFY", "Ask the user for clarification"), ChoiceOption("STOP", "Stop safely")]

def tool_options(m, active_page):
    return [ChoiceOption(x.option_id, x.description) for x in m.resident_options() if x.page_id == active_page] + [ChoiceOption("CLARIFY", "Ask the user for clarification"), ChoiceOption("STOP", "Stop safely")]

def run_case(c, target_page, state):
    m = manager(); target_tool = PAGES[target_page][0]; target_id = f"{target_page}:{target_tool}"
    if state == "wrong_page":
        wrong = next(p for p in PAGES if p != target_page); m.page_in(wrong)
    elif state in ("stale", "correct_resident"):
        m.page_in(target_page)
        if state == "stale": m.invalidate_page(target_page)
    query = QUERIES[target_page]; start = time.perf_counter(); blocked = 0; gate = "unknown"
    try:
        m.resolve(target_id)
        gate = "resident_ok"
    except StaleVirtualOption:
        blocked = 1
        gate = "stale_option"
    except OptionFault:
        blocked = 1
        gate = "missing_option"
    page_choice = None; materialized = None
    if gate != "resident_ok":
        # The directory hint is runtime ranking metadata, not target metadata.
        page_result = c.choose(state=f"User request: {query}\nChoose a virtual page from these summaries.", instructions="Choose exactly one PAGE:<page_id>, CLARIFY, or STOP.", options=page_options())
        page_choice = page_result.choice; materialized = page_choice.removeprefix("PAGE:") if page_choice.startswith("PAGE:") else None
        if materialized == target_page:
            try:
                if state == "stale":
                    tools = PAGES[target_page]
                    m.register_page(target_page, [VirtualOption(f"{target_page}:{t}", f"Use {t}", page_id=target_page, kind="tool", revision=2) for t in tools], revision=2)
                m.page_in(target_page, limit=2)
            except (OptionFault, StaleVirtualOption):
                materialized = None
    tool_choice = None; tool_ok = False
    active_page = target_page if gate == "resident_ok" or materialized == target_page else None
    if active_page is not None:
        result = c.choose(state=f"User request: {query}\nChoose only a tool from the materialized page.", instructions="Choose exactly one listed tool, CLARIFY, or STOP.", options=tool_options(m, active_page))
        tool_choice = result.choice; tool_ok = tool_choice == target_id
    return {"page":target_page,"state":state,"gate_trigger":gate,"page_choice":page_choice,"page_recovery":materialized == target_page or state == "correct_resident","blocked_invalid_tool_calls":blocked,"in_page_selection":tool_ok,"end_to_end_success":tool_ok,"tool_choice":tool_choice,"latency_ms":round((time.perf_counter()-start)*1000,3),"resident_count":len(m.resident_options()),"resident_bound":2,"external_side_effects":0}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=Path(__file__).parent/"results"/"recovery-gate-live-latest.json"); args=ap.parse_args(); c=TypeSafeJevChooser(timeout_seconds=30)
    rows=[run_case(c,p,s) for p in PAGES for s in STATES]; nonresident=[r for r in rows if r["state"] != "correct_resident"]; times=sorted(r["latency_ms"] for r in rows)
    summary={"name":"recovery-gate-live","backend":"live Jev","cases":len(rows),"page_recovery_rate":round(sum(r["page_recovery"] for r in nonresident)/len(nonresident),3),"in_page_selection_rate":round(sum(r["in_page_selection"] for r in rows)/len(rows),3),"end_to_end_success_rate":round(sum(r["end_to_end_success"] for r in rows)/len(rows),3),"blocked_invalid_tool_calls":sum(r["blocked_invalid_tool_calls"] for r in rows),"p50_ms":times[len(times)//2],"p95_ms":times[min(len(times)-1,int(len(times)*.95)-1)],"resident_peak":max(r["resident_count"] for r in rows),"resident_bound":2,"external_side_effects":0}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps({**summary,"cases_detail":rows},ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__ == "__main__": main()
