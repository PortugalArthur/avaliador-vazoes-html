"""Calcula e empacota todas as análises sem depender de Streamlit."""
from pathlib import Path
import gc
import numpy as np
import pandas as pd
import duckdb

from aplicacao.fontes import ROTULOS,CORES,recortar_historico
from relatorio.blocos import tabela,vetor
from calculos.base_estatistica_cobre import organizar_amostras_dados
from calculos.teste_welch_cobre import avaliar_welch
from calculos.resultado_global_levene import calcular_levene_por_estagio
from calculos.resultado_global_ks import calcular_ks_por_estagio
from calculos.resultado_global_sequencias import _grupos_por_usina
from calculos.analise_sequencias_cobre import organizar_horizonte,calcular_sequencias_usina
from calculos.indicadores_p90_sequencias import calcular_indicadores_p90,calcular_indicadores_p50
from calculos.correlacao_espacial_cobre import gerar_correlacao_espacial,MOTIVOS
from calculos.comparacao_espacial_historico import gerar_correlacao_historica
from calculos.correlacao_anual_bacias import gerar_medias_anuais_bacias,comparar_bacias_anuais
from dados.cadastro_bacias import ler_cadastro_bacias,associar_usinas_bacias,organizar_agrupamento_bacias

def adicionar_tempo(df,fonte):
    d=df.copy()
    if 'stage_id' in d:
        d['ordem_estagio']=d.stage_id.map({s:e['ordem'] for s,e in fonte.calendario.items()})
    return d

def _testes(dados,historico,u,fonte):
    try:
        organizacao=organizar_amostras_dados(dados,historico,u,fonte.nomes[u],fonte.calendario)
    except ValueError as erro:
        rows=[]
        for s,e in fonte.calendario.items():
            rows.append(dict(hydro_id=u,nome_usina=fonte.nomes[u],stage_id=s,ordem_estagio=e['ordem'],
                             inicio_estagio=e['inicio'],fim_estagio=e['fim'],mes=e['mes'],ano=e['ano'],
                             p_valor=None,status_teste='Não calculado',motivo_nao_calculado=str(erro)))
        return {k:pd.DataFrame(rows) for k in ('medias','variancias','distribuicao')}
    welch=[]
    for s,a in organizacao.amostras_por_estagio.items():
        e=fonte.calendario[s]
        linha=dict(hydro_id=u,nome_usina=fonte.nomes[u],stage_id=s,ordem_estagio=e['ordem'],
                   inicio_estagio=e['inicio'],fim_estagio=e['fim'],ano=e['ano'],mes=e['mes'],
                   historico_inicio=str(organizacao.historico_inicio),historico_fim=str(organizacao.historico_fim),
                   primeiro_mes_historico_usado=str(a.historico.index.min()) if len(a.historico) else None,
                   ultimo_mes_historico_usado=str(a.historico.index.max()) if len(a.historico) else None,
                   n_sintetico=len(a.sintetico),n_historico=len(a.historico),alfa=.05)
        try:
            linha.update(avaliar_welch(a.historico.to_numpy(),a.sintetico.to_numpy(),.05),status_teste='Calculado')
        except ValueError as erro:
            linha.update(status_teste='Não calculado',motivo_nao_calculado=str(erro),p_valor=None)
        welch.append(linha)
    return {'medias':pd.DataFrame(welch),'variancias':calcular_levene_por_estagio(organizacao),
            'distribuicao':calcular_ks_por_estagio(organizacao)}

def _matriz_espacial(r,i):
    return {k:vetor(getattr(r,atributo)[i]) for k,atributo in [
        ('n','pares_validos'),('r','correlacoes'),('media','medias'),('desvio','desvios'),
        ('cov','covariancias'),('estado','estados')]} | {'esperados':int(r.pares_esperados[i])}

