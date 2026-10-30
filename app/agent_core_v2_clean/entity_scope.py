from __future__ import annotations
from dataclasses import dataclass,asdict
import re
ALIASES={"manufacturer":{"manufacturer","brand","vendor","fabricante","marca"},"product":{"product","solution","producto","solucion"},"model":{"model","device_model","printer_model","modelo"},"operating_system":{"operating_system","os","sistema_operativo"},"architecture":{"architecture","arch","arquitectura"}}
_OS=re.compile(r"\b(windows(?:\s+server)?\s*\d+(?:\.\d+)?|macos(?:\s+[\w.]+)?|ubuntu(?:\s+[\w.]+)?|linux)\b",re.I)
_ARCH=re.compile(r"\b(32|64)\s*(?:bits?|bit)\b",re.I)
_MODEL=re.compile(r"\b(?=[A-Z0-9-]{4,}\b)(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]+\b",re.I)
_GENERIC={"impresora","printer","modelo","model","equipo","device"}
@dataclass(frozen=True)
class CanonicalScope:
 manufacturer:str|None=None;product:str|None=None;model:str|None=None;operating_system:str|None=None;architecture:str|None=None
 def to_dict(self):return asdict(self)
 def explicit_fields(self):return [k for k,v in self.to_dict().items() if v]
def _clean(v):return " ".join(str(v or '').split()).strip() or None
def _split_model(value):
 value=_clean(value)
 if not value:return None,None
 match=_MODEL.search(value)
 if not match:return None,None
 model=match.group(0);prefix=value[:match.start()].strip().split();manufacturer=prefix[-1] if prefix and prefix[-1].casefold() not in _GENERIC else None
 return manufacturer,model
def normalize_scope(details=None):
 raw={str(k).casefold():_clean(v) for k,v in (details or {}).items() if _clean(v)};values={}
 for canonical,aliases in ALIASES.items():values[canonical]=next((raw[a] for a in aliases if a in raw),None)
 # A combined device_model such as "HP E52645" is decomposed canonically.
 derived_manufacturer,derived_model=_split_model(values.get('model'))
 if derived_model:values['model']=derived_model
 if derived_manufacturer and not values['manufacturer']:values['manufacturer']=derived_manufacturer
 platform=raw.get('platform') or raw.get('plataforma')
 if platform:
  os_match=_OS.search(platform);arch=_ARCH.search(platform)
  if os_match:
   values['operating_system']=values['operating_system'] or os_match.group(0);values['architecture']=values['architecture'] or (f"{arch.group(1)} bits" if arch else None)
  else:values['product']=values['product'] or platform
 subject=raw.get('subject') or ''
 os_match=_OS.search(subject);arch=_ARCH.search(subject)
 if os_match:values['operating_system']=values['operating_system'] or os_match.group(0)
 if arch:values['architecture']=values['architecture'] or f"{arch.group(1)} bits"
 subject_manufacturer,subject_model=_split_model(subject)
 if subject_model:values['model']=values['model'] or subject_model
 if subject_manufacturer:values['manufacturer']=values['manufacturer'] or subject_manufacturer
 if values['operating_system']:
  os_match=_OS.search(values['operating_system']);arch=_ARCH.search(values['operating_system'])
  if os_match:values['operating_system']=os_match.group(0)
  if arch:values['architecture']=values['architecture'] or f"{arch.group(1)} bits"
 return CanonicalScope(**values)
