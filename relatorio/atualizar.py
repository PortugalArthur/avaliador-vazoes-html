"""Aplica os recursos atuais a um relatório sem alterar os blocos de cálculo."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

from aplicacao.executar import VERSAO, agora
from aplicacao.fontes import assinatura
from relatorio.blocos import ArquivoHTML

PREFIXO='<script type="application/octet-stream" id="bloco-'

def ler_manifesto(caminho):
    with open(caminho,'rb') as f:
        f.seek(0,2);n=f.tell();f.seek(max(0,n-12*1024*1024))
        fim=f.read().decode('utf-8')
    achado=re.search(r'<script id="manifesto" type="application/json">(.*?)</script>',fim,re.S)
    if not achado:raise ValueError('Manifesto do avaliador HTML não encontrado.')
    return json.loads(achado[1])

def atualizar(caminho,saida=None):
    origem=Path(caminho).resolve();antes=assinatura(origem);m=ler_manifesto(origem)
    destino=Path(saida).resolve() if saida else origem.with_name(origem.stem.rsplit('_',2)[0]+f'_{agora():%Y%m%d_%H%M%S}.html')
    if destino.exists() or destino==origem:raise ValueError('Escolha uma saída nova; o relatório anterior será preservado.')
    if destino.suffix.lower()!='.html':raise ValueError('A saída deve ser um arquivo .html.')
    arquivo=ArquivoHTML(destino);hashes={}
    try:
        with origem.open(encoding='utf-8') as f:
            for linha in f:
                if not linha.startswith(PREFIXO):continue
                chave=linha[len(PREFIXO):].split('"',1)[0]
                if chave in hashes:raise ValueError(f'Bloco duplicado: {chave}.')
                b=base64.b64decode(linha.split('>',1)[1].rsplit('</script>',1)[0],validate=True)
                if len(b)!=m['blocos'][chave]['bytes']:raise ValueError(f'Tamanho incorreto do bloco {chave}.')
                hashes[chave]=hashlib.sha256(b).hexdigest()
                arquivo.f.write(linha)
        if set(hashes)!=set(m['blocos']):raise ValueError('O relatório possui blocos ausentes.')
        if assinatura(origem)!=antes:raise ValueError('O relatório de origem mudou durante a atualização.')
        arquivo.indice=m['blocos']
        m.setdefault('dados_gerados_em',m['gerado_em'])
        m['gerado_em']=agora().isoformat();m['versao']=VERSAO
        arquivo.concluir(m)
        return destino,{'origem':str(origem),'arquivo':str(destino),'bytes':destino.stat().st_size,
                        'blocos_preservados':len(hashes),'sha256_blocos':hashes,'versao':VERSAO,
                        'atualizado_em':m['gerado_em']}
    except BaseException:
        arquivo.cancelar();raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('html');p.add_argument('--saida');p.add_argument('--auditoria')
    a=p.parse_args();c,r=atualizar(a.html,a.saida)
    if a.auditoria:Path(a.auditoria).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(c)
