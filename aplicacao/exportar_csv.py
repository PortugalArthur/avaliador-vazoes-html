"""Consulta e exportação de linhas originais dos Parquets, sem contas estatísticas."""
from __future__ import annotations

from dataclasses import dataclass,field
from datetime import date,datetime
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import queue
import tempfile
import threading

from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({'duckdb':'duckdb>=1.0','pyarrow':'pyarrow>=14','xlsxwriter':'XlsxWriter>=3.2'})
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import xlsxwriter


MESES=['Todos','Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
MAX_LINHAS_EXCEL=1048576
FORMATO_DECIMAL_EXCEL='0.'+'#'*30
FORMATO_CIENTIFICO_EXCEL='0.'+'#'*16+'E+00'


def identificador(nome):return '"'+nome.replace('"','""')+'"'


def assinatura(p):
    s=Path(p).stat();return s.st_size,s.st_mtime_ns


@dataclass
class Fonte:
    caminho: Path
    tipo: str
    modelo: str
    colunas: tuple
    linhas: int
    usinas: tuple
    estagios: tuple=()
    cenarios: tuple=()
    periodos: tuple=()
    nomes: dict=field(default_factory=dict)
    datas: dict=field(default_factory=dict)
    assinatura: tuple=()


@dataclass
class Filtros:
    usinas: list | None=None
    estagio_inicio: int | None=None
    estagio_fim: int | None=None
    cenario_inicio: int | None=None
    cenario_fim: int | None=None
    periodo_inicio: str | None=None
    periodo_fim: str | None=None
    mes: int | None=None
    colunas: list | None=None
    incluir_cadastro: bool=False


def inspecionar(caminho,deck=None,*,apenas_historico=False):
    p=Path(caminho).resolve()
    if not p.is_file() or p.suffix.lower()!='.parquet':raise ValueError('Selecione um arquivo .parquet existente.')
    antes=assinatura(p);arq=pq.ParquetFile(p);schema=arq.schema_arrow;cols=tuple(schema.names)
    historico={'hydro_id','start_date','end_date','value_m3s'}.issubset(cols)
    if apenas_historico and not historico:
        raise ValueError('Selecione o histórico inflow_history.parquet, com hydro_id, start_date, end_date e value_m3s.')
    if not historico and not {'hydro_id','stage_id','scenario_id','incremental_inflow_m3s'}.issubset(cols):
        raise ValueError('O arquivo não contém as colunas de cenários nem as do histórico de vazões.')
    for c in ['hydro_id']+([] if historico else ['stage_id','scenario_id']):
        if not pa.types.is_integer(schema.field(c).type):raise ValueError(f'{c} deve ser inteiro.')
    meta=schema.metadata or {};modelo=meta.get(b'source_model',b'COBRE').decode('utf-8')
    nomes={};datas={}
    try:
        for u in json.loads(meta.get(b'hydro_mapping',b'[]')):nomes[int(u['hydro_id'])]=u['nome_usina_cadastro']
        for e in json.loads(meta.get(b'stage_mapping',b'[]')):
            datas[int(e['stage_id'])]=(str(e['start_date']),str(e['end_date']))
    except (ValueError,TypeError,KeyError,UnicodeError) as e:raise ValueError('Metadados de nomes/datas inválidos.') from e
    if deck and (not nomes or (not historico and not datas)):
        pasta=Path(deck)
        try:
            h=json.loads((pasta/'system/hydros.json').read_text(encoding='utf-8-sig'))['hydros']
            if not nomes:nomes={int(u['id']):u['name'] for u in h}
            if not historico and not datas:
                es=json.loads((pasta/'stages.json').read_text(encoding='utf-8-sig'))['stages']
                datas={int(e['id']):(e['start_date'],e['end_date']) for e in es}
        except (OSError,ValueError,KeyError,TypeError) as e:
            raise ValueError('Deck inválido: confira system/hydros.json e stages.json na pasta selecionada.') from e
    for a,b in datas.values():date.fromisoformat(a);date.fromisoformat(b)
    with duckdb.connect() as con:
        con.execute('SET threads=4')
        usinas=tuple(r[0] for r in con.execute('SELECT DISTINCT hydro_id FROM read_parquet(?) ORDER BY hydro_id',[str(p)]).fetchall())
        if historico:
            periodos=tuple(r[0] for r in con.execute("SELECT DISTINCT strftime(CAST(start_date AS DATE),'%Y-%m') FROM read_parquet(?) ORDER BY 1",[str(p)]).fetchall())
            estagios=cenarios=()
        else:
            estagios=tuple(r[0] for r in con.execute('SELECT DISTINCT stage_id FROM read_parquet(?) ORDER BY stage_id',[str(p)]).fetchall())
            cenarios=tuple(r[0] for r in con.execute('SELECT DISTINCT scenario_id FROM read_parquet(?) ORDER BY scenario_id',[str(p)]).fetchall())
            periodos=()
    if None in usinas or None in estagios or None in cenarios or None in periodos:
        raise ValueError('Há identificadores ou datas nulos; confira a origem antes de filtrar.')
    if nomes and set(usinas)-set(nomes):raise ValueError('Há IDs de usinas sem correspondência no cadastro selecionado.')
    if datas and set(estagios)-set(datas):raise ValueError('Há estágios sem correspondência no calendário selecionado.')
    if datas:estagios=tuple(sorted(estagios,key=lambda s:datas[s][0]))
    if assinatura(p)!=antes:raise ValueError('O Parquet mudou durante a leitura. Carregue novamente.')
    return Fonte(p,'historico' if historico else 'cenarios',modelo,cols,arq.metadata.num_rows,
                 usinas,estagios,cenarios,periodos,nomes,datas,antes)


def intervalo(valores,inicio,fim,nome):
    if not valores:raise ValueError(f'Não há {nome} disponíveis.')
    a=valores[0] if inicio is None else inicio;b=valores[-1] if fim is None else fim
    if a not in valores or b not in valores:raise ValueError(f'Limite de {nome} não encontrado no arquivo.')
    ia,ib=valores.index(a),valores.index(b)
    if ia>ib:raise ValueError(f'Intervalo de {nome} invertido.')
    return valores[ia:ib+1]


def preparar_consulta(fonte,filtros):
    if assinatura(fonte.caminho)!=fonte.assinatura:raise ValueError('O arquivo mudou desde que foi carregado. Carregue novamente.')
    colunas=list(fonte.colunas) if filtros.colunas is None else list(filtros.colunas)
    if not colunas or len(set(colunas))!=len(colunas) or set(colunas)-set(fonte.colunas):
        raise ValueError('Selecione ao menos uma coluna válida, sem repetições.')
    if filtros.mes is not None and (isinstance(filtros.mes,bool) or filtros.mes not in range(1,13)):
        raise ValueError('Mês deve ser de 1 a 12.')
    usinas=list(fonte.usinas) if filtros.usinas is None else list(filtros.usinas)
    if not usinas or set(usinas)-set(fonte.usinas):raise ValueError('Selecione ao menos uma usina presente no arquivo.')
    cond=['hydro_id IN ('+','.join('?' for _ in usinas)+')'];params=[str(fonte.caminho),*usinas]
    if fonte.tipo=='cenarios':
        etapas=intervalo(fonte.estagios,filtros.estagio_inicio,filtros.estagio_fim,'estágios')
        if filtros.mes:
            if not fonte.datas:raise ValueError('Para filtrar por mês, carregue o deck com o calendário.')
            etapas=tuple(s for s in etapas if date.fromisoformat(fonte.datas[s][0]).month==filtros.mes)
        cond.append('stage_id IN ('+','.join('?' for _ in etapas)+')' if etapas else 'FALSE');params.extend(etapas)
        cs=intervalo(fonte.cenarios,filtros.cenario_inicio,filtros.cenario_fim,'cenários')
        cond.append('scenario_id BETWEEN ? AND ?');params.extend([cs[0],cs[-1]])
        ordem='hydro_id, CASE stage_id '+''.join(f'WHEN {int(s)} THEN {i} ' for i,s in enumerate(fonte.estagios))+'END, scenario_id'
        if 'node_id' in fonte.colunas:ordem+=', node_id'
    else:
        ps=intervalo(fonte.periodos,filtros.periodo_inicio,filtros.periodo_fim,'períodos')
        ano,mes=map(int,ps[-1].split('-'));fim=date(ano+(mes==12),mes%12+1,1)
        cond+=['CAST(start_date AS DATE)>=?','CAST(start_date AS DATE)<?'];params.extend([date.fromisoformat(ps[0]+'-01'),fim])
        if filtros.mes:cond.append('EXTRACT(MONTH FROM CAST(start_date AS DATE))=?');params.append(filtros.mes)
        ordem='hydro_id, start_date, end_date'
    extras=[]
    if filtros.incluir_cadastro:
        if not fonte.nomes and not fonte.datas:raise ValueError('Não há cadastro disponível. Carregue o deck ou desmarque os dados de cadastro.')
        if fonte.nomes:extras.append('nome_usina')
        if fonte.tipo=='cenarios' and fonte.datas:extras+=['inicio_estagio','fim_estagio']
        if set(extras)&set(colunas):raise ValueError('As colunas de cadastro já existem na seleção de colunas originais.')
    # IDs auxiliares servem apenas para localizar cadastro, mesmo se não forem exportados.
    leitura=colunas+[c for c in ['hydro_id','stage_id'] if c in fonte.colunas and c not in colunas]
    base=' FROM read_parquet(?) WHERE '+' AND '.join(cond)
    sql='SELECT '+','.join(identificador(c) for c in leitura)+base+' ORDER BY '+ordem
    return sql,params,'SELECT COUNT(*)'+base,leitura,colunas+extras


def linhas_saida(rows,leitura,colunas,fonte):
    for row in rows:
        d=dict(zip(leitura,row))
        if 'nome_usina' not in leitura:d['nome_usina']=fonte.nomes.get(d.get('hydro_id'))
        inicio,fim=fonte.datas.get(d.get('stage_id'),(None,None))
        d.setdefault('inicio_estagio',inicio);d.setdefault('fim_estagio',fim)
        yield [d.get(c) for c in colunas]


def formatar_valor(valor):
    if valor is None:return ''
    if isinstance(valor,bool):return 'true' if valor else 'false'
    if isinstance(valor,float):
        if math.isnan(valor):return 'NaN'
        if math.isinf(valor):return 'Infinity' if valor>0 else '-Infinity'
        return repr(valor).replace('.',',')
    if isinstance(valor,Decimal):return str(valor).replace('.',',')
    if isinstance(valor,(date,datetime)):return valor.isoformat()
    if isinstance(valor,(dict,list)):return json.dumps(valor,ensure_ascii=False)
    return str(valor)


def previa(fonte,filtros,limite=30):
    sql,params,count,leitura,colunas=preparar_consulta(fonte,filtros)
    with duckdb.connect() as con:
        total=con.execute(count,params).fetchall()[0][0]
        rows=con.execute(sql+' LIMIT ?',params+[int(limite)]).fetchall()
    return total,colunas,list(linhas_saida(rows,leitura,colunas,fonte))


def exportar(fonte,filtros,destino,sobrescrever=False,progresso=lambda _:None):
    """Exporta exclusivamente XLSX, com números nativos e sem arredondar vazões.

    A precisão numérica é limitada pelo Excel, não por casas decimais impostas
    na consulta. O formato permite até 30 casas na apresentação, sem milhares.
    """
    dest=Path(destino).resolve()
    if dest.suffix.lower()!='.xlsx' or dest==fonte.caminho:raise ValueError('Escolha um arquivo .xlsx diferente do Parquet de origem.')
    if dest.exists() and not sobrescrever:raise ValueError('O Excel já existe. Escolha outro nome.')
    if not dest.parent.is_dir():raise ValueError('A pasta de destino não existe.')
    sql,params,_,leitura,colunas=preparar_consulta(fonte,filtros)
    if len(colunas)>16384:raise ValueError('A seleção excede o limite de colunas do Excel. Reduza as colunas selecionadas.')
    tmp=None;total=0
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent,suffix='.tmp',delete=False) as f:tmp=Path(f.name)
        with xlsxwriter.Workbook(str(tmp),{'constant_memory':True,'strings_to_urls':False}) as livro:
            cab=livro.add_format({'bold':True,'font_color':'#FFFFFF','bg_color':'#154765'})
            inteiro=livro.add_format({'num_format':'0'})
            decimal=livro.add_format({'num_format':FORMATO_DECIMAL_EXCEL})
            cientifico=livro.add_format({'num_format':FORMATO_CIENTIFICO_EXCEL})
            folha=None;linha=1;numero_folha=0
            def finalizar():
                if folha is not None:folha.autofilter(0,0,linha-1,len(colunas)-1)
            def nova_folha():
                nonlocal folha,linha,numero_folha
                finalizar();numero_folha+=1;linha=1
                folha=livro.add_worksheet(f'Dados {numero_folha}')
                folha.freeze_panes(1,0)
                for j,c in enumerate(colunas):
                    folha.write_string(0,j,c,cab)
                    folha.set_column(j,j,min(42,max(26,len(c)+2)),decimal)
            nova_folha()
            with duckdb.connect() as con:
                con.execute('SET threads=4');con.execute(sql,params)
                while rows:=con.fetchmany(10000):
                    for row in linhas_saida(rows,leitura,colunas,fonte):
                        if linha>=MAX_LINHAS_EXCEL:nova_folha()
                        for j,v in enumerate(row):
                            if v is None:continue
                            if isinstance(v,bool):folha.write_boolean(linha,j,v)
                            elif isinstance(v,int):
                                # Excel só garante 15 algarismos. IDs maiores
                                # permanecem como texto para não perder dígitos.
                                if abs(v)>=10**15:folha.write_string(linha,j,str(v))
                                else:folha.write_number(linha,j,v,inteiro)
                            elif isinstance(v,(float,Decimal)) and math.isfinite(v):
                                if isinstance(v,Decimal) and len(''.join(map(str,v.as_tuple().digits)).rstrip('0'))>15:
                                    folha.write_string(linha,j,formatar_valor(v))
                                else:
                                    formato=cientifico if v and (abs(v)<1e-14 or abs(v)>=1e15) else decimal
                                    folha.write_number(linha,j,v,formato)
                            else:folha.write_string(linha,j,formatar_valor(v))
                        linha+=1;total+=1
                    progresso(f'{total} linhas exportadas…')
            finalizar()
        if assinatura(fonte.caminho)!=fonte.assinatura:raise ValueError('O Parquet mudou durante a exportação. O Excel não foi publicado.')
        if dest.exists() and not sobrescrever:raise ValueError('Já existe um Excel nesse destino. Escolha outro nome.')
        os.replace(tmp,dest);tmp=None
        return total,dest
    finally:
        if tmp and tmp.exists():tmp.unlink()


