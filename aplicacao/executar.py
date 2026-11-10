"""Janela de entradas e geração independente por linha de comando."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import tempfile
import threading
import webbrowser
from zoneinfo import ZoneInfo

from infraestrutura.preparar_ambiente import garantir_dependencias,PASTA_PROJETO
garantir_dependencias({'duckdb':'duckdb>=0.10','pandas':'pandas>=2.0','numpy':'numpy>=1.24',
                      'scipy':'scipy>=1.11','pyarrow':'pyarrow>=14','plotly':'plotly>=5.18',
                      'xlsxwriter':'XlsxWriter>=3.2','tzdata':'tzdata>=2024.1'})
from aplicacao.fontes import inspecionar,assinatura,sha256,ROTULOS,periodo_proposto
from relatorio.blocos import ArquivoHTML
from relatorio.motor import calcular_modelo
from dados.validacao_dados_cobre import localizar_fontes_deck,validar_historico
from dados.cadastro_bacias import ler_cadastro_bacias
import pandas as pd

VERSAO='1.2.0'

def agora():
    return datetime.now(ZoneInfo('America/Sao_Paulo'))

def gerar(deck,novo=None,newave=None,periodos=None,saida=None,progresso=print, *,
          tipo_comparacao='novo_newave',deck_referencia=None,rotulo_novo=None,rotulo_referencia=None):
    caminhos,nomes,fontes,limites=inspecionar(deck,novo,newave,periodos,progresso,
        tipo_comparacao=tipo_comparacao,deck_referencia=deck_referencia,
        rotulo_novo=rotulo_novo,rotulo_referencia=rotulo_referencia)
    origens=[Path(v) for v in caminhos.values()]+[Path(f.caminho) for f in fontes]
    antes=[assinatura(p) for p in origens]
    comparacao=len(fontes)==2
    modo=('comparacao_'+('novo_modelo_novo_modelo' if tipo_comparacao=='novo_novo' else 'novo_modelo_newave')) if comparacao else 'analise_'+('novo_modelo' if fontes[0].chave=='novo' else 'newave')
    if saida:
        destino=Path(saida).resolve()
        if destino.exists(): raise ValueError('A saída já existe. Escolha outro nome; relatórios anteriores são preservados.')
    else:
        destino=PASTA_PROJETO/'relatorios'/f'{modo}_{agora():%Y%m%d_%H%M%S}.html'
        i=1
        while destino.exists():
            destino=PASTA_PROJETO/'relatorios'/f'{modo}_{agora():%Y%m%d_%H%M%S}_{i}.html';i+=1
    if destino.suffix.lower()!='.html' or destino in [p.resolve() for p in origens]:
        raise ValueError('Selecione uma saída .html diferente das fontes.')
    arquivo=ArquivoHTML(destino)
    try:
        models=[]
        with tempfile.TemporaryDirectory(prefix='avaliador_html_') as tmp:
            for f in fontes: models.append(calcular_modelo(f,caminhos['historico'],tmp,arquivo,progresso))
        uhes=sorted(set(fontes[0].ids_deck.values()),key=lambda u:nomes[u])
        etapas=sorted(fontes[0].calendario.values(),key=lambda e:e['inicio'])
        manifesto={'versao':VERSAO,'modo':'Comparação' if comparacao else 'Análise','alfa':.05,
                   'tipo_comparacao':tipo_comparacao,
                   'gerado_em':agora().isoformat(),'historico_disponivel':limites,
                   'usinas':[{'id':u,'nome':nomes[u]} for u in uhes],
                   'estagios':[{'i':i,'inicio':str(e['inicio']),'fim':str(e['fim']),'mes':e['mes'],'ano':e['ano'],
                                'rotulo':f"{e['mes']:02d}/{e['ano']}"} for i,e in enumerate(etapas)],
                   'modelos':models,'cadastro_versao':ler_cadastro_bacias().attrs.get('versao'),
                   'fontes':antes,'metodos':{'medias':'Welch bilateral','variancias':'Levene original — centro na média',
                                            'distribuicao':'KS bilateral — distribuição limite de Kolmogorov'}}
        manifesto['rotulos']=json.loads((PASTA_PROJETO/'recursos/rotulos.json').read_text(encoding='utf-8'))
        progresso('Conferindo integridade das fontes e gravando o HTML…')
        for a in antes:
            atual=assinatura(a['caminho'])
            if atual!=a: raise ValueError(f"A fonte mudou durante a geração: {a['caminho']}")
            a['sha256']=sha256(a['caminho'])
        caminho=arquivo.concluir(manifesto)
        progresso(f'Relatório concluído: {caminho}')
        return caminho,manifesto
    except BaseException:
        arquivo.cancelar();raise

def janela():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    raiz=tk.Tk();raiz.title('Avaliador de vazões — relatório HTML');raiz.geometry('990x900');raiz.minsize(850,740)
    estilo=ttk.Style(raiz);estilo.theme_use('clam')
    for n in ['TFrame','TLabel']:estilo.configure(n,background='#f3f6fa',foreground='#102a43')
    estilo.configure('TLabel',font=('Segoe UI',10));estilo.configure('TButton',padding=8,font=('Segoe UI',10))
    estilo.configure('Titulo.TLabel',font=('Segoe UI',20,'bold'),foreground='#154765')
    raiz.configure(background='#f3f6fa')
    canvas=tk.Canvas(raiz,highlightthickness=0,background='#f3f6fa');scroll=ttk.Scrollbar(raiz,orient='vertical',command=canvas.yview)
    scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
    painel=ttk.Frame(canvas,padding=24);janela_painel=canvas.create_window((0,0),window=painel,anchor='nw')
    painel.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(janela_painel,width=e.width))
    raiz.bind_all('<MouseWheel>',lambda e:canvas.yview_scroll(int(-e.delta/120),'units'))
    painel.columnconfigure(1,weight=1)
    ttk.Label(painel,text='Avaliador de vazões em HTML',style='Titulo.TLabel').grid(row=0,column=0,columnspan=3,sticky='w')
    ttk.Label(painel,text='Todos os testes são modelo × histórico · Significância fixa: 5%').grid(row=1,column=0,columnspan=3,sticky='w',pady=(5,16))
    config=PASTA_PROJETO/'.ultimas_entradas.json'
    try: anteriores=json.loads(config.read_text(encoding='utf-8'))
    except (OSError,ValueError): anteriores={}
    vars={k:tk.StringVar(value=anteriores.get(k,v)) for k,v in [('modo','Comparação'),('modelo','Novo modelo'),('deck',''),('novo',''),('newave',''),('novo_inicio',''),('novo_fim',''),('newave_inicio',''),('newave_fim',''),('tipo_comparacao','novo_newave'),('deck_referencia',''),('rotulo_novo','Novo modelo'),('rotulo_referencia','NEWAVE')]}
    ttk.Label(painel,text='Geração').grid(row=2,column=0,sticky='w')
    cb=ttk.Combobox(painel,textvariable=vars['modo'],values=['Análise','Comparação'],state='readonly',width=20);cb.grid(row=2,column=1,sticky='w',pady=5)
    modelo=ttk.Combobox(painel,textvariable=vars['modelo'],values=['Novo modelo','NEWAVE'],state='readonly',width=20);modelo.grid(row=2,column=2,sticky='e')
    tipos={'Novo modelo × NEWAVE':'novo_newave','Novo modelo × Novo modelo':'novo_novo'}
    tipo=tk.StringVar(value=next((k for k,v in tipos.items() if v==vars['tipo_comparacao'].get()),next(iter(tipos))))
    ttk.Label(painel,text='Tipo de comparação').grid(row=3,column=0,sticky='w',pady=8)
    comparador=ttk.Combobox(painel,textvariable=tipo,values=list(tipos),state='readonly',width=36);comparador.grid(row=3,column=1,columnspan=2,sticky='w')
    botoes=[];botoes_fontes={};entradas={};etiquetas={};ocupado=False
    def atualizar_periodos():
        try:
            notas=[]
            for chave in ['novo','newave']:
                dupla=vars['modo'].get()=='Comparação' and tipos[tipo.get()]=='novo_novo'
                d=vars['deck_referencia' if dupla and chave=='newave' else 'deck'].get()
                if not d or not Path(vars[chave].get()).is_file():continue
                h=validar_historico(localizar_fontes_deck(d)['historico'])
                limites=[str(pd.Period(h['inicio'],freq='M')),str(pd.Period(h['fim'],freq='M'))]
                a,b,origem=periodo_proposto(vars[chave].get(),limites,'novo' if dupla else chave)
                vars[chave+'_inicio'].set(a);vars[chave+'_fim'].set(b)
                notas.append(f"{vars['rotulo_'+('novo' if chave=='novo' else 'referencia')].get()}: {a} a {b}. {origem}.")
            nota.set('\n'.join(notas) or 'Selecione os decks e Parquets para propor os períodos.')
        except (ValueError,OSError) as e:nota.set(str(e))
    for linha,chave,texto in [(4,'deck','Deck A — novo modelo'),(5,'novo','Parquet A — novo modelo'),(6,'newave','Parquet B — NEWAVE'),(7,'deck_referencia','Deck B — novo modelo')]:
        lab=ttk.Label(painel,text=texto);lab.grid(row=linha,column=0,sticky='w',pady=7,padx=(0,10));etiquetas[chave]=lab
        en=ttk.Entry(painel,textvariable=vars[chave],state='readonly');en.grid(row=linha,column=1,sticky='ew',padx=(0,10));entradas[chave]=en
        def escolher(c=chave):
            base=Path(vars[c].get()).parent if vars[c].get() else PASTA_PROJETO.parent
            v=(filedialog.askdirectory(parent=raiz,title='Raiz do deck: system, scenarios e stages.json',initialdir=base) if c.startswith('deck') else
               filedialog.askopenfilename(parent=raiz,title='Selecionar Parquet',filetypes=[('Parquet','*.parquet')],initialdir=base))
            if v:vars[c].set(v);atualizar_periodos()
        bt=ttk.Button(painel,text='Selecionar…',command=escolher);bt.grid(row=linha,column=2);botoes.append(bt);botoes_fontes[chave]=bt
    for row,key,label in [(8,'rotulo_novo','Nome/versão A'),(9,'rotulo_referencia','Nome/versão B')]:
        ttk.Label(painel,text=label).grid(row=row,column=0,sticky='w',pady=6)
        en=ttk.Entry(painel,textvariable=vars[key]);en.grid(row=row,column=1,columnspan=2,sticky='ew');entradas[key]=en
    ttk.Label(painel,text='Histórico usado na avaliação — início e fim inclusivos (AAAA-MM)',font=('Segoe UI',11,'bold')).grid(row=10,column=0,columnspan=3,sticky='w',pady=(20,8))
    for row,chave in [(11,'novo'),(12,'newave')]:
        lab=ttk.Label(painel,text=ROTULOS[chave]);lab.grid(row=row,column=0,sticky='w');etiquetas[chave+'_hist']=lab
        fr=ttk.Frame(painel);fr.grid(row=row,column=1,columnspan=2,sticky='w',pady=5)
        for k,label in [('inicio','De'),('fim','Até')]:
            ttk.Label(fr,text=label).pack(side='left',padx=(0,8))
            en=ttk.Entry(fr,textvariable=vars[chave+'_'+k],width=13);en.pack(side='left',padx=(0,18));entradas[chave+'_'+k]=en
    nota=tk.StringVar(value='Escolha a pasta e os Parquets. O período NEWAVE será lido dos metadados quando disponível.')
    ttk.Label(painel,textvariable=nota,wraplength=850,justify='left').grid(row=13,column=0,columnspan=3,sticky='w',pady=12)
    recalcular=ttk.Button(painel,text='Recarregar períodos propostos',command=atualizar_periodos);recalcular.grid(row=14,column=0,columnspan=3,sticky='w');botoes.append(recalcular)
    ttk.Label(painel,text='Mesmo horizonte e mesmas usinas em Comparação. O histórico é recortado por modelo.\nSaída: um HTML independente em relatorios. Os arquivos originais são somente lidos.',wraplength=850).grid(row=15,column=0,columnspan=3,sticky='w',pady=(16,12))
    status=tk.StringVar(value='Pronto para conferir e gerar.');ttk.Label(painel,textvariable=status,wraplength=850).grid(row=16,column=0,columnspan=3,sticky='w',pady=8)
    barra=ttk.Progressbar(painel,mode='indeterminate');barra.grid(row=17,column=0,columnspan=3,sticky='ew',pady=8)
    fila=queue.Queue()
    def trabalhar():
        nonlocal ocupado
        if ocupado:return
        chaves=['novo','newave'] if vars['modo'].get()=='Comparação' else ['newave' if vars['modelo'].get()=='NEWAVE' else 'novo']
        if not vars['deck'].get() or any(not vars[k].get() for k in chaves):
            messagebox.showerror('Entradas incompletas','Selecione a pasta e os Parquets do modo escolhido.',parent=raiz);return
        if any(not vars[k+'_inicio'].get() or not vars[k+'_fim'].get() for k in chaves):
            messagebox.showerror('Período histórico','Informe início e fim para cada modelo selecionado.',parent=raiz);return
        args={'tipo_comparacao':tipos[tipo.get()] if vars['modo'].get()=='Comparação' else 'novo_newave',
              'deck_referencia':vars['deck_referencia'].get(),
              'rotulo_novo':vars['rotulo_novo'].get(),'rotulo_referencia':vars['rotulo_referencia'].get(),
              'deck':vars['deck'].get(),**{k:vars[k].get() for k in chaves},'periodos':{k:(vars[k+'_inicio'].get(),vars[k+'_fim'].get()) for k in chaves}}
        snapshot={k:v.get() for k,v in vars.items()};ocupado=True;barra.start(12)
        for b in botoes:b.configure(state='disabled')
        for w in [cb,modelo,comparador,*entradas.values()]:w.configure(state='disabled')
        def worker():
            try:fila.put(('ok',gerar(**args,progresso=lambda s:fila.put(('progresso',s))),snapshot))
            except Exception as e:fila.put(('erro',str(e),None))
        threading.Thread(target=worker,daemon=True).start()
    bt=ttk.Button(painel,text='Gerar relatório HTML',command=trabalhar);bt.grid(row=18,column=0,columnspan=3,sticky='e',pady=12);botoes.append(bt)
    def alternar(event=None):
        comparacao=vars['modo'].get()=='Comparação'
        if event is not None and event.widget==cb and not comparacao and tipos[tipo.get()]=='novo_novo':
            # Uma análise NEWAVE não pode herdar o arquivo/identificação da versão B.
            tipo.set('Novo modelo × NEWAVE')
            vars['newave'].set('');vars['deck_referencia'].set('')
            vars['newave_inicio'].set('');vars['newave_fim'].set('')
            vars['rotulo_referencia'].set('NEWAVE')
        dupla=comparacao and tipos[tipo.get()]=='novo_novo'
        modelo.configure(state='disabled' if comparacao else 'readonly')
        comparador.configure(state='readonly' if comparacao else 'disabled')
        if event is not None and event.widget==comparador:
            vars['newave'].set('');vars['deck_referencia'].set('')
            vars['newave_inicio'].set('');vars['newave_fim'].set('')
            vars['rotulo_novo'].set('Novo modelo A' if dupla else 'Novo modelo')
            vars['rotulo_referencia'].set('Novo modelo B' if dupla else 'NEWAVE')
        vars['tipo_comparacao'].set(tipos[tipo.get()])
        etiquetas['newave'].configure(text='Parquet B — novo modelo' if dupla else 'Parquet B — NEWAVE')
        for k in ['novo','newave']:
            ativo=comparacao or vars['modelo'].get()==ROTULOS[k]
            entradas[k].configure(state='readonly' if ativo else 'disabled')
            botoes_fontes[k].configure(state='normal' if ativo else 'disabled')
            for campo in ['inicio','fim']:entradas[k+'_'+campo].configure(state='normal' if ativo else 'disabled')
            nomekey='rotulo_'+('novo' if k=='novo' else 'referencia')
            entradas[nomekey].configure(state='normal' if ativo else 'disabled')
            etiquetas[k+'_hist'].configure(text='Histórico A' if k=='novo' else 'Histórico B')
        entradas['deck_referencia'].configure(state='readonly' if dupla else 'disabled')
        botoes_fontes['deck_referencia'].configure(state='normal' if dupla else 'disabled')
    cb.bind('<<ComboboxSelected>>',alternar);modelo.bind('<<ComboboxSelected>>',alternar)
    comparador.bind('<<ComboboxSelected>>',alternar);alternar()
    def acompanhar():
        nonlocal ocupado
        try:
            while True:
                e=fila.get_nowait()
                if e[0]=='progresso':status.set(e[1]);continue
                ocupado=False;barra.stop()
                for b in botoes:b.configure(state='normal')
                cb.configure(state='readonly');entradas['deck'].configure(state='readonly');alternar()
                if e[0]=='erro':status.set('Geração interrompida.');messagebox.showerror('Não foi gerado relatório',e[1],parent=raiz)
                else:
                    caminho,_=e[1];config.write_text(json.dumps(e[2],ensure_ascii=False,indent=2),encoding='utf-8')
                    status.set(f'Concluído: {caminho.name}');webbrowser.open(caminho.as_uri())
        except queue.Empty:pass
        raiz.after(150,acompanhar)
    def fechar():
        if ocupado:messagebox.showinfo('Geração em andamento','Aguarde a conclusão antes de fechar.',parent=raiz)
        else:raiz.destroy()
    raiz.protocol('WM_DELETE_WINDOW',fechar);raiz.after(150,acompanhar);raiz.mainloop()

def main():
    p=argparse.ArgumentParser(description='Avaliador de vazões em um único HTML — alfa fixo em 5%.')
    p.add_argument('--tipo-comparacao',choices=['novo_newave','novo_novo'],default='novo_newave')
    p.add_argument('--deck-referencia',help='Deck da fonte B, na comparação de versões do novo modelo')
    p.add_argument('--rotulo-novo',help='Nome/versão A')
    p.add_argument('--rotulo-referencia',help='Nome/versão B')
    for campo in ['deck','novo','newave','saida']:p.add_argument('--'+campo)
    for campo in ['novo','newave']:
        p.add_argument('--'+campo+'-inicio');p.add_argument('--'+campo+'-fim')
    p.add_argument('--sem-abrir',action='store_true')
    a=p.parse_args()
    if not a.deck and not a.novo and not a.newave:janela();return
    if not a.deck:p.error('--deck é obrigatório.')
    periodos={}
    for k in ['novo','newave']:
        ini,fim=getattr(a,k+'_inicio'),getattr(a,k+'_fim')
        if bool(ini)!=bool(fim):p.error(f'Informe --{k}-inicio e --{k}-fim juntos.')
        if ini:periodos[k]=(ini,fim)
    caminho,_=gerar(a.deck,a.novo,a.newave,periodos,a.saida,progresso=lambda s:print(s,flush=True),
                    tipo_comparacao=a.tipo_comparacao,deck_referencia=a.deck_referencia,
                    rotulo_novo=a.rotulo_novo,rotulo_referencia=a.rotulo_referencia)
    if not a.sem_abrir:webbrowser.open(caminho.as_uri())

if __name__=='__main__':main()
