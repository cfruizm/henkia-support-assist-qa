from __future__ import annotations
import hashlib,json,re,unicodedata
from .models import AgentResponse
from .source_footer import compact_sources, strip_generated_source_footer
from .diagnostic_language import soften_diagnostic_certainty
from .guidance_integrity import build_guidance_integrity_contract, integrity_diagnostic
PROMPT_VERSION="procedural_v21_transparent_partial_publication"
SYSTEM="""Eres un colega de soporte empresarial de impresión. Responde solo con la evidencia documental suministrada. Redacta una orientación operativa práctica, completa y proporcional al alcance de la pregunta en el idioma del usuario. Prioriza primero las etapas, decisiones, acciones, validaciones y resultados operativos; limita propósito, alcance y contexto a un párrafo breve. Cuando response_contract.mode sea full_document_procedure, sintetiza el flujo completo disponible en la evidencia, desde las condiciones de inicio hasta el resultado o cierre. Conserva el orden documental y cubre todas las etapas, ramas, actores, entradas, enlaces o valores literales, salidas, validaciones, excepciones y límites que estén explícitamente documentados. No dediques casi toda la respuesta a las primeras páginas dejando las etapas finales en una frase. Si una categoría no aparece en la evidencia, omítela sin inventar ni afirmar globalmente que el documento no la contiene. Cuando response_contract.mode sea focused_followup, responde solo el punto solicitado y su contexto mínimo. Si el turno es una continuación y el usuario aporta un nuevo hecho o resultado, empieza directamente por la implicación de ese dato y la siguiente validación útil. No vuelvas a definir el producto, resumir su propósito ni repetir contexto ya establecido. Si el usuario pregunta por una decisión, opción, paso o dato específico dentro de un procedimiento ya tratado, responde directamente ese punto y no repitas el procedimiento completo. No afirmes que una validación fue ejecutada o verificada salvo que figure en user_confirmed_attempts; formula las demás como acciones pendientes. assistant_delivered_guidance contiene recomendaciones previas y nunca demuestra ejecución. Antes de publicar una acción, evalúa semánticamente impacto y reversibilidad. Toda acción con riesgo de pérdida de configuración o datos, interrupción, impacto amplio, cambios de seguridad/acceso o rollback difícil debe presentarse solo bajo condiciones explícitas, con impacto, prerrequisitos de respaldo/recuperación, autorización o ventana cuando apliquen, y alternativa de escalamiento si no puede ejecutarse con seguridad. No descartes una capa ni confirmes una causa por una única validación; expresa únicamente que aumenta o reduce su probabilidad. Usa una o más secciones numeradas en Markdown con el formato **1. Título**. La evidencia puede describir pasos, requisitos, compatibilidad, comprobaciones, alternativas o límites. No inventes pasos ni completes vacíos con conocimiento interno. Conserva las relaciones lógicas de la evidencia: no conviertas alternativas en requisitos conjuntos, no sustituyas el método solicitado por otro parecido y no presentes una modalidad parcial como equivalente al objetivo. Si la evidencia describe opciones pero no el procedimiento exacto, indícalo. Cada párrafo o viñeta factual debe terminar con citas [R#]. Finaliza con **Validaciones finales** citada. Antes de afirmar que una dimensión solicitada no está documentada, revisa todos los fragmentos suministrados, incluidos fragmentos de la misma página. Si algún fragmento contiene la dimensión solicitada y valores asociados, enumera esos valores y no publiques una afirmación de ausencia. No menciones el laboratorio."""
BOILERPLATE=("aviso legal","legal notice","información restringida","restricted information","control de registros","records control","control de cambios","change control","tiempo de retención","retention period","disposición final","final disposition")
OPERATIONAL_MARKERS=("validar","verificar","comprobar","confirmar","requisito","requiere","compatible","compatibilidad","admite","soporta","configurar","seleccionar","habilitar","instalar","conectar","sincronizar","importar","asignar","probar","actualizar","guardar","abrir","validate","verify","check","confirm","requirement","requires","required","compatible","compatibility","supports","supported","configure","configured","select","enable","enabled","install","connect","synchronize","sync","import","assign","test","update","authenticate","authentication","available","depends")
def _clean(text):return " ".join(str(text or "").split())
def _norm(text):return unicodedata.normalize("NFKD",str(text or "")).encode("ascii","ignore").decode().casefold()
def _usable(e):
 text=_clean(e.get("text"));low=_norm(text);signals=sum(1 for x in OPERATIONAL_MARKERS if x in low);noise=sum(1 for x in BOILERPLATE if x in low)
 return len(text)>=80 and signals>=1 and signals>noise
