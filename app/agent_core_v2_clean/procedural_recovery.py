from __future__ import annotations
from copy import deepcopy
import re

def should_compact_retry(provider_result):
 return bool(provider_result) and (provider_result.get('finish_reason')=='length' or not str(provider_result.get('text') or '').rstrip().endswith((']','.',':')))

def compact_documented_instruction():
 return ('REINTENTO COMPACTO: cubre el procedimiento completo desde el primer paso hasta el cierre. '
         'Usa una línea breve por etapa, conserva el orden de las páginas disponibles y cita cada etapa. '
         'No omitas las etapas finales para ampliar las iniciales. No añadas pasos no documentados.')

def _compact_text(text,limit=360):
 text=' '.join(str(text or '').split())
 # Remove repeated document headers while keeping procedural content.
 text=re.sub(r'^DA\d[^•]*?(?=(?:OBJETIVO|ALCANCE|CONTENIDO|\d+\.|•))','',text,flags=re.I)
 if len(text)<=limit:return text
 cut=text[:limit].rsplit(' ',1)[0]
 return cut+'…'

def compact_retrieval_for_retry(retrieval,max_items=8,chars_per_item=360):
 """Compact every stage instead of retaining only the first pages."""
 out=deepcopy(retrieval or {});source=list(out.get('generation_evidence') or out.get('evidence') or [])
 compact=[]
 for item in source[:max_items]:
  compact.append({'id':item.get('id'),'title':item.get('title'),'page':item.get('page'),'text':_compact_text(item.get('text'),chars_per_item),'stable_id':item.get('stable_id')})
 out['generation_evidence']=compact;out['evidence']=compact
 out['procedural_recovery_selection']={'strategy':'ordered_full_stage_compaction','source_count':len(source),'selected_count':len(compact),'selected_ids':[x.get('id') for x in compact]}
 return out
