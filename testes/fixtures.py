from pathlib import Path
import json
from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({'pyarrow':'pyarrow>=14','pandas':'pandas>=2.0'})
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

def criar_caso(pasta):
    pasta=Path(pasta);deck=pasta/'deck';(deck/'system').mkdir(parents=True,exist_ok=True);(deck/'scenarios').mkdir(exist_ok=True)
    nomes={0:'CAMARGOS',7:'SOBRADINHO',15:'TUCURUI'}
    (deck/'system/hydros.json').write_text(json.dumps({'hydros':[{'id':u,'name':n} for u,n in nomes.items()]}),encoding='utf-8')
    periodos=pd.period_range('2026-08','2028-12',freq='M')
    etapas=[{'id':500+i*3,'start_date':str(p.start_time.date()),'end_date':str((p+1).start_time.date())} for i,p in enumerate(periodos)]
    (deck/'stages.json').write_text(json.dumps({'stages':etapas}),encoding='utf-8')
    hist=[]
    for u in nomes:
        for p in pd.period_range('2000-01','2010-12',freq='M'):
            hist.append(dict(hydro_id=u,start_date=p.start_time.date(),end_date=(p+1).start_time.date(),value_m3s=float(0 if u==15 else 30+u+3*p.month+((p.year-2000)*7)%23)))
    pd.DataFrame(hist).to_parquet(deck/'scenarios/inflow_history.parquet',index=False)
    arquivos={}
    for modelo in ('novo','newave'):
        rows=[];rng=np.random.default_rng(2026 if modelo=='novo' else 2027)
        for u in nomes:
            for i,p in enumerate(periodos):
                for c in [2,8,17,24,50,80,104]:
                    rows.append(dict(scenario_id=c,stage_id=etapas[i]['id'] if modelo=='novo' else 800+i*5,
                                     node_id=c+100 if modelo=='novo' else None,hydro_id=u if modelo=='novo' else u+100,
                                     incremental_inflow_m3s=float(0 if u==15 else 35+u+3*p.month+rng.normal(0,14))))
        dados=pd.DataFrame(rows).sample(frac=1,random_state=2)
        caminho=pasta/(modelo+'.parquet')
        if modelo=='novo':dados.to_parquet(caminho,index=False)
        else:
            schema=pa.schema([(c,pa.int64() if c!='incremental_inflow_m3s' else pa.float64()) for c in rows[0]])
            meta={b'source_model':b'NEWAVE',b'node_id_semantics':b'unavailable',
                  b'hydro_mapping':json.dumps([{'hydro_id':u+100,'nome_usina_cadastro':n} for u,n in nomes.items()]).encode(),
                  b'stage_mapping':json.dumps([dict(stage_id=800+i*5,start_date=e['start_date'],end_date=e['end_date']) for i,e in enumerate(etapas)]).encode(),
                  b'parpvaz_history_periods':b'[[2000,2009]]'}
            pq.write_table(pa.Table.from_pandas(dados,schema=schema,preserve_index=False).replace_schema_metadata(meta),caminho)
        arquivos[modelo]=str(caminho)
    return str(deck),arquivos
