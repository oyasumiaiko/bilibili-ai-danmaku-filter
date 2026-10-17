// ==UserScript==
// @name         B站 AI 弹幕过滤 · 本地 EmbeddingGemma 2
// @namespace    https://local.ai-danmaku.example/
// @version      1.3.0
// @description  右侧弹幕列表内低调的 AI诊断入口，记录屏幕弹幕与预判结果；不覆盖视频，后台实时过滤。
// @match        https://www.bilibili.com/video/*
// @match        https://www.bilibili.com/bangumi/play/*
// @match        https://www.bilibili.com/list/watchlater*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      api.bilibili.com
// @noframes
// ==/UserScript==

(function(){
  'use strict';
  const BASE='http://127.0.0.1:39683';
  const TOKEN='__AUTH_TOKEN__';
  const PREF_KEY='ai-dmk-local-preferences';
  const COMMENT='.bpx-player-row-dm-wrap .bili-danmaku-x-dm';
  const ROOT='.bpx-player-row-dm-wrap';
  const dflt={
    enabled:true,preset:'high_recall',disabled:[],preload:true,
    lookahead:22,batchSize:32,requestTimeout:16000,clientCacheSize:12000,
    thresholdOffsets:{},blockPhrases:[],allowPhrases:[]
  };
  function boundedInt(value,min,max,otherwise){
    const n=Number(value);
    return Number.isInteger(n)&&n>=min&&n<=max?n:otherwise;
  }
  function parsePhrases(v){
    if(!Array.isArray(v))return [];
    return [...new Set(v.map(x=>typeof x==='string'?x.trim():'')
      .filter(x=>x.length>=1&&x.length<=80))].slice(0,100);
  }
  function parseThresholds(v){
    const ret={};
    if(!v||typeof v!=='object'||Array.isArray(v))return ret;
    for(const [k,x] of Object.entries(v)){
      const n=Number(x);
      if(k.length<60&&Number.isFinite(n)&&Math.abs(n)<=.1&&Math.abs(n)>1e-5)
          ret[k]=Math.round(n*1000)/1000;
    }
    return ret;
  }
  function readPrefs(){
    let x=dflt;
    try{x=GM_getValue(PREF_KEY,dflt)||dflt;}catch(_){}
    return {
      enabled:x.enabled!==false,
      preset:['balanced','high_recall','aggressive','keywords_only'].includes(x.preset)?x.preset:'high_recall',
      disabled:Array.isArray(x.disabled)?x.disabled.filter(y=>typeof y==='string'):[],
      preload:x.preload!==false,
      lookahead:boundedInt(x.lookahead,5,90,22),
      batchSize:boundedInt(x.batchSize,1,64,32),
      requestTimeout:boundedInt(x.requestTimeout,5000,30000,16000),
      clientCacheSize:boundedInt(x.clientCacheSize,500,25000,12000),
      thresholdOffsets:parseThresholds(x.thresholdOffsets),
      blockPhrases:parsePhrases(x.blockPhrases),
      allowPhrases:parsePhrases(x.allowPhrases)
    };
  }
  const S={
    prefs:readPrefs(),ready:false,epoch:0,status:'连接中',
    categories:{},cid:0,route:'',lastTime:-1,video:null,
    root:null,observer:null,seen:new WeakMap(),
    pending:new Map(),liveQueue:new Set(),preloadQueue:new Set(),busy:false,flushTimer:null,
    cache:new Map(),segments:new Map(),fetching:new Set(),
    stats:{seen:0,blocked:0,allowed:0,prefetched:0},
    backendSettings:null,backendRuntime:null,activeTab:'filter',
    panel:null
  };
  function req(url, method, body, responseType, timeout){
    return new Promise(function(resolve,reject){
      GM_xmlhttpRequest({
        url:url,method:method||'GET',timeout:timeout||15000,responseType:responseType||'json',
        headers:Object.assign({},
          url.startsWith(BASE+'/api/')?{'X-AI-Danmaku-Token':TOKEN}:{},
          method==='POST'?{'Content-Type':'application/json'}:{}),
        data:body===undefined?undefined:JSON.stringify(body),
        onload:function(r){
          if(r.status<200||r.status>=300) return reject(new Error('HTTP '+r.status));
          if(responseType==='arraybuffer')return resolve(r.response);
          try{resolve(r.response&&typeof r.response==='object'?r.response:JSON.parse(r.responseText));}
          catch(e){reject(e);}
        },
        onerror:function(){reject(new Error('请求失败'));},
        ontimeout:function(){reject(new Error('请求超时'));}
      });
    });
  }
  function log(message){console.info('[AI弹幕] '+message);}
  function style(){
    if(document.getElementById('ai-dmk-style'))return;
    const el=document.createElement('style');
    el.id='ai-dmk-style';
    el.textContent=[
      'html.ai-dmk-active ',COMMENT,'[data-ai-dmk-ok="0"]{visibility:hidden!important}',
      '#ai-dmk-panel{display:none;position:fixed;right:50%;top:50%;transform:translate(50%,-50%);',
      'z-index:2147483642;width:min(490px,calc(100vw - 24px));max-height:82vh;overflow:auto;padding:14px;',
      'color:#eaf1ff;background:#1a2332f7;border:1px solid #65798f;border-radius:10px;',
      'box-shadow:0 6px 20px #0009;font:13px/1.55 system-ui,"Microsoft YaHei",sans-serif}',
      '#ai-dmk-panel.ai-open{display:block}',
      '#ai-dmk-panel label{display:block;margin:5px 0;cursor:pointer}',
      '#ai-dmk-panel input{accent-color:#8ac0f0}',
      '#ai-dmk-panel select{background:#26364c;color:#eef7ff;border:1px solid #526b87;',
      'padding:3px;border-radius:5px;margin-left:4px}',
      '#ai-dmk-panel button{cursor:pointer;color:#edf5fc;background:#34465e;',
      'border:1px solid #576e86;padding:3px 8px;border-radius:6px}',
      '#ai-dmk-panel details{margin:7px 0;border-top:1px solid #3c4c61;padding-top:7px}',
      '#ai-dmk-panel summary{cursor:pointer}',
      '#ai-dmk-panel .ai-muted{color:#a4b5c9;font-size:11px}',
      '#ai-dmk-panel .ai-cat{font-size:12px}',
      '#ai-dmk-panel .ai-head{display:flex;align-items:center;justify-content:space-between;gap:8px}',
      '#ai-dmk-panel .ai-tabs{display:flex;gap:6px;margin:12px 0 10px}',
      '#ai-dmk-panel .ai-tabs button{flex:1;padding:7px 3px}',
      '#ai-dmk-panel .ai-tabs button[aria-selected=true]{background:#48627f;border-color:#9cc9ff}',
      '#ai-dmk-panel .ai-section{display:none}',
      '#ai-dmk-panel .ai-section.ai-visible{display:block}',
      '#ai-dmk-panel .ai-toolbar{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}',
      '#ai-dmk-panel .ai-box{border:1px solid #3b4f65;padding:10px;margin:10px 0;border-radius:8px}',
      '#ai-dmk-panel .ai-group{border-top:1px solid #364a60;padding:7px 0}',
      '#ai-dmk-panel .ai-group-head{display:flex;justify-content:space-between;align-items:center;gap:5px}',
      '#ai-dmk-panel .ai-group-head b{font-size:12px}',
      '#ai-dmk-panel .ai-line{display:flex;align-items:center;gap:6px;justify-content:space-between;margin:4px 0}',
      '#ai-dmk-panel .ai-line .ai-check{display:flex;align-items:center;gap:5px;flex:1}',
      '#ai-dmk-panel .ai-line select{font-size:11px;max-width:110px}',
      '#ai-dmk-panel .ai-phrase{width:100%;height:67px;box-sizing:border-box;resize:vertical;',
      'background:#26364c;color:#eaf1ff;border:1px solid #597189;border-radius:7px;padding:8px}',
      '#ai-dmk-panel .ai-field{box-sizing:border-box;width:100%;background:#26364c;color:#eaf1ff;',
      'border:1px solid #597189;border-radius:6px;padding:7px}',
      '#ai-dmk-panel .ai-notice{white-space:pre-wrap;word-break:break-word;color:#b6d9fc;font-size:12px}',
      '#ai-dmk-panel .ai-data{white-space:pre-wrap;word-break:break-all;font-size:11px;font-family:Consolas,monospace}',
      '@media(max-width:550px){#ai-dmk-panel{width:calc(100vw - 24px);max-height:78vh}}'
    ].join('');
    (document.head||document.documentElement).appendChild(el);
  }
  function gate(){
    document.documentElement.classList.toggle('ai-dmk-active',!!(S.ready&&S.prefs.enabled));
  }
  const GROUP_NAMES={
    production:'制作画面与经费',
    spoiler:'剧透及观看引导',
    hostile:'争吵、审判与拉踩',
    noise:'无意义刷屏',
    emotion:'悲伤和复杂情绪',
    virtue:'仪式感谢、致敬和道德套话'
  };
  function say(id,text){
    const el=document.getElementById(id);
    if(el)el.textContent=text;
  }
  function openSettings(tab){
    ui();
    const panel=document.getElementById('ai-dmk-panel');
    if(!panel)return;
    panel.classList.add('ai-open');
    showTab(tab||S.activeTab||'filter');
  }
  function showTab(tab){
    const panel=document.getElementById('ai-dmk-panel');
    if(!panel)return;
    S.activeTab=tab;
    for(const section of panel.querySelectorAll('.ai-section')){
      section.classList.toggle('ai-visible',section.dataset.section===tab);
    }
    for(const btn of panel.querySelectorAll('[data-ai-tab]')){
      btn.setAttribute('aria-selected',String(btn.dataset.aiTab===tab));
    }
    if(tab==='filter')renderCategories();
    if(tab==='backend')void refreshBackend();
    refreshUi();
  }
  function ui(){
    if(!document.body||document.getElementById('ai-dmk-panel'))return;
    const panel=document.createElement('div');
    panel.id='ai-dmk-panel';
    panel.innerHTML="<div class=\"ai-head\">\n  <b style=\"font-size:15px\">本地 AI 弹幕过滤 · 设置</b>\n  <button type=\"button\" id=\"ai-dmk-close\">✕</button>\n</div>\n<div class=\"ai-muted\" id=\"ai-dmk-health\">正在连接本机服务…</div>\n<div class=\"ai-muted\" id=\"ai-dmk-stats\"></div>\n<div class=\"ai-tabs\">\n  <button type=\"button\" data-ai-tab=\"filter\" aria-selected=\"true\">过滤规则</button>\n  <button type=\"button\" data-ai-tab=\"playback\" aria-selected=\"false\">播放与缓存</button>\n  <button type=\"button\" data-ai-tab=\"backend\" aria-selected=\"false\">本地后端</button>\n</div>\n<section class=\"ai-section ai-visible\" data-section=\"filter\">\n  <label><input id=\"ai-dmk-enabled\" type=\"checkbox\"> 启用即时语义过滤（等待判断时不隐藏）</label>\n  <label>过滤档位\n    <select id=\"ai-dmk-preset\">\n      <option value=\"balanced\">F1 优先：更少误伤</option>\n      <option value=\"high_recall\">高召回（推荐）</option>\n      <option value=\"aggressive\">激进：更少漏判</option>\n      <option value=\"keywords_only\">仅强规则（跳过模型）</option>\n    </select>\n  </label>\n  <div class=\"ai-box\">\n    <div class=\"ai-head\"><b>19 类独立过滤</b><span class=\"ai-muted\" id=\"ai-dmk-selected\">—</span></div>\n    <div class=\"ai-toolbar\">\n      <button type=\"button\" id=\"ai-dmk-all-enable\">全选类别</button>\n      <button type=\"button\" id=\"ai-dmk-all-disable\">全部关闭</button>\n      <button type=\"button\" id=\"ai-dmk-reset-sensitivity\">恢复灵敏度</button>\n    </div>\n    <p class=\"ai-muted\">每类可单独开关。灵敏度越高，语义匹配越容易屏蔽；已经明确命中关键词强规则的弹幕不受灵敏度调整影响。</p>\n    <div id=\"ai-dmk-categories\"></div>\n  </div>\n  <div class=\"ai-box\">\n    <b>手动黑白名单</b>\n    <p class=\"ai-muted\">每行一个短语，按“包含文本”匹配，不是正则。始终放行优先于始终屏蔽和语义模型。</p>\n    <label>始终屏蔽\n      <textarea id=\"ai-dmk-block-phrases\" class=\"ai-phrase\" placeholder=\"例如：经费警察\"></textarea>\n    </label>\n    <label>始终放行\n      <textarea id=\"ai-dmk-allow-phrases\" class=\"ai-phrase\" placeholder=\"例如：你希望完整保留的固定台词\"></textarea>\n    </label>\n    <div class=\"ai-toolbar\"><button type=\"button\" id=\"ai-dmk-save-phrases\">保存黑白名单</button></div>\n    <div class=\"ai-notice\" id=\"ai-dmk-phrase-result\"></div>\n  </div>\n  <div class=\"ai-box\">\n    <b>测试一条弹幕</b>\n    <input id=\"ai-dmk-preview-text\" class=\"ai-field\" placeholder=\"输入弹幕，查看命中类别与分数\">\n    <div class=\"ai-toolbar\"><button type=\"button\" id=\"ai-dmk-preview-btn\">检查这条弹幕</button></div>\n    <div class=\"ai-notice\" id=\"ai-dmk-preview-output\"></div>\n  </div>\n</section>\n<section class=\"ai-section\" data-section=\"playback\">\n  <div class=\"ai-box\">\n    <b>预判与缓冲</b>\n    <label><input id=\"ai-dmk-preload\" type=\"checkbox\"> 预判当前视频即将出现的弹幕</label>\n    <p class=\"ai-muted\">仅从当前视频的公开6分钟分段接口读取附近的弹幕；拖动进度条会自动重新定位。</p>\n    <label>提前预判的时间\n      <select id=\"ai-dmk-lookahead\">\n        <option value=\"5\">5 秒</option><option value=\"10\">10 秒</option>\n        <option value=\"15\">15 秒</option><option value=\"22\">22 秒（默认）</option>\n        <option value=\"30\">30 秒</option><option value=\"45\">45 秒</option>\n        <option value=\"60\">60 秒</option>\n      </select>\n    </label>\n    <label>单次请求最大弹幕数量\n      <select id=\"ai-dmk-batch\">\n        <option value=\"1\">1</option><option value=\"8\">8</option>\n        <option value=\"16\">16</option><option value=\"32\">32（默认）</option>\n        <option value=\"64\">64</option>\n      </select>\n    </label>\n    <label>模型请求超时\n      <select id=\"ai-dmk-timeout\">\n        <option value=\"5000\">5 秒</option><option value=\"8000\">8 秒</option>\n        <option value=\"12000\">12 秒</option><option value=\"16000\">16 秒（默认）</option>\n        <option value=\"24000\">24 秒</option><option value=\"30000\">30 秒</option>\n      </select>\n    </label>\n    <label>页面结果缓存数量上限\n      <select id=\"ai-dmk-clientcache\">\n        <option value=\"500\">500</option><option value=\"2000\">2,000</option>\n        <option value=\"6000\">6,000</option><option value=\"12000\">12,000（默认）</option>\n        <option value=\"20000\">20,000</option><option value=\"25000\">25,000</option>\n      </select>\n    </label>\n    <div class=\"ai-toolbar\">\n      <button type=\"button\" id=\"ai-dmk-save-playback\">保存播放设置</button>\n      <button type=\"button\" id=\"ai-dmk-clear-client-cache\">清除页面结果缓存</button>\n    </div>\n    <div class=\"ai-notice\" id=\"ai-dmk-playback-notice\"></div>\n    <p class=\"ai-muted\">弹幕立即显示，优先判断正在屏幕上出现的文字；预判结果命中时会在显示前拦截，否则收到屏蔽结果后隐藏。后端离线时不影响原生弹幕。</p>\n  </div>\n</section>\n<section class=\"ai-section\" data-section=\"backend\">\n  <div class=\"ai-box\">\n    <div class=\"ai-head\">\n      <b>本地推理服务</b><button type=\"button\" id=\"ai-dmk-backend-refresh\">刷新</button>\n    </div>\n    <div id=\"ai-dmk-backend-status\" class=\"ai-muted\">正在连接 127.0.0.1:39683…</div>\n  </div>\n  <div class=\"ai-box\">\n    <b>可即时生效的后端参数</b>\n    <label>CPU 计算线程\n      <select id=\"ai-dmk-threads\">\n        <option value=\"1\">1</option><option value=\"2\">2</option>\n        <option value=\"3\">3</option><option value=\"4\">4（推荐）</option>\n        <option value=\"6\">6</option><option value=\"8\">8</option>\n        <option value=\"12\">12</option><option value=\"16\">16</option>\n      </select>\n    </label>\n    <label>后端每组配置的最大缓存条目\n      <select id=\"ai-dmk-backcache\">\n        <option value=\"500\">500</option><option value=\"2000\">2,000</option>\n        <option value=\"8000\">8,000</option><option value=\"16000\">16,000（默认）</option>\n        <option value=\"32000\">32,000</option><option value=\"50000\">50,000</option>\n      </select>\n    </label>\n    <label><input type=\"checkbox\" id=\"ai-dmk-earlyblock\"> 命中强规则时直接拦截，不再跑额外语义模型</label>\n    <label>日志详细程度\n      <select id=\"ai-dmk-loglevel\">\n        <option value=\"WARNING\">WARNING（最少）</option>\n        <option value=\"INFO\">INFO（默认）</option>\n        <option value=\"DEBUG\">DEBUG（排障）</option>\n      </select>\n    </label>\n    <div class=\"ai-toolbar\">\n      <button type=\"button\" id=\"ai-dmk-backend-save\">保存后端参数</button>\n      <button type=\"button\" id=\"ai-dmk-backend-clear\">清空后端缓存</button>\n    </div>\n    <div class=\"ai-notice\" id=\"ai-dmk-backend-notice\"></div>\n  </div>\n  <div class=\"ai-box\">\n    <b>服务信息（只读）</b>\n    <div id=\"ai-dmk-backend-paths\" class=\"ai-muted ai-data\">—</div>\n    <p class=\"ai-muted\">为防止网页误改后失去连接，模型路径和本地端口只显示、不在线修改。Windows任务计划程序负责登录后自动启动后端。</p>\n  </div>\n</section>";
    // Settings UI exists only after the user explicitly opens it from Tampermonkey.
    document.body.append(panel);
    panel.querySelector('#ai-dmk-close').onclick=()=>panel.classList.remove('ai-open');
    panel.querySelectorAll('[data-ai-tab]').forEach(el=>{
      el.addEventListener('click',()=>showTab(el.dataset.aiTab));
    });
    panel.querySelector('#ai-dmk-enabled').onchange=e=>setPrefs({enabled:e.target.checked});
    panel.querySelector('#ai-dmk-preset').onchange=e=>setPrefs({preset:e.target.value});
    panel.querySelector('#ai-dmk-all-enable').onclick=()=>enableAll(true);
    panel.querySelector('#ai-dmk-all-disable').onclick=()=>enableAll(false);
    panel.querySelector('#ai-dmk-reset-sensitivity').onclick=()=>{
      setPrefs({thresholdOffsets:{}});renderCategories();
    };
    panel.querySelector('#ai-dmk-save-phrases').onclick=savePhrases;
    panel.querySelector('#ai-dmk-preview-btn').onclick=()=>void preview();
    panel.querySelector('#ai-dmk-preview-text').addEventListener('keydown',e=>{
      if(e.key==='Enter'){e.preventDefault();void preview();}
    });
    panel.querySelector('#ai-dmk-save-playback').onclick=savePlayback;
    panel.querySelector('#ai-dmk-clear-client-cache').onclick=()=>{
      S.cache.clear();S.epoch++;S.pending.clear();S.liveQueue.clear();S.preloadQueue.clear();
      for(const el of document.querySelectorAll(COMMENT)){
        el.removeAttribute('data-ai-dmk-ok');S.seen.delete(el);
        if(S.ready&&S.prefs.enabled)checkNode(el);
      }
      say('ai-dmk-playback-notice','页面缓存已清理。');
    };
    panel.querySelector('#ai-dmk-backend-refresh').onclick=()=>void refreshBackend();
    panel.querySelector('#ai-dmk-backend-save').onclick=()=>void saveBackend();
    panel.querySelector('#ai-dmk-backend-clear').onclick=()=>void clearBackend();
    S.panel=panel;
    refreshUi();
    syncForm();
  }
  function renderCategories(){
    const container=document.getElementById('ai-dmk-categories');
    if(!container)return;
    container.replaceChildren();
    let selected=0,total=0;
    for(const [group,title] of Object.entries(GROUP_NAMES)){
      const list=Object.entries(S.categories).filter(([,info])=>info.group===group);
      if(!list.length)continue;
      const box=document.createElement('div');box.className='ai-group';
      const header=document.createElement('div');header.className='ai-group-head';
      const head=document.createElement('b');head.textContent=title;
      const actions=document.createElement('div');actions.className='ai-toolbar';
      for(const [mode,label] of [[true,'全开'],[false,'全关']]){
        const button=document.createElement('button');
        button.textContent=label;button.type='button';
        button.onclick=()=>{
          const disabled=new Set(S.prefs.disabled);
          for(const [cat] of list){if(mode)disabled.delete(cat);else disabled.add(cat);}
          setPrefs({disabled:[...disabled]});renderCategories();
        };
        actions.appendChild(button);
      }
      header.append(head,actions);box.appendChild(header);
      for(const [id,info] of list){
        total++;
        const line=document.createElement('div');line.className='ai-line';
        const label=document.createElement('label');label.className='ai-check';
        const chk=document.createElement('input');chk.type='checkbox';
        chk.checked=!S.prefs.disabled.includes(id);
        if(chk.checked)selected++;
        chk.onchange=()=>{
          const disabled=new Set(S.prefs.disabled);
          if(chk.checked)disabled.delete(id);else disabled.add(id);
          setPrefs({disabled:[...disabled]});renderCategories();
        };
        const name=document.createElement('span');name.textContent=info.name||id;
        label.append(chk,name);
        const select=document.createElement('select');
        select.title='负阈值：更容易拦截；正阈值：减少误伤';
        for(const [v,title] of [
          [-.08,'极高召回'],[-.05,'高召回'],[-.03,'偏召回'],
          [0,'默认'],[.03,'偏精确'],[.05,'高精确'],[.08,'极高精确']
        ])select.add(new Option(title,String(v)));
        const offset=Number(S.prefs.thresholdOffsets[id]||0);
        select.value=[...select.options].some(x=>Number(x.value)===offset)?String(offset):'0';
        select.onchange=()=>{
          const offsets=Object.assign({},S.prefs.thresholdOffsets);
          const val=Number(select.value);
          if(val===0)delete offsets[id];else offsets[id]=val;
          setPrefs({thresholdOffsets:offsets});
        };
        line.append(label,select);box.appendChild(line);
      }
      container.appendChild(box);
    }
    say('ai-dmk-selected',selected+'/'+total+' 已启用');
  }
  function enableAll(flag){
    setPrefs({disabled:flag?[]:Object.keys(S.categories)});
    renderCategories();
  }
  function syncForm(){
    const options=[
      ['ai-dmk-lookahead',S.prefs.lookahead],
      ['ai-dmk-batch',S.prefs.batchSize],
      ['ai-dmk-timeout',S.prefs.requestTimeout],
      ['ai-dmk-clientcache',S.prefs.clientCacheSize]
    ];
    for(const [id,val] of options){
      const el=document.getElementById(id);
      if(el)el.value=String(val);
    }
    const b=document.getElementById('ai-dmk-block-phrases');
    const a=document.getElementById('ai-dmk-allow-phrases');
    if(b&&document.activeElement!==b)b.value=S.prefs.blockPhrases.join('\n');
    if(a&&document.activeElement!==a)a.value=S.prefs.allowPhrases.join('\n');
    const p=document.getElementById('ai-dmk-preload');
    if(p)p.checked=S.prefs.preload;
  }
  function refreshUi(){
    say('ai-dmk-health',S.status+(S.prefs.enabled?'':'（已关闭）'));
    say('ai-dmk-stats','当前页面：拦截 '+S.stats.blocked+'、放行 '+S.stats.allowed+
        '、预判 '+S.stats.prefetched+'、待处理 '+S.pending.size);
    const check=document.getElementById('ai-dmk-enabled');
    if(check)check.checked=S.prefs.enabled;
    const p=document.getElementById('ai-dmk-preset');
    if(p)p.value=S.prefs.preset;
    const pre=document.getElementById('ai-dmk-preload');
    if(pre)pre.checked=S.prefs.preload;
  }
  function setPrefs(update){
    const previous=S.prefs;
    const next=Object.assign({},previous,update);
    S.prefs=next;
    try{GM_setValue(PREF_KEY,next);}catch(e){console.warn('[AI弹幕] 偏好设置无法保存',e);}
    const affectsDecision=Object.keys(update).some(k=>
      ['preset','disabled','enabled','thresholdOffsets','blockPhrases','allowPhrases'].includes(k));
    if(affectsDecision){
      if(update.enabled===false)diagMarkPendingUnavailable();
      if(Object.keys(update).some(k=>['preset','disabled','thresholdOffsets',
        'blockPhrases','allowPhrases'].includes(k))){
        D.forecast.clear();diagScheduleRender();
      }
      S.epoch++;S.liveQueue.clear();S.preloadQueue.clear();S.pending.clear();S.cache.clear();
      for(const el of document.querySelectorAll(COMMENT)){
        el.removeAttribute('data-ai-dmk-ok');S.seen.delete(el);
      }
    }
    if(update.preload===false)discardStalePrefetch();
    while(S.cache.size>S.prefs.clientCacheSize)S.cache.delete(S.cache.keys().next().value);
    gate();observe();
    if(affectsDecision&&S.ready&&S.prefs.enabled){
      for(const el of document.querySelectorAll(COMMENT))checkNode(el);
    }
    refreshUi();
    if(S.prefs.preload)prefetch();
  }
  function savePhrases(){
    const lines=id=>parsePhrases(document.getElementById(id).value.split(/\r?\n/));
    const blockPhrases=lines('ai-dmk-block-phrases');
    const allowPhrases=lines('ai-dmk-allow-phrases');
    setPrefs({blockPhrases,allowPhrases});
    say('ai-dmk-phrase-result','已保存 '+blockPhrases.length+' 条始终屏蔽、'+allowPhrases.length+' 条始终放行。');
  }
  function savePlayback(){
    const val=id=>document.getElementById(id);
    const next={
      preload:val('ai-dmk-preload').checked,
      lookahead:boundedInt(val('ai-dmk-lookahead').value,5,90,22),
      batchSize:boundedInt(val('ai-dmk-batch').value,1,64,32),
      requestTimeout:boundedInt(val('ai-dmk-timeout').value,5000,30000,16000),
      clientCacheSize:boundedInt(val('ai-dmk-clientcache').value,500,25000,12000)
    };
    setPrefs(next);say('ai-dmk-playback-notice','播放和浏览器缓存设置已保存。');
  }
  function payloadFor(text){
    return {texts:[text],preset:S.prefs.preset,disabled:S.prefs.disabled,
      threshold_offsets:S.prefs.thresholdOffsets,
      allow_phrases:S.prefs.allowPhrases,block_phrases:S.prefs.blockPhrases};
  }
  async function preview(){
    const input=document.getElementById('ai-dmk-preview-text');
    const text=input?.value.trim();
    if(!text)return say('ai-dmk-preview-output','请输入弹幕。');
    if(text.length>1200)return say('ai-dmk-preview-output','最多支持1200个字符。');
    say('ai-dmk-preview-output','正在判断…');
    try{
      const r=await req(BASE+'/api/preview','POST',payloadFor(text),'json',30000);
      const result=r.results[0];
      let str=result.blocked?'将屏蔽':'将放行';
      str+='\n类别：'+(result.categories.map(k=>S.categories[k]?.name||k).join('、')||'无');
      if(result.reason&&Object.keys(result.reason).length){
        str+='\n触发：'+Object.entries(result.reason).map(([k,v])=>(S.categories[k]?.name||k)+'='+v).join('；');
      }
      if(result.scores&&Object.keys(result.scores).length){
        str+='\n分数：'+Object.entries(result.scores).slice(0,8)
          .map(([k,v])=>(S.categories[k]?.name||k)+' '+v.score+'／'+v.threshold).join('；');
      }
      str+='\n服务耗时 '+r.ms+' 毫秒';
      say('ai-dmk-preview-output',str);
    }catch(e){say('ai-dmk-preview-output','判断失败：'+e.message);}
  }
  async function refreshBackend(){
    try{
      const r=await req(BASE+'/api/settings','GET',undefined,'json',5000);
      S.backendSettings=r.settings;S.backendRuntime=r.runtime;
      const v=r.runtime;
      say('ai-dmk-backend-status',
        '状态：'+v.status+' · PID '+v.pid+' · 运行 '+Math.floor(v.uptime_s/60)+' 分钟'+
        '\n请求 '+(v.stats.requests||0)+'、文本 '+(v.stats.received||0)+
        '、实际模型编码 '+(v.stats.model_encodes||0)+
        '\n缓存 '+v.cache_entries+' 条，共 '+v.active_profiles+' 种配置');
      say('ai-dmk-backend-paths',
        '模型：'+v.model_path+
        '\n监听：'+v.bind_address+':'+v.port+
        '\n日志：'+v.log_path+
        '\n设置文件：'+v.settings_path+
        '\n开机启动：'+v.autostart_task);
      for(const [id,value] of [['ai-dmk-threads',r.settings.cpu_threads],
        ['ai-dmk-backcache',r.settings.cache_size],['ai-dmk-loglevel',r.settings.log_level]]){
        const el=document.getElementById(id);if(el)el.value=String(value);
      }
      const e=document.getElementById('ai-dmk-earlyblock');if(e)e.checked=r.settings.early_block;
    }catch(e){
      say('ai-dmk-backend-status','无法读取服务状态：'+e.message);
    }
  }
  async function saveBackend(){
    say('ai-dmk-backend-notice','正在保存…');
    try{
      const v=id=>document.getElementById(id);
      const data={
        cpu_threads:Number(v('ai-dmk-threads').value),
        cache_size:Number(v('ai-dmk-backcache').value),
        early_block:v('ai-dmk-earlyblock').checked,
        log_level:v('ai-dmk-loglevel').value
      };
      const result=await req(BASE+'/api/settings','POST',data,'json',12000);
      S.backendSettings=result;
      await refreshBackend();
      say('ai-dmk-backend-notice','设置已即时生效。CPU线程数：'+result.cpu_threads+'。');
    }catch(e){say('ai-dmk-backend-notice','保存失败：'+e.message);}
  }
  async function clearBackend(){
    say('ai-dmk-backend-notice','正在清空…');
    try{
      const r=await req(BASE+'/api/cache/clear','POST',{},'json',10000);
      S.cache.clear();
      await refreshBackend();
      say('ai-dmk-backend-notice','已清理 '+r.cleared_entries+' 条本地结果缓存。');
    }catch(e){say('ai-dmk-backend-notice','清理失败：'+e.message);}
  }
  async function probe(){
    if(!S.prefs.enabled){gate();refreshUi();return;}
    try{
      const r=await req(BASE+'/health','GET',undefined,'json',2500);
      if(r.status!=='ready'){
        if(S.ready)diagMarkPendingUnavailable();
        S.ready=false;S.status=r.status==='loading'?'模型加载中；暂时显示原弹幕':'后端未就绪；暂时显示原弹幕';
      }else{
        if(!S.ready){
          S.ready=true;S.categories=r.categories||{};
          S.status='本机模型已连接';
          if(D.open)diagRefreshCategories();
          if(S.activeTab==='filter'&&document.getElementById('ai-dmk-panel')?.classList.contains('ai-open'))renderCategories();
          gate();observe();
          // Reconnect: re-check existing native nodes, including any formerly
          // pending ones. Without this, an offline error could leave them hidden.
          for(const el of document.querySelectorAll(COMMENT)){
            el.removeAttribute('data-ai-dmk-ok');S.seen.delete(el);checkNode(el);
          }
          prefetch();
        }else{
          S.status='本机模型已连接';
        }
      }
    }catch(e){
      if(S.ready)diagMarkPendingUnavailable();
      S.ready=false;S.status='本地后端离线；原弹幕已恢复';
    }
    gate();refreshUi();
  }
  function commentText(node){
    const special=node.querySelector('.bili-danmaku-x-high-text');
    return String(special?special.textContent:node.textContent||'').replace(/\u200b/g,'').trim();
  }
  function reveal(node,text,decision){
    if(!node.isConnected||commentText(node)!==text)return;
    node.dataset.aiDmkOk=decision.blocked?'0':'1';
    diagResolvedNode(node,text,decision);
    if(decision.blocked)S.stats.blocked++;else S.stats.allowed++;
  }
  function queueText(text,el,prefetched){
    if(!S.ready||!S.prefs.enabled||!text||text.length>1200)return;
    if(S.cache.has(text)){
      if(el)reveal(el,text,Object.assign({},S.cache.get(text),{appliedFromCache:true}));
      return;
    }
    let item=S.pending.get(text);
    if(!item){
      item={nodes:new Set(),prefetched:!!prefetched};
      S.pending.set(text,item);
      if(el)S.liveQueue.add(text);
      else S.preloadQueue.add(text);
    }
    if(el){
      item.nodes.add(el);
      // A danmaku previously queued for prefetch becomes urgent on screen.
      if(S.preloadQueue.delete(text))S.liveQueue.add(text);
    }
    schedule();
  }
  function checkNode(node){
    if(!node.isConnected||!S.ready||!S.prefs.enabled)return;
    const text=commentText(node);
    if(!text){node.dataset.aiDmkOk='1';S.seen.set(node,'');return;}
    if(S.seen.get(node)===text&&node.dataset.aiDmkOk!==undefined)return;
    S.seen.set(node,text);
    diagObserveNode(node,text);
    if(text.length>1200){
      node.dataset.aiDmkOk='1';diagUnknownNode(node,text,'超长文本未分类');return;
    }
    // Pending means visible, not blocked. Only a confirmed rejection uses "0".
    node.dataset.aiDmkOk='pending';
    S.stats.seen++;
    queueText(text,node,false);
  }
  function onAdded(node){
    if(node.nodeType!==1)return;
    if(node.matches&&node.matches(COMMENT))checkNode(node);
    if(node.querySelectorAll)
      for(const el of node.querySelectorAll(COMMENT))checkNode(el);
  }
  function observe(){
    const root=document.querySelector(ROOT);
    if(root===S.root)return;
    if(S.observer)S.observer.disconnect();
    S.root=root;
    if(!root)return;
    S.observer=new MutationObserver(function(mutations){
      if(!S.ready||!S.prefs.enabled)return;
      const changed=new Set();
      for(const m of mutations){
        if(m.type==='childList'){
          for(const n of m.addedNodes)onAdded(n);
        }
        let target=m.target;
        while(target&&target!==root){
          if(target.nodeType===1&&target.matches&&target.matches(COMMENT)){
            changed.add(target);break;
          }
          target=target.parentNode;
        }
      }
      for(const node of changed)checkNode(node);
    });
    S.observer.observe(root,{childList:true,characterData:true,subtree:true});
    for(const node of root.querySelectorAll(COMMENT))checkNode(node);
  }
  function schedule(){
    if(S.flushTimer||S.busy||!S.ready||!S.prefs.enabled)return;
    S.flushTimer=setTimeout(function(){S.flushTimer=null;flush();},25);
  }
  async function flush(){
    if(S.busy||(!S.liveQueue.size&&!S.preloadQueue.size)||!S.ready||!S.prefs.enabled)return;
    S.busy=true;
    const epoch=S.epoch;
    // Never let background prefetch batches hold newly visible danmaku in a queue.
    // Keep prefetch batches short to bound an already-running batch's latency.
    const fromLive=S.liveQueue.size>0;
    const queue=fromLive?S.liveQueue:S.preloadQueue;
    const limit=fromLive?S.prefs.batchSize:Math.min(8,S.prefs.batchSize);
    const texts=Array.from(queue).slice(0,limit);
    for(const t of texts)queue.delete(t);
    try{
      const result=await req(BASE+'/api/classify','POST',{
        texts:texts,preset:S.prefs.preset,disabled:S.prefs.disabled,
        threshold_offsets:S.prefs.thresholdOffsets,
        block_phrases:S.prefs.blockPhrases,allow_phrases:S.prefs.allowPhrases
      },'json',S.prefs.requestTimeout);
      if(epoch!==S.epoch)return;
      if(!Array.isArray(result.results)||result.results.length!==texts.length)
        throw Error('服务结果长度异常');
      texts.forEach(function(text,i){
        const raw=result.results[i];
        const decision={blocked:!!raw.blocked,
                        categories:raw.categories||[],reason:raw.reason||{},
                        origin:fromLive?'live':'prefetch',latencyMs:result.ms};
        S.cache.set(text,decision);
        diagResolveForecast(text,decision);
        if(S.cache.size>S.prefs.clientCacheSize)S.cache.delete(S.cache.keys().next().value);
        const item=S.pending.get(text);
        if(item){
          if(item.prefetched)S.stats.prefetched++;
          for(const n of item.nodes)reveal(n,text,decision);
          S.pending.delete(text);
        }
      });
      refreshUi();
    }catch(e){
      if(epoch!==S.epoch)return; // Ignore errors from obsolete preference versions.
      console.warn('[AI弹幕] 本地分类失败；保持原生弹幕显示',e);
      S.liveQueue.clear();S.preloadQueue.clear();S.pending.clear();
      S.ready=false;
      S.status='本地推理超时或报错，暂时恢复原弹幕';
      diagMarkPendingUnavailable();
      gate();refreshUi();
      setTimeout(probe,2600);
    }finally{
      S.busy=false;
      if((S.liveQueue.size||S.preloadQueue.size)&&S.ready&&S.prefs.enabled)schedule();
    }
  }
  // Parse only the currently watched video segment, not Bilibili's entire catalog.
  function varint(bytes,p){
    let n=0,pow=1;
    for(let j=0;j<10;j++){
      if(p.i>=bytes.length)throw Error('bad varint');
      const b=bytes[p.i++];n+=(b&127)*pow;
      if(!(b&128))return n;
      pow*=128;
    }
    throw Error('varint length exceeded');
  }
  function parseFields(bytes,handler){
    const p={i:0};
    while(p.i<bytes.length){
      const tag=varint(bytes,p),field=Math.floor(tag/8),wire=tag%8;
      if(wire===0)handler(field,wire,varint(bytes,p));
      else if(wire===2){
        const len=varint(bytes,p);
        if(len<0||len>bytes.length-p.i)throw Error('length overflow');
        handler(field,wire,bytes.subarray(p.i,p.i+len));
        p.i+=len;
      }else if(wire===1)p.i+=8;
      else if(wire===5)p.i+=4;
      else throw Error('invalid protobuf wire');
      if(p.i>bytes.length)throw Error('field overflow');
    }
  }
  function decodeSegment(arraybuf){
    const b=new Uint8Array(arraybuf),ret=[],decode=new TextDecoder('utf-8');
    if(b.length>15000000)throw Error('danmaku segment too large');
    parseFields(b,function(field,wire,data){
      if(field!==1||wire!==2||ret.length>=40000)return;
      let time=0,txt='';
      parseFields(data,function(f,w,x){
        if(f===2&&w===0)time=x;
        if(f===7&&w===2)txt=decode.decode(x);
      });
      if(txt.trim())ret.push({ms:time,text:txt.trim()});
    });
    ret.sort((a,b)=>a.ms-b.ms);
    return ret;
  }
  function playerInfo(){
    const w=typeof unsafeWindow==='undefined'?window:unsafeWindow;
    const init=w.__INITIAL_STATE__||{};
    const cid=Number(init.cid||init.videoData?.cid||init.epInfo?.cid||0);
    const video=document.querySelector('.bpx-player-container video');
    return {cid:cid,video:video,route:location.pathname+location.search};
  }
  async function getSegment(cid,index){
    if(!cid||index<1||S.fetching.has(index)||S.segments.has(index))return;
    S.fetching.add(index);
    try{
      const address='https://api.bilibili.com/x/v2/dm/web/seg.so?type=1&oid='+cid+'&segment_index='+index;
      const data=await req(address,'GET',undefined,'arraybuffer',15000);
      if(S.cid!==cid)return;
      S.segments.set(index,decodeSegment(data));
      while(S.segments.size>3)S.segments.delete(S.segments.keys().next().value);
      prefetch();
    }catch(e){console.warn('[AI弹幕] 分段预判失败，仍启用实时拦截：',e.message);}
    finally{S.fetching.delete(index);}
  }
  function discardStalePrefetch(){
    // Drop unsent background work when switching videos or seeking.
    // Never discard already visible danmaku or their live requests.
    for(const text of S.preloadQueue){
      const item=S.pending.get(text);
      if(item&&!item.nodes.size)S.pending.delete(text);
    }
    S.preloadQueue.clear();
  }
  function prefetch(){
    if(!S.ready||!S.prefs.enabled||!S.prefs.preload)return;
    const info=playerInfo();
    diagEnsureVideo();
    if(info.cid!==S.cid||info.route!==S.route){
      S.cid=info.cid;S.route=info.route;
      S.segments.clear();S.fetching.clear();
      discardStalePrefetch();
      S.lastTime=-1;
    }
    if(!info.cid||!info.video)return;
    const t=Math.max(0,info.video.currentTime||0);
    if(S.lastTime>=0&&Math.abs(t-S.lastTime)>8)discardStalePrefetch();
    S.lastTime=t;
    const index=Math.floor(t/360)+1;
    if(!S.segments.has(index))void getSegment(info.cid,index);
    if(t%360>337&&!S.segments.has(index+1))void getSegment(info.cid,index+1);
    const earliest=t*1000-600,latest=t*1000+S.prefs.lookahead*1000;
    let sent=0;
    for(const id of [index,index+1]){
      const arr=S.segments.get(id);
      if(!arr)continue;
      let low=0,high=arr.length;
      while(low<high){
        const mid=(low+high)>>1;
        if(arr[mid].ms<earliest)low=mid+1;else high=mid;
      }
      for(let i=low;i<arr.length&&arr[i].ms<=latest;i++){
        const text=arr[i].text;
        diagTrackForecast(text,arr[i].ms);
        if(S.cache.has(text)||S.pending.has(text))continue;
        queueText(text,null,true);
        if(++sent>=Math.max(30,S.prefs.batchSize*4))return;
      }
    }
  }
  /* __DIAGNOSTICS_MODULE__ */
  function boot(){
    if(!document.documentElement)return;
    style();gate();diagMountSidebar();
    if(typeof GM_registerMenuCommand==='function'){
      try{GM_registerMenuCommand('AI 弹幕过滤：设置',()=>openSettings('filter'));}catch(_){}
      try{GM_registerMenuCommand('AI 弹幕过滤：诊断',()=>diagOpen());}catch(_){}
    }
    probe();
    setInterval(function(){
      diagMountSidebar();diagEnsureVideo();observe();
      if(S.ready)prefetch();
      else if(S.prefs.enabled)probe();
    },2700);
    setInterval(function(){if(S.prefs.enabled)probe();},13000);
    setInterval(refreshUi,2100);
  }
  // At document-start Chrome may not have created the <html> element yet.
  // The DOMContentLoaded hook will always install styles before enabling gating.
  if(document.documentElement)style();
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();