def evidence_pack(retrieval,max_items=8,max_chars=9000,preserve_document_context=False):
 items=[];used=0;seen=set()
 for e in retrieval.get("evidence") or []:
  # Full-document procedure requests need headings, scope, branch descriptions
  # and closing stages as well as imperative chunks. Focused troubleshooting
  # keeps the stricter operational filter.
  if not _usable(e) and not (preserve_document_context and len(_clean(e.get("text")))>=80):continue
  text=_clean(e.get("text"))[:2100];sig=hashlib.sha256(text.casefold().encode()).hexdigest()
  if sig in seen:continue
  seen.add(sig);item={"id":e.get("id"),"title":e.get("title"),"page":e.get("page"),"source":e.get("url") or e.get("source"),"text":text};size=len(json.dumps(item,ensure_ascii=False))
  if items and used+size>max_chars:break
  items.append(item);used+=size
  if len(items)>=max_items:break
 return items
def _section_numbers(text):
 return [int(x) for x in re.findall(r"(?m)^\s*(?:#{1,6}\s*)?\*\*(\d+)\s*[.)]\s+[^*\n]+\*\*\s*$",str(text or ""))]
def _is_web(item):
 metadata=item.get("metadata") or {}
 value=str(item.get("url") or metadata.get("canonical_url") or metadata.get("source_url") or item.get("source") or "")
 return value.startswith(("http://","https://"))

def _limit_web_document_chunks(evidence,maximum=4):
 if not evidence:return []
 identities={str(x.get("url") or x.get("source") or (x.get("metadata") or {}).get("canonical_url") or x.get("title") or "") for x in evidence}
 return evidence[:maximum] if len(identities)==1 and all(_is_web(x) for x in evidence) else evidence

def _terminal_complete(text):
 value=str(text or "").rstrip()
 if not value:return False
 if re.search(r"\[R\d+\](?:[\]\"\')}]*)$",value):return True
 closing=value.rstrip("]}\'\"")
 return closing.endswith((".","!","?",":",";"))

def _safe_cited_partial(text,ids,finish_reason,semantic_truncation=False):
 reason=str(finish_reason or "").casefold()
 if reason not in {"length","max_tokens"} and not semantic_truncation:return None,[]
 cited=set(re.findall(r"\[(R\d+)\]",str(text or "")));sections=_section_numbers(text)
 if not text.strip() or not sections or sections!=list(range(sections[0],sections[0]+len(sections))) or not cited or not cited.issubset(set(ids)):return None,[]
 matches=list(re.finditer(r"\[(R\d+)\]",text))
 if not matches:return None,[]
 partial=text[:matches[-1].end()].rstrip()
 partial_cited=set(re.findall(r"\[(R\d+)\]",partial))
 return partial,sorted(partial_cited)

def _remove_contradicted_absence_blocks(text,question,evidence):
 blocks=[block.strip() for block in re.split(r"\n\s*\n",str(text or "")) if block.strip()]
 kept=[];removed=[]
 for block in blocks:
  units=[unit.strip() for unit in re.split(r"(?<=[.!?])\s+",block) if unit.strip()]
  safe_units=[]
  for unit in units:
   if contradicted_absence_claim(unit,question,evidence):removed.append(unit)
   else:safe_units.append(unit)
  candidate=" ".join(safe_units).strip()
  # Do not publish an orphan heading after removing its contradictory body.
  if candidate and not re.fullmatch(r"(?:#{1,6}\s*)?\*\*[^*]+\*\*",candidate):kept.append(candidate)
 safe="\n\n".join(kept).strip()
 cited=sorted(set(re.findall(r"\[(R\d+)\]",safe)))
 return safe,cited,removed

def validate(text,ids,finish_reason=None,minimum_sections=1):
 cited=set(re.findall(r"\[(R\d+)\]",str(text or "")));sections=_section_numbers(text);ordered=not sections or sections==list(range(sections[0],sections[0]+len(sections)));provider_complete=str(finish_reason or "").casefold() in {"","none","stop","completed"};terminal_complete=_terminal_complete(text);complete=provider_complete and terminal_complete;valid=bool(str(text or "").strip()) and bool(sections) and ordered and bool(cited) and cited.issubset(set(ids)) and complete
 return valid,sorted(cited),{"sections":sections,"ordered":ordered,"finish_complete":provider_complete,"terminal_complete":terminal_complete,"semantic_truncation":provider_complete and not terminal_complete,"cited_ids":sorted(cited)}
def readable_sources(retrieval,cited):
 by={str(e.get("id")):e for e in retrieval.get("evidence") or []};return [f"[{rid}] {by[rid].get('title') or 'Fuente sin título'}, página {by[rid].get('page') or 'N/D'}" for rid in cited if rid in by]
