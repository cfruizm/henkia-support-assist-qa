from __future__ import annotations
from copy import deepcopy
import hashlib,re
CITE=re.compile(r"\[(R\d+)\]")
def _stable(item):
 m=item.get('metadata') or {};payload='|'.join(str(x or '') for x in (m.get('content_hash'),m.get('canonical_url'),item.get('source'),item.get('url'),item.get('page'),item.get('text')));return hashlib.sha256(payload.encode()).hexdigest()[:16]
def register_evidence(items):
 rows=[];mapping={};seen=set()
 for item in items or []:
  stable=_stable(item)
  if stable in seen:continue
  seen.add(stable);row=deepcopy(item);old=str(row.get('id') or '');new=f'R{len(rows)+1}';row.update({'id':new,'stable_id':stable,'original_id':old or None});rows.append(row);mapping[stable]=new
  if old:mapping[old]=new
 return rows,mapping
