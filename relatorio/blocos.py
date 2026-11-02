"""Blocos gzip incorporados: publicação atômica, precisão e carregamento parcial."""
import base64
from datetime import date,datetime
import gzip
import json
import os
from pathlib import Path
import tempfile

from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({'plotly':'plotly>=5.18'})
import numpy as np
import pandas as pd
from plotly.offline import get_plotlyjs

RAIZ=Path(__file__).resolve().parents[1]

def limpar(v):
    if v is None or v is pd.NA or v is pd.NaT: return None
    if isinstance(v,(np.bool_,bool)): return bool(v)
    if isinstance(v,(np.integer,int)): return int(v)
    if isinstance(v,(np.floating,float)): return float(v) if np.isfinite(v) else None
    if isinstance(v,(date,datetime,pd.Period,pd.Timestamp)): return str(v)
    if isinstance(v,dict): return {str(k):limpar(x) for k,x in v.items()}
    if isinstance(v,(list,tuple,np.ndarray)): return [limpar(x) for x in v]
    return v

def tabela(df):
    return {'c':list(df.columns),'r':[[limpar(v) for v in r] for r in df.itertuples(index=False,name=None)]}

def vetor(a):
    a=np.asarray(a,dtype='<f8',order='C')
    return {'tipo':'f8','forma':list(a.shape),'b64':base64.b64encode(a.tobytes()).decode('ascii')}

def json_seguro(obj):
    return json.dumps(limpar(obj),ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028').replace('\u2029','\\u2029')

class ArquivoHTML:
    def __init__(self,destino):
        self.destino=Path(destino).resolve(); self.destino.parent.mkdir(parents=True,exist_ok=True)
        self.f=tempfile.NamedTemporaryFile('w',encoding='utf-8',newline='\n',suffix='.tmp',dir=self.destino.parent,delete=False)
        self.tmp=Path(self.f.name); self.indice={}
        css=(RAIZ/'recursos/estilos.css').read_text(encoding='utf-8')
        html=(RAIZ/'recursos/relatorio.html').read_text(encoding='utf-8')
        self.f.write(html.replace('/*__CSS__*/',css))
    def bloco(self,chave,obj):
        bruto=json_seguro(obj).encode('utf-8')
        zipado=gzip.compress(bruto,compresslevel=3,mtime=0)
        self.indice[chave]={'bytes':len(zipado),'original':len(bruto)}
        self.f.write(f'<script type="application/octet-stream" id="bloco-{chave}">')
        self.f.write(base64.b64encode(zipado).decode('ascii')); self.f.write('</script>\n')
        return chave
    def concluir(self,manifesto):
        manifesto['blocos']=self.indice
        self.f.write('<script id="manifesto" type="application/json">'+json_seguro(manifesto)+'</script>\n')
        for nome in ['LICENCA_PLOTLY.txt','LICENCA_FFLATE.txt']:
            aviso=(RAIZ/'recursos'/nome).read_text(encoding='utf-8').replace('--','—')
            self.f.write('<!-- '+nome+'\n'+aviso+'\n-->\n')
        self.f.write('<script>'+get_plotlyjs().replace('</script','<\\/script')+'</script>\n')
        for nome in ['fflate.js','interacao.js']:
            self.f.write('<script>\n'+(RAIZ/'recursos'/nome).read_text(encoding='utf-8').replace('</script','<\\/script')+'\n</script>\n')
        self.f.write('</body></html>');self.f.close()
        os.replace(self.tmp,self.destino)
        return self.destino
    def cancelar(self):
        if not self.f.closed:self.f.close()
        self.tmp.unlink(missing_ok=True)