def fingerprint(message,understanding,retrieval,model=""):
 exp=retrieval.get("procedural_expansion") or {};payload={"q":" ".join(str(message).split()).casefold(),"goal":understanding.get("current_goal"),"evidence":[(e.get("id"),e.get("url") or e.get("source"),e.get("page")) for e in retrieval.get("evidence") or []],"pages":exp.get("pages"),"model":model,"prompt":PROMPT_VERSION};return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]

def _response_contract(understanding,retrieval,evidence):
 fields=(retrieval.get("query") or {}).get("fields") or {}
 relation=str(fields.get("topic_relation") or understanding.get("topic_relation") or "")
 act=str(fields.get("user_act") or understanding.get("user_act") or "")
 initial=relation=="new_topic" and act in {"new_request","request_elaboration"}
 mode="full_document_procedure" if initial else "focused_followup"
 pages=[]
 for item in evidence:
  page=str(item.get("page") or "").strip()
  if page and page not in pages:pages.append(page)
 return {"mode":mode,"preserve_document_order":True,"evidence_items":len(evidence),"evidence_pages":pages,"coverage_expectation":"all_distinct_documented_stages" if initial else "requested_dimension_only","omit_unsupported_categories":True}

def _procedural_coverage(text,evidence,focused_followup):
 cited=set(re.findall(r"\[(R\d+)\]",str(text or "")))
 by_id={str(item.get("id")):item for item in evidence}
 evidence_ids=set(by_id)
 cited_pages={str((by_id.get(cid) or {}).get("page") or "") for cid in cited if cid in by_id and (by_id.get(cid) or {}).get("page") not in (None,"")}
 evidence_pages={str(item.get("page")) for item in evidence if item.get("page") not in (None,"")}
 id_ratio=len(cited & evidence_ids)/max(1,len(evidence_ids))
 page_ratio=len(cited_pages)/max(1,len(evidence_pages))
 expected=focused_followup or len(evidence_ids)<=2 or id_ratio>=0.50 or page_ratio>=0.60
 return {"checked":True,"focused_followup":bool(focused_followup),"evidence_ids":sorted(evidence_ids),"cited_ids":sorted(cited & evidence_ids),"evidence_pages":sorted(evidence_pages),"cited_pages":sorted(cited_pages),"citation_coverage":round(id_ratio,4),"page_coverage":round(page_ratio,4),"coverage_sufficient":bool(expected)}

def contradicted_absence_claim(text, question, evidence):
 q=_norm(question);a=_norm(text)
 absence=any(x in a for x in ("no especifica","no contiene","no detalla","no proporciona","no documenta","not specify","not contain"))
 if not absence:return False
 terms={x for x in re.findall(r"[a-z0-9]+",q) if len(x)>4 and x not in {"cuales","especificamente","requisitos","requirements"}}
 body=_norm(" ".join(str(x.get("text") or "") for x in evidence))
 return bool(terms and terms.intersection(set(re.findall(r"[a-z0-9]+",body))))