# Mantém o nome já utilizado por integrações; a única saída aceita é XLSX.
exportar_excel=exportar


def janela(apenas_historico=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    titulo='Exportar histórico de vazões' if apenas_historico else 'Exportar Parquet de vazões'
    raiz=tk.Tk();raiz.title(titulo);raiz.geometry('1040x850');raiz.minsize(850,700)
    estilo=ttk.Style(raiz);estilo.theme_use('clam');estilo.configure('TButton',padding=6)
    estilo.configure('Titulo.TLabel',font=('Segoe UI',18,'bold'),foreground='#154765')
    painel=ttk.Frame(raiz,padding=18);painel.pack(fill='both',expand=True);painel.columnconfigure(1,weight=1);painel.rowconfigure(4,weight=1)
    ttk.Label(painel,text='Exportar histórico — observações originais' if apenas_historico else 'Exportar linhas originais para Excel',style='Titulo.TLabel').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,8))
    arquivo=tk.StringVar();deck=tk.StringVar();estado=tk.StringVar(value='Selecione o inflow_history.parquet do deck real.' if apenas_historico else 'Selecione o Parquet do novo modelo, NEWAVE ou histórico.')
    info=None;ocupado=False;fila=queue.Queue();botoes=[]
    for row,var,label in [(1,arquivo,'Histórico Parquet' if apenas_historico else 'Parquet'),(2,deck,'Deck para nomes — opcional' if apenas_historico else 'Deck COBRE — opcional')]:
        ttk.Label(painel,text=label).grid(row=row,column=0,sticky='w',padx=(0,8),pady=4)
        ttk.Entry(painel,textvariable=var,state='readonly').grid(row=row,column=1,sticky='ew',padx=(0,8))
        def selecionar(v=var):
            nonlocal info
            path=(filedialog.askopenfilename(parent=raiz,title='Selecionar inflow_history.parquet' if apenas_historico else 'Selecionar Parquet',filetypes=[('Parquet','*.parquet')]) if v is arquivo else filedialog.askdirectory(parent=raiz,title='Deck para os nomes e o calendário'))
            if path:
                v.set(path);info=None
                carregar()
        bt=ttk.Button(painel,text='Selecionar…',command=selecionar);bt.grid(row=row,column=2);botoes.append(bt)
    nota=('Cada mês/ano permanece em uma linha. Selecione o deck para buscar usinas pelo nome; sem deck, use o hydro_id.' if apenas_historico else
          'NEWAVE: nomes/datas vêm dos metadados. COBRE: o deck permite filtrar por nome e mês. Sem deck, use os IDs.')
    ttk.Label(painel,text=nota).grid(row=3,column=0,columnspan=3,sticky='w',pady=8)
    area=ttk.Frame(painel);area.grid(row=4,column=0,columnspan=3,sticky='nsew');area.columnconfigure(0,weight=1);area.columnconfigure(1,weight=1);area.rowconfigure(1,weight=1)
    search=tk.StringVar();ttk.Label(area,text='Usinas — buscar por nome ou ID; Ctrl/clique seleciona várias').grid(row=0,column=0,sticky='w')
    ttk.Label(area,text='Colunas para exportar').grid(row=0,column=1,sticky='w',padx=12)
    left=ttk.Frame(area);left.grid(row=1,column=0,sticky='nsew');left.columnconfigure(0,weight=1);left.rowconfigure(1,weight=1)
    ttk.Entry(left,textvariable=search).grid(row=0,column=0,columnspan=2,sticky='ew')
    plants=tk.Listbox(left,selectmode='extended',exportselection=False,height=6);plants.grid(row=1,column=0,sticky='nsew')
    sb=ttk.Scrollbar(left,orient='vertical',command=plants.yview);sb.grid(row=1,column=1,sticky='ns');plants.configure(yscrollcommand=sb.set)
    right=ttk.Frame(area);right.grid(row=1,column=1,sticky='nsew',padx=(12,0));right.columnconfigure(0,weight=1);right.rowconfigure(0,weight=1)
    columns=tk.Listbox(right,selectmode='extended',exportselection=False,height=7);columns.grid(row=0,column=0,sticky='nsew')
    sc=ttk.Scrollbar(right,orient='vertical',command=columns.yview);sc.grid(row=0,column=1,sticky='ns');columns.configure(yscrollcommand=sc.set)
    shown=[]
    def listar(*_):
        plants.delete(0,'end');shown.clear()
        if not info:return
        q=search.get().strip().casefold()
        for u in info.usinas:
            label=f'{u} — {info.nomes[u]}' if u in info.nomes else str(u)
            if not q or q in label.casefold():shown.append(u);plants.insert('end',label)
        plants.select_set(0,'end')
    search.trace_add('write',listar)
    def essenciais():
        if not info:return
        wanted={'hydro_id','stage_id','scenario_id','incremental_inflow_m3s','start_date','end_date','value_m3s'}
        columns.selection_clear(0,'end')
        for i,c in enumerate(info.colunas):
            if c in wanted:columns.select_set(i)
    bar=ttk.Frame(painel);bar.grid(row=5,column=0,columnspan=3,sticky='ew',pady=5)
    for label,cmd in [('Todas as usinas exibidas',lambda:plants.select_set(0,'end')),('Todas as colunas',lambda:columns.select_set(0,'end')),('Somente identificação e vazões',essenciais)]:
        bt=ttk.Button(bar,text=label,command=cmd);bt.pack(side='left',padx=(0,8));botoes.append(bt)
    filtros=ttk.Frame(painel);filtros.grid(row=6,column=0,columnspan=3,sticky='ew',pady=6)
    inicio=ttk.Combobox(filtros,state='readonly',width=28);fim=ttk.Combobox(filtros,state='readonly',width=28)
    ci=ttk.Combobox(filtros,state='readonly',width=14);cf=ttk.Combobox(filtros,state='readonly',width=14)
    mes=ttk.Combobox(filtros,state='readonly',values=MESES,width=15);mes.current(0)
    linhas_filtros=[(0,'Período histórico — de / até' if apenas_historico else 'Estágios / período — de / até',inicio,fim)]
    if not apenas_historico:linhas_filtros.append((1,'Cenários — de / até',ci,cf))
    for row,label,a,b in linhas_filtros:
        ttk.Label(filtros,text=label).grid(row=row,column=0,sticky='w',pady=4,padx=(0,12));a.grid(row=row,column=1,sticky='w',padx=(0,12));b.grid(row=row,column=2,sticky='w')
    ttk.Label(filtros,text='Mês do ano').grid(row=2,column=0,sticky='w',pady=4);mes.grid(row=2,column=1,sticky='w')
    cadastro=tk.BooleanVar(value=False)
    ttk.Checkbutton(filtros,text='Acrescentar nome da usina' if apenas_historico else 'Acrescentar nome da usina e datas disponíveis do cadastro',variable=cadastro).grid(row=3,column=0,columnspan=3,sticky='w',pady=4)
    ttk.Label(painel,textvariable=estado,wraplength=980).grid(row=7,column=0,columnspan=3,sticky='w',pady=6)
    preview=ttk.Treeview(painel,show='headings',height=5);preview.grid(row=8,column=0,columnspan=3,sticky='ew')
    sx=ttk.Scrollbar(painel,orient='horizontal',command=preview.xview);sx.grid(row=9,column=0,columnspan=3,sticky='ew');preview.configure(xscrollcommand=sx.set)
    ttk.Label(painel,wraplength=980,text='Saída: Excel (.xlsx), sem separador de milhar e sem arredondamento adicional. A precisão numérica do Excel é de aproximadamente 15 algarismos significativos.').grid(row=10,column=0,columnspan=3,sticky='w',pady=7)
    ações=ttk.Frame(painel);ações.grid(row=11,column=0,columnspan=3,sticky='e')
    def iniciar(func,kind):
        nonlocal ocupado
        if ocupado:return
        ocupado=True
        for b in botoes:b.configure(state='disabled')
        estado.set('Lendo…' if kind=='load' else 'Processando filtros…')
        def worker():
            try:fila.put((kind,func()))
            except Exception as e:fila.put(('erro',str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def carregar():
        if not arquivo.get():return
        p,d=arquivo.get(),deck.get();iniciar(lambda:inspecionar(p,d or None,apenas_historico=apenas_historico),'load')
    def filtros_atuais():
        if not info:raise ValueError('Carregue um Parquet primeiro.')
        f=Filtros(usinas=[shown[i] for i in plants.curselection()],colunas=[info.colunas[i] for i in columns.curselection()],
                  mes=mes.current() or None,incluir_cadastro=cadastro.get())
        if info.tipo=='cenarios':
            f.estagio_inicio=info.estagios[inicio.current()];f.estagio_fim=info.estagios[fim.current()]
            f.cenario_inicio=info.cenarios[ci.current()];f.cenario_fim=info.cenarios[cf.current()]
        else:f.periodo_inicio=info.periodos[inicio.current()];f.periodo_fim=info.periodos[fim.current()]
        return f
    def executar(exportando=False):
        try:
            f=filtros_atuais();preparar_consulta(info,f)
            if exportando:
                nome=info.caminho.stem+'_filtrado_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.xlsx'
                path=filedialog.asksaveasfilename(parent=raiz,title='Salvar Excel filtrado',initialdir=info.caminho.parent,initialfile=nome,defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')])
                fonte=info
                if path:iniciar(lambda:exportar(fonte,f,path,sobrescrever=True,progresso=lambda s:fila.put(('progresso',s))),'export')
            else:iniciar(lambda:previa(info,f),'preview')
        except (ValueError,IndexError) as e:messagebox.showerror('Confira os filtros',str(e),parent=raiz)
    for label,cmd in [('Atualizar prévia e contar linhas',lambda:executar(False)),('Exportar Excel (.xlsx)…',lambda:executar(True))]:
        bt=ttk.Button(ações,text=label,command=cmd);bt.pack(side='left',padx=5);botoes.append(bt)
    def acompanhar():
        nonlocal ocupado,info
        try:
            while True:
                kind,v=fila.get_nowait()
                if kind=='progresso':estado.set(v);continue
                ocupado=False
                for b in botoes:b.configure(state='normal')
                if kind=='erro':estado.set('Operação interrompida.');messagebox.showerror('Não foi concluído',v,parent=raiz)
                elif kind=='load':
                    info=v;search.set('');listar();columns.delete(0,'end')
                    for c in info.colunas:columns.insert('end',c)
                    columns.select_set(0,'end');cadastro.set(False);mes.current(0)
                    labels=[f'{info.datas[s][0][:7]} — estágio {s}' if s in info.datas else str(s) for s in info.estagios] if info.tipo=='cenarios' else list(info.periodos)
                    for widget in [inicio,fim]:widget.configure(values=labels,state='readonly')
                    if labels:inicio.current(0);fim.current(len(labels)-1)
                    for widget in [ci,cf]:widget.configure(values=list(info.cenarios),state='readonly' if info.cenarios else 'disabled')
                    if info.cenarios:ci.current(0);cf.current(len(info.cenarios)-1)
                    mes.configure(state='readonly' if info.tipo=='historico' or info.datas else 'disabled')
                    estado.set(f'{"Histórico" if info.tipo=="historico" else info.modelo}: {info.linhas} linhas; {len(info.usinas)} usinas. Selecione os filtros e atualize a prévia.')
                    preview.delete(*preview.get_children())
                elif kind=='preview':
                    n,cs,rows=v;preview.delete(*preview.get_children());preview.configure(columns=cs)
                    for c in cs:preview.heading(c,text=c);preview.column(c,width=155,minwidth=85,stretch=False)
                    for r in rows:preview.insert('', 'end',values=[formatar_valor(x) for x in r])
                    estado.set(f'{n} linhas no filtro. Prévia: primeiras {len(rows)} linhas; a exportação incluirá todas as {n}.')
                elif kind=='export':
                    n,path=v;estado.set(f'Concluído: {n} linhas → {path}');messagebox.showinfo('Arquivo exportado',f'{n} linhas exportadas.\n\n{path}',parent=raiz)
        except queue.Empty:pass
        raiz.after(120,acompanhar)
    def fechar():
        if ocupado:messagebox.showinfo('Operação em andamento','Aguarde a conclusão.',parent=raiz)
        else:raiz.destroy()
    raiz.protocol('WM_DELETE_WINDOW',fechar);raiz.after(120,acompanhar);raiz.mainloop()


if __name__=='__main__':janela()
