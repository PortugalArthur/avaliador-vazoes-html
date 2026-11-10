"""Audita somas, denominadores e filtros do HTML usando resultados já gravados.

Não recalcula Welch/Levene/KS nem altera relatórios ou insumos. Uma contagem
independente em Python é comparada com o JavaScript e com os elementos visíveis.
"""
import argparse
import base64
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path
import re
import sys

from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({'playwright': 'playwright>=1.50'})
from playwright.sync_api import sync_playwright

TIPOS = ('medias', 'variancias', 'distribuicao')
DECISAO = dict(medias='rejeita_igualdade', variancias='rejeita_igualdade_variancias',
               distribuicao='rejeita_igualdade_distribuicoes')


def manifesto(caminho):
    with caminho.open('rb') as f:
        f.seek(max(0, caminho.stat().st_size-12*1024*1024))
        fim = f.read().decode('utf-8')
    return json.loads(re.search(r'<script id="manifesto" type="application/json">(.*?)</script>', fim, re.S)[1])


def blocos(caminho, chaves):
    restantes = set(chaves)
    prefixo = '<script type="application/octet-stream" id="bloco-'
    with caminho.open(encoding='utf-8') as f:
        for linha in f:
            if not linha.startswith(prefixo):
                continue
            chave = linha[len(prefixo):].split('"', 1)[0]
            if chave in restantes:
                payload = linha.split('>', 1)[1].rsplit('</script>', 1)[0]
                yield chave, json.loads(gzip.decompress(base64.b64decode(payload)))
                restantes.remove(chave)
                if not restantes:
                    break
    assert not restantes, f'Blocos ausentes: {restantes}'


def objetos(t):
    return [dict(zip(t['c'], r)) for r in t['r']]


def numero(x):
    return type(x) in (int, float) and math.isfinite(x)


def valido(r):
    return r['status_teste'] == 'Calculado' and numero(r['p_valor']) and 0 <= r['p_valor'] <= 1


def contagem_independente(linhas, inicio, fim, alfa=.05):
    # Conta cada par uma única vez; não usa summaries nem indicadores do programa.
    selecionadas = [r for r in linhas if inicio <= r['ordem_estagio'] <= fim]
    assert len({(r['hydro_id'], r['ordem_estagio']) for r in selecionadas}) == len(selecionadas)
    por_uhe, por_estagio = defaultdict(Counter), defaultdict(Counter)
    for r in selecionadas:
        categoria = 'nao_calculado' if not valido(r) else 'reprovado' if r['p_valor'] < alfa else 'aprovado'
        por_uhe[r['hydro_id']][categoria] += 1
        por_estagio[r['ordem_estagio']][categoria] += 1
    aprovados = sum(c['aprovado'] for c in por_uhe.values())
    reprovados = sum(c['reprovado'] for c in por_uhe.values())
    calculados = aprovados + reprovados
    testadas = sum(c['aprovado'] + c['reprovado'] > 0 for c in por_uhe.values())
    com_reprovacao = sum(c['reprovado'] > 0 for c in por_uhe.values())
    completas = sum(c['aprovado'] == fim-inicio+1 and c['reprovado'] == 0 and c['nao_calculado'] == 0
                    for c in por_uhe.values())
    percent = lambda a, b: 100*a/b if b else None
    valores = [calculados, reprovados, percent(aprovados, calculados), testadas,
               com_reprovacao, percent(completas, testadas)]
    # Relações entre os três níveis impedem somar usinas repetidas por estágio.
    assert calculados == sum(c['aprovado'] + c['reprovado'] for c in por_estagio.values())
    assert reprovados == sum(c['reprovado'] for c in por_estagio.values())
    return dict(valores=valores, usinas=por_uhe, estagios=por_estagio,
                completas=completas, nao_calculados=len(selecionadas)-calculados)


