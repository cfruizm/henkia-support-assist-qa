from __future__ import annotations
import re
_PATTERNS=(
 (re.compile(r"(?i)\bel problema no reside en ([^.,;]+), sino en ([^.;]+)"),lambda m:f"la validación realizada reduce la probabilidad de {m.group(1).strip()}, pero conviene ampliar el diagnóstico hacia {m.group(2).strip()}"),
 (re.compile(r"(?i)\besto descarta ([^.;]+)"),lambda m:f"esto hace menos probable {m.group(1).strip()}, sin descartarlo por completo"),
 (re.compile(r"(?i)\bthe problem is not in ([^.,;]+), but in ([^.;]+)"),lambda m:f"the completed validation makes {m.group(1).strip()} less likely, while the diagnosis should expand toward {m.group(2).strip()}"),
)
def soften_diagnostic_certainty(text,intent):
 value=str(text or "")
 if str(intent or "").casefold() not in {"troubleshooting","procedural"}:return value,False
 changed=False
 for rx,repl in _PATTERNS:
  value,n=rx.subn(repl,value);changed=changed or bool(n)
 return value,changed
