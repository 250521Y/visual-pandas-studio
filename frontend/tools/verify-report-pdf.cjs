// Generates actual report-page PDFs in an isolated browser session.
const {createRequire}=require('node:module');
const path=require('node:path');
const fs=require('node:fs/promises');
const crypto=require('node:crypto');
const localRequire=createRequire(__filename);
let playwright;
try {playwright=localRequire('playwright')} catch {
 console.error('Optional PDF verification requires Playwright. In frontend/, run: npm install --no-save --package-lock=false playwright');
 process.exit(1);
}
const root=path.resolve(__dirname,'../..');
const out=path.join(root,'output/pdf');
const origin=process.env.VPS_FRONTEND_URL||'http://127.0.0.1:5173';
const api=process.env.VPS_API_URL||'http://127.0.0.1:8000';
const session=crypto.randomUUID();
async function request(url,init={}) {
 const response=await fetch(api+'/api'+url,{...init,headers:{'X-Studio-Session':session,...init.headers}});
 if(!response.ok)throw Error(response.status+' '+await response.text());
 return response.json();
}
async function main(){
 await fs.mkdir(out,{recursive:true});
 const columns=['region',...Array.from({length:48},(_,i)=>'measure_'+String(i).padStart(2,'0'))];
 const csv=[columns.join(','),...Array.from({length:120},(_,row)=>[['East','West','North','South'][row%4],...Array.from({length:48},(_,col)=>((row+1)*(col+1)%997)/10)].join(','))].join('\n');
 const form=new FormData();form.append('file',new Blob([csv]),'PDF-pagination.csv');
 let dataset=await request('/upload',{method:'POST',body:form});
 const browser=await playwright.chromium.launch({channel:process.env.VPS_BROWSER_CHANNEL||'chrome',headless:true});
 const result=[];
 try {
  for(const language of ['zh','en']) {
   const title=language==='zh'?'可视化数据分析报告 · 分页验收':'Visual data analysis report - pagination acceptance';
   const notes=Array.from({length:24},(_,i)=> language==='zh'?`分析说明 ${i+1}：本报告基于 120 条真实记录及 48 个数值字段生成。我们比较不同区域的指标分布，并保留图表、统计值与分析过程。跨页内容应完整显示，不裁切文本，也不拆开图表。`:`Analysis note ${i+1}: This report uses 120 actual records and 48 numeric measures. Regional distributions, statistics and charts are calculated from the current snapshot. Text should wrap across pages, table headings should repeat, and each chart should remain on one page.`).join('\n\n');
   const types=['bar','line','scatter','histogram','pie','box','bar','line','scatter','histogram','pie','box'];
   const charts=types.map((type,i)=>({id:crypto.randomUUID(),type,x:['scatter','histogram','box'].includes(type)?'measure_00':'region',y:'measure_01',color:type==='scatter'?'region':'',agg:'sum',bins:15,title:(language==='zh'?'图表 ':'Chart ')+(i+1)+' - '+type,primary:'#67B8B0',secondary:'#D999AC',legend:true}));
   dataset=await request('/datasets/'+dataset.id+'/project',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:dataset.revision,project:{report:{title,notes,hidden:[]},charts}})});
   const context=await browser.newContext({viewport:{width:1440,height:1000},locale:language==='zh'?'zh-CN':'en-US',reducedMotion:'reduce'});
   await context.addInitScript(({session,id,language})=>{localStorage.setItem('vps-session',session);localStorage.setItem('vps-active',id);localStorage.setItem('vps-language',language);},{session,id:dataset.id,language});
   const page=await context.newPage();
   const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=400)errors.push(r.status()+' '+r.url())});
   await page.goto(origin+'/reports');
   await page.waitForSelector('.report-chart canvas',{timeout:60000});
   await page.waitForFunction(()=>document.querySelectorAll('.report-chart canvas').length===12&&document.querySelectorAll('.report-paper tbody tr').length===48&&document.querySelectorAll('.chart-loading').length===0);
   await page.waitForFunction(()=>document.querySelectorAll('.report-chart .plot-print-image svg').length===12);
   // Print media triggers the same chart sizing and beforeprint capture as browser printing.
   await page.emulateMedia({media:'print'});
   await page.waitForFunction(()=>document.fonts.status==='loaded');
   await page.waitForTimeout(600);
   const pdf=path.join(out,'report-pagination-'+language+'.pdf');
   await page.pdf({path:pdf,format:'A4',preferCSSPageSize:true,printBackground:true,displayHeaderFooter:false});
   const layout=await page.evaluate(()=>({width:document.querySelector('.report-paper').getBoundingClientRect().width,charts:[...document.querySelectorAll('.report-chart')].map(e=>({title:e.querySelector('h3').textContent,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})),title:document.querySelector('.print-title').textContent,rows:document.querySelectorAll('.report-paper tbody tr').length,vectorCharts:document.querySelectorAll('.report-chart .plot-print-image svg').length}));
   if(errors.length)throw Error(JSON.stringify(errors));
   result.push({language,pdf,errors,layout});
   await context.close();
  }
 } finally {
  await browser.close();
  await request('/datasets/'+dataset.id,{method:'DELETE'});
 }
 await fs.writeFile(path.join(out,'browser-verification.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify(result.map(x=>({language:x.language,pdf:x.pdf,charts:x.layout.charts.length,rows:x.layout.rows,errors:x.errors}))));
}
main().catch(e=>{console.error(e);process.exitCode=1});
