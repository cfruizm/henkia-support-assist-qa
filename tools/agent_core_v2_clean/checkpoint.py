from pathlib import Path
import ast,json
root=Path(__file__).resolve().parents[2]/'app'/'agent_core_v2_clean';files=sorted(root.glob('*.py'));checks=[]
for p in files:
    try:ast.parse(p.read_text(encoding='utf-8'));checks.append((p.name,True,'ok'))
    except Exception as e:checks.append((p.name,False,str(e)))
pass_compile=all(x[1] for x in checks)
print(json.dumps({'gate':'agent_core_v2_clean_minimal_checkpoint','status':'passed' if pass_compile else 'failed','file_count':len(files),'checks':[{'file':a,'passed':b,'detail':c} for a,b,c in checks],'production_changed':False},ensure_ascii=False,indent=2))
raise SystemExit(0 if pass_compile else 1)
