# -*- coding: utf-8 -*-
"""Deterministic UI regression: visible-while-pending, live-priority, cached prefilter and fallback.
Uses isolated headless Chrome and a simulated Bilibili DOM/protobuf segment. Classification
and /health use the installed localhost backend; the userscript is the deployed v1.2 file.
No modifications to the user's Chrome profile, Bilibili account or backend settings.
"""
from __future__ import annotations
import base64, json, os, pathlib, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(pathlib.Path(__file__).resolve().parents[2]/"browser_filter")
SCRIPT = (ROOT/"bilibili_ai_filter.user.js").read_text(encoding="utf8").replace("http://127.0.0.1:39683",os.environ.get("AI_DANMAKU_TEST_BASE","http://127.0.0.1:39683"))
TOKEN = json.loads((ROOT/"state/local_auth.json").read_text(encoding="utf8"))["token"]
assert "// @version      1.3.0" in SCRIPT and TOKEN in SCRIPT

def varint(number: int) -> bytes:
    out=[]
    while number>127:
        out.append((number&127)|128)
        number >>= 7
    out.append(number)
    return bytes(out)

def field(number: int, wire: int, body: bytes) -> bytes:
    return varint(number*8+wire) + (varint(len(body))+body if wire==2 else body)

def dm_segment(texts):
    result=bytearray()
    for i,txt in enumerate(texts):
        dm = field(2,0,varint(1000+(i%15)*100)) + field(7,2,txt.encode("utf-8"))
        result.extend(field(1,2,dm))
    return bytes(result)

PREFETCH = ["经费又不够了"] + ["preload-backlog-%03d" % i for i in range(60)]
SEGMENT_BASE64 = base64.b64encode(dm_segment(PREFETCH)).decode("ascii")

def bridge(source, opts):
    url=opts["url"]
    if "/seg.so" in url:
        return {"status":200,"kind":"bin","base64":SEGMENT_BASE64}
    req=urllib.request.Request(url,method=opts.get("method","GET"),
        headers=opts.get("headers",{}),
        data=opts["data"].encode("utf8") if opts.get("data") else None)
    try:
        with urllib.request.urlopen(req,timeout=28) as resp:
            return {"status":resp.status,"kind":"json","data":json.loads(resp.read())}
    except urllib.error.HTTPError as exc:
        return {"status":exc.code,"kind":"json","data":json.loads(exc.read())}

