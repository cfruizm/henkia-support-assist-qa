from __future__ import annotations
def _mb(v):
 try:return float(v or 0)/(1024*1024)
 except Exception:return 0.0
def _kb(v):
 try:return float(v or 0)/1024
 except Exception:return 0.0
def render_resource_monitor(st,store,telemetry=None):
 telemetry=telemetry or store.get("telemetry") or {};history=list(store.get("resource_observability") or []);latest=history[-1] if history else dict(store.get("runtime_memory_diagnostic") or {})
 rss=_mb(latest.get("process_rss_bytes"));status="Crítico para el prototipo" if rss>=2200 else "Elevado" if rss>=1500 else "Estable" if rss else "Sin muestras"
 if rss>=2200:st.error(f"Recursos: {status}. RSS actual aproximado: {rss:,.0f} MB")
 elif rss>=1500:st.warning(f"Recursos: {status}. RSS actual aproximado: {rss:,.0f} MB")
 elif rss:st.success(f"Recursos: {status}. RSS actual aproximado: {rss:,.0f} MB")
 else:st.info("Recursos: aún no hay una muestra de RSS.")
 a,b=st.columns(2);a.metric("RSS del proceso",f"{rss:,.0f} MB" if rss else "Sin dato");b.metric("Store de sesión",f"{_mb(latest.get('session_store_bytes') or latest.get('estimated_store_bytes')):,.2f} MB")
 a,b=st.columns(2);a.metric("Retrieval del último turno",f"{_kb(latest.get('retrieval_payload_bytes')):,.1f} KB");b.metric("Caches de sesión",f"{_kb(latest.get('cache_total_bytes')):,.1f} KB");st.metric("Tokens acumulados",f"{int(telemetry.get('total_tokens') or 0):,}")
 if history:
  st.line_chart({"RSS del proceso (MB)":[round(_mb(x.get('process_rss_bytes')),2) for x in history]},height=190)
  st.line_chart({"Store (KB)":[round(_kb(x.get('session_store_bytes')),2) for x in history],"Retrieval (KB)":[round(_kb(x.get('retrieval_payload_bytes')),2) for x in history],"Caches (KB)":[round(_kb(x.get('cache_total_bytes')),2) for x in history]},height=190)
 st.caption("Los estados son umbrales operativos del prototipo. El monitor no genera llamadas LLM ni retrieval.")