def parametros_kde(v):
    """Mesmos parâmetros do gráfico original; avaliação da curva é desenho no HTML."""
    v=np.sort(np.asarray(v,float))
    if len(v)<2 or not np.isfinite(v).all():return None
    sigma=float(np.std(v,ddof=0));tol=1e-12*max(1.,float(np.abs(v).max()))
    largura=sigma*len(v)**(-1/5)
    if sigma<=tol or largura<=tol or not np.isfinite(largura):return None
    a,b=float(v.min()-6*largura),float(v.max()+6*largura)
    n=min(16001,max(1024,int(np.ceil((b-a)*5/largura))+1))
    return [largura,a,b,n]

def calcular_modelo(fonte,historico_original,pasta,arquivo,progresso):
    chave=fonte.chave
    hp=Path(pasta)/f'historico_{chave}.parquet'
    h=recortar_historico(fonte,historico_original,hp)
    por_h={int(u):g for u,g in h.groupby('hydro_id',sort=False)}
    rotulo=fonte.rotulo or ROTULOS[chave]
    meta={'key':chave,'nome':rotulo,'cor':CORES[chave],
          'historico_fonte':fonte.historico_caminho or str(historico_original),
          'historico_disponivel':fonte.limites_h,
          'historico':[fonte.inicio_h,fonte.fim_h],'origem_periodo':fonte.origem_periodo,
          'cenario_n':fonte.resumo['cenarios'],'uhe':{},'testes':{},
          'stage_ids':[s for s in sorted(fonte.calendario,key=lambda s:fonte.calendario[s]['ordem'])],
          'hydro_ids':sorted(fonte.nomes),'ids_deck':fonte.ids_deck,'motivos_espaciais':MOTIVOS}
    progresso(f'{rotulo} — correlações espaciais mensais…')
    espacial=gerar_correlacao_espacial(fonte.caminho,fonte.nomes,fonte.calendario)
    meta['spatial_hydros']=list(espacial.hydro_ids)
    meta['espacial']=[arquivo.bloco(f'{chave}_esp_{i}',_matriz_espacial(espacial,i)) for i in range(len(espacial.stage_ids))]
    del espacial;gc.collect()
    rh=gerar_correlacao_historica(hp,tuple(sorted(fonte.nomes)),fonte.nomes)
    meta['espacial_historico']=[arquivo.bloco(f'{chave}_eh_{i}',_matriz_espacial(rh.matrizes,i)) for i in range(12)]
    meta['avisos_historicos']=rh.avisos
    cadastro=organizar_agrupamento_bacias(associar_usinas_bacias(fonte.nomes,ler_cadastro_bacias()),True)
    meta['cadastro']=tabela(cadastro)
    progresso(f'{rotulo} — correlações anuais entre bacias…')
    if cadastro.bacia_id.notna().any():
        anual=gerar_medias_anuais_bacias(fonte.caminho,hp,fonte.calendario,cadastro)
        meta['anos_completos']=anual.anos_completos;meta['anos_incompletos']=anual.anos_incompletos
        meta['anual_medias']=arquivo.bloco(f'{chave}_am',{'sintetico':tabela(anual.sintetico),'historico':tabela(anual.historico),'composicao':tabela(anual.composicao),'sem_bacia':tabela(anual.sem_bacia)})
        pares=[];meta['anual_pares']={}
        for a in sorted(anual.composicao.bacia_id.unique()):
            coef,resumo=comparar_bacias_anuais(anual,int(a))
            for b in sorted(resumo.bacia_id.unique()) if not resumo.empty else []:
                if int(b)<=int(a):continue
                linha=resumo.loc[resumo.bacia_id.eq(b)].iloc[0].to_dict()
                v=coef.loc[coef.bacia_id.eq(b)]
                validos=v['Correlação'].dropna().to_numpy()
                q=np.quantile(validos,[.25,.5,.75],method='linear') if len(validos) else [None]*3
                nome_a=anual.composicao.loc[anual.composicao.bacia_id.eq(a),'Bacia'].iloc[0]
                nome_b=linha.pop('Bacia comparada');linha.pop('bacia_id')
                par=f'{int(a)}_{int(b)}'
                pares.append({'par':par,'Bacia A':nome_a,'Bacia B':nome_b,'Q1':q[0],'Mediana':q[1],'Q3':q[2],**linha})
                meta['anual_pares'][par]=arquivo.bloco(f'{chave}_ap_{par}',tabela(v))
        meta['anual_resumo']=arquivo.bloco(f'{chave}_ar',tabela(pd.DataFrame(pares)))
        del anual;gc.collect()
    else:
        meta['anual_aviso']='Nenhuma usina foi identificada no cadastro de bacias.'
        meta['anos_completos']=[]; meta['anos_incompletos']=[];meta['anual_pares']={}
        meta['anual_resumo']=arquivo.bloco(f'{chave}_ar',tabela(pd.DataFrame()))
        meta['anual_medias']=arquivo.bloco(f'{chave}_am',{k:tabela(pd.DataFrame()) for k in ['sintetico','historico','composicao','sem_bacia']})
    frames={k:[] for k in ('medias','variancias','distribuicao')};resumos_p=[]
    horizonte=organizar_horizonte(fonte.calendario,tuple(fonte.calendario))
    with duckdb.connect() as con:
        con.execute('SET threads=4')
        for n,(u,dados) in enumerate(_grupos_por_usina(con,fonte.caminho),1):
            historico=por_h.get(u,h.iloc[:0])
            testes=_testes(dados,historico,u,fonte)
            for k,v in testes.items(): frames[k].append(v)
            seq=calcular_sequencias_usina(dados,historico,u,fonte.nomes[u],horizonte)
            resumos_p.append(seq.resumos)
            matriz=dados.pivot(index='scenario_id',columns='stage_id',values='incremental_inflow_m3s').reindex(columns=meta['stage_ids']).sort_index()
            presente=dados.assign(presente=1).pivot(index='scenario_id',columns='stage_id',values='presente').reindex(index=matriz.index,columns=meta['stage_ids']).fillna(0)
            hist=historico.sort_values('start_date')
            obj={'scenario_ids':matriz.index.astype(int).tolist(),'flows':vetor(matriz.to_numpy(float)),'presentes':vetor(presente.to_numpy(float)),
                 'hist_dates':pd.to_datetime(hist.start_date).dt.strftime('%Y-%m').tolist(),
                 'hist_values':vetor(hist.value_m3s.to_numpy(float)),
                 'kde_s':[parametros_kde(matriz.iloc[:,i].to_numpy(float)) for i in range(len(meta['stage_ids']))],
                 'kde_h':{str(m):parametros_kde(hist.loc[pd.to_datetime(hist.start_date).dt.month.eq(m),'value_m3s'].to_numpy(float)) for m in range(1,13)},
                 'sequencias':{k:tabela(getattr(seq,k)) for k in ['resumos','eventos','mlts','blocos','intervalos_nao_utilizados','diagnosticos']}}
            uid=fonte.ids_deck[u]
            seq_dados=obj.pop('sequencias')
            meta['uhe'][str(uid)]={'id_original':u,'bloco':arquivo.bloco(f'{chave}_u_{uid}',obj),
                                  'linhas_sequencias':{k:len(v['r']) for k,v in seq_dados.items()},
                                  'blocos_sequencias':{k:arquivo.bloco(f'{chave}_u_{uid}_seq_{k}',v) for k,v in seq_dados.items()}}
            if n==1 or n%10==0 or n==len(fonte.nomes):
                progresso(f'{rotulo} — testes, vazões e sequências: {n}/{len(fonte.nomes)} usinas')
    for k,lista in frames.items():
        frame=adicionar_tempo(pd.concat(lista,ignore_index=True),fonte)
        meta['testes'][k]=arquivo.bloco(f'{chave}_t_{k}',tabela(frame))
    resumos=pd.concat(resumos_p,ignore_index=True)
    meta['percentis']={}
    for q,func in [(90,calcular_indicadores_p90),(50,calcular_indicadores_p50)]:
        p,i=func(resumos)
        meta['percentis'][str(q)]=arquivo.bloco(f'{chave}_p{q}',{'por_usina':tabela(p),'indicadores':tabela(i)})
    meta['registros_testes']={k:sum(len(v) for v in lista) for k,lista in frames.items()}
    meta['trajetorias']=len(resumos)
    return meta
