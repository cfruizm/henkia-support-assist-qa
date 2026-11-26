# Backlog y plan por fases — Henkia Support Assist QA

Estado al 2026-11-26. Cada fase se valida en QA (Reboot de la app, conversación nueva, JSON de diagnóstico) antes de cerrarse.

## Fase 1 — Confiabilidad (cerrada)

- Turnos interrumpidos: prompt pendiente + store transaccional (`process_pending`).
- Contrato de comprensión: recuperación de campos anidados.
- Bug de `memory.py` en `attempt_result`.

## Fase 2 — Calidad del Agent Core (cerrada)

- Puente de idioma es→en en la autoridad de evidencia (`operation_bridge.py`).
- Contrato del LLM: esquema estricto, alias y contrato explícito en el mensaje.
- Sin avisos falsos de "cobertura parcial"; retorno a tema con listas completas.
- Deduplicación de candidatos por documento + página + contenido.

Limitaciones conocidas:

- El troubleshooting de un tema activo puede seguir usando el documento anterior (`primary_document_progressive_rerank`) en lugar del artículo de troubleshooting.
- Procedimientos muy largos pueden cortarse en 1.100 tokens de salida (el aviso de corte es real).

## Fase 3 — Henkia KE como RAG principal (en curso)

| Paso | Objetivo | Estado |
| --- | --- | --- |
| KE-03.x | Sombra KE aislada y comparación local vs KE | Hecho |
| KE-03.4 | Búsqueda en varias bases del KE (`HENKIA_KE_KB_IDS`) | Hecho en código; pendiente validar con la nueva API key |
| KE-04 | Publicación del KE como complemento (`KNOWLEDGE_PUBLISH_MODE=complement`) cuando Chroma no tiene evidencia y el KE sí | Pendiente |
| KE-05 | Adaptar el Agent Core al KE: búsqueda dentro de un documento (`rag.filters.document_uri`), documento completo (`/document?uri=`), varias consultas es/en | Pendiente |
| KE-06 | KE como proveedor principal con Chroma de respaldo | Requiere corpus completo y campaña etiquetada |
| KE-07 | Retiro de Chroma | Requiere aprobación de Arquitectura/Seguridad/IA |

### Corpus del KE

- Bases: `Impresion` (HP SDS, GAV Tracking, HP AC, HP WJA) y `OperacionSIMP` (DA Arus vía conector SharePoint).
- Sitios web (PaperCut, HP, Epson…): sin conector en el KE. Solicitud al desarrollador del KE: <https://claude.ai/artifact/JFMg11QiJAtJLjawbmLzNW>.

### Opción C — crawler externo + API del KE (a explorar)

Mientras el KE no tenga conector web, nuestro crawler sube las páginas al KE:

1. Recorre los sitios configurados (semillas, prefijos, profundidad), como hoy hace `scripts/build_vectorstore.py` en Colab.
2. Extrae el texto principal y arma metadatos: `reference_url`, `document_title`, `document_date`, `document_kind`, `vendor`, `product`.
3. Sube los documentos con `POST /knowledge-bases/{id}/documents:batch` (hasta 100 por llamada; el mismo nombre sobrescribe).
4. Se programa periódicamente (cron o CI); detecta páginas eliminadas y las borra con `DELETE /knowledge-bases/{id}/documents/{name}`.
5. Requiere una API key con `kb:write` e `ingest` solo sobre la base destino, distinta de la key de consulta de la app.

Al pasar después a un conector del KE, cada página debe conservar su `reference_url`.

## Fase 4 — Deuda técnica

- Respaldo entre proveedores de LLM y errores del gateway sin clasificar.
- `scripts/build_vectorstore.py` usa por defecto un modelo de embeddings distinto al de la app.
- Herramientas rotas (`tools/audit_secret_keys.py`, validadores 4C3), código muerto, `requirements.txt` sin versiones fijas.
- `response_reconciler` sobrescribe `functional_events`.
- Recarga en caliente de Streamlit Cloud: hacer Reboot tras cada push antes de validar.
