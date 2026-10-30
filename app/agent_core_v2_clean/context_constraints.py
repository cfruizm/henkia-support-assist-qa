from typing import Any

def _c(v:Any)->str:return " ".join(str(v or "").split()).strip()
def build_confirmed_case_context(memory):
 case=memory.support_case; records=getattr(memory,"fact_records",{}) or {}
 return {"observations":list(dict.fromkeys(_c(x) for x in case.observations if _c(x))),
 "attempts":[{"action":_c(x.get("action")),"result":_c(x.get("result"))} for x in case.attempts if _c(x.get("action"))],
 "affected_scope":_c(case.affected_scope) or None,
 "confirmed_facts":[{"key":_c(x.get("key")),"value":_c(x.get("value"))} for x in records.values() if x.get("status")=="confirmed" and _c(x.get("value"))]}
def confirmed_case_prompt(memory):
 c=build_confirmed_case_context(memory); lines=["CONFIRMED CASE CONTEXT:"]
 lines += [f"- Confirmed observation: {x}" for x in c["observations"]]
 for x in c["attempts"]: lines += [f"- Already performed: {x['action']}",f"  Confirmed result: {x['result']}"]
 lines += [f"- Confirmed fact: {x['value']}" for x in c["confirmed_facts"]]
 lines += ["MANDATORY: do not contradict confirmed context; do not ask again for a confirmed fact; do not repeat an action unless the variation and diagnostic value are explicit; choose one reversible next step."]
 return "\n".join(lines)
