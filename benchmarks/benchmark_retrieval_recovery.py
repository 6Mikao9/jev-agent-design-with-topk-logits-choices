"""Retrieval -> decision -> PAGE/REFINE recovery benchmark.

The locator only sees query/page summaries and does not receive a target page id.
The decision step is a deterministic contract backend, so this isolates retrieval
and recovery mechanics before a live Jev backend is added. No external effects.
"""
from __future__ import annotations
import json,time
from pathlib import Path

OUT=Path(__file__).parent/'results'/'retrieval-recovery-latest.json'
PAGES={
 'files': 'read and write files in the workspace',
 'calendar': 'schedule meetings and inspect calendar availability',
 'database': 'query records and update database rows',
 'deploy': 'deploy services and inspect rollout status',
 'memory': 'retrieve archived task context and prior decisions',
 'refine': 'construct detailed parameters for a coarse action',
}
CASES=[
 ('read source file','files','PAGE'),('schedule review','calendar','PAGE'),('query user records','database','PAGE'),
 ('inspect rollout','deploy','PAGE'),('retrieve prior decision','memory','PAGE'),('construct exact path parameter','refine','REFINE'),
 ('ambiguous file or database request','files','CLARIFY'),('stale deployment schema','deploy','PAGE'),
 ('coarse calendar event needs exact time','calendar','REFINE'),('unsafe delete production records','database','STOP'),
 ('read source file again','files','PAGE'),('retrieve archived decision','memory','PAGE')]

def score(q,s):
    qw=set(q.lower().split()); sw=set(s.lower().split()); return len(qw&sw)
def main():
 rows=[]; loc_ok=rec_ok=missing=0; lat=[]
 for i,(query,target,expected) in enumerate(CASES,1):
  t=time.perf_counter(); ranked=sorted(PAGES,key=lambda p:(score(query,PAGES[p]),p),reverse=True); top=ranked[:2]
  # target is not given to locator; only used for evaluation.
  located=target in top
  if expected=='PAGE': missing+=1; action='PAGE' if located else 'STOP'
  elif expected=='REFINE': action='REFINE' if 'exact' in query or 'coarse' in query else 'PAGE'
  else: action=expected
  recovery=(action==expected and (expected not in ('PAGE','REFINE') or located))
  loc_ok += int(located); rec_ok += int(recovery); lat.append((time.perf_counter()-t)*1000)
  rows.append({'step':i,'query':query,'ranked_pages':ranked,'top_k':top,'expected_action':expected,'action':action,'target_page_for_evaluation':target,'missing_detected':expected in ('PAGE','REFINE'),'page_localized':located,'recovery_success':recovery,'simulated_side_effect':False,'latency_ms':round(lat[-1],4)})
 rows.sort(key=lambda x:x['step']); lat2=sorted(lat); p50=lat2[len(lat2)//2]; p95=lat2[max(0,int(len(lat2)*.95)-1)]
 out={'name':'retrieval-recovery','cases':len(rows),'oracle_decision_backend':True,'target_hidden_from_locator':True,'external_side_effects':0,'missing_detection_rate':round(sum(r['missing_detected'] for r in rows)/len(rows),3),'page_localization_rate':round(loc_ok/len(rows),3),'recovery_success_rate':round(rec_ok/len(rows),3),'p50_ms':round(p50,4),'p95_ms':round(p95,4),'steps':rows}
 OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({k:v for k,v in out.items() if k!='steps'},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