def igual(a, b):
    if a is None or b is None:
        assert a is b, (a, b)
    else:
        assert math.isclose(a, b, rel_tol=1e-13, abs_tol=1e-11), (a, b)


def conferir_resumo(esperado, obtido, inicio, fim):
    for a, b in zip(esperado['valores'], (v for _, v in obtido['metrics']), strict=True):
        igual(a, b)
    assert len(obtido['unavailable']) == esperado['nao_calculados']
    assert [s['Estágio'] for s in obtido['stages']] == list(range(inicio, fim+1))
    for s in obtido['stages']:
        c = esperado['estagios'][s['Estágio']]
        n = c['aprovado']+c['reprovado']
        assert (s['Combinações testadas'], s['Reprovações']) == (n, c['reprovado'])
        igual(s['Reprovações (%)'], 100*c['reprovado']/n if n else None)
    ranks = obtido['rank']
    assert {r['ID da UHE'] for r in ranks} == set(esperado['usinas'])
    anteriores = []
    for r in ranks:
        c = esperado['usinas'][r['ID da UHE']]
        n = c['aprovado']+c['reprovado']
        assert (r['Estágios calculados'], r['Estágios reprovados'], r['Estágios não calculados']) == (
            n, c['reprovado'], fim-inicio+1-n)
        assert r['Posição'] == 1+sum(x['Estágios reprovados'] > c['reprovado'] for x in ranks)
        if anteriores:
            assert anteriores[-1] >= c['reprovado']
        anteriores.append(c['reprovado'])


