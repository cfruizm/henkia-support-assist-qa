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
| KE-04 | Publicación del KE como complemento (`KNOWLEDGE_PUBLISH_MODE=complement`) cuando Chroma no tiene evidencia y el KE sí | Implementado (F3.5); activar con el secret |
| KE-05 | Adaptar el Agent Core al KE: búsqueda dentro de un documento (`rag.filters.document_uri`), documento completo (`/document?uri=`), varias consultas es/en | KE-05.1 búsqueda dentro del documento; KE-05.3 documento completo vía MCP leer_documento (`HENKIA_KE_FULL_DOCUMENT=procedural`). Pendiente: varias consultas es/en |
| KE-06 | KE como proveedor principal con Chroma de respaldo (`KNOWLEDGE_PUBLISH_MODE=primary`) | Implementado; falta campaña de validación en QA antes de dejarlo por defecto. Local sigue de respaldo para lo que KE no tiene (sitios web) |
| KE-07 | Retiro de Chroma | Requiere aprobación de Arquitectura/Seguridad/IA |

### Corpus del KE

- Bases: `Impresion` (HP SDS, GAV Tracking, HP AC, HP WJA) y `OperacionSIMP` (DA Arus vía conector SharePoint).
- Sitios web (PaperCut, HP, Epson…): sin conector en el KE. Solicitud al desarrollador del KE: <https://claude.ai/artifact/JFMg11QiJAtJLjawbmLzNW>.

### Inventario de corpus local vs KE (2026-11-26)

| Contenido | Local (Chroma) | KE | Brecha |
|---|---|---|---|
| PDFs GAV Tracking, HP AC, HP SDS, HP WJA | 67 | 67 (base Impresion) | Ninguna |
| PDFs internos DA Arus | 31 | 30 (base OperacionSIMP, conector SharePoint) | Falta DA0390 (Analizar Dashboard Control Operación SIMP) |
| Páginas web de PaperCut (manuales, KB, known issues, requisitos) | 964 | 0 como páginas web | **Brecha principal** → opción C o conector web |
| Material solo en KE | — | 31 en Impresion (certificación PaperCut, OXP, Hive, Epson Embedded) y al menos 8 en OperacionSIMP (IN0504, DA0425, DA0445, plantillas…) | KE ya supera a local en estos temas |

Método: Impresion listada con la herramienta MCP `listar_documentos`; OperacionSIMP no se puede listar (`HENKIA-RAG-4001`, fuente conectada), se verificó buscando cada título DA Arus en esa base. Los conteos de OperacionSIMP son un mínimo.

### Opción C — crawler externo + API del KE (implementada 2026-11-27)

Estado: las 963 páginas web de PaperCut están en la base Impresion (una de las 964 ya no existe, 404) con `scripts/ke_web_sync.py` (`--dry-run`, `--upload`, `--prune`, `--ingest`, `--ingest-only`; MCP `subir_documento` con una key `kb:write` + `ingest` solo para el sincronizador). Validado en QA: Find-Me, Hold/Release, sincronización de varios dominios AD, Pull Delivery de Hive y solución de problemas de Find-Me responden desde KE con la página pública de PaperCut.

Pendientes: programar la ejecución periódica (páginas nuevas, cambiadas y eliminadas con `--prune`); revisar la respuesta de requisitos de Mobility Print (usó la página de requisitos de PaperCut NG); falta DA0390 en OperacionSIMP; `leer_documento` falla de forma intermitente en Impresion (reportar al equipo de KE).

Diseño original:

Mientras el KE no tenga conector web, nuestro crawler sube las páginas al KE:

1. Recorre los sitios configurados (semillas, prefijos, profundidad), como hoy hace `scripts/build_vectorstore.py` en Colab.
2. Extrae el texto principal y arma metadatos: `reference_url`, `document_title`, `document_date`, `document_kind`, `vendor`, `product`.
3. Sube los documentos con `POST /knowledge-bases/{id}/documents:batch` (hasta 100 por llamada; el mismo nombre sobrescribe).
4. Se programa periódicamente (cron o CI); detecta páginas eliminadas y las borra con `DELETE /knowledge-bases/{id}/documents/{name}`.
5. Requiere una API key con `kb:write` e `ingest` solo sobre la base destino, distinta de la key de consulta de la app.

Al pasar después a un conector del KE, cada página debe conservar su `reference_url`.

### Pendientes detectados en QA

- Seguimiento de valores sin pedir la lista completa ("¿Y los puertos?" tras los requisitos de HP SDS) responde con los fragmentos recuperados (3 de 10 puertos): activar la lectura dentro del documento cuando el seguimiento pide valores del mismo documento.

## Fase 4 — Deuda técnica

- Respaldo entre proveedores de LLM y errores del gateway sin clasificar.
- `scripts/build_vectorstore.py` usa por defecto un modelo de embeddings distinto al de la app.
- Herramientas rotas (`tools/audit_secret_keys.py`, validadores 4C3), código muerto, `requirements.txt` sin versiones fijas.
- `response_reconciler` sobrescribe `functional_events`.
- Recarga en caliente de Streamlit Cloud: hacer Reboot tras cada push antes de validar.
