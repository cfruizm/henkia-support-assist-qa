# Arus PrintAssist - Guía de Operación del Prototipo

## 1. Objetivo

Arus PrintAssist es un chatbot de soporte N1 para servicios de impresión. Responde consultas documentales, troubleshooting básico, procedimientos operativos y guía la recopilación de información para escalar incidentes.

## 2. Arquitectura actual

- Frontend: Streamlit.
- Backend: Python en `app/backend.py`.
- Vectorstore: Chroma persistente.
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`.
- LLM remoto: configurable por Secrets.
- Modelo baseline actual: `Qwen/Qwen3.6-35B-A3B`.
- Provider actual: `deepinfra`.
- Observabilidad: tokens, costo, latencia, fuentes, intención y soporte documental.

## 3. Secrets requeridos

HF_TOKEN = "..."
HF_MODEL = "Qwen/Qwen3.6-35B-A3B"
HF_PROVIDER = "deepinfra"
HF_DISABLE_THINKING = true
HF_MAX_TOKENS = 600
DEBUG_UI = false

## 4. Qué consume créditos

Consume créditos:

Consultas realizadas en chat normal que llaman al LLM.

No consume créditos:

Ver estado backend.
Debug retrieval.
Buscar metadata/vectorstore.
Ver resumen de observabilidad.
Flujo determinístico de escalamiento, si no llama al LLM.

### 5. Uso del panel técnico

Activar con:

DEBUG_UI = true

Permite:

Ver estado backend.
Ejecutar debug retrieval.
Buscar metadata/vectorstore.
Ver última llamada LLM.
Ver último turno observado.
Ver resumen de observabilidad.
6. Observabilidad

El archivo turn_observability.jsonl registra:

intención detectada,
soporte documental,
fuentes,
modelo,
proveedor,
tokens,
costo estimado,
latencia,
errores,
fallback.

Esto servirá para comparación de modelos y sizing local/self-hosted.

## 7. Errores comunes
402 / créditos insuficientes: Reducir pruebas LLM y usar debug retrieval.

429 / model busy / engine overloaded : Reintentar más tarde o reducir tokens.

504 Gateway Timeout: Provider saturado o respuesta demasiado lenta.

Error Streamlit / Starlette / GZipResponder:  Revisar versiones en requirements.txt, especialmente streamlit, starlette y protobuf.

### 8. Flujo de escalamiento

El agente recopila:

software,
versión,
acciones realizadas,
error o síntoma,
datos de impresora,
cliente/ubicación,
evidencia,
impacto.

Al finalizar, genera un resumen y permite exportar el caso desde la barra lateral.

## 9. Baseline actual

Baseline v0.1:

* Retrieval entity-aware funcional.
* Filtro de fuentes tangenciales.
* Observabilidad mínima activa.
* Escalamiento sin bucle de resumen.
* Modelo remoto configurable.