class ProceduralAnswerComposer:
 def __init__(self,gateway,max_tokens=900):self.gateway=gateway;self.max_tokens=max(620,min(1100,int(max_tokens)));self.last_provider_result={};self.validation={}
 def compose(self,message,understanding,retrieval):
  exp=retrieval.get("procedural_expansion") or {}
  fields=(retrieval.get("query") or {}).get("fields") or {}
  relation=str(fields.get("topic_relation") or understanding.get("topic_relation") or "")
  act=str(fields.get("user_act") or understanding.get("user_act") or "")
  full_document_request=relation=="new_topic" and act in {"new_request","request_elaboration"}
  packed_evidence=evidence_pack(retrieval,preserve_document_context=full_document_request)
  evidence=_limit_web_document_chunks(packed_evidence)
  if not (exp.get("ok") and exp.get("same_document_only") and exp.get("ordered") and evidence):return AgentResponse("La evidencia operacional todavía no es suficiente o consistente para redactar una orientación segura.","procedural_evidence_guard",False)
  from app.llm_gateway.models import LLMRequest
  integrity_contract=build_guidance_integrity_contract(retrieval)
  response_contract=_response_contract(understanding,retrieval,evidence)
  payload={"question":message,"goal":understanding.get("current_goal"),"document":exp.get("seed_document"),"pages":exp.get("pages"),"evidence":evidence,"response_contract":response_contract,"guidance_integrity_contract":integrity_contract,"user_confirmed_attempts":integrity_contract["user_confirmed_attempts"],"assistant_delivered_guidance":integrity_contract["assistant_delivered_guidance"]}
  r=self.gateway.complete(LLMRequest([{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(payload,ensure_ascii=False,separators=(",",":"))}],"agent_core_v2_clean_procedural_answer",self.max_tokens,0.,None));self.last_provider_result=r.to_dict()
  if not r.ok:return AgentResponse("Encontré evidencia operacional, pero no pude redactar la respuesta en este turno.","procedural_provider_degraded",False)
  text=str(r.text or "").strip()
  text,certainty_softened=soften_diagnostic_certainty(text,understanding.get("intent"))
  fields=(retrieval.get("query") or {}).get("fields") or {}
  details=fields.get("details") or {}
  relation=str(fields.get("topic_relation") or understanding.get("topic_relation") or "")
  act=str(fields.get("user_act") or understanding.get("user_act") or "")
  message_text=str(fields.get("current_message") or message or "").casefold()
  broad_request=bool(re.search(r"\b(todos?|todas?|completo|completa|completos|completas|entero|entera|principio a fin|paso a paso|full|complete|all steps|entire)\b",message_text))
  focused_followup=relation in {"same_topic","same_topic_refinement"} and act in {"follow_up","request_elaboration","answer_to_question"} and not broad_request and (relation=="same_topic_refinement" or bool(details.get("detail")) or understanding.get("intent") in {"requirements","verification","compatibility"})
  ids=[str(x["id"]) for x in evidence]
  ok,cited,self.validation=validate(text,ids,r.finish_reason,1)
  partial_text,partial_cited=_safe_cited_partial(text,ids,r.finish_reason,self.validation.get("semantic_truncation",False))
  safe_partial=bool(not ok and partial_text)
  if safe_partial:text=partial_text;cited=partial_cited
  self.validation["safe_partial_published"]=safe_partial
  self.validation["partial_reason"]="generation_truncated" if safe_partial else None
  self.validation["web_chunk_limit_applied"]=bool(len(packed_evidence)>len(evidence))
  self.validation["packed_evidence_count"]=len(packed_evidence)
  self.validation["generation_evidence_count"]=len(evidence)
  self.validation["focused_followup"]=focused_followup
  self.validation["minimum_sections"]=1
  self.validation["broad_request"]=broad_request
  self.validation["response_contract"]=response_contract
  self.validation["procedural_completeness"]=_procedural_coverage(text,evidence,focused_followup)
  self.validation["diagnostic_certainty_softened"]=certainty_softened
  self.validation["guidance_integrity"]=integrity_diagnostic(integrity_contract)
  contradiction=bool(self.validation.get("terminal_complete") and contradicted_absence_claim(text,message,evidence))
  self.validation["contradicted_absence_claim"]=contradiction
  coverage_partial=False
  if contradiction:
   safe_text,safe_cited,removed=_remove_contradicted_absence_blocks(text,message,evidence)
   self.validation["contradicted_blocks_removed"]=len(removed)
   self.validation["transparent_partial_publication"]=bool(safe_text and safe_cited)
   if safe_text and safe_cited:
    text=safe_text;cited=safe_cited;coverage_partial=True
   else:return AgentResponse("La síntesis generada contradijo la evidencia recuperada y no será publicada. Regenera la consulta para obtener una respuesta documentada consistente.","procedural_evidence_contradiction_guard",False,r.provider,r.model,r.usage,r.finish_reason)
  if not ok and not safe_partial and not coverage_partial:return AgentResponse("La estructura o las citas no superaron la validación. No mostraré instrucciones sin respaldo.","procedural_citation_guard",False,r.provider,r.model,r.usage,r.finish_reason)
  text=strip_generated_source_footer(text)
  if safe_partial:text+="\n\n> **Respuesta parcial:** la generación terminó antes de completar toda la respuesta. Se muestra únicamente el contenido completo y citado obtenido antes del corte."
  elif coverage_partial:text+="\n\n> **Cobertura documental parcial:** se retiraron afirmaciones de ausencia que no pudieron validarse frente a la evidencia recuperada. El contenido visible conserva únicamente afirmaciones completas y citadas."
  footer=compact_sources(evidence,cited)
  if footer:text+="\n\n"+footer
  partial=bool(safe_partial or coverage_partial)
  self.validation["transparent_partial_publication"]=partial
  self.validation["partial_reason"]="generation_truncated" if safe_partial else "unverified_absence_removed" if coverage_partial else None
  return AgentResponse(text,"procedural_documented_answer_partial" if partial else "procedural_documented_answer",True,r.provider,r.model,r.usage,"safe_partial" if partial else r.finish_reason)
