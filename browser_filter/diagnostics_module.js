// Bounded diagnostics for actually rendered and prefetched danmaku.
// Injected into the private userscript closure at build time.
const DMAX_SCREEN=2500,DMAX_FORECAST=1800;
const D={
 route:'',cid:0,serial:0,rows:[],nodeRows:new WeakMap(),forecast:new Map(),
 host:null,button:null,panel:null,open:false,scope:'screen',
 status:'all',category:'all',query:'',shown:100,renderTimer:null
};
function diagEnsureVideo(){
 const info=playerInfo();
 // Query parameters such as ?t= only seek within the same video.
 const route=location.pathname;
 const changed=D.route&&(D.route!==route||
   (info.cid>0&&D.cid>0&&D.cid!==info.cid));
 if(changed){
   D.serial=0;D.rows=[];D.nodeRows=new WeakMap();D.forecast.clear();
   D.scope='screen';D.status='all';D.category='all';D.query='';D.shown=100;
   if(D.panel){
     const lookup={'ai-dmk-diag-scope':'screen','ai-dmk-diag-status':'all',
       'ai-dmk-diag-category':'all','ai-dmk-diag-query':''};
     for(const [id,value] of Object.entries(lookup)){
       const el=D.panel.querySelector('#'+id);if(el)el.value=value;
     }
   }
 }
 D.route=route;
 if(changed)D.cid=0;
 if(info.cid>0)D.cid=info.cid;
 if(changed)diagScheduleRender();
 return info;
}
function diagObserveNode(node,text){
 const info=diagEnsureVideo();
 const existing=D.nodeRows.get(node);
 if(existing&&existing.text===text)return existing;
 if(existing&&existing.status==='pending'){
   existing.status='unclassified';existing.source='节点复用前未完成';
 }
 const seconds=info.video&&Number.isFinite(info.video.currentTime)?
   Math.max(0,info.video.currentTime):null;
 const row={id:++D.serial,text,at:Date.now(),videoMs:seconds===null?null:Math.round(seconds*1000),
   status:'pending',source:'',profile:S.prefs.preset,
   categories:[],reason:{},latencyMs:null};
 D.nodeRows.set(node,row);D.rows.push(row);
 if(D.rows.length>DMAX_SCREEN)D.rows.shift();
 diagScheduleRender();return row;
}
function diagApplyDecision(row,decision){
 if(!row)return;
 row.status=decision.blocked?'blocked':'allowed';
 row.profile=S.prefs.preset;
 row.categories=Array.isArray(decision.categories)?decision.categories.slice():[];
 row.reason=decision.reason&&typeof decision.reason==='object'?Object.assign({},decision.reason):{};
 row.source=decision.appliedFromCache?
   (D.forecast.has(row.text)&&D.forecast.get(row.text).status!=='pending'?'提前预判缓存':'结果缓存'):
   (decision.origin==='prefetch'?'提前预判':'实时判断');
 row.latencyMs=Number.isFinite(decision.latencyMs)?decision.latencyMs:null;
 diagScheduleRender();
}
function diagResolvedNode(node,text,decision){
 const row=D.nodeRows.get(node);
 if(row&&row.text===text)diagApplyDecision(row,decision);
}
function diagUnknownNode(node,text,label){
 const row=D.nodeRows.get(node);
 if(row&&row.text===text){
   row.status='unclassified';row.source=label||'未判定';diagScheduleRender();
 }
}
function diagMarkPendingUnavailable(){
 for(const row of D.rows){
   if(row.status==='pending'){row.status='unclassified';row.source='后端不可用';}
 }
 for(const row of D.forecast.values()){
   if(row.status==='pending'){row.status='unclassified';row.source='后端不可用';}
 }
 diagScheduleRender();
}
function diagTrackForecast(text,timeMs){
 diagEnsureVideo();
 let row=D.forecast.get(text);
 if(!row){
   row={id:++D.serial,text,videoMs:Math.round(timeMs),
     positions:[Math.round(timeMs)],status:'pending',source:'提前预判',
     profile:S.prefs.preset,categories:[],reason:{},latencyMs:null};
   D.forecast.set(text,row);
   if(D.forecast.size>DMAX_FORECAST)D.forecast.delete(D.forecast.keys().next().value);
 }else if(!row.positions.includes(Math.round(timeMs))&&row.positions.length<8){
   row.positions.push(Math.round(timeMs));
 }
 const cached=S.cache.get(text);
 if(cached&&row.status==='pending')diagApplyDecision(row,cached);
 diagScheduleRender();
}
function diagResolveForecast(text,decision){
 const row=D.forecast.get(text);
 if(row)diagApplyDecision(row,decision);
}
function diagStyle(){
 if(document.getElementById('ai-dmk-diag-style'))return;
 const st=document.createElement('style');st.id='ai-dmk-diag-style';
 st.textContent=[
  '#danmukuBox.ai-dmk-diag-host{position:relative!important}',
  '#ai-dmk-diag-entry{position:absolute;right:46px;top:50%;transform:translateY(-50%);',
  'font:11px/1.35 system-ui,"Microsoft YaHei",sans-serif;color:#9499a1;',
  'background:transparent;border:0;padding:6px 5px;min-height:26px;',
  'cursor:pointer;white-space:nowrap;z-index:2}',
  '#ai-dmk-diag-entry:hover,#ai-dmk-diag-entry.ai-active{color:#00a1d6}',
  '#ai-dmk-diag-panel{display:none;position:absolute;right:0;top:44px;z-index:1003;',
  'width:100%;max-height:min(680px,calc(100vh - 125px));box-sizing:border-box;',
  'background:#fff;color:#333;border:1px solid #e3e5e7;box-shadow:0 9px 30px #0002;',
  'font:12px/1.45 system-ui,"Microsoft YaHei",sans-serif;overflow:hidden}',
  '#ai-dmk-diag-panel.ai-open{display:flex;flex-direction:column}',
  '#ai-dmk-diag-panel.ai-dmk-diag-fallback{position:fixed!important;right:15px;top:65px;',
  'width:min(350px,calc(100vw - 30px));max-height:min(680px,calc(100vh - 90px))}',
  '#ai-dmk-diag-panel *{box-sizing:border-box}',
  '#ai-dmk-diag-panel button,#ai-dmk-diag-panel select,#ai-dmk-diag-panel input{',
  'font:12px/1.4 system-ui,"Microsoft YaHei",sans-serif}',
  '#ai-dmk-diag-panel button{color:#555;background:#f5f6f7;border:1px solid #e3e5e7;',
  'padding:4px 7px;cursor:pointer;border-radius:4px}',
  '#ai-dmk-diag-panel button:hover{color:#00a1d6;border-color:#99dff2}',
  '#ai-dmk-diag-top{display:flex;align-items:center;justify-content:space-between;',
  'padding:9px 10px 6px;border-bottom:1px solid #f0f0f0}',
  '#ai-dmk-diag-top b{font-weight:600;font-size:13px}',
  '#ai-dmk-diag-controls{padding:8px 10px;display:grid;grid-template-columns:1fr 1fr;gap:6px}',
  '#ai-dmk-diag-controls select,#ai-dmk-diag-controls input{min-width:0;width:100%;',
  'border:1px solid #e3e5e7;background:#fff;color:#333;border-radius:4px;padding:5px}',
  '#ai-dmk-diag-controls #ai-dmk-diag-query{grid-column:span 2}',
  '#ai-dmk-diag-summary{color:#757575;padding:0 10px 7px;font-size:11px}',
  '#ai-dmk-diag-list{overflow-y:auto;flex:1;min-height:70px;max-height:460px;',
  'padding:0 10px;border-top:1px solid #eee;overscroll-behavior:contain}',
  '.ai-dmk-diag-row{border-bottom:1px solid #f1f2f3;padding:8px 0}',
  '.ai-dmk-diag-title{display:flex;justify-content:space-between;gap:8px;',
  'font-size:11px;color:#777}',
  '.ai-dmk-diag-result{font-weight:600}',
  '.ai-dmk-diag-result[data-status=blocked]{color:#bf4545}',
  '.ai-dmk-diag-result[data-status=allowed]{color:#28825b}',
  '.ai-dmk-diag-text{white-space:pre-wrap;overflow-wrap:anywhere;margin:3px 0;',
  'font-size:12px;color:#333}',
  '.ai-dmk-diag-detail{font-size:11px;color:#828282;overflow-wrap:anywhere}',
  '#ai-dmk-diag-actions{display:flex;gap:5px;padding:8px 10px;border-top:1px solid #eee}',
  '#ai-dmk-diag-actions button{flex:1}'
 ].join('');
 (document.head||document.documentElement).appendChild(st);
}
function diagMountSidebar(){
 const host=document.querySelector('#danmukuBox');
 const header=host&&host.querySelector('.bpx-player-collapse .bui-collapse-header');
 if(!host||!header)return;
 if(D.host===host&&D.button?.isConnected&&D.button.parentNode===header)return;
 if(D.button)D.button.remove();
 if(D.panel)D.panel.remove();
 diagStyle();host.classList.add('ai-dmk-diag-host');
 const btn=document.createElement('button');btn.type='button';btn.id='ai-dmk-diag-entry';
 btn.textContent='AI诊断';btn.title='查看当前视频已处理和预判的弹幕';
 for(const name of ['pointerdown','mousedown','mouseup','click','dblclick']){
   btn.addEventListener(name,event=>{
     event.stopPropagation();
     if(name==='click'){event.preventDefault();diagToggle();}
   });
 }
 header.appendChild(btn);
 D.host=host;D.button=btn;D.panel=null;
 if(D.open)diagOpen();
}
function diagCreatePanel(){
 if(D.panel?.isConnected)return D.panel;
 diagStyle();
 const panel=document.createElement('section');panel.id='ai-dmk-diag-panel';
 panel.setAttribute('aria-label','AI弹幕过滤诊断');
 panel.innerHTML=[
   '<div id="ai-dmk-diag-top"><b>弹幕过滤诊断</b>',
   '<button type="button" id="ai-dmk-diag-close" aria-label="关闭诊断">关闭</button></div>',
   '<div id="ai-dmk-diag-controls">',
   '<select id="ai-dmk-diag-scope" aria-label="记录来源">',
   '<option value="screen">实际进入画面</option><option value="forecast">提前预判缓存</option></select>',
   '<select id="ai-dmk-diag-status" aria-label="过滤结果">',
   '<option value="all">全部结果</option><option value="blocked">已屏蔽</option>',
   '<option value="allowed">已保留</option><option value="pending">等待判定</option>',
   '<option value="unclassified">未判定</option></select>',
   '<select id="ai-dmk-diag-category" aria-label="命中类别">',
   '<option value="all">所有命中类别</option></select>',
   '<input id="ai-dmk-diag-query" placeholder="搜索弹幕文字" aria-label="搜索弹幕文字" maxlength="200"/>',
   '</div><div id="ai-dmk-diag-summary"></div>',
   '<div id="ai-dmk-diag-list" role="list"></div>',
   '<div id="ai-dmk-diag-actions"><button id="ai-dmk-diag-more" type="button">显示更多</button>',
   '<button id="ai-dmk-diag-export" type="button">导出 JSON</button>',
   '<button id="ai-dmk-diag-clear" type="button">清空记录</button></div>'
 ].join('');
 (D.host?.isConnected?D.host:document.body).appendChild(panel);
 if(!D.host?.isConnected)panel.classList.add('ai-dmk-diag-fallback');
 const on=(sel,evt,cb)=>panel.querySelector(sel).addEventListener(evt,cb);
 on('#ai-dmk-diag-close','click',diagClose);
 on('#ai-dmk-diag-scope','change',e=>{D.scope=e.target.value;D.shown=100;diagRender();});
 on('#ai-dmk-diag-status','change',e=>{D.status=e.target.value;D.shown=100;diagRender();});
 on('#ai-dmk-diag-category','change',e=>{D.category=e.target.value;D.shown=100;diagRender();});
 on('#ai-dmk-diag-query','input',e=>{D.query=e.target.value.toLocaleLowerCase();D.shown=100;diagRender();});
 on('#ai-dmk-diag-more','click',()=>{D.shown+=100;diagRender();});
 on('#ai-dmk-diag-export','click',diagExport);
 on('#ai-dmk-diag-clear','click',diagClear);
 D.panel=panel;return panel;
}
function diagRefreshCategories(){
 const selector=D.panel?.querySelector('#ai-dmk-diag-category');
 if(!selector)return;
 const current=D.category;
 selector.replaceChildren();selector.add(new Option('所有命中类别','all'));
 for(const [id,info] of Object.entries(S.categories)){
   selector.add(new Option(info.name||id,id));
 }
 selector.value=[...selector.options].some(o=>o.value===current)?current:'all';
}
function diagOpen(){
 diagEnsureVideo();diagMountSidebar();D.open=true;
 const panel=diagCreatePanel();panel.classList.add('ai-open');
 D.button?.classList.add('ai-active');
 panel.querySelector('#ai-dmk-diag-scope').value=D.scope;
 panel.querySelector('#ai-dmk-diag-status').value=D.status;
 panel.querySelector('#ai-dmk-diag-query').value=D.query;
 diagRefreshCategories();diagRender();
}
function diagClose(){
 D.open=false;D.panel?.classList.remove('ai-open');D.button?.classList.remove('ai-active');
}
function diagToggle(){if(D.open)diagClose();else diagOpen();}
function diagClear(){
 D.rows=[];D.nodeRows=new WeakMap();D.forecast.clear();D.serial=0;diagRender();
}
function diagScheduleRender(){
 if(!D.open||D.renderTimer)return;
 D.renderTimer=setTimeout(()=>{D.renderTimer=null;if(D.open)diagRender();},180);
}
function diagTime(ms){
 if(ms===null||!Number.isFinite(ms))return '—';
 const n=Math.floor(ms/1000);
 return String(Math.floor(n/3600)).padStart(2,'0')+':'+
   String(Math.floor(n%3600/60)).padStart(2,'0')+':'+
   String(n%60).padStart(2,'0');
}
function diagStatusName(s){
 return ({blocked:'已屏蔽',allowed:'已保留',pending:'待判定',
   unclassified:'未判定'})[s]||s;
}
function diagReasonText(row){
 const reason=Object.entries(row.reason||{}).map(([key,val])=>{
   const title=S.categories[key]?.name||key;
   const hint={strong_pattern:'规则',semantic_similarity:'语义',
     always_allow:'始终放行',always_block:'始终屏蔽'}[val]||val;
   return title+'（'+hint+'）';
 });
 return reason.length?reason.join('、'):
   (row.categories||[]).map(id=>S.categories[id]?.name||id).join('、');
}
function diagRender(){
 const panel=D.panel;
 if(!D.open||!panel?.isConnected)return;
 const all=D.scope==='forecast'?[...D.forecast.values()]:D.rows;
 const counts={blocked:0,allowed:0,pending:0,unclassified:0};
 for(const row of all){if(counts[row.status]!==undefined)counts[row.status]++;}
 const intro=D.scope==='screen'?'实际进入画面':'预判去重文本（不代表已显示）';
 panel.querySelector('#ai-dmk-diag-summary').textContent=intro+'：'+all.length+
   ' 条 · 屏蔽 '+counts.blocked+' · 保留 '+counts.allowed+
   ' · 等待 '+counts.pending+' · 未判定 '+counts.unclassified+
   ' · 上限 '+(D.scope==='screen'?DMAX_SCREEN:DMAX_FORECAST);
 const subset=all.filter(row=>
   (D.status==='all'||row.status===D.status)&&
   (D.category==='all'||row.categories.includes(D.category))&&
   (!D.query||row.text.toLocaleLowerCase().includes(D.query))
 ).slice().reverse();
 const visible=subset.slice(0,D.shown);
 const list=panel.querySelector('#ai-dmk-diag-list');
 const scroll=list.scrollTop;
 const fragment=document.createDocumentFragment();
 for(const row of visible){
   const wrap=document.createElement('div');wrap.className='ai-dmk-diag-row';
   wrap.setAttribute('role','listitem');wrap.dataset.status=row.status;
   const title=document.createElement('div');title.className='ai-dmk-diag-title';
   const left=document.createElement('span');left.textContent=diagTime(row.videoMs);
   const right=document.createElement('span');right.className='ai-dmk-diag-result';
   right.dataset.status=row.status;right.textContent=diagStatusName(row.status);
   title.append(left,right);
   const txt=document.createElement('div');txt.className='ai-dmk-diag-text';txt.textContent=row.text;
   const note=document.createElement('div');note.className='ai-dmk-diag-detail';
   const detail=diagReasonText(row);
   note.textContent=[row.source,detail,
     row.positions?.length>1?'重复时间点 '+row.positions.length:''
   ].filter(Boolean).join(' · ');
   wrap.append(title,txt,note);fragment.appendChild(wrap);
 }
 if(!visible.length){
   const empty=document.createElement('div');empty.className='ai-dmk-diag-detail';
   empty.style.padding='16px 0';empty.textContent='暂无符合条件的记录';
   fragment.appendChild(empty);
 }
 list.replaceChildren(fragment);list.scrollTop=scroll;
 const more=panel.querySelector('#ai-dmk-diag-more');
 more.disabled=subset.length<=visible.length;
 more.textContent=more.disabled?'已显示全部':'显示更多（剩余 '+(subset.length-visible.length)+'）';
}
function diagExportData(){
 return {version:'1.3.0',video:{route:D.route,cid:D.cid,title:document.title},
   exportedAt:new Date().toISOString(),
   scope:'当前页面观察到的弹幕和附近预判文本；非完整视频弹幕数据库',
   limits:{screen:DMAX_SCREEN,forecast:DMAX_FORECAST},
   screen:D.rows.map(r=>Object.assign({},r)),
   forecast:[...D.forecast.values()].map(r=>Object.assign({},r))};
}
function diagExport(){
 const data=JSON.stringify(diagExportData(),null,2);
 const url=URL.createObjectURL(new Blob([data],{type:'application/json;charset=utf-8'}));
 const anchor=document.createElement('a');anchor.href=url;
 const filePart=(D.route.split('/').filter(Boolean).pop()||'video').replace(/[^a-zA-Z0-9_-]/g,'_');
 anchor.download='bilibili-danmaku-diagnostics-'+filePart+'.json';
 document.body.appendChild(anchor);anchor.click();anchor.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1200);
}
