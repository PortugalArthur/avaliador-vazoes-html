"""Entradas, correspondências por nome/data e referências históricas locais."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import hashlib
import json
import re

from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({'duckdb':'duckdb>=0.10','pandas':'pandas>=2.0','pyarrow':'pyarrow>=14'})
import duckdb
import pandas as pd
import pyarrow.parquet as pq

from dados.validacao_dados_cobre import (localizar_fontes_deck, validar_hydros_json,
    validar_stages_json, validar_parquet_consolidado, validar_historico)
from dados.metadados_vazoes import normalizar_nome_usina

ROTULOS = {'novo':'Novo modelo', 'newave':'NEWAVE'}
CORES = {'novo':'#09B6CB', 'newave':'#C56A1A'}

@dataclass
class Fonte:
    chave: str
    caminho: str
    resumo: dict
    nomes: dict
    calendario: dict
    ids_deck: dict
    inicio_h: str
    fim_h: str
    origem_periodo: str

def assinatura(caminho):
    p=Path(caminho).resolve(); s=p.stat()
    return {'caminho':str(p),'bytes':s.st_size,'modificado_ns':s.st_mtime_ns}

def sha256(caminho):
    h=hashlib.sha256()
    with open(caminho,'rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()

def periodo_proposto(caminho, limites, chave):
    a,b=(pd.Period(v,freq='M') for v in limites)
    if chave=='newave':
        meta=pq.read_schema(caminho).metadata or {}
        try:
            periodos=json.loads(meta.get(b'parpvaz_history_periods',b'[]'))
            if len(periodos)==1 and len(periodos[0])==2:
                x,y=periodos[0]
                a=max(a,pd.Period(f'{int(x)}-01')); b=min(b,pd.Period(f'{int(y)}-12'))
                if b<a: raise ValueError('Período PARPVAZ fora do histórico disponível.')
                return str(a),str(b),'Metadados PARPVAZ do Parquet NEWAVE'
        except (TypeError, json.JSONDecodeError):
            pass
        return '', '', 'Não identificado: informe o período histórico do ajuste NEWAVE'
    return str(a),str(b),'Histórico disponível no deck; conferir com o período do ajuste'

def inspecionar(deck, novo=None, newave=None, periodos=None, progresso=lambda s:None):
    caminhos=localizar_fontes_deck(deck)
    nomes_deck=validar_hydros_json(caminhos['hydros'])
    calendario_deck=validar_stages_json(caminhos['stages'])
    historico=validar_historico(caminhos['historico'])
    limites=(str(pd.Period(historico['inicio'],freq='M')),str(pd.Period(historico['fim'],freq='M')))
    por_nome={}
    for u,nome in nomes_deck.items():
        n=normalizar_nome_usina(nome)
        if n in por_nome: raise ValueError(f'Nome de UHE ambíguo no deck: {nome}.')
        por_nome[n]=u
    fontes=[]
    for chave,caminho in [('novo',novo),('newave',newave)]:
        if not caminho: continue
        progresso(f'Conferindo Parquet e correspondências — {ROTULOS[chave]}…')
        resumo=validar_parquet_consolidado(caminho)
        if (resumo['modelo_origem']=='NEWAVE') != (chave=='newave'):
            raise ValueError(f'Origem do Parquet incompatível com o campo {ROTULOS[chave]}.')
        if chave=='newave':
            nomes={int(v['hydro_id']):v['nome_usina_cadastro'] for v in resumo['mapeamento_usinas']}
            etapas=resumo['mapeamento_estagios']
            if set(nomes)!=set(resumo['usinas']) or {v['stage_id'] for v in etapas}!=set(resumo['ids_estagios']):
                raise ValueError('Mapas NEWAVE não correspondem às chaves presentes no Parquet.')
            registros=[]
            for e in etapas:
                a,b=date.fromisoformat(e['start_date']),date.fromisoformat(e['end_date'])
                if a.day!=1 or b!=(pd.Timestamp(a)+pd.offsets.MonthBegin()).date():
                    raise ValueError('Calendário NEWAVE contém estágio não mensal.')
                registros.append((e['stage_id'],a,b))
            registros.sort(key=lambda v:v[1])
            if any(a[2]!=b[1] for a,b in zip(registros,registros[1:])):
                raise ValueError('Lacuna ou sobreposição no calendário NEWAVE.')
            calendario={s:dict(inicio=a,fim=b,ano=a.year,mes=a.month,ordem=i) for i,(s,a,b) in enumerate(registros)}
        else:
            if set(resumo['usinas'])-set(nomes_deck) or set(resumo['ids_estagios'])-set(calendario_deck):
                raise ValueError('UHEs ou estágios do novo modelo ausentes no deck selecionado.')
            nomes={u:nomes_deck[u] for u in resumo['usinas']}
            calendario={s:calendario_deck[s] for s in resumo['ids_estagios']}
            for ordem,s in enumerate(sorted(calendario,key=lambda s:calendario[s]['inicio'])):
                calendario[s]={**calendario[s],'ordem':ordem}
            if any(a['fim']!=b['inicio'] for a,b in zip(list(sorted(calendario.values(),key=lambda e:e['inicio'])),list(sorted(calendario.values(),key=lambda e:e['inicio']))[1:])):
                raise ValueError('Horizonte sintético com lacunas.')
        ids_deck={}; vistos=set()
        for u,nome in nomes.items():
            normal=normalizar_nome_usina(nome)
            if normal in vistos or normal not in por_nome:
                raise ValueError(f'UHE sem correspondência única com o deck: {nome}.')
            vistos.add(normal); ids_deck[u]=por_nome[normal]
            nomes[u]=nomes_deck[ids_deck[u]]
        a,b,origem=periodo_proposto(caminho,limites,chave)
        escolhido=(periodos or {}).get(chave)
        if escolhido:
            if len(escolhido)!=2 or any(not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',str(v)) for v in escolhido):
                raise ValueError(f'{ROTULOS[chave]}: informe o período como AAAA-MM, por exemplo 2024-12.')
            x,y=map(lambda v:str(pd.Period(v,freq='M')),escolhido)
            if (x,y)!=(a,b): origem='Definido pelo usuário'
            a,b=x,y
        if not a or not b:
            raise ValueError(f'{ROTULOS[chave]}: informe início e fim do histórico na janela ou na linha de comando.')
        if pd.Period(a)<pd.Period(limites[0]) or pd.Period(b)>pd.Period(limites[1]) or pd.Period(a)>pd.Period(b):
            raise ValueError(f'{ROTULOS[chave]}: período histórico fora dos limites {limites[0]} a {limites[1]}.')
        # A chave estatística é UHE × estágio × cenário, independentemente do nó.
        with duckdb.connect() as con:
            duplicada=con.execute('SELECT hydro_id,stage_id,scenario_id FROM read_parquet(?) GROUP BY ALL HAVING count(*)>1 LIMIT 1',[str(caminho)]).fetchone()
        if duplicada: raise ValueError(f'Chave UHE × estágio × cenário duplicada em {ROTULOS[chave]}: {duplicada}.')
        fontes.append(Fonte(chave,str(Path(caminho).resolve()),resumo,nomes,calendario,ids_deck,a,b,origem))
    if not fontes: raise ValueError('Selecione ao menos um Parquet.')
    if len(fontes)==2:
        a,b=fontes
        datas=lambda f:{(str(v['inicio']),str(v['fim'])) for v in f.calendario.values()}
        if datas(a)!=datas(b): raise ValueError('Comparação exige exatamente o mesmo horizonte sintético de mês/ano.')
        if set(a.ids_deck.values())!=set(b.ids_deck.values()):
            so_a=sorted(set(a.nomes.values())-set(b.nomes.values())); so_b=sorted(set(b.nomes.values())-set(a.nomes.values()))
            raise ValueError(f'Comparação exige as mesmas usinas. Só novo modelo: {so_a}; só NEWAVE: {so_b}.')
    return caminhos,nomes_deck,fontes,limites

def recortar_historico(fonte, caminho, destino):
    with duckdb.connect() as con:
        dados=con.execute('SELECT hydro_id,start_date,end_date,value_m3s FROM read_parquet(?) WHERE start_date>=? AND start_date<?',
            [str(caminho),pd.Period(fonte.inicio_h).start_time.date(),(pd.Period(fonte.fim_h)+1).start_time.date()]).df()
    inverso={v:k for k,v in fonte.ids_deck.items()}
    dados=dados.loc[dados.hydro_id.isin(inverso)].copy()
    dados['hydro_id']=dados.hydro_id.map(inverso).astype('int64')
    dados.to_parquet(destino,index=False)
    return dados
