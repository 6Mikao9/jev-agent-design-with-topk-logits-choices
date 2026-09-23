"""Break down direct Jev HTTPS latency into connection, headers, and body phases."""
from __future__ import annotations
import argparse, json, os, ssl
from http.client import HTTPSConnection
from pathlib import Path
from time import perf_counter

URL_HOST = "api.typesafe.ai"
URL_PATH = "/v1/systemone"

STATES = [
    ("resident_commit", "The current resident candidate is complete, current and authorized."),
    ("missing_page", "The resident candidate does not cover the explicit request; another option page is available."),
    ("commit_after_page", "A current page has been materialized and contains the validated requested operation."),
    ("coarse_refine", "The resident candidate has the right tool but a coarse query field; refine it before execution."),
    ("commit_after_refine", "The refined candidate is schema-valid and current; no coarse candidate remains resident."),
    ("ambiguous_clarify", "Friday and Saturday options conflict and the user has not specified a preference."),
    ("stale_stop", "The only candidate is stale after a revision and no safe replacement is available."),
    ("context_page", "The required context block is cold; retrieve it before committing a decision."),
]

CONTROLS = {
    "COMMIT": "Commit a current validated resident candidate and execute the simulated operation.",
    "PAGE": "Materialize another page or context block because current coverage is insufficient.",
    "REFINE": "Construct a finer-grained OptionSpace from a current coarse candidate.",
    "CLARIFY": "Ask the user because current constraints or preferences are ambiguous.",
    "STOP": "Stop safely because the state is stale, unauthorized, or unrecoverable.",
}


def payload(state: str, step: str) -> bytes:
    # Same shape as TypeSafeJevChooser; keep the option set fixed to isolate server latency.
    criteria = {"CANDIDATE": "A current resident candidate relevant to the request.", **CONTROLS}
    return json.dumps({
        "model": "jev-latest", "state": state,
        "questions": {"decision": {"type": "choice", "instructions": "Choose exactly one resident candidate or runtime action. Do not invent an option.", "criteria": criteria}},
    }, ensure_ascii=False).encode()


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, required=True); ap.add_argument("--reuse", action="store_true", help="reuse one HTTPS connection"); args = ap.parse_args()
    key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
    if not key: raise SystemExit("Set TYPESAFE_API_KEY or JEV_API_KEY")
    conn = None
    rows=[]
    for step, state in STATES:
        body = payload(state, step)
        t0=perf_counter(); connect_ms=None
        try:
            if conn is None or not args.reuse:
                if conn is not None:
                    conn.close()
                conn = HTTPSConnection(URL_HOST, timeout=30, context=ssl.create_default_context())
            # Explicit connect isolates DNS/TCP/TLS; --reuse pays it only on the first call.
            if not conn.sock:
                tc=perf_counter(); conn.connect(); connect_ms=(perf_counter()-tc)*1000
            tr=perf_counter()
            conn.request("POST", URL_PATH, body=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Connection": "keep-alive"})
            resp=conn.getresponse(); headers_ms=(perf_counter()-tr)*1000
            tb=perf_counter(); raw=resp.read(); body_ms=(perf_counter()-tb)*1000
            total_ms=(perf_counter()-t0)*1000
            data=json.loads(raw.decode())
            usage=data.get("usage", {})
            rows.append({"step":step,"status":resp.status,"payload_bytes":len(body),"response_bytes":len(raw),"connect_ms":connect_ms,"headers_ms":round(headers_ms,3),"body_ms":round(body_ms,3),"total_ms":round(total_ms,3),"input_tokens":usage.get("input_tokens"),"output_tokens":usage.get("output_tokens"),"model":data.get("model")})
        except Exception as exc:
            rows.append({"step":step,"error":type(exc).__name__+": "+str(exc),"total_ms":round((perf_counter()-t0)*1000,3)})
            try: conn.close()
            except Exception: pass
            conn=None
    totals=[r["total_ms"] for r in rows if "total_ms" in r and "status" in r]
    ordered=sorted(totals)
    summary={"calls":len(rows),"successful":len(totals),"mean_ms":sum(totals)/len(totals) if totals else None,"p50_ms":ordered[(len(ordered)-1)//2] if ordered else None,"p95_ms":ordered[min(len(ordered)-1, max(0,int(len(ordered)*.95)-1))] if ordered else None,"min_ms":min(totals) if totals else None,"max_ms":max(totals) if totals else None,"notes":["Direct HTTPSConnection with proxy bypass; headers_ms includes request send and server time to response headers; body_ms is response download/JSON bytes.",f"Connection reuse: {args.reuse}; default is fresh direct TLS per call to mirror the current urllib adapter.","No key or response body is written to the report."]}
    out={"experiment":"jev-direct-latency-breakdown","summary":summary,"rows":rows}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__": main()
