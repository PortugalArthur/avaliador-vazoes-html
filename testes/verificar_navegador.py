"""Verifica file:// offline no Chrome, navegação, filtros, cores e memoriais."""
import argparse
import json
from pathlib import Path
import time
import threading

from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({'playwright':'playwright>=1.50','psutil':'psutil>=5.9'})
from playwright.sync_api import sync_playwright
import psutil

def verificar(caminho,pasta,real=False):
    pasta=Path(pasta);pasta.mkdir(parents=True,exist_ok=True)
    resultado={'arquivo':str(caminho),'offline':True,'abas':{},'erros':[],'requisicoes_externas':[]}
    stop=threading.Event();peak=[0]
    def sample():
        while not stop.wait(.25):
            try:
                processos=psutil.Process().children(recursive=True)
                peak[0]=max(peak[0],sum(p.memory_info().rss for p in processos if 'chrome' in p.name().lower()))
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    threading.Thread(target=sample,daemon=True).start()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(offline=True,viewport={'width':1500,'height':1000})
        page=context.new_page();page.on('pageerror',lambda e:resultado['erros'].append(str(e)))
        page.on('request',lambda r:resultado['requisicoes_externas'].append(r.url) if r.url.startswith(('http:','https:')) else None)
        t=time.perf_counter();page.goto(Path(caminho).resolve().as_uri(),wait_until='domcontentloaded',timeout=300000)
        page.wait_for_function('window.AVALIADOR?.ready===true',timeout=180000)
        resultado['abertura_segundos']=round(time.perf_counter()-t,3)
        nomes_modelos=page.evaluate('AVALIADOR.manifesto.modelos.map(m=>m.nome)')
        assert page.locator('#abas [role=tab]').count()==5
        assert 'Resultados gerais' not in page.locator('#abas').text_content()
        assert page.locator('.js-plotly-plot').count()==0
        assert page.locator('.metrica').count()==12
        print('Primeira visão utilizável em',resultado['abertura_segundos'],'segundos.',flush=True)
        page.screenshot(path=str(pasta/'visao_geral_medias.png'))
        # Correlação do SIN: dois seletores e barras agrupadas, com histórico mensal.
        for tab in ['medias','variancias','distribuicao','espacial','sequencias']:
            page.evaluate('([view,tab])=>AVALIADOR.go(view,tab)',['sin',tab])
            assert page.locator('.js-plotly-plot').count()==(len(nomes_modelos) if tab=='espacial' else 0),tab
            if tab in ['medias','variancias','distribuicao']:
                assert page.locator('.metrica').count()==12
                titles=page.locator('.modelo-cabecalho h3').all_text_contents()
                assert titles==[m+' — '+kind for kind in ['Indicadores','Resumo do teste por estágio','Ranking de usinas por estágios reprovados','Memorial completo'] for m in nomes_modelos],titles
            if tab=='sequencias':assert page.locator('.metrica').count()==12
            if tab=='espacial':
                a=page.get_by_label('Bacia A',exact=True)
                b=page.get_by_label('Bacia B',exact=True)
                assert a.input_value()!=b.input_value()
                curves=page.locator('.js-plotly-plot').evaluate_all('(plots)=>plots.map(p=>({n:p.data.map(t=>t.y.length),range:p.layout.yaxis.range,types:p.data.map(t=>t.type),mode:p.layout.barmode}))')
                stage_count=page.evaluate('AVALIADOR.manifesto.estagios.length')
                assert all(c['n']==[stage_count,stage_count] and c['range']==[-1.05,1.05] for c in curves)
                assert all(c['types']==['bar','bar'] and c['mode']=='group' for c in curves)
                resultado['espacial_sin_bacias_por_estagio']=True
            assert not page.evaluate('AVALIADOR.error||null'),tab
        # Memorial geral volumoso é paginado através de blocos, inclusive busca/ordem.
        page.get_by_text('Resumos por trajetória',exact=True).click()
        page.wait_for_function("document.querySelector('details.memorial[open] .contador')?.textContent?.includes('linha(s)')",timeout=120000)
        opened=page.locator('details.memorial[open]').first
        opened.locator('.painel').first.locator('th button').filter(has_text='ID da UHE').click()
        page.wait_for_timeout(300)
        opened.locator('.painel').first.locator('input[type=search]').fill('CAMARGOS')
        page.wait_for_function("document.querySelector('details.memorial[open] tbody tr td:nth-child(2)')?.textContent==='CAMARGOS'",timeout=120000)
        assert opened.locator('.painel').first.locator('tbody tr').count()<=50
        resultado['memorial_paginado']=True
        # Sliders afetam simultaneamente as tabelas dos dois modelos.
        page.evaluate("async()=>{await AVALIADOR.go('sin','medias');const s=AVALIADOR.state.states['sin-medias'];s.lo=3;s.hi=5;await AVALIADOR.render();}")
        stats_=page.evaluate("async()=>{const A=AVALIADOR;return Promise.all(A.manifesto.modelos.map(async m=>{const t=A.objects(await A.load(m.testes.medias));return A.summaries(t,A.state.states['sin-medias']);}));}")
        assert all(len(x['stages'])==3 for x in stats_)
        assert all(x['rank'][0]['Estágios calculados']<=3 for x in stats_)
        # UHE por nome, local a cada uma das cinco abas.
        esperado={'medias':6,'variancias':6,'distribuicao':6,'espacial':4,'sequencias':8}
        for tab,plots in esperado.items():
            page.evaluate('([view,tab])=>AVALIADOR.go(view,tab)',['usina',tab])
            assert page.locator('#abas [role=tab]').count()==5
            assert page.locator('.js-plotly-plot').count()==0 # sem seleção nesta aba
            inp=page.locator('input[list]');inp.fill('CAMARGOS');inp.dispatch_event('change')
            page.wait_for_function('AVALIADOR.ready===true',timeout=120000)
            assert not page.evaluate('AVALIADOR.error||null'),tab
            assert page.locator('.js-plotly-plot').count()==plots,tab
            names=page.locator('#conteudo .modelo-cabecalho h3').all_text_contents()
            assert names[:2]==nomes_modelos,(tab,names)
            fields=page.evaluate("Array.from(document.querySelectorAll('.js-plotly-plot')).map(e=>({types:e.data.map(t=>t.type),ytitle:e._fullLayout.yaxis.title.text,colors:e.data.map(t=>t.line?.color||t.marker?.color),annotations:e.layout.annotations||[],dataN:e.data.map(t=>(t.y||[]).length)}))")
            resultado['abas'][tab]={'graficos':plots,'figuras':fields}
            assert all(f['ytitle'] and not f['ytitle'].startswith('Click') for f in fields)
            if tab in ['medias','variancias','distribuicao']:
                assert fields[-1]['types']==['bar']
                assert any('aprovados' in a.get('text','') for a in fields[-1]['annotations'])
            if tab=='medias':
                assert fields[2]['types']==['box','box']
                assert fields[2]['dataN'][0]==(144000 if real else 7*29)
                page.locator('section.secao').nth(1).screenshot(path=str(pasta/'boxplots_vazoes.png'))
                page.locator('section.secao').nth(0).screenshot(path=str(pasta/'medias_desvios.png'))
            if tab=='sequencias':
                assert page.locator('input[type=range]').count()==0
                assert page.locator('.filtros select option').all_text_contents()==['Máximo','Média']
                assert fields[0]['colors']==['#09B6CB','#000000']
                assert fields[1]['colors']==['#C56A1A','#000000']
                page.locator('section.secao').nth(1).screenshot(path=str(pasta/'sequencias.png'))
                page.locator('.filtros select').select_option('Média')
                page.wait_for_function('AVALIADOR.ready===true',timeout=120000)
                assert 'Média' in page.locator('section.secao h2').first.text_content()
        # Conferência da curva empírica desenhada: D é idêntico ao resultado Python.
        ec=page.evaluate("async()=>{const A=AVALIADOR,m=A.manifesto.modelos[0],d=await A.load(m.uhe['0'].bloco),s=A.array(d.flows),N=A.manifesto.estagios.length,i=Math.min(36,N-1),ss=d.scenario_ids.map((_,j)=>s[j*N+i]),hs=A.array(d.hist_values),h=Array.from(hs).filter((_,j)=>+d.hist_dates[j].slice(5,7)===A.manifesto.estagios[i].mes),p=A.empirical(ss,h),row=A.objects(await A.load(m.testes.distribuicao)).find(r=>r.hydro_id===m.uhe['0'].id_original&&r.ordem_estagio===i);return {desenho:Math.max(...p.map(r=>r['Distância absoluta'])),python:row.estatistica_ks};}")
        assert abs(ec['desenho']-ec['python'])<1e-14
        resultado['ecdf_D']=ec
        # Numeric sort and synchronized upper scrollbar on the full memorial.
        page.evaluate("()=>AVALIADOR.go('sin','medias')")
        panel=page.locator('.bloco-modelo').filter(has=page.get_by_role('heading',name=nomes_modelos[0]+' — Memorial completo',exact=True)).locator('.painel')
        panel.locator('th button').filter(has_text='p-valor').click()
        vals=panel.locator('tbody tr').evaluate_all("rows=>rows.map(r=>{const cs=Array.from(r.closest('table').querySelectorAll('thead th button')).map(x=>x.textContent.replace(/[↕↑↓]/g,'').trim().toLowerCase());return r.children[cs.indexOf('p-valor')]?.title;}).filter(Boolean).map(x=>Number(x.replace(',','.')))")
        assert vals==sorted(vals),vals
        panel.locator('.tabela-scroll-topo').evaluate('(e)=>{e.scrollLeft=120;e.dispatchEvent(new Event("scroll"));}')
        assert panel.locator('.tabela-scroll').evaluate('(e)=>e.scrollLeft')>0
        assert not resultado['erros'],resultado['erros']
        assert not resultado['requisicoes_externas'],resultado['requisicoes_externas']
        context.close();browser.close()
    stop.set();resultado['pico_memoria_chrome_mb']=round(peak[0]/1024**2,1)
    (pasta/'navegador.json').write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in resultado.items() if k!='abas'},ensure_ascii=False),flush=True)
    return resultado

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('html');p.add_argument('--pasta',required=True);p.add_argument('--real',action='store_true');a=p.parse_args();verificar(a.html,a.pasta,a.real)
