from __future__ import annotations

def retrieve_same_document(query:str,source:str,k:int=8)->dict:
 """Read-only, zero-LLM retrieval constrained to one already-selected document."""
 try:
  from app.vectorstore_runtime import get_vectorstore
  vectorstore=get_vectorstore()
  retriever=vectorstore.as_retriever(search_kwargs={"k":max(2,min(12,int(k))),"filter":{"source":source}})
  docs=retriever.invoke(query)
 except Exception as exc:
  return {"ok":False,"adapter":"app.vectorstore_runtime.get_vectorstore","evidence":[],"errors":[f"{type(exc).__name__}: {exc}"]}
 evidence=[]
 for doc in docs or []:
  meta=dict(getattr(doc,"metadata",{}) or {});text=str(getattr(doc,"page_content","") or "").strip()
  if text:evidence.append({"text":text,"title":meta.get("title") or meta.get("source_name") or "","source":meta.get("source") or source,"url":meta.get("canonical_url") or meta.get("source") or source,"score":None,"metadata":meta})
 return {"ok":True,"adapter":"app.vectorstore_runtime.get_vectorstore.same_document","evidence":evidence,"errors":[]}
