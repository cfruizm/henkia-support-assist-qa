from __future__ import annotations
import re,unicodedata,time
RX=re.compile(r'\b[A-Za-z]{2,}\d{3,}(?:[-_][A-Za-z0-9]+)*\b');CACHE={'at':0.0,'entries':[],'error':None}
def norm(v):return ' '.join(re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode().casefold()))
def identifiers(*values):
 out=[]
 for value in values:
  for x in RX.findall(str(value or '')):
   n=norm(x)
   if n and n not in out:out.append(n)
 return out
def catalog(force=False):
 now=time.time()
 if CACHE['entries'] and not force and now-CACHE['at']<900:return CACHE
 try:
  from app.vectorstore_runtime import get_vectorstore
  vs=get_vectorstore();col=getattr(vs,'_collection',None) or getattr(vs,'collection',None);raw=col.get(include=['metadatas']);unique={}
  for m in raw.get('metadatas') or []:
   m=dict(m or {});src=str(m.get('canonical_url') or m.get('source') or m.get('source_name') or '')
   if not src:continue
   title=str(m.get('title') or m.get('source_name') or src.rsplit('/',1)[-1]);unique.setdefault(src,{'source':src,'title':title,'normalized':norm(' '.join((title,str(m.get('source_name') or ''),src))),'metadata':m})
  CACHE.update(at=now,entries=list(unique.values()),error=None)
 except Exception as e:CACHE.update(at=now,entries=[],error=f'{type(e).__name__}: {e}')
 return CACHE
def resolve(*values):
 ids=identifiers(*values);c=catalog();matches=[x for x in c['entries'] if ids and any(i in x['normalized'] for i in ids)];status='exact_match' if len(matches)==1 else 'ambiguous' if len(matches)>1 else 'not_found'
 return {'enabled':bool(ids),'identifiers':ids,'status':status,'matches':matches,'catalog_size':len(c['entries']),'error':c['error'],'strategy':'metadata_catalog_exact_identity_v1'}
def retrieve(resolution,query,k=24):
 if resolution.get('status')!='exact_match':return []
 try:
  from app.integration.document_expansion_adapter import retrieve_same_document
  return (retrieve_same_document(query,resolution['matches'][0]['source'],k) or {}).get('evidence') or []
 except Exception:return []

def retrieve_all_chunks(source):
 """Return every stored chunk for one resolved source using metadata equality.

 The operation is deterministic and source-scoped. It does not use similarity,
 product vocabularies, request phrases, or a model call.
 """
 source=str(source or "").strip()
 diagnostic={"attempted":bool(source),"ok":False,"source":source,"strategy":"metadata_exact_source_scan_v1","matched_fields":[],"raw_count":0,"errors":[]}
 if not source:return [],diagnostic
 try:
  from app.vectorstore_runtime import get_vectorstore
  vs=get_vectorstore();collection=getattr(vs,"_collection",None) or getattr(vs,"collection",None)
  if collection is None:raise RuntimeError("vectorstore_collection_unavailable")
  merged={}
  for field in ("canonical_url","source","source_name"):
   try:raw=collection.get(where={field:source},include=["documents","metadatas"])
   except Exception as exc:diagnostic["errors"].append(f"{field}:{type(exc).__name__}:{exc}");continue
   ids=list(raw.get("ids") or []);documents=list(raw.get("documents") or []);metadatas=list(raw.get("metadatas") or [])
   found=0
   for index,item_id in enumerate(ids):
    metadata=dict(metadatas[index] or {}) if index<len(metadatas) else {};text=str(documents[index] or "") if index<len(documents) else ""
    identity=str(metadata.get("canonical_url") or metadata.get("source") or metadata.get("source_name") or "")
    if identity!=source:continue
    page=str(metadata.get("page_label") or metadata.get("page") or "");chunk=str(metadata.get("chunk_index") or metadata.get("chunk") or metadata.get("start_index") or index)
    key=(page,chunk,str(item_id));merged[key]={"id":str(item_id),"title":str(metadata.get("title") or metadata.get("source_name") or source.rsplit("/",1)[-1]),"source":source,"url":str(metadata.get("source_url") or metadata.get("canonical_url") or source),"page":page,"text":text,"metadata":metadata};found+=1
   if found:diagnostic["matched_fields"].append(field)
  def order(row):
   metadata=row.get("metadata") or {};raw_page=metadata.get("page_label") or metadata.get("page") or row.get("page") or "";raw_chunk=metadata.get("chunk_index") or metadata.get("chunk") or metadata.get("start_index") or 0
   try:page=(0,int(str(raw_page).strip()))
   except Exception:page=(1,str(raw_page))
   try:chunk=(0,int(str(raw_chunk).strip()))
   except Exception:chunk=(1,str(raw_chunk))
   return page,chunk,str(row.get("id") or "")
  rows=sorted(merged.values(),key=order);diagnostic["raw_count"]=len(rows);diagnostic["ok"]=bool(rows)
  return rows,diagnostic
 except Exception as exc:
  diagnostic["errors"].append(f"{type(exc).__name__}:{exc}");return [],diagnostic

