"""Provider-neutral evidence contracts for QA comparison."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any
@dataclass
class EvidenceItem:
    evidence_id:str|None=None; source_name:str|None=None; content:str|None=None
    score:float|None=None; vector_score:float|None=None; rerank_score:float|None=None
    chunk_id:str|None=None; ordinal:int|str|None=None; document_kind:str|None=None
    document_date:str|None=None; page:str|None=None; section:str|None=None
    reference_url:str|None=None; file_id:str|None=None; document_uri:str|None=None
    content_truncated:bool=False
    def to_dict(self)->dict[str,Any]:return asdict(self)
@dataclass
class SearchResult:
    provider:str; query:str; latency_ms:float|None=None; knowledge_base_id:str|None=None
    mode:str|None=None; http_status:int|None=None; results:list[EvidenceItem]=field(default_factory=list)
    has_more:bool|None=None; next_page:str|None=None; error:dict[str,Any]|None=None; published:bool=False
    request_diagnostic:dict[str,Any]|None=None
    def to_dict(self)->dict[str,Any]:
        data=asdict(self);data["results"]=[x.to_dict() for x in self.results];return data
