from typing import Mapping
import hashlib,json
def _m(v):return dict(v) if isinstance(v,Mapping) else {}
def _t(v):return " ".join(str(v or "").split())
def apply_canonical_query(q,frame):
 f=_m(frame);s=_m(f.get("subject"));o=_m(f.get("operation"));t=_m(f.get("topic"));c=_m(f.get("case"));sv=_t(s.get("value"));op=_t(o.get("text"));fields=dict(getattr(q,"fields",{}) or {})
 if sv:fields.update({"subject":sv,"subject_type":_t(s.get("type")),"subject_id":_t(s.get("canonical_id")) or sv})
 if _t(o.get("intent")) not in {"","unknown"}:fields["intent"]=_t(o.get("intent"))
 fields.update({"operation":op,"topic_id":_t(t.get("topic_id")),"topic_relation":_t(t.get("relation")),"canonical_query":True})
 for k in ("symptoms","observations","affected_scope"):
  if c.get(k):fields[k]=c[k]
 parts=[]
 for v in (sv,op):
  if v and v.casefold() not in [x.casefold() for x in parts]:parts.append(v)
 q.text=". ".join(parts) or _t(q.text);q.fields=fields;q.fingerprint=hashlib.sha256(json.dumps({"text":q.text,"fields":fields},sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()[:20];return q