def intervalos(n):
    # Todos os estágios isolados, anos, extremos e intervalos atravessando anos.
    return sorted({(0, n-1), (0, min(35, n-1)), (min(36, n-1), n-1),
                   (min(5, n-1), min(17, n-1)), (min(23, n-1), min(48, n-1)),
                   (max(0, n//2-1), min(n-1, n//2)),
                   *((i, i) for i in range(n)),
                   *((i, min(i+11, n-1)) for i in range(0, n, 12))})


def texto_metricas(valores):
    return ['—' if x is None else f'{x:.2f}'.replace('.', ',')+'%' if i in (2, 5) else str(x)
            for i, x in enumerate(valores)]


def conferir_limites(page):
    # Casos pequenos e declarados apenas em memória. Não substituem as fontes
    # reais: verificam fronteiras que raramente aparecem exatamente nos decks.
    linhas = []
    for uid, pares in enumerate([[(.05, True), (.3, True)],
                                [(.049999, True), (None, False)],
                                [(1, True), (None, True)],
                                [(.9, False), (None, False)],
                                [(0, True), (1, True)]]):
        for etapa, (p, calculado) in enumerate(pares):
            linhas.append(dict(hydro_id=uid, nome_usina=f'Teste {uid}', ordem_estagio=etapa,
                               p_valor=p, status_teste='Calculado' if calculado else 'Não calculado'))
    casos = [
        (linhas, 0, 1, [6, 2, 100*4/6, 4, 2, 25]),
        (linhas, 0, 0, [4, 2, 50, 4, 2, 50]),
        (linhas, 1, 1, [2, 0, 100, 2, 0, 100]),
        ([], 0, 1, [0, 0, None, 0, 0, None]),
        ([r for r in linhas if r['hydro_id']==3], 0, 1, [0, 0, None, 0, 0, None]),
        # Usina com uma linha ausente não pode contar como completamente aprovada.
        (linhas+[dict(hydro_id=5, nome_usina='Ausente', ordem_estagio=0,
                      p_valor=1, status_teste='Calculado')], 0, 1, [7, 2, 100*5/7, 5, 2, 20]),
        ([dict(hydro_id=i, nome_usina=f'Inválido {i}', ordem_estagio=0,
               p_valor=p, status_teste='Calculado') for i,p in enumerate([-.1, 1.01, True])],
         0, 0, [0, 0, None, 0, 0, None]),
    ]
    for rows, lo, hi, esperado in casos:
        obtido=page.evaluate('''({rows,lo,hi})=>AVALIADOR.summaries(rows,{lo,hi}).metrics.map(r=>r[1])''',
                             dict(rows=rows,lo=lo,hi=hi))
        for a,b in zip(esperado,obtido,strict=True):
            igual(a,b)
    return len(casos)


def conferir_tabelas_visiveis(page, modelos, dados, tipo, lo, hi):
    tabelas=page.evaluate('''()=>Array.from(document.querySelectorAll('.bloco-modelo'))
      .filter(b=>/— (Resumo do teste por estágio|Ranking de usinas por estágios reprovados)$/.test(b.querySelector('h3')?.textContent))
      .map(b=>({titulo:b.querySelector('h3').textContent,
        linhas:Array.from(b.querySelectorAll('tbody tr')).map(tr=>Array.from(tr.cells).map(td=>td.textContent))}))''')
    assert len(tabelas)==2*len(modelos)
    for pos, modelo in enumerate(modelos):
        esperado=contagem_independente(objetos(dados[modelo['testes'][tipo]]),lo,hi)
        stages=tabelas[pos]['linhas']
        assert len(stages)==min(50,hi-lo+1)
        for cells in stages:
            stage=int(cells[0]);assert lo<=stage<=hi
            c=esperado['estagios'][stage];n=c['aprovado']+c['reprovado']
            assert [cells[3],cells[4]]==[str(n),str(c['reprovado'])]
            assert cells[5]==('—' if not n else f'{100*c["reprovado"]/n:.2f}'.replace('.',','))
        ranking=tabelas[len(modelos)+pos]['linhas']
        assert len(ranking)==min(50,len(esperado['usinas']))
        for cells in ranking:
            c=esperado['usinas'][int(cells[1])];n=c['aprovado']+c['reprovado']
            assert cells[3:6]==[str(c['reprovado']),str(n),str(hi-lo+1-n)]


def conferir_demais(m, dados):
    percentis = []
    for q, chave in m['percentis'].items():
        d = dados[chave]
        linhas = objetos(d['por_usina'])
        for i in objetos(d['indicadores']):
            rs = [r for r in linhas if r['medida'] == i['medida']]
            validas = [r for r in rs if numero(r[f'p{q}_sintetico']) and numero(r[f'p{q}_historico'])]
            maior = sum(r[f'p{q}_sintetico'] > r[f'p{q}_historico'] for r in validas)
            menor = sum(r[f'p{q}_sintetico'] < r[f'p{q}_historico'] for r in validas)
            iguais = len(validas)-maior-menor
            assert all(r['comparavel'] == (r in validas) for r in rs)
            assert (i['usinas_total'], i['usinas_comparaveis'], i['usinas_sintetico_maior'],
                    i['usinas_sintetico_menor'], i['usinas_iguais'], i['usinas_sem_comparacao']) == (
                        len(rs), len(validas), maior, menor, iguais, len(rs)-len(validas))
            igual(i['percentual_sintetico_maior'], 100*maior/len(validas) if validas else None)
            percentis.append(dict(percentil=q, medida=i['medida'], acima=maior,
                                  comparaveis=len(validas), percentual=i['percentual_sintetico_maior']))
    pares = 0
    for r in objetos(dados[m['anual_resumo']]):
        vals = objetos(dados[m['anual_pares'][r['par']]])
        n = sum(numero(v['Correlação']) for v in vals)
        assert (r['Cenários válidos'], r['Cenários indisponíveis']) == (n, len(vals)-n)
        assert len(vals) == m['cenario_n']
        pares += 1
    return dict(percentis=percentis, pares_anual_contagens_conferidas=pares)


def verificar(caminho, pasta, pw):
    caminho = Path(caminho).resolve()
    antes = caminho.stat()
    m = manifesto(caminho)
    assert m['alfa'] == .05
    chaves = set()
    for modelo in m['modelos']:
        chaves.update(modelo['testes'].values())
        chaves.update(modelo['percentis'].values())
        chaves.add(modelo['anual_resumo'])
        chaves.update(modelo['anual_pares'].values())
    dados = dict(blocos(caminho, chaves))
    print('Blocos lidos:', caminho.name, flush=True)
    resultado = dict(arquivo=str(caminho), etapas=len(m['estagios']), modelos=[], erros_navegador=[])
    navegador = pw.chromium.launch(channel='chrome', headless=True)
    contexto = navegador.new_context(offline=True, viewport={'width':1500, 'height':1000})
    page = contexto.new_page()
    page.on('pageerror', lambda e: resultado['erros_navegador'].append(str(e)))
    try:
        page.goto(caminho.as_uri(), wait_until='domcontentloaded', timeout=300000)
        page.wait_for_function('window.AVALIADOR?.ready===true', timeout=180000)
        resultado['casos_limite_conferidos']=conferir_limites(page)
        ints = intervalos(len(m['estagios']))
        for modelo in m['modelos']:
            rm = dict(nome=modelo['nome'], testes={}, demais=conferir_demais(modelo, dados))
            resultado['modelos'].append(rm)
            for tipo in TIPOS:
                linhas = objetos(dados[modelo['testes'][tipo]])
                assert len(linhas) == len(m['usinas'])*len(m['estagios'])
                assert all(not valido(r) or r[DECISAO[tipo]] == (r['p_valor'] < .05) for r in linhas)
                obtidos = page.evaluate('''async ({key,intervalos})=>{
                  const A=AVALIADOR,rows=A.objects(await A.load(key));
                  return intervalos.map(([lo,hi])=>A.summaries(rows,{lo,hi}));
                }''', dict(key=modelo['testes'][tipo], intervalos=ints))
                conferidos = []
                for (lo, hi), obtido in zip(ints, obtidos, strict=True):
                    esperado = contagem_independente(linhas, lo, hi)
                    conferir_resumo(esperado, obtido, lo, hi)
                    conferidos.append(dict(inicio=lo, fim=hi, valores=esperado['valores'],
                                           completas=esperado['completas'], nao_calculados=esperado['nao_calculados']))
                rm['testes'][tipo] = conferidos
            print('Contagens independentes conferidas:', modelo['nome'], len(ints), 'intervalos por teste', flush=True)
        # Usa os controles reais: oninput/onchange, não apenas chamadas à função.
        resultado['filtros_visuais'] = []
        escolhas = [(0, len(m['estagios'])-1), (0, 0), (5, 17), (35, 36), (len(m['estagios'])-1,)*2]
        for tipo in TIPOS:
            page.evaluate('tab=>AVALIADOR.go("sin",tab)', tipo)
            for lo, hi in escolhas:
                page.evaluate('''([lo,hi])=>{
                  const a=document.querySelector('[aria-label="Primeiro estágio"]');
                  const b=document.querySelector('[aria-label="Último estágio"]');
                  a.value=lo;b.value=hi;a.dispatchEvent(new Event('input'));
                  b.dispatchEvent(new Event('change'));
                }''', [lo, hi])
                page.wait_for_function('AVALIADOR.ready===true', timeout=180000)
                valores = []
                for modelo in m['modelos']:
                    esperado = contagem_independente(objetos(dados[modelo['testes'][tipo]]), lo, hi)
                    valores.extend(texto_metricas(esperado['valores']))
                assert page.locator('.metrica strong').all_text_contents() == valores
                conferir_tabelas_visiveis(page,m['modelos'],dados,tipo,lo,hi)
                resultado['filtros_visuais'].append(dict(teste=tipo, inicio=lo, fim=hi, indicadores=valores))
            # Busca/resultado são do memorial; não devem alterar o total geral.
            antes_metricas = page.locator('.metrica strong').all_text_contents()
            page.get_by_placeholder('Todas as usinas', exact=True).fill('CAMARGOS')
            page.get_by_placeholder('Todas as usinas', exact=True).dispatch_event('change')
            page.wait_for_function('AVALIADOR.ready===true', timeout=180000)
            page.get_by_label('Resultado', exact=True).select_option('Reprovado')
            page.wait_for_function('AVALIADOR.ready===true', timeout=180000)
            assert page.locator('.metrica strong').all_text_contents() == antes_metricas
            resultado['filtros_visuais'].append(dict(teste=tipo, busca_status_restritos_ao_memorial=True))
        # O percentual no gráfico deve usar apenas a UHE e o intervalo selecionados.
        resultado['graficos_p'] = []
        for tipo in TIPOS:
            page.evaluate('tab=>AVALIADOR.go("usina",tab)', tipo)
            inp = page.locator('input[list]')
            inp.fill('CAMARGOS'); inp.dispatch_event('change')
            page.wait_for_function('AVALIADOR.ready===true', timeout=180000)
            for lo, hi in [(0, len(m['estagios'])-1), (36, 36)]:
                page.evaluate('''async ({tipo,lo,hi})=>{
                  const s=AVALIADOR.state.states['uhe-'+tipo];s.lo=lo;s.hi=hi;s.stage=lo;
                  await AVALIADOR.render();
                }''', dict(tipo=tipo,lo=lo,hi=hi))
                plots = page.evaluate('''()=>Array.from(document.querySelectorAll('.js-plotly-plot'))
                  .filter(p=>p.layout.yaxis.title.text==='p-valor').map(p=>({
                    texto:p.layout.annotations[0].text, x:p.data[0].x,
                    y:p.data[0].y,cores:p.data[0].marker.color}))''')
                assert len(plots) == len(m['modelos'])
                for modelo, plot in zip(m['modelos'], plots, strict=True):
                    uid = modelo['uhe']['0']['id_original']
                    rows = [r for r in objetos(dados[modelo['testes'][tipo]]) if r['hydro_id']==uid and lo<=r['ordem_estagio']<=hi]
                    bons = [r for r in rows if valido(r)]
                    aprovados = sum(r['p_valor'] >= .05 for r in bons)
                    texto = (f'{100*aprovados/len(bons):.2f}'.replace('.', ',')+'% aprovados') if bons else 'Sem testes válidos'
                    assert plot['texto'] == texto, (plot['texto'], texto)
                    assert len(plot['y']) == hi-lo+1
                    assert plot['y'] == [r['p_valor'] if valido(r) else None for r in rows]
                    assert plot['cores'] == ['#DC2626' if valido(r) and r['p_valor']<.05 else '#16A34A' for r in rows]
                    resultado['graficos_p'].append(dict(teste=tipo, modelo=modelo['nome'], inicio=lo, fim=hi, texto=texto))
        page.evaluate('()=>AVALIADOR.go("sin","sequencias")')
        esperados = []
        for q in ['90','50']:
            for modelo in m['modelos']:
                for i in objetos(dados[modelo['percentis'][q]]['indicadores']):
                    x=i['percentual_sintetico_maior']
                    esperados.append('—' if x is None else f'{x:.2f}'.replace('.', ',')+'%')
        assert page.locator('.metrica strong').all_text_contents() == esperados
        assert not resultado['erros_navegador']
    finally:
        navegador.close()
    depois = caminho.stat()
    assert (antes.st_size, antes.st_mtime_ns) == (depois.st_size, depois.st_mtime_ns)
    resultado['relatorio_original_preservado'] = True
    resultado['aprovado'] = True
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta/(caminho.stem+'.json')).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
    print('APROVADO:', caminho.name, flush=True)
    return resultado


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('html', nargs='+', type=Path)
    p.add_argument('--saida', type=Path, default=Path('outputs/verificacao/contadores'))
    a=p.parse_args()
    with sync_playwright() as pw:
        for html in a.html:
            verificar(html, a.saida, pw)
