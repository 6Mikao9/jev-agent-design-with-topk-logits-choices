"""Deterministic decision-dense runtime workload.

This is an oracle/control-flow baseline: no network, model, or external side effect.
It drives a 24-step trajectory through paging, refinement, context faults,
stale revisions, clarification, and stop, while recording bounded residency.
"""
from __future__ import annotations
import json, time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from jev_agent.virtual_option import VirtualOptionManager, VirtualOption, OptionFault, StaleVirtualOption
from jev_agent.context_residency import ContextResidencyManager, ContextBlock, ContextFault

OUT = Path(__file__).parent / "results" / "decision-dense-workload-latest.json"

def opt(oid, page, desc, rev=1):
    return VirtualOption(oid, desc, page_id=page, revision=rev, kind="action")

def main():
    om = VirtualOptionManager(max_resident=4)
    cm = ContextResidencyManager(max_working=3, minimum_residency_steps=1)
    pages = {
      "root": [opt("observe", "root", "observe state"), opt("commit", "root", "commit action")],
      "page:tools": [opt("tool.read", "page:tools", "read file"), opt("tool.write", "page:tools", "write file")],
      "page:memory": [opt("mem.recent", "page:memory", "read recent memory"), opt("mem.archive", "page:memory", "read archive")],
      "page:plan": [opt("plan.coarse", "page:plan", "choose plan")],
    }
    for pid, options in pages.items(): om.register_page(pid, options)
    om.page_in("root")
    for i in range(8):
        cm.register(ContextBlock(f"ctx{i}", f"context block {i} state", f"memory://{i}", kind="task_state" if i == 0 else "observation"))
    records=[]; side_effects=0; costs=0.0
    events = ["COMMIT","COMMIT","PAGE","COMMIT","PAGE","COMMIT","REFINE","COMMIT","CTX_FAULT","COMMIT","STALE","PAGE","COMMIT","CLARIFY","COMMIT","REFINE","COMMIT","CTX_FAULT","PAGE","COMMIT","COMMIT","STOP","STOP","STOP"]
    page_for={3:"page:tools",5:"page:memory",12:"page:plan",19:"page:tools"}
    for step, event in enumerate(events, 1):
        t=time.perf_counter(); fault=None; recovery=None; action=event; effect=False
        try:
            if event == "PAGE":
                fault="OptionFault"; target=page_for[step]; om.page_in(target, limit=2); recovery="page_in"
            elif event == "REFINE":
                parent="plan.coarse"; om.refine(parent,[opt("plan.safe","refine:plan.coarse:r1","safe plan"),opt("plan.fast","refine:plan.coarse:r1","fast plan")],page_id="refine:plan.coarse:r1"); recovery="materialize_children"
            elif event == "CTX_FAULT":
                requested=f"ctx{step % 8}"
                try: cm.require(requested)
                except ContextFault:
                    fault="ContextFault"; cm.rebuild(f"context block {requested[3:]} state"); cm.require(requested); recovery="context_rebuild"
            elif event == "STALE":
                om.invalidate_page("page:tools"); fault="StaleVirtualOption"
                om.register_page("page:tools", [opt("tool.read.v2","page:tools","read file v2",rev=2),opt("tool.write.v2","page:tools","write file v2",rev=2)],revision=2)
                om.page_in("page:tools"); recovery="revision_refresh"
            elif event == "CLARIFY":
                action="CLARIFY"; recovery="safe_pause"
            elif event == "STOP":
                action="STOP"; recovery="terminal"
            elif event == "COMMIT":
                effect=True; side_effects += 1
        except (OptionFault, StaleVirtualOption, ContextFault) as exc:
            fault=type(exc).__name__; recovery="blocked"
        elapsed=(time.perf_counter()-t)*1000
        costs += 1.0 + (0.5 if fault else 0.0) + (0.25 if recovery else 0.0)
        records.append({"step":step,"event":event,"action":action,"fault":fault,"recovery":recovery,"simulated_side_effect":effect,"resident_count":len(om.resident_options()),"resident_bound":om.max_resident,"context_working_count":len(cm._working),"context_bound":cm.max_working,"latency_ms":round(elapsed,4),"cost_units":round(1.0+(0.5 if fault else 0.0)+(0.25 if recovery else 0.0),2)})
    result={"name":"decision-dense-workload","workload_steps":len(records),"oracle_control":True,"external_side_effects":0,"simulated_side_effects":side_effects,"resident_bound":om.max_resident,"max_resident_observed":max(r["resident_count"] for r in records),"context_bound":cm.max_working,"max_context_working_observed":max(r["context_working_count"] for r in records),"faults":sum(bool(r["fault"]) for r in records),"recoveries":sum(bool(r["recovery"]) for r in records),"total_cost_units":round(costs,2),"steps":records}
    OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps({k:result[k] for k in result if k!="steps"},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
