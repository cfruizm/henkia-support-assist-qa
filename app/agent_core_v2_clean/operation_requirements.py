from __future__ import annotations
import re, unicodedata

def _norm(v): return unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode().casefold()
def derive_missing_details(operation,subject,scope):
    text=_norm(f'{operation} {subject}')
    missing=[]
    queue=bool(re.search(r'cola|queue|compartid|shared|servidor de impresion|print server',text))
    firmware=bool(re.search(r'firmware|microcodigo',text))
    driver=bool(re.search(r'controlador|driver',text))
    if queue:
        if not scope.operating_system: missing.append('operating_system')
        if not scope.architecture: missing.append('architecture')
    elif firmware:
        if not (scope.manufacturer or scope.product): missing.append('manufacturer')
        if not scope.model: missing.append('model')
    elif driver:
        if not scope.operating_system: missing.append('operating_system')
        if not scope.model: missing.append('model')
    else:
        if not scope.operating_system: missing.append('operating_system')
        if not (scope.manufacturer or scope.model or scope.product): missing.append('manufacturer_or_model')
    return missing[:2]
