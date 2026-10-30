from __future__ import annotations
from pathlib import Path
import streamlit as st
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from app.config import CONFIG
from app.agent_core_v2_clean.resource_observability import checkpoint, mark_resource_state

@st.cache_resource
def get_embedding_model():
    checkpoint("before_embedding_model_load", embedding_model_name=CONFIG.get("embedding_model_name"))
    model=HuggingFaceEmbeddings(model_name=CONFIG["embedding_model_name"])
    mark_resource_state(embedding_model_loaded=True, embedding_model_name=CONFIG.get("embedding_model_name"))
    checkpoint("after_embedding_model_load")
    return model

def get_vectorstore_signature(vectorstore_dir: str) -> str:
    base=Path(vectorstore_dir)
    if not base.exists():return "missing"
    parts=[]
    for path in sorted(base.rglob("*")):
        if path.is_file():parts.append(f"{path.relative_to(base)}:{path.stat().st_size}")
    return "|".join(parts)

@st.cache_resource
def get_vectorstore_cached(signature: str):
    checkpoint("before_vectorstore_load", signature_length=len(str(signature or "")))
    store=Chroma(
        collection_name=CONFIG.get("collection_name","langchain"),
        persist_directory=CONFIG["vectorstore_dir"],
        embedding_function=get_embedding_model(),
    )
    mark_resource_state(vectorstore_loaded=True, chroma_collection_name=CONFIG.get("collection_name","langchain"))
    checkpoint("after_vectorstore_load")
    return store

def get_vectorstore():
    mark_resource_state(retrieval_runtime_initialized=True)
    checkpoint("before_get_vectorstore")
    vectorstore_dir=CONFIG["vectorstore_dir"]
    if not Path(vectorstore_dir).exists():
        raise FileNotFoundError(f"Vector store directory not found: {vectorstore_dir}")
    return get_vectorstore_cached(get_vectorstore_signature(vectorstore_dir))
