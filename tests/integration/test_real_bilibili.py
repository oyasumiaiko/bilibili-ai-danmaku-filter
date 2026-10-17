# -*- coding: utf-8 -*-
"""Test the ACTUAL userscript against real Bilibili DOM in isolated headless Chrome.
Tampermonkey's GM_xmlhttpRequest is shimmed into a Python urllib broker because
the actual installed extension is not auto-operated in the user's running Chrome.
The real 127.0.0.1 service and EmbeddingGemma2 model are used.
"""
from __future__ import annotations
import atexit,base64,json,os,pathlib,urllib.request,urllib.error,time
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(pathlib.Path(__file__).resolve().parents[2])
SECRET=json.loads((ROOT/"browser_filter"/"state"/"local_auth.json").read_text(encoding="utf8"))["token"]
TEST_BASE=os.environ.get("AI_DANMAKU_TEST_BASE","http://127.0.0.1:39683")
SCRIPT=(ROOT/"browser_filter"/"bilibili_ai_filter.user.js").read_text(encoding="utf8").replace("http://127.0.0.1:39683",TEST_BASE)
assert "__AUTH_TOKEN__" not in SCRIPT and SECRET in SCRIPT, "Must test deployed userscript"
# Save live backend settings so testing never overwrites the user's chosen values.
settings_req=urllib.request.Request(TEST_BASE+'/api/settings',headers={'X-AI-Danmaku-Token':SECRET})
with urllib.request.urlopen(settings_req,timeout=5) as settings_response:
    settings_before_test=json.load(settings_response)['settings']
def restore_original_settings():
    try:
        req=urllib.request.Request(TEST_BASE+'/api/settings',method='POST',
            headers={'X-AI-Danmaku-Token':SECRET,'Content-Type':'application/json'},
            data=json.dumps(settings_before_test).encode('utf8'))
        with urllib.request.urlopen(req,timeout=10) as response:
            restored=json.load(response)
        assert restored==settings_before_test, (restored,settings_before_test)
        print('ORIGINAL_BACKEND_SETTINGS_RESTORED',restored,flush=True)
    except Exception as exc:
        print('CRITICAL: BACKEND_SETTINGS_RESTORE_FAILED',repr(exc),flush=True)
atexit.register(restore_original_settings)

REPORT=ROOT/"browser_filter"/"test_output"
REPORT.mkdir(parents=True,exist_ok=True)
page_url="https://www.bilibili.com/video/BV1BQ4y1y79R/"
def gm_request(source,options):
    url=options["url"]
    method=options.get("method","GET")
    headers=options.get("headers",{})
    data=options.get("data")
    req=urllib.request.Request(url,method=method,headers=headers,data=(data.encode("utf8") if data else None))
    try:
        with urllib.request.urlopen(req,timeout=18) as res:
            raw=res.read()
            if options.get("responseType")=="arraybuffer":
                return {"status":res.status,"type":"arraybuffer","b64":base64.b64encode(raw).decode("ascii")}
            return {"status":res.status,"type":"json","json":json.loads(raw)}
    except urllib.error.HTTPError as e:
        return {"status":e.code,"type":"json","json":json.loads(e.read())}
