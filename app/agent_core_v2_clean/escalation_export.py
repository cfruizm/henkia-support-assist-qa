from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from .escalation_contract import FIELDS
SCHEMA='agent_core_v2_clean_escalation_v1'
def build_export(state,conversation_id):
 return {'schema_version':SCHEMA,'status':'confirmed' if state.confirmed else state.status,'conversation_id':conversation_id,'created_at':datetime.now(timezone.utc).isoformat(),'incident':deepcopy(state.fields),'unknown_fields':list(state.unknown_fields),'corrections':deepcopy(state.corrections),'sources_consulted':deepcopy(state.sources_consulted),'escalation_reason':deepcopy(state.escalation_reason),'lifecycle':{'started_turn':state.started_turn,'completed_turn':state.completed_turn,'completion_reason':state.completion_reason}}
def build_text(state):
 lines=['Resumen del incidente:']
 for spec in FIELDS:
  row=state.fields.get(spec.key) or {};value=row.get('value')
  if value not in (None,''):lines.append(f'- {spec.label}: {value}')
 if state.sources_consulted:
  lines.append('- Fuentes consultadas: '+ '; '.join(str(x.get('title') or x.get('source') or '') for x in state.sources_consulted if x.get('title') or x.get('source')))
 if state.escalation_reason.get('value'):lines.append('- Motivo de escalamiento: '+str(state.escalation_reason['value']))
 if state.unknown_fields:lines.append('- Información no disponible: '+', '.join(state.unknown_fields))
 return '\n'.join(lines)
