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

VERSAO='1.1.0'

def agora():
    return datetime.now(ZoneInfo('America/Sao_Paulo'))

def gerar(deck,novo=None,newave=None,periodos=None,saida=None,progresso=print):
    caminhos,nomes,fontes,limites=inspecionar(deck,novo,newave,periodos,progresso)
    origens=[Path(v) for v in caminhos.values()]+[Path(f.caminho) for f in fontes]
    antes=[assinatura(p) for p in origens]
    comparacao=len(fontes)==2
    modo='comparacao_novo_modelo_newave' if comparacao else 'analise_'+('novo_modelo' if fontes[0].chave=='novo' else 'newave')
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
    raiz=tk.Tk();raiz.title('Avaliador de vazões — relatório HTML');raiz.geometry('940x830');raiz.minsize(800,760)
    estilo=ttk.Style(raiz);estilo.theme_use('clam')
    for n in ['TFrame','TLabel']:estilo.configure(n,background='#f3f6fa',foreground='#102a43')
    estilo.configure('TLabel',font=('Segoe UI',10));estilo.configure('TButton',padding=8,font=('Segoe UI',10))
    estilo.configure('Titulo.TLabel',font=('Segoe UI',20,'bold'),foreground='#154765')
    raiz.configure(background='#f3f6fa');painel=ttk.Frame(raiz,padding=24);painel.pack(fill='both',expand=True)
    painel.columnconfigure(1,weight=1)
    ttk.Label(painel,text='Avaliador de vazões em HTML',style='Titulo.TLabel').grid(row=0,column=0,columnspan=3,sticky='w')
    ttk.Label(painel,text='Todos os testes são modelo × histórico · Significância fixa: 5%').grid(row=1,column=0,columnspan=3,sticky='w',pady=(5,16))
    config=PASTA_PROJETO/'.ultimas_entradas.json'
    try: anteriores=json.loads(config.read_text(encoding='utf-8'))
    except (OSError,ValueError): anteriores={}
    vars={k:tk.StringVar(value=anteriores.get(k,v)) for k,v in [('modo','Comparação'),('modelo','Novo modelo'),('deck',''),('novo',''),('newave',''),('novo_inicio',''),('novo_fim',''),('newave_inicio',''),('newave_fim','')]}
    ttk.Label(painel,text='Geração').grid(row=2,column=0,sticky='w')
    cb=ttk.Combobox(painel,textvariable=vars['modo'],values=['Análise','Comparação'],state='readonly',width=20);cb.grid(row=2,column=1,sticky='w',pady=5)
    modelo=ttk.Combobox(painel,textvariable=vars['modelo'],values=['Novo modelo','NEWAVE'],state='readonly',width=20);modelo.grid(row=2,column=2,sticky='e')
    botoes=[];botoes_fontes={};entradas={};ocupado=False
    def atualizar_periodos():
        try:
            h=validar_historico(localizar_fontes_deck(vars['deck'].get())['historico'])
            limites=[str(pd.Period(h['inicio'],freq='M')),str(pd.Period(h['fim'],freq='M'))]
            notas=[]
            for chave in ['novo','newave']:
                if Path(vars[chave].get()).is_file():
                    a,b,origem=periodo_proposto(vars[chave].get(),limites,chave)
                    vars[chave+'_inicio'].set(a);vars[chave+'_fim'].set(b)
                    notas.append(f'{ROTULOS[chave]}: {origem}.')
            nota.set('Histórico disponível: '+ ' a '.join(limites)+'\n'+'\n'.join(notas))
        except (ValueError,OSError) as e: nota.set(str(e))
    for linha,chave,texto in [(3,'deck','Pasta do deck COBRE'),(4,'novo','Parquet do novo modelo'),(5,'newave','Parquet NEWAVE')]:
        ttk.Label(painel,text=texto).grid(row=linha,column=0,sticky='w',pady=10,padx=(0,10))
        en=ttk.Entry(painel,textvariable=vars[chave],state='readonly');en.grid(row=linha,column=1,sticky='ew',padx=(0,10));entradas[chave]=en
        def escolher(c=chave):
            base=Path(vars[c].get()).parent if vars[c].get() else PASTA_PROJETO.parent
            v=(filedialog.askdirectory(parent=raiz,title='Raiz do deck: system, scenarios e stages.json',initialdir=base) if c=='deck' else
               filedialog.askopenfilename(parent=raiz,title='Selecionar Parquet',filetypes=[('Parquet','*.parquet')],initialdir=base))
            if v:vars[c].set(v);atualizar_periodos()
        bt=ttk.Button(painel,text='Selecionar…',command=escolher);bt.grid(row=linha,column=2);botoes.append(bt);botoes_fontes[chave]=bt
    ttk.Label(painel,text='Histórico usado na avaliação — início e fim inclusivos (AAAA-MM)',font=('Segoe UI',11,'bold')).grid(row=6,column=0,columnspan=3,sticky='w',pady=(20,8))
    for row,chave in [(7,'novo'),(8,'newave')]:
        ttk.Label(painel,text=ROTULOS[chave]).grid(row=row,column=0,sticky='w')
        fr=ttk.Frame(painel);fr.grid(row=row,column=1,columnspan=2,sticky='w',pady=5)
        for k,label in [('inicio','De'),('fim','Até')]:
            ttk.Label(fr,text=label).pack(side='left',padx=(0,8))
            en=ttk.Entry(fr,textvariable=vars[chave+'_'+k],width=13);en.pack(side='left',padx=(0,18));entradas[chave+'_'+k]=en
    nota=tk.StringVar(value='Escolha a pasta e os Parquets. O período NEWAVE será lido dos metadados quando disponível.')
    ttk.Label(painel,textvariable=nota,wraplength=850,justify='left').grid(row=9,column=0,columnspan=3,sticky='w',pady=12)
    recalcular=ttk.Button(painel,text='Recarregar períodos propostos',command=atualizar_periodos);recalcular.grid(row=10,column=0,columnspan=3,sticky='w');botoes.append(recalcular)
    ttk.Label(painel,text='Mesmo horizonte e mesmas usinas em Comparação. O histórico é recortado por modelo.\nSaída: um HTML independente em relatorios. Os arquivos originais são somente lidos.',wraplength=850).grid(row=11,column=0,columnspan=3,sticky='w',pady=(16,12))
    status=tk.StringVar(value='Pronto para conferir e gerar.');ttk.Label(painel,textvariable=status,wraplength=850).grid(row=12,column=0,columnspan=3,sticky='w',pady=8)
    barra=ttk.Progressbar(painel,mode='indeterminate');barra.grid(row=13,column=0,columnspan=3,sticky='ew',pady=8)
    fila=queue.Queue()
    def trabalhar():
        nonlocal ocupado
        if ocupado:return
        chaves=['novo','newave'] if vars['modo'].get()=='Comparação' else ['newave' if vars['modelo'].get()=='NEWAVE' else 'novo']
        if not vars['deck'].get() or any(not vars[k].get() for k in chaves):
            messagebox.showerror('Entradas incompletas','Selecione a pasta e os Parquets do modo escolhido.',parent=raiz);return
        if any(not vars[k+'_inicio'].get() or not vars[k+'_fim'].get() for k in chaves):
            messagebox.showerror('Período histórico','Informe início e fim para cada modelo selecionado.',parent=raiz);return
        args={'deck':vars['deck'].get(),**{k:vars[k].get() for k in chaves},'periodos':{k:(vars[k+'_inicio'].get(),vars[k+'_fim'].get()) for k in chaves}}
        snapshot={k:v.get() for k,v in vars.items()};ocupado=True;barra.start(12)
        for b in botoes:b.configure(state='disabled')
        for w in [cb,modelo,*entradas.values()]:w.configure(state='disabled')
        def worker():
            try:fila.put(('ok',gerar(**args,progresso=lambda s:fila.put(('progresso',s))),snapshot))
            except Exception as e:fila.put(('erro',str(e),None))
        threading.Thread(target=worker,daemon=True).start()
    bt=ttk.Button(painel,text='Gerar relatório HTML',command=trabalhar);bt.grid(row=14,column=0,columnspan=3,sticky='e',pady=12);botoes.append(bt)
    def alternar(*_):
        comparacao=vars['modo'].get()=='Comparação';modelo.configure(state='disabled' if comparacao else 'readonly')
        for k in ['novo','newave']:
            ativo=comparacao or vars['modelo'].get()==ROTULOS[k]
            entradas[k].configure(state='readonly' if ativo else 'disabled')
            botoes_fontes[k].configure(state='normal' if ativo else 'disabled')
            for s in ['inicio','fim']:entradas[k+'_'+s].configure(state='normal' if ativo else 'disabled')
    cb.bind('<<ComboboxSelected>>',alternar);modelo.bind('<<ComboboxSelected>>',alternar);alternar()
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
    caminho,_=gerar(a.deck,a.novo,a.newave,periodos,a.saida,progresso=lambda s:print(s,flush=True))
    if not a.sem_abrir:webbrowser.open(caminho.as_uri())

if __name__=='__main__':main()
