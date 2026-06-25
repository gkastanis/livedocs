#!/usr/bin/env python3
"""Codex (gpt-5.5) as an INDEPENDENT judge of change-plan context-completeness.

Plan authors are Claude; judge is a different model family -> no self-preference.
For each (arm,task) plan (extracted from subagent transcripts, newest wins) it
asks Codex to score, against the rubric criteria, which load-bearing context
elements the plan genuinely surfaces. Output constrained by verdict.schema.json.
"""
import json, glob, os, re, sys, subprocess, pathlib
SC = str(pathlib.Path(__file__).resolve().parent)
sys.path.insert(0, SC)
from score import TASKS  # rubric source of truth: element -> (terms, discriminator)

TX = os.environ.get("LIVEDOCS_EVAL_TRANSCRIPTS", "./transcripts")
VERDICT_SCHEMA = f"{SC}/verdict.schema.json"
OUT = pathlib.Path(f"{SC}/verdicts"); OUT.mkdir(exist_ok=True)

TASK_INPUT = {
 "alloc_1": "Add a 'room capacity' column to the instructor session-schedule table shown on the instructor profile.",
 "alloc_2": "Add an audit-log entry whenever a participant's recorded position (delta) in an seat session slot changes.",
 "avail_1": "Change the duplicate-availability message so it also shows the session period name.",
 "avail_2": "Change the 'earliest departure the day before' rule so it applies to Fridays instead of its current day.",
 "mig_1":   "Add normalization for a third payment gateway alongside Stripe and Paypal during the D7->D11 commerce-payment migration.",
 "mig_2":   "Add a third session-level parent product (T1) to the post-migration product creation.",
}
TASKPHRASE={"room capacity":"alloc_1","audit-log entry whenever a participant":"alloc_2",
 "duplicate-availability message":"avail_1","earliest departure the day before":"avail_2",
 "third payment gateway":"mig_1","third session-level parent product":"mig_2"}
ARMPATH=[("runG/acme","G"),("runGG/acme","GG"),("runL/acme","L")]

def classify(t):
    for p,a in ARMPATH:
        if "eval/"+p in t: return a
    return None
def plan_text(txt):
    out=[]
    for line in txt.splitlines():
        try:o=json.loads(line)
        except:continue
        m=o.get("message") or {}
        if m.get("role")!="assistant": continue
        c=m.get("content")
        if isinstance(c,str): out.append(c)
        elif isinstance(c,list):
            for b in c:
                if isinstance(b,dict) and b.get("type")=="text": out.append(b.get("text",""))
    return "\n".join(out)

cand={}
for f in glob.glob(f"{TX}/agent-*.jsonl"):
    txt=open(f,errors="ignore").read()
    if "CHANGE PLAN" not in txt: continue
    arm=classify(txt); task=next((v for k,v in TASKPHRASE.items() if k in txt),None)
    if not arm or not task: continue
    mt=os.path.getmtime(f); key=(arm,task)
    if key not in cand or mt>cand[key][1]: cand[key]=(f,mt,txt)

def criteria_lines(task):
    L=[]
    for elem,(terms,disc) in TASKS[task].items():
        L.append(f"- {elem}{' [KEY]' if disc else ''}: surfaced if the plan shows genuine awareness "
                 f"(e.g. names/uses: {', '.join(terms[:3])})")
    return "\n".join(L)

def judge(arm, task, plan):
    prompt = (
      "You are an INDEPENDENT code-review evaluator. Judge ONLY the change-plan text below. "
      "Do NOT use tools, do NOT explore any repo, do NOT act.\n\n"
      f"A developer was asked to: {TASK_INPUT[task]}\n\n"
      "They produced this CHANGE PLAN:\n<plan>\n" + plan[:14000] + "\n</plan>\n\n"
      "Score whether the plan surfaces each required CONTEXT element. Mark 'met' true ONLY if the plan "
      "demonstrates real awareness (names the symbol/file or correctly describes the constraint/relationship), "
      "not a vague or generic mention. Be strict and skeptical.\n\n"
      f"Context elements:\n{criteria_lines(task)}\n\n"
      "Output ONLY JSON: coverage = fraction of elements met (0..1); criteria = per-element {id,met,evidence}."
    )
    of = OUT/f"verdict-{arm}-{task}.json"
    r = subprocess.run(["codex","exec","-s","read-only","--skip-git-repo-check",
                        "--output-schema",VERDICT_SCHEMA,"-o",str(of),prompt],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    try: return json.loads(of.read_text())
    except Exception as e: return {"coverage":None,"criteria":[],"err":str(e),"rc":r.returncode}

ARMS=["G","GG","L"]; res={}
for task in TASKS:
    for arm in ARMS:
        c=cand.get((arm,task))
        if not c: res[(arm,task)]={"coverage":None}; print(f"MISSING {arm} {task}",flush=True); continue
        v=judge(arm,task,plan_text(c[2]))
        # discriminator subset coverage from per-criterion verdicts
        discids={e for e,(_,d) in TASKS[task].items() if d}
        dm=[x for x in v.get("criteria",[]) if x.get("id") in discids]
        v["disc_coverage"]=(sum(1 for x in dm if x.get("met"))/len(dm)) if dm else None
        res[(arm,task)]=v
        print(f"judged {arm} {task}: coverage={v.get('coverage')}",flush=True)

print("\n==== CODEX JUDGE: context-completeness ====")
print(f"{'task':9} | {'G':>6} {'GG':>6} {'L':>6}   (coverage)")
for task in TASKS:
    print(f"{task:9} | "+" ".join(f"{(res[(a,task)].get('coverage') if res[(a,task)].get('coverage') is not None else -1):>6.2f}" for a in ARMS))
print("-"*40)
for a in ARMS:
    cs=[res[(a,t)]['coverage'] for t in TASKS if res[(a,t)].get('coverage') is not None]
    ds=[res[(a,t)]['disc_coverage'] for t in TASKS if res[(a,t)].get('disc_coverage') is not None]
    print(f"ARM {a}: codex coverage={sum(cs)/len(cs):.0%}  discriminator={sum(ds)/len(ds):.0%}  (n={len(cs)})")
json.dump({f"{a}|{t}":res[(a,t)] for a in ARMS for t in TASKS}, open(f"{SC}/codex_verdicts.json","w"), indent=2)
print("saved -> codex_verdicts.json")
