#!/usr/bin/env python3
"""Context-completeness scorer for the livedocs context-quality eval.

Source of truth for the per-task rubrics. Each rubric check is a must_contain_any
over accepted phrasings of one load-bearing CONTEXT element. `discriminator=True`
marks elements that grep/graph cannot recover from code (intent: gates, rules,
the right abstraction), the ones docs should uniquely supply.

Usage:
  score.py emit-rubrics <out_dir>     # write schema-valid rubric/*.yaml (dogfood)
  score.py score <plans_dir>          # score plan-*.txt files, print table
A plan file is named plan-<arm>-<task>.txt (arm in G|GG|L).
"""
import sys, re, json, pathlib

# element: (accepted_terms[], discriminator?)
TASKS = {
 "alloc_1": {
   "builder":            (["displaySessionSchedule"], False),
   "row_helper":         (["instructorScheduleTableMarkup"], False),
   "attach_hook":        (["acme_alloc_entity_view", "hook_entity_view", "entity_view"], True),
   "release_date_gate":  (["field_instructor_schedule_date", "schedule release", "release date",
                            "released", "schedule_date", "until the schedule"], True),
   "coordinator_source": (["getCoordinatorData", "coordinator"], False),
 },
 "alloc_2": {
   "seat_time_entity":   (["SeatTime"], False),
   "delta_field":        (["field_delta", "delta"], False),
   "save_path":          (["saveSeatTime", "assignSeatTime", "SessionAllocationParticipantAssignAction",
                            "AssignParticipantToSessionSlotsForm"], False),
   "available_compute":  (["getAvailableSeatTimeOptions", "SeatTimeStorage"], True),
   "priority_rule":    (["priority", "field_is_priority_shift", "30 min", "15 min",
                            "30-min", "15-min", "30/15"], True),
 },
 "avail_1": {
   "constraint_mechanism": (["AvailabilityCalendarUniqueConstraint", "validation constraint",
                             "symfony constraint", "constraint plugin", "Unique constraint"], True),
   "validator":            (["UniqueConstraintValidator", "::validate", "validator"], False),
   "lookup_method":        (["getByUserAndSessionPeriod"], False),
   "links_to_existing":    (["link", "existing"], False),
 },
 "avail_2": {
   "widget":               (["AvailabilityCalendarFieldDefaultWidget", "formElement", "FieldWidget"], False),
   "day_constant":         (["DEPARTURE_TIME_ALLOWED_DAYS"], False),
   "current_value_insight":(["[6]", "Saturday", "day 6", "currently 6", "[5]", "Friday", "day 5"], True),
   "validator_also_reads": (["AvailabilityCalendarFieldConstraintValidator", "constraint validator",
                             "also enforced", "validation"], False),
 },
 "mig_1": {
   "method":        (["prepareRow"], False),
   "source_class":  (["AcmePaymentTransaction"], False),
   "stripe_path": (["Stripe", "unserialize"], True),
   "paypal_path":     (["Paypal", "parse"], True),
   "date_convert":  (["timestamp", "DrupalDateTime", "date conversion", "to unix"], False),
 },
 "mig_2": {
   "subscriber":        (["PostMigrationSubscriber"], False),
   "post_import_event": (["POST_IMPORT", "MigrateEvents", "event subscriber", "getSubscribedEvents"], True),
   "create_method":     (["createProducts"], False),
   "per_level_pattern": (["T2", "T3", "session level", "Acme-CERT"], True),
   "attach_variations": (["variation", "variations field"], False),
 },
}

def check_hit(plan_low, terms):
    return any(t.lower() in plan_low for t in terms)

def score_plan(plan_text, task):
    low = plan_text.lower()
    rows = []
    for elem, (terms, disc) in TASKS[task].items():
        rows.append((elem, disc, check_hit(low, terms)))
    n = len(rows); hit = sum(1 for _,_,h in rows if h)
    dn = sum(1 for _,d,_ in rows if d); dhit = sum(1 for _,d,h in rows if d and h)
    return {"coverage": hit/n, "n": n, "hit": hit,
            "disc_coverage": (dhit/dn if dn else None), "dn": dn, "dhit": dhit,
            "rows": rows}

def emit_rubrics(out_dir):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    try: import yaml
    except ImportError: yaml=None
    for task, elems in TASKS.items():
        checks = [{"id": elem, "kind": "must_contain_any", "case_sensitive": False,
                   "values": terms, "metadata": {"discriminator": disc}}
                  for elem,(terms,disc) in elems.items()]
        rub = {"id": f"ctx_{task}", "version": "1.0",
               "description": f"Context-completeness for change task {task}",
               "applicable_bundles": ["code_navigation"],
               "checks": checks,
               "scoring": {"combine": "weighted_avg",
                           "weights": {e: (2.0 if d else 1.0) for e,(_,d) in elems.items()},
                           "threshold": 0.6}}
        p = out / f"ctx_{task}.yaml"
        if yaml: p.write_text("# yaml-language-server: $schema=https://git.drupalcode.org/project/ai_eval/-/raw/1.0.x/schema/rubric.schema.json\n"+yaml.safe_dump(rub, sort_keys=False))
        else: p.write_text(json.dumps(rub, indent=2))
    print(f"wrote {len(TASKS)} rubrics to {out}")

if __name__ == "__main__":
    if sys.argv[1] == "emit-rubrics":
        emit_rubrics(sys.argv[2])
    elif sys.argv[1] == "score":
        d = pathlib.Path(sys.argv[2])
        ARMS=["G","GG","L"]; agg={a:[] for a in ARMS}; daggr={a:[] for a in ARMS}
        print(f"{'task':9}", *[f"{a:>14}" for a in ARMS]); print("-"*60)
        for task in TASKS:
            cells=[]
            for a in ARMS:
                f=d/f"plan-{a}-{task}.txt"
                if not f.exists(): cells.append("    -    "); continue
                s=score_plan(f.read_text(), task)
                agg[a].append(s["coverage"]);
                if s["disc_coverage"] is not None: daggr[a].append(s["disc_coverage"])
                cells.append(f"{s['hit']}/{s['n']} ({s['dhit']}/{s['dn']}d)")
            print(f"{task:9}", *[f"{c:>14}" for c in cells])
        print("-"*60)
        for a in ARMS:
            cov=sum(agg[a])/len(agg[a]) if agg[a] else 0
            dcov=sum(daggr[a])/len(daggr[a]) if daggr[a] else 0
            print(f"ARM {a}: mean context coverage={cov:.0%}  | discriminator-only={dcov:.0%}")
        print("(cell = elements_hit/total (discriminator_hit/discriminator_total))")
