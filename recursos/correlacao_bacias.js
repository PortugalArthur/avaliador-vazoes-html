/* Correlação entre somas de vazões incrementais, com composição fixa por bacia. */
(() => {
'use strict';
const finite=v=>typeof v==='number'&&Number.isFinite(v);

function pearson(pairs){
 const valid=pairs.filter(([x,y])=>finite(x)&&finite(y)),n=valid.length;
 const result={n,r:null,media_a:null,media_b:null,desvio_a:null,desvio_b:null,covariancia:null,motivo:''};
 if(n<2){result.motivo='Menos de dois pares finitos.';return result;}
 const mx=valid.reduce((s,p)=>s+p[0],0)/n,my=valid.reduce((s,p)=>s+p[1],0)/n;
 let vx=0,vy=0,cov=0;
 for(const [x,y] of valid){const dx=x-mx,dy=y-my;vx+=dx*dx;vy+=dy*dy;cov+=dx*dy;}
 const sx=Math.sqrt(vx/n),sy=Math.sqrt(vy/n);
 Object.assign(result,{media_a:mx,media_b:my,desvio_a:sx,desvio_b:sy,covariancia:cov/n});
 if(vx<=0||vy<=0){result.motivo='Soma das vazões de uma das bacias constante entre os pares.';return result;}
 if(sx*Math.sqrt(n)<1e-13*Math.abs(mx)||sy*Math.sqrt(n)<1e-13*Math.abs(my)){
  result.motivo='Totais quase constantes; correlação numericamente instável.';return result;
 }
 const r=cov/Math.sqrt(vx*vy);
 if(!finite(r)||Math.abs(r)>1+1e-10){result.motivo='Coeficiente numericamente inválido.';return result;}
 result.r=Math.max(-1,Math.min(1,r));return result;
}

async function somar(model,basinId,stages,{load,array,isCurrent=()=>true,onProgress=()=>{},yieldControl=async()=>{}}){
 const cadastro=model.cadastro.r.map(r=>Object.fromEntries(model.cadastro.c.map((c,i)=>[c,r[i]])));
 const members=cadastro.filter(r=>r.bacia_id!=null&&String(r.bacia_id)===String(basinId));
 if(!members.length)return null;
 const N=stages.length,scenarios=new Map(),history=new Map(),used=new Set();
 for(let k=0;k<members.length;k++){
  if(!isCurrent())return null;
  const member=members[k],entry=Object.values(model.uhe).find(e=>String(e.id_original)===String(member.hydro_id));
  if(used.has(String(member.hydro_id)))throw Error('Usina repetida na composição da bacia.');
  used.add(String(member.hydro_id));
  if(!entry)throw Error('Usina da composição ausente no relatório: '+member.Usina);
  onProgress(k+1,members.length,members[0].Bacia);
  const d=await load(entry.bloco),flows=array(d.flows),present=d.presentes?array(d.presentes):null,h=array(d.hist_values);
  if(flows.length!==d.scenario_ids.length*N||present&&present.length!==flows.length||h.length!==d.hist_dates.length)
   throw Error('Dimensões incompatíveis nas vazões da bacia.');
  if(new Set(d.scenario_ids.map(String)).size!==d.scenario_ids.length||new Set(d.hist_dates).size!==d.hist_dates.length)
   throw Error('Cenário ou mês histórico repetido na usina '+member.Usina);
  for(let c=0;c<d.scenario_ids.length;c++){
   const id=String(d.scenario_ids[c]);
   if(!scenarios.has(id))scenarios.set(id,{soma:new Float64Array(N),n:new Uint32Array(N)});
   const row=scenarios.get(id);
   for(let i=0;i<N;i++){const j=c*N+i,v=flows[j];if((!present||present[j]>0)&&finite(v)){row.soma[i]+=v;row.n[i]++;}}
  }
  for(let i=0;i<d.hist_dates.length;i++){
   const date=d.hist_dates[i];
   if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(date))throw Error('Mês histórico inválido: '+date);
   if(!history.has(date))history.set(date,{soma:0,n:0});
   if(finite(h[i])){const row=history.get(date);row.soma+=h[i];row.n++;}
  }
  await yieldControl();
 }
 for(const row of scenarios.values())for(let i=0;i<N;i++)if(row.n[i]!==members.length)row.soma[i]=NaN;
 for(const row of history.values())if(row.n!==members.length)row.soma=NaN;
 return {id:String(basinId),nome:members[0].Bacia,members,scenarios,history};
}

function comparar(a,b,stages){
 if(a.id===b.id)throw Error('Selecione duas bacias diferentes.');
 const scenarios=[...new Set([...a.scenarios.keys(),...b.scenarios.keys()])].sort((x,y)=>Number(x)-Number(y));
 const dates=[...new Set([...a.history.keys(),...b.history.keys()])].sort(),historic=new Map();
 for(let month=1;month<=12;month++){
  const selected=dates.filter(d=>Number(d.slice(5,7))===month);
  historic.set(month,{...pearson(selected.map(d=>[a.history.get(d)?.soma,b.history.get(d)?.soma])),esperados:selected.length});
 }
 const rows=stages.map((stage,i)=>{
  const s=pearson(scenarios.map(id=>[a.scenarios.get(id)?.soma[i],b.scenarios.get(id)?.soma[i]]));
  const h=historic.get(Number(stage.mes)),row={'Estágio':stage.i??i,'Mês/ano':stage.rotulo,'Mês civil':Number(stage.mes)};
  for(const [name,r,expected] of [['sintético',s,scenarios.length],['histórico',h,h.esperados]]){
   row['Correlação '+name]=r.r;row['Pares válidos '+name]=r.n;row['Pares esperados '+name]=expected;
   row['Média da bacia A '+name]=r.media_a;row['Média da bacia B '+name]=r.media_b;
   row['Desvio da bacia A '+name]=r.desvio_a;row['Desvio da bacia B '+name]=r.desvio_b;
   row['Covariância '+name]=r.covariancia;row['Motivo '+name]=r.motivo;
  }
  return row;
 });
 return {rows,scenarios,dates};
}

function paresSinteticos(a,b,comparison,i){
 return comparison.scenarios.map(id=>({'Cenário':Number(id),'Vazão da bacia A (m³/s)':a.scenarios.get(id)?.soma[i]??null,
  'Vazão da bacia B (m³/s)':b.scenarios.get(id)?.soma[i]??null,
  'Par válido':finite(a.scenarios.get(id)?.soma[i])&&finite(b.scenarios.get(id)?.soma[i])}));
}
function paresHistoricos(a,b,comparison,month){
 return comparison.dates.filter(d=>Number(d.slice(5,7))===Number(month)).map(date=>({'Mês histórico':date,
  'Vazão da bacia A (m³/s)':a.history.get(date)?.soma??null,'Vazão da bacia B (m³/s)':b.history.get(date)?.soma??null,
  'Par válido':finite(a.history.get(date)?.soma)&&finite(b.history.get(date)?.soma)}));
}
window.CorrelacaoBacias={somar,comparar,paresSinteticos,paresHistoricos};
})();
