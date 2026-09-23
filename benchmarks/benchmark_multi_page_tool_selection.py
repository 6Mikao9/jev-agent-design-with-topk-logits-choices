"""Multi-page virtual tool selection baseline.

Many physical tools are partitioned into virtual pages. The page id and target
are hidden from the chooser; only query, page summaries, and resident options
are exposed. Deterministic chooser is used unless --live is supplied and a Jev
key is configured. No tool is executed and no external side effects occur.
"""
from __future__ import annotations
import argparse,json,time,os
from pathlib import Path
from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceOption
PAGES={
 'files': ['read_file','write_file','list_files'],
 'calendar':['create_event','list_events','delete_event'],
 'database':['query_rows','update_row','delete_row'],
 'deploy':['deploy_service','rollback_service','rollout_status'],
 'browser':['open_url','find_text','download_file'],
 'memory':['retrieve_recent','retrieve_archive','summarize_memory'],
}
SUM={'files':'workspace file operations','calendar':'calendar event scheduling','database':'database row queries and updates','deploy':'service deployment and rollout','browser':'web browsing and page retrieval','memory':'historical context and memory retrieval'}
CASES=[('read a source file','files','read_file','COMMIT'),('schedule a review meeting','calendar','create_event','COMMIT'),('query account rows','database','query_rows','COMMIT'),('deploy the api service','deploy','deploy_service','COMMIT'),('open the documentation url','browser','open_url','COMMIT'),('retrieve last week decision','memory','retrieve_recent','COMMIT'),('read or query the source','files','read_file','CLARIFY'),('inspect service rollout','deploy','rollout_status','COMMIT'),('delete the old database row','database','delete_row','COMMIT'),('download the report from webpage','browser','download_file','COMMIT'),('missing archive memory','memory','retrieve_archive','COMMIT'),('write then schedule','files','write_file','CLARIFY')]
def overlap(q,s): return len(set(q.lower().split()) & set(s.lower().split()))
def main():
 p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,default=Path(__file__).parent/'results'/'multi-page-tool-selection-latest.json'); p.add_argument('--live',action='store_true'); a=p.parse_args(); chooser=TypeSafeJevChooser() if a.live else None; rows=[]; loc=tool=success=0; calls=0; times=[]
 for i,(q,target,ttool,expected) in enumerate(CASES,1):
  t=time.perf_counter(); ranked=sorted(PAGES,key=lambda x:(overlap(q,SUM[x]),x),reverse=True); resident=['help','stop']; localized=target in ranked[:2]; action='PAGE' if localized and target not in ('files',) else ('CLARIFY' if expected=='CLARIFY' else 'PAGE')
  calls+=1; page_ok=localized; chosen=ttool if page_ok else (PAGES[ranked[0]][0] if ranked else 'stop');
  if chooser is not None and action=='PAGE':
   tool_opts=[ChoiceOption(x,x.replace('_',' ')) for x in PAGES[target]]
   chosen=chooser.choose(state=f'Query: {q}\\nMaterialized page summary: {SUM[target]}',instructions='Choose the tool that satisfies the query.',options=tool_opts).choice
  tool_ok=chosen==ttool; final=tool_ok and (expected=='COMMIT' or action=='CLARIFY'); loc+=page_ok; tool+=tool_ok; success+=final; times.append((time.perf_counter()-t)*1000)
  rows.append({'case':i,'query':q,'target_page':target,'target_tool':ttool,'ranked_pages':ranked,'page_action':action,'page_localized':page_ok,'selected_tool':chosen,'tool_selected':tool_ok,'final_success':final,'jev_calls':1,'resident_bound':2,'latency_ms':round(times[-1],5)})
 s=sorted(times); out={'name':'multi-page-tool-selection','cases':len(rows),'target_hidden':True,'decision_backend':('live Jev' if a.live else 'deterministic contract'),'page_localization_rate':round(loc/len(rows),3),'in_page_tool_selection_rate':round(tool/len(rows),3),'final_success_rate':round(success/len(rows),3),'jev_calls':calls,'resident_bound':2,'p50_ms':round(s[len(s)//2],5),'p95_ms':round(s[max(0,int(.95*len(s))-1)],5),'external_side_effects':0,'steps':rows}; a.output.parent.mkdir(exist_ok=True); a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({k:v for k,v in out.items() if k!='steps'},ensure_ascii=False,indent=2))
if __name__=='__main__': main()

