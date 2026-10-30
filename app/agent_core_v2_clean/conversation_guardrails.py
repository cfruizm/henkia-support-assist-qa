from __future__ import annotations
import re,unicodedata
from copy import deepcopy

def norm(v):return unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode().casefold().strip()
_DENIAL=(
 re.compile(r'\b(?:no|eso no|esto no)\s+(?:tiene|tienen)\s+(?:nada\s+)?que\s+ver\s+con\s+(.+?)(?:[.,;!?]|$)',re.I),
 re.compile(r'\b(?:no corresponde|no esta relacionado|no se relaciona|no aplica)\s+(?:con|a)?\s*(.*?)(?:[.,;!?]|$)',re.I),
 re.compile(r'\b(?:ese|esa|aquel|aquella)\s+(?:producto|herramienta|documento|tema)\s+no\s+(?:es|corresponde|aplica)(?:\s+el correcto)?(?:[.,;!?]|$)',re.I),
)
_REPLACEMENT=re.compile(r'\b(?:sino|me refiero a|realmente es|el correcto es)\s+(.+?)(?:[.,;!?]|$)',re.I)

def rejected_association(message):
 text=str(message or '');denied=[]
 for rx in _DENIAL:
  for value in rx.findall(text):
   value=' '.join(str(value or '').split())
   if value and value.casefold() not in {x.casefold() for x in denied}:denied.append(value)
 replacement=None;m=_REPLACEMENT.search(text)
 if m:replacement=' '.join(m.group(1).split())
 return {'detected':bool(denied) or bool(re.search(r'\b(?:no corresponde|no tiene nada que ver|no esta relacionado)\b',norm(text))), 'rejected_subjects':denied, 'replacement_subject':replacement}

def reconcile_association(message,understanding,state_before):
 u=dict(understanding or {});event=rejected_association(message)
 if not event['detected']:return u,event
 if event['replacement_subject']:
  subject=event['replacement_subject'];details=dict(u.get('goal_updates') or {});details['subject']=subject;u['goal_updates']=details;u['canonical_subject']=subject;u['subject_origin']='current_message';u['reference_relation']='corrected_subject';u['topic_relation']='same_topic';u['should_retrieve']=True
  return u,event
 # A rejected association without replacement is unresolved. Do not guess another product.
 details=dict(u.get('goal_updates') or {});details.pop('product',None);details.pop('subject',None);u['goal_updates']=details;u['canonical_subject']=None;u['subject_origin']='rejected_without_replacement';u['reference_relation']='association_rejected';u['needs_clarification']=True;u['clarification_target']='producto, proceso o documento correcto';u['should_retrieve']=False;u['topic_relation']='same_topic';u['current_goal']=str(u.get('current_goal') or message)
 return u,event

def scope_gate(message,understanding,state_before):
 u=dict(understanding or {});scope=str(u.get('domain_relevance') or 'uncertain');act=str(u.get('user_act') or '');relation=str(u.get('topic_relation') or '');subject_origin=str(u.get('subject_origin') or '')
 active=bool((state_before or {}).get('active_topic'))
 referential=act in {'follow_up','answer_to_question','request_elaboration','attempt_result'} and relation=='same_topic' and subject_origin in {'conversation_memory','previous_subject','inherited','current_subject'}
 independent=act in {'new_request','independent_question','topic_change'} or relation in {'new_topic','independent'}
 # Never convert an explicitly out-of-scope independent request into in-scope because a printing topic was active.
 if scope=='out_of_scope' and independent:
  u['should_retrieve']=False;u['needs_clarification']=False;u['clarification_target']=None;u['case_updates']=[];u['requested_workflow']='none';u['goal_complete']=True
  return u,{'blocked':True,'closed':True,'reason':'explicit_independent_out_of_scope','original_scope':scope,'active_context_ignored':active}
 # Only a genuine referential follow-up may inherit the in-scope domain.
 if scope=='out_of_scope' and referential:
  u['domain_relevance']='in_scope';return u,{'blocked':False,'reason':'referential_followup_inherits_scope','original_scope':scope,'active_context_ignored':False}
 if scope=='uncertain' and independent:
  u['should_retrieve']=False;u['needs_clarification']=True;u['clarification_target']='relación con el servicio de impresión'
  return u,{'blocked':False,'reason':'independent_scope_uncertain_clarify','original_scope':scope,'active_context_ignored':active}
 return u,{'blocked':False,'reason':'scope_preserved','original_scope':scope,'active_context_ignored':False}
