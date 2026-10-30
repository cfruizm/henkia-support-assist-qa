from __future__ import annotations
from copy import deepcopy

def _sentences(text):
    import re
    return [x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+',str(text or '')) if x.strip()]

def recover_natural_response(result):
    answer=result.get('answer') or {}
    finish=str(answer.get('finish_reason') or '').casefold()
    if answer.get('mode')!='natural_support' or finish not in {'length','max_tokens'}:
        return result
    raw=((result.get('provider_trace') or {}).get('response') or {}).get('text') or answer.get('text') or ''
    complete=[]
    for sentence in _sentences(raw):
        if sentence.endswith(('.', '!', '?')) or sentence.endswith(']'):
            complete.append(sentence)
    if complete:
        text='\n'.join(complete[:6])
        if not text.endswith(('.', '!', '?')): text+='.'
        answer.update(text=text,mode='natural_compact_recovery',finish_reason='recovered',knowledge_used=True)
        useful=True
    else:
        answer.update(text='No repetiré lo ya validado. El siguiente paso debe comprobar un componente todavía no descartado.',mode='natural_safe_recovery',finish_reason='recovered',knowledge_used=False)
        useful=False
    result['answer']=answer
    result['natural_response_recovery']={'triggered':True,'reason':'provider_output_truncated','retry_used':False,'published_partial':False,'useful_content_preserved':useful}
    result.setdefault('functional_events',[]).append({'type':'truncated_natural_response_recovered','severity':'medium'})
    return result
