"""Auditoria integral dos blocos e atualização de recursos sem refazer contas.

Utilitário de desenvolvimento: a atualização copia cada bloco estatístico
literalmente e só substitui template, CSS, bibliotecas e código de consulta.
"""
import argparse
import base64
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re

from aplicacao.executar import agora
from relatorio.blocos import ArquivoHTML
import numpy as np

PREFIXO='<script type="application/octet-stream" id="bloco-'

def manifesto(caminho):
    with open(caminho,'rb') as f:
        f.seek(0,2);n=f.tell();f.seek(max(0,n-12*1024*1024));fim=f.read().decode('utf-8')
    return json.loads(re.search(r'<script id="manifesto" type="application/json">(.*?)</script>',fim,re.S)[1])

def auditar(caminho,atualizar=False):
    caminho=Path(caminho).resolve();m=manifesto(caminho)
    novo=caminho.with_name(caminho.name.rsplit('_',2)[0]+'_'+agora().strftime('%Y%m%d_%H%M%S')+'.html') if atualizar else None
    if novo and novo.exists():raise ValueError('Saída já existe.')
    arquivo=ArquivoHTML(novo) if novo else None
    validos={};guardados={};shapes={};total_eventos={};n=0
    try:
        with caminho.open(encoding='utf-8') as f:
            for linha in f:
                if not linha.startswith(PREFIXO):continue
                chave=linha[len(PREFIXO):].split('"',1)[0]
                assert chave not in validos, f'ID de bloco duplicado: {chave}'
                payload=linha.split('>',1)[1].rsplit('</script>',1)[0]
                bruto=base64.b64decode(payload,validate=True)
                assert len(bruto)==m['blocos'][chave]['bytes'],chave
                descompactado=gzip.decompress(bruto)
                assert len(descompactado)==m['blocos'][chave]['original'],chave
                obj=json.loads(descompactado)
                validos[chave]=hashlib.sha256(bruto).hexdigest();n+=1
                if arquivo and not ('sequencias' in obj and re.match(r'^(novo|newave)_u_\d+$',chave)):arquivo.f.write(linha)
                if re.match(r'^(novo|newave)_u_\d+$',chave):
                    modelo,_,uid=chave.split('_');ref=next(v for v in m['modelos'] if v['key']==modelo)['uhe'][uid]
                    seq=obj.get('sequencias')
                    if seq is not None:ref['linhas_sequencias']={k:len(v['r']) for k,v in seq.items()}
                    formas=[obj[k]['forma'] for k in ['flows','presentes']]
                    assert formas[0]==formas[1]
                    assert formas[0]==[len(obj['scenario_ids']),len(m['estagios'])]
                    assert len(base64.b64decode(obj['flows']['b64']))==np.prod(formas[0])*8
                    shapes[chave]=formas[0]
                    total_eventos[modelo]=total_eventos.get(modelo,0)+ref['linhas_sequencias']['eventos']
                    if uid=='0':guardados[chave]=obj.copy()
                    if arquivo and seq is not None:
                        # Mesmos valores, separados para consultar resumos sem
                        # descompactar vazões e eventos que não serão exibidos.
                        antes=obj.copy();obj.pop('sequencias')
                        ref['blocos_sequencias']={k:arquivo.bloco(chave+'_seq_'+k,v) for k,v in seq.items()}
                        assert {**obj,'sequencias':seq}==antes
                        arquivo.bloco(chave,obj)
                        continue
                elif '_seq_' in chave:
                    mo,uid,campo=re.match(r'^(novo|newave)_u_(\d+)_seq_(.+)$',chave).groups()
                    ref=next(v for v in m['modelos'] if v['key']==mo)['uhe'][uid]
                    assert len(obj['r'])==ref['linhas_sequencias'][campo],chave
                    if uid=='0':guardados[chave]=obj
                elif '_t_' in chave or re.search(r'_p(50|90)$',chave):guardados[chave]=obj
                if n%100==0:print(f'{n} blocos íntegros',flush=True)
        assert set(validos)==set(m['blocos'])
        if arquivo:
            arquivo.indice={**m['blocos'],**arquivo.indice};m['gerado_em']=agora().isoformat()
            arquivo.concluir(m)
        return novo or caminho,m,guardados,{'blocos':n,'hashes_blocos':validos,'matrizes':shapes,'eventos':total_eventos,
                                          'arquivo':str(novo or caminho),'bytes':(novo or caminho).stat().st_size}
    except BaseException:
        if arquivo:arquivo.cancelar()
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('html');p.add_argument('--atualizar-interface',action='store_true');p.add_argument('--saida-auditoria',required=True)
    a=p.parse_args();path,m,d,r=auditar(a.html,a.atualizar_interface)
    Path(a.saida_auditoria).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(path)
