# Construcción y actualización del Vectorstore

## 1. Objetivo

Construir o reconstruir el vectorstore Chroma usado por Arus PrintAssist para recuperación documental.

El vectorstore se construye a partir de PDFs públicos o sanitizados. El flujo general es:

PDFs -> extracción de texto -> chunking -> embeddings -> Chroma persistente

El prototipo usó Chroma como vectorstore persistente y sentence-transformers/all-MiniLM-L6-v2 como modelo de embeddings

## 2. Estructura sugerida de documentos

Organizar los PDFs así:

knowledge_base_pdfs/
  DA Arus/
    DA0393-6_V1 Consultar y asignar PIN en print evolve.pdf
    DA0421-6_V1 Operación Herramienta PaperCut.pdf
    DA0422-6_V1 Operación Herramienta MFPsecure.pdf

  HP SDS/
    HP SDS Manager - System Requirements v2.6 SPANISH.pdf
    HP Smart Device Services Manager - End User Guide V1.7 - Spanish.pdf

  HP WJA/
    HP Web Jetadmin - Guía del usuario.pdf
    HP Web Jetadmin - Guía de instalación y configuración.pdf

  HP AC/
    Administrator Guide - HP Access Control.pdf
    HP Access Control - Technical Training Guide.pdf

  GAV Tracking/
    TRK40 - Arquitectura de seguridad Nube.pdf
    TRK40 - Arquitectura de seguridad On premises.pdf

## 3. Reglas antes de agregar documentos

Antes de agregar una fuente:

1. Confirmar que el documento no contiene datos sensibles.
2. Confirmar que se puede usar para soporte interno.
3. Nombrar el archivo de forma clara.
4. Ubicarlo en una carpeta de producto o proceso.
5. Evitar duplicados.
5. Revisar si requiere metadata especial en domain_registry.py.

## 4. Chunking recomendado

Configuración usada como referencia:
chunk_size = 800
chunk_overlap = 150

