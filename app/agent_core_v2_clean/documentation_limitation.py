def classify(r,provider=None):
 r=r or {};res=r.get('document_resolution') or {};v=r.get('evidence_verdict') or {};ev=r.get('diagnostic_evidence') or r.get('evidence') or [];provider=provider or {}
 if provider and (not provider.get('ok',True) or str(provider.get('finish_reason') or '').casefold() in {'length','max_tokens'}):kind='provider_degraded'
 elif res.get('enabled') and res.get('status')=='not_found':kind='document_not_found'
 elif res.get('enabled') and res.get('status')=='ambiguous':kind='document_ambiguous'
 elif str(v.get('status') or '').casefold()=='partial' and (v.get('selected_evidence') or ev):kind='evidence_partial_applicable'
 elif res.get('status')=='exact_match' and ev and not v.get('accepted'):kind='document_found_operational_evidence_insufficient'
 elif ev and not v.get('accepted'):kind='evidence_found_not_authorized'
 elif not ev:kind='no_evidence_retrieved'
 else:kind='none'
 return {'schema_version':1,'kind':kind,'document_found':res.get('status')=='exact_match','document_title':((res.get('matches') or [{}])[0].get('title') if res.get('status')=='exact_match' else None),'diagnostic_evidence_count':len(ev),'verdict_status':v.get('status'),'verdict_reason':v.get('reason')}
def user_message(c):
 c=c or {};k=c.get('kind');t=c.get('document_title') or 'el documento solicitado'
 return {'document_not_found':'No encontré el documento solicitado en el catálogo documental disponible.','document_ambiguous':'Encontré más de un documento compatible y no es seguro seleccionar uno automáticamente.','document_found_operational_evidence_insufficient':f'Encontré {t}, pero los fragmentos disponibles no contienen la operación solicitada con suficiente detalle para presentarla como documentada.','evidence_partial_applicable':'La evidencia recuperada cubre una parte útil de la solicitud. Presenta primero esa parte como documentada y limita cualquier complemento a lo que no quedó cubierto.','evidence_found_not_authorized':'Encontré fragmentos relacionados, pero no ofrecen soporte suficiente para presentar la respuesta como documentada.','provider_degraded':'La evidencia estaba disponible, pero no fue posible generar la respuesta completa en este momento.','no_evidence_retrieved':'No recuperé fragmentos documentales útiles para esta solicitud.'}.get(k,'')