SHIM = r"""
(() => {
    window.__prefs = {enabled:true,preset:'high_recall',disabled:[],preload:true,lookahead:22};
    window.__calls=[];
    window.__forceClassifyFailure=false;
    window.GM_getValue = (key, fallback) => window.__prefs || fallback;
    window.GM_setValue = (key, val) => { window.__prefs=val; };
    window.GM_registerMenuCommand = () => {};
    window.unsafeWindow=window;
    window.__INITIAL_STATE__={cid:123456789};
    window.GM_xmlhttpRequest = o => {
      const isClassify=o.url.includes('/api/classify');
      const payload=isClassify?JSON.parse(o.data):null;
      if(isClassify)window.__calls.push({texts:payload.texts,at:performance.now()});
      window.__visibility_bridge({url:o.url,method:o.method||'GET',headers:o.headers||{},
          data:o.data||null,responseType:o.responseType||'json'}).then(res=>{
         // Emulate a saturated model. A slow response must NEVER hide unclassified DOM.
         const delay=isClassify?700:0;
         setTimeout(()=>{
           if(isClassify && window.__forceClassifyFailure){
             o.onload({status:503,response:{error:'simulated'},responseText:'{"error":"simulated"}'});
             return;
           }
           if(res.kind==='bin'){
             const binary=atob(res.base64);
             const buf=Uint8Array.from(binary, c=>c.charCodeAt(0));
             o.onload({status:res.status,response:buf.buffer});
           }else o.onload({status:res.status,response:res.data,responseText:JSON.stringify(res.data)});
         },delay);
      }).catch(err => {console.error('BRIDGE_TEST',err);o.onerror?.(err);});
      return {abort(){}};
    };
})();
"""
HTML="""<!doctype html><html><head><meta charset='utf-8'></head><body>
<div class="bpx-player-container">
  <video preload="none" style="width:300px;height:120px"></video>
  <div class="bpx-player-row-dm-wrap"></div>
</div></body></html>"""
ADDRESS="https://www.bilibili.com/video/BV1DETERMINISTIC/"
script_errors=[]
results={}
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=__import__("os").environ.get("CHROME_BIN") or None,
         headless=True,args=["--no-sandbox","--disable-gpu"])
    page=browser.new_page(viewport={"width":1250,"height":720})
    page.route(ADDRESS, lambda route:route.fulfill(status=200,content_type="text/html; charset=UTF-8",body=HTML))
    page.expose_binding("__visibility_bridge",bridge)
    page.add_init_script(script=SHIM+"\n"+SCRIPT)
    page.on("pageerror",lambda e:script_errors.append(str(e)))
    page.goto(ADDRESS,wait_until="domcontentloaded",timeout=15000)
    page.wait_for_function("document.documentElement.classList.contains('ai-dmk-active')",timeout=8000)
    assert page.locator("#ai-dmk-toggle").count()==0
    assert page.locator("#ai-dmk-panel").count()==0
    page.wait_for_function("window.__calls.length>0",timeout=8000)
    first=page.evaluate("window.__calls[0].texts")
    assert len(first)<=8 and first[0]=="经费又不够了",first
    print("FIRST_PREFETCH_BATCH",len(first),first[:3],flush=True)

    # Live comment appears during the first prefetch batch, before the backend response.
    early=page.evaluate("""() => {
       const node=document.createElement('div');
       node.id='urgent';node.className='bili-danmaku-x-dm';
       node.textContent='感谢大体老师，逝者安息';
       document.querySelector('.bpx-player-row-dm-wrap').append(node);
       return {visible:getComputedStyle(node).visibility,flag:node.dataset.aiDmkOk||null};
    }""")
    assert early["visible"]=="visible",early
    page.wait_for_function("document.querySelector('#urgent')?.dataset.aiDmkOk==='pending'",timeout=1800)
    page.wait_for_timeout(200)
    still=page.evaluate("""() => ({
      flag:document.querySelector('#urgent').dataset.aiDmkOk,
      visible:getComputedStyle(document.querySelector('#urgent')).visibility
    })""")
    assert still=={"flag":"pending","visible":"visible"},still
    print("VISIBLE_WHILE_MODEL_IS_SLOW",early,still,flush=True)

    # Next batch after any in-flight prefetch must prioritize the visible urgent comment.
    page.wait_for_function("window.__calls.length>=2",timeout=15000)
    second=page.evaluate("window.__calls[1].texts")
    assert "感谢大体老师，逝者安息" in second,second
    assert len(second)<=32,second
    print("LIVE_PRIORITY_CONFIRMED",second[:4],flush=True)

    # Prefetched blocked text should be hidden as soon as added to DOM (cached decision).
    precached=page.evaluate("""() => {
       let node=document.createElement('div');
       node.id='precached';node.className='bili-danmaku-x-dm';
       node.textContent='经费又不够了';
       document.querySelector('.bpx-player-row-dm-wrap').append(node);
       return getComputedStyle(node).visibility;
    }""")
    page.wait_for_function("""() => document.querySelector('#precached')?.dataset.aiDmkOk==='0' &&
       getComputedStyle(document.querySelector('#precached')).visibility==='hidden'""",timeout=1200)
    assert precached=="visible",precached
    print("PREFETCHED_BLOCK_APPLIED",flush=True)
    page.wait_for_function("""() => document.querySelector('#urgent')?.dataset.aiDmkOk==='0' &&
       getComputedStyle(document.querySelector('#urgent')).visibility==='hidden'""",timeout=10000)

    # Bilibili recycles its nodes. Previously blocked content must not remain hidden
    # while the new text is awaiting classification.
    page.evaluate("document.querySelector('#urgent').textContent='这集太有意思了'")
    page.wait_for_function("""() => {
       const el=document.querySelector('#urgent');
       return el.dataset.aiDmkOk!=='0' && getComputedStyle(el).visibility==='visible';
    }""",timeout=1300)
    page.wait_for_function("document.querySelector('#urgent')?.dataset.aiDmkOk==='1'",timeout=10000)
    print("RECYCLED_NODE_REVEALED",flush=True)

    # On a backend error, ordinary content must stay visible. The real backend stays running.
    page.wait_for_timeout(5000) # Drain bounded background queue without changing service.
    page.evaluate("window.__forceClassifyFailure=true")
    injected=page.evaluate("""() => {
      const el=document.createElement('div');el.className='bili-danmaku-x-dm';
      el.id='forced-error';el.textContent='经费不足了，特效太差';
      document.querySelector('.bpx-player-row-dm-wrap').append(el);
      return getComputedStyle(el).visibility;
    }""")
    assert injected=="visible"
    page.wait_for_function("document.querySelector('#forced-error')?.dataset.aiDmkOk==='pending'",timeout=1500)
    page.wait_for_function("!document.documentElement.classList.contains('ai-dmk-active')",timeout=11000)
    failed=page.evaluate("""() => ({
      visible:getComputedStyle(document.querySelector('#forced-error')).visibility,
      filtering_active:document.documentElement.classList.contains('ai-dmk-active'),
      floating_button:!!document.getElementById('ai-dmk-toggle'),
      settings_panel:!!document.getElementById('ai-dmk-panel')
    })""")
    assert failed["filtering_active"] is False
    assert failed["floating_button"] is False and failed["settings_panel"] is False
    assert failed["visible"]=="visible",failed
    print("BACKEND_ERROR_FAIL_OPEN",failed,flush=True)

    results={"first_prefetch_batch":first,"second_live_priority_batch":second,
       "pending_visible":still,"cached_block":"hidden","recycled_allow":"visible",
       "backend_error":failed,"classify_calls":page.evaluate("window.__calls.length"),
       "page_errors":script_errors}
    assert not script_errors,script_errors
    browser.close()

out=ROOT/"test_output"/"realtime_visible_v12_smoke.json"
out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
print("REALTIME_V12_FULL_REGRESSION_PASS",flush=True)