SHIM=r"""
(() => {
  window.__gmLocalState={enabled:true,preset:'high_recall',disabled:[],preload:false};
  window.GM_getValue=(key,fallback)=>window.__gmLocalState||fallback;
  window.GM_setValue=(key,value)=>{window.__gmLocalState=value;};
  window.__gmMenus={};
  window.GM_registerMenuCommand=(name,callback)=>{window.__gmMenus[name]=callback;};
  window.unsafeWindow=window;
  window.GM_xmlhttpRequest=(o)=>{
    window.gm_bridge({url:o.url,method:o.method||'GET',headers:o.headers||{},
                      data:o.data||null,responseType:o.responseType||'json'})
    .then(data=>{
      if(data.type==='arraybuffer'){
        const binary=atob(data.b64);
        const b=new Uint8Array(binary.length);
        for(let i=0;i<binary.length;i++)b[i]=binary.charCodeAt(i);
        o.onload({status:data.status,response:b.buffer});
      }else o.onload({status:data.status,response:data.json,responseText:JSON.stringify(data.json)});
    }).catch(e=>{console.error('GM_TEST_ERROR',e);if(o.onerror)o.onerror(e);});
    return {abort(){}};
  };
})();
"""
errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch(
        executable_path=__import__("os").environ.get("CHROME_BIN") or None,
        headless=True,args=["--no-sandbox","--autoplay-policy=no-user-gesture-required","--disable-gpu"])
    page=browser.new_page(viewport={"width":1290,"height":820})
    page.on("pageerror",lambda e:errors.append(str(e)))
    page.on("console",lambda m:print("BROWSER_CONSOLE",m.type,m.text[:170],flush=True) if m.type=="error" or "[AI弹幕]" in m.text else None)
    page.expose_binding("gm_bridge",gm_request)
    page.add_init_script(script=SHIM+"\n"+SCRIPT)
    print("BROWSER_OPEN",page_url,flush=True)
    try:page.goto(page_url,wait_until="domcontentloaded",timeout=30000)
    except Exception as e:print("BROWSER_NAV_WARNING",str(e)[:220],flush=True)
    page.wait_for_selector(".bpx-player-row-dm-wrap",timeout=30000)
    try:
        page.wait_for_function("document.documentElement.classList.contains('ai-dmk-active')",timeout=14000)
    except Exception:
        print("BOOT_DIAGNOSTICS",page.evaluate("""() => ({hasScript:!!document.getElementById('ai-dmk-style'),hasToggle:!!document.getElementById('ai-dmk-toggle'),health:document.getElementById('ai-dmk-health')?.textContent,gm:typeof GM_xmlhttpRequest,prefs:window.__gmLocalState,ready:document.readyState,cls:document.documentElement.className})"""),"ERRORS",errors,flush=True)
        raise
    print("FILTER_GATE_ACTIVE",page.evaluate("document.documentElement.classList.contains('ai-dmk-active')"),flush=True)
    assert page.locator("#ai-dmk-toggle").count()==0, "Persistent floating control must not exist"
    assert page.locator("#ai-dmk-panel").count()==0, "Settings panel must be lazy-created"
    page.wait_for_function("typeof window.__gmMenus['AI 弹幕过滤：设置']==='function'",timeout=8000)
    print("NO_PERMANENT_PAGE_CONTROLS_AND_MENU_REGISTERED",flush=True)
    # The subtle diagnostics entry must stay inside the real Bilibili sidebar.
    page.wait_for_selector("#danmukuBox .bui-collapse-header",timeout=12000)
    page.wait_for_selector("#danmukuBox #ai-dmk-diag-entry",timeout=8000)
    before_fold=page.evaluate("document.querySelector('#danmukuBox .bui-collapse-wrap').classList.contains('bui-collapse-wrap-folded')")
    page.locator("#danmukuBox #ai-dmk-diag-entry").click()
    assert page.locator("#danmukuBox #ai-dmk-diag-panel.ai-open").count()==1
    after_fold=page.evaluate("document.querySelector('#danmukuBox .bui-collapse-wrap').classList.contains('bui-collapse-wrap-folded')")
    assert before_fold==after_fold, "Diagnostics click inadvertently toggled native Bilibili list"
    side_geometry=page.evaluate("""() => {
      const box=q=>{const r=document.querySelector(q).getBoundingClientRect();
        return {x:r.x,right:r.right,y:r.y,width:r.width,height:r.height};};
      return {video:box('.bpx-player-container'),sidebar:box('#danmukuBox'),
        entry:box('#ai-dmk-diag-entry'),panel:box('#ai-dmk-diag-panel')};
    }""")
    print("REAL_BILIBILI_SIDEBAR_DIAGNOSTIC_GEOMETRY",side_geometry,flush=True)
    assert side_geometry["panel"]["x"]>=side_geometry["video"]["right"]-5,side_geometry
    assert side_geometry["entry"]["x"]>=side_geometry["sidebar"]["x"],side_geometry
    page.screenshot(path=str(REPORT/"diagnostics_v13_real_bilibili_sidebar.png"),timeout=10000)
    page.locator("#ai-dmk-diag-close").click()
    assert page.locator("#ai-dmk-diag-panel.ai-open").count()==0
    result=page.evaluate("""() => {
       const root=document.querySelector('.bpx-player-row-dm-wrap');
       const cases=[
        ['test-ritual','感谢大体老师，逝者安息'],
        ['test-anime','经费又不够了'],
        ['test-plain','谢谢，我不吃'],
        ['test-normal','这集太有意思了'],
        ['test-front','2020来考古']
       ];
       return cases.map(([id,text])=>{
         const el=document.createElement('div');
         el.id=id;el.className='bili-danmaku-x-dm';
         el.textContent=text;
         root.append(el);
         return {id,initial:getComputedStyle(el).visibility};
       });
    }""")
    print("INITIAL_NODES",result,flush=True)
    assert all(x["initial"]=="visible" for x in result), "New danmaku must be visible immediately"
    page.wait_for_function("""() => [
      ['test-ritual','0'],['test-anime','0'],
      ['test-plain','1'],['test-normal','1'],['test-front','1']
    ].every(([id,status])=>document.getElementById(id)?.dataset.aiDmkOk===status)""",timeout=22000)
    state=page.evaluate("""() => Object.fromEntries(
       ['test-ritual','test-anime','test-plain','test-normal','test-front'].map(id=>{
       const el=document.getElementById(id);
       return [id,{text:el.textContent,result:el.dataset.aiDmkOk,visible:getComputedStyle(el).visibility}];
    }))""")
    print("DOM_DECISIONS",json.dumps(state,ensure_ascii=False),flush=True)
    assert state["test-ritual"]["result"]=="0"
    assert state["test-anime"]["result"]=="0"
    assert state["test-plain"]["result"]=="1"
    assert state["test-normal"]["result"]=="1"
    assert state["test-front"]["result"]=="1"
    assert all(state[k]["visible"]=="hidden" for k in ("test-ritual","test-anime"))
    assert all(state[k]["visible"]=="visible" for k in ("test-plain","test-normal","test-front"))
    # DOM reused node needs reclassification. Bili itself often reuses danmaku DOM.
    page.evaluate("document.querySelector('#test-plain').textContent='前方高能'")
    page.wait_for_function("""() => document.querySelector('#test-plain')?.dataset.aiDmkOk==='0'""",timeout=20000)
    recycled=page.evaluate("""() => {const e=document.querySelector('#test-plain');return {
      text:e.textContent,visibility:getComputedStyle(e).visibility,flag:e.dataset.aiDmkOk
    }}""")
    print("RECYCLED_NODE",recycled,flush=True)
    assert recycled["visibility"]=="hidden"
    # Settings are opened only from the user's explicit Tampermonkey menu action.
    page.evaluate("window.__gmMenus['AI 弹幕过滤：设置']()")
    assert page.locator("#ai-dmk-panel.ai-open").count()==1, "Menu must open settings"
    assert page.locator("#ai-dmk-toggle").count()==0
    # Changing the preset must retrigger active node decisions.
    page.locator("#ai-dmk-preset").select_option("balanced")
    assert page.locator("#ai-dmk-preset").input_value()=="balanced"
    page.wait_for_timeout(750)
    changed=page.evaluate("""() => ({flag:document.querySelector('#test-plain')?.dataset.aiDmkOk,
      preset:document.querySelector('#ai-dmk-preset')?.value,
      gate:document.documentElement.classList.contains('ai-dmk-active')})""")
    print("PRESET_SWITCH",changed,flush=True)
    assert changed["gate"] is True
    # Disable must show all native danmaku again (no lingering direct display:none).
    page.locator("#ai-dmk-enabled").uncheck()
    state_off=page.evaluate("""() => ({active:document.documentElement.classList.contains('ai-dmk-active'),
      vis:getComputedStyle(document.querySelector('#test-ritual')).visibility})""")
    print("DISABLED_FAIL_OPEN",state_off,flush=True)
    assert state_off["active"] is False and state_off["vis"]=="visible"
    # Settings panel remains open in the original test after changing the preset.
    page.locator("#ai-dmk-enabled").check()
    page.wait_for_timeout(200)
    assert page.locator(".ai-tabs button").count()==3
    page.locator("#ai-dmk-all-disable").click()
    assert page.locator("#ai-dmk-categories .ai-line input:checked").count()==0
    page.locator("#ai-dmk-all-enable").click()
    assert page.locator("#ai-dmk-categories .ai-line input:checked").count()==19
    cat_select=page.locator("#ai-dmk-categories .ai-line select").first
    cat_select.select_option("-0.05")
    assert page.evaluate("Object.values(window.__gmLocalState.thresholdOffsets).includes(-0.05)")
    cat_select.select_option("0")

    page.locator("#ai-dmk-preview-text").fill("感谢大体老师，逝者安息")
    page.locator("#ai-dmk-preview-btn").click()
    page.wait_for_function("document.querySelector('#ai-dmk-preview-output')?.textContent.includes('将屏蔽')",timeout=18000)
    print("PREVIEW",page.locator("#ai-dmk-preview-output").inner_text()[:210],flush=True)

    page.locator("#ai-dmk-block-phrases").fill("自定义测试词")
    page.locator("#ai-dmk-save-phrases").click()
    assert page.evaluate("window.__gmLocalState.blockPhrases.includes('自定义测试词')")
    page.evaluate("""() => {
        const e=document.createElement('div');e.id='test-custom';
        e.className='bili-danmaku-x-dm';e.textContent='这条是自定义测试词的测试';document.querySelector('.bpx-player-row-dm-wrap').append(e);
    }""")
    page.wait_for_function("document.querySelector('#test-custom')?.dataset.aiDmkOk==='0'",timeout=20000)
    page.locator("#ai-dmk-allow-phrases").fill("自定义测试词")
    page.locator("#ai-dmk-save-phrases").click()
    page.wait_for_function("document.querySelector('#test-custom')?.dataset.aiDmkOk==='1'",timeout=20000)
    print("CUSTOM_OVERRIDE",page.evaluate("({block:window.__gmLocalState.blockPhrases,allow:window.__gmLocalState.allowPhrases,flag:document.querySelector('#test-custom').dataset.aiDmkOk})"),flush=True)

    page.locator('[data-ai-tab="playback"]').click()
    page.locator("#ai-dmk-lookahead").select_option("30")
    page.locator("#ai-dmk-batch").select_option("8")
    page.locator("#ai-dmk-timeout").select_option("12000")
    page.locator("#ai-dmk-clientcache").select_option("6000")
    page.locator("#ai-dmk-save-playback").click()
    saved=page.evaluate("window.__gmLocalState")
    assert saved["lookahead"]==30 and saved["batchSize"]==8 and saved["requestTimeout"]==12000 and saved["clientCacheSize"]==6000
    print("PLAYBACK_SETTINGS",[(x,saved[x]) for x in ("lookahead","batchSize","requestTimeout","clientCacheSize")],flush=True)

    page.locator('[data-ai-tab="backend"]').click()
    page.wait_for_function("document.querySelector('#ai-dmk-backend-status')?.textContent.includes('PID ')",timeout=10000)
    assert "embeddinggemma" in page.locator("#ai-dmk-backend-paths").inner_text().lower()
    print("BACKEND_STATUS",page.locator("#ai-dmk-backend-status").inner_text()[:220],flush=True)
    page.locator("#ai-dmk-threads").select_option("2")
    page.locator("#ai-dmk-backcache").select_option("8000")
    page.locator("#ai-dmk-earlyblock").uncheck()
    page.locator("#ai-dmk-loglevel").select_option("WARNING")
    page.locator("#ai-dmk-backend-save").click()
    page.wait_for_function("document.querySelector('#ai-dmk-backend-notice')?.textContent.includes('即时生效')",timeout=12000)
    result=page.evaluate("""() => ({
      status:document.querySelector('#ai-dmk-backend-status').textContent,
      threads:document.querySelector('#ai-dmk-threads').value,
      cache:document.querySelector('#ai-dmk-backcache').value,
      early:document.querySelector('#ai-dmk-earlyblock').checked
    })""")
    print("BACKEND_UPDATED",result,flush=True)
    assert result["threads"]=="2" and result["cache"]=="8000" and result["early"] is False
    page.locator("#ai-dmk-threads").select_option("4")
    page.locator("#ai-dmk-backcache").select_option("16000")
    page.locator("#ai-dmk-earlyblock").check()
    page.locator("#ai-dmk-loglevel").select_option("INFO")
    page.locator("#ai-dmk-backend-save").click()
    page.wait_for_function("document.querySelector('#ai-dmk-backend-notice')?.textContent.includes('即时生效')",timeout=12000)
    page.locator("#ai-dmk-backend-clear").click()
    page.wait_for_function("document.querySelector('#ai-dmk-backend-notice')?.textContent.includes('清理')",timeout=12000)
    print("BACKEND_RESTORED_AND_CLEARED",page.locator("#ai-dmk-backend-notice").inner_text(),flush=True)

    page.locator('[data-ai-tab="filter"]').click()
    page.locator("#ai-dmk-enabled").uncheck()
    assert page.evaluate("!document.documentElement.classList.contains('ai-dmk-active')")
    page.locator("#ai-dmk-close").click()
    assert page.locator("#ai-dmk-panel.ai-open").count()==0
    assert page.locator("#ai-dmk-toggle").count()==0

    page.screenshot(path=str(REPORT/"settings_v11_production_smoke.png"),timeout=10000)
    (REPORT/"settings_v11_production_smoke.json").write_text(
        json.dumps({"decisions":state,"recycled":recycled,"changed":changed,
                    "disabled":state_off,"page_errors":errors},ensure_ascii=False,indent=2),encoding="utf8")
    print("PAGE_ERRORS",errors[:8],flush=True)
    assert not errors
    browser.close()
print("BROWSER_SETTINGS_V11_PRODUCTION_TEST_PASS",flush=True)
