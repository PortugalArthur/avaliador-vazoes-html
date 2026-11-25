// Executa o mesmo módulo incorporado ao HTML, sem DOM ou bibliotecas externas.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
global.window={};
vm.runInThisContext(fs.readFileSync(path.join(__dirname,'../recursos/correlacao_bacias.js'),'utf8'));
(async()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8')),C=window.CorrelacaoBacias;
 const env={load:async key=>input.dados[key],array:v=>v};
 const a=await C.somar(input.modelo,input.a??1,input.estagios,env);
 const b=await C.somar(input.modelo,input.b??2,input.estagios,env);
 if(!a||!b){process.stdout.write(JSON.stringify({ausente:true}));return;}
 const c=C.comparar(a,b,input.estagios);
 process.stdout.write(JSON.stringify({rows:c.rows,sintetico:C.paresSinteticos(a,b,c,0),historico:C.paresHistoricos(a,b,c,1),inverso:C.comparar(b,a,input.estagios).rows}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
