# -*- coding: utf-8 -*-
"""Test Bilibili 6-minute protobuf danmaku segment lookahead with browser userscript
and real private local backend in a separate isolated Chrome profile."""
import base64,json,os,pathlib,time,urllib.request,urllib.error
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(pathlib.Path(__file__).resolve().parents[2])
js=(ROOT/"browser_filter"/"bilibili_ai_filter.user.js").read_text(encoding="utf8").replace("http://127.0.0.1:39683",os.environ.get("AI_DANMAKU_TEST_BASE","http://127.0.0.1:39683"))
url="https://www.bilibili.com/video/BV1BQ4y1y79R/"
counters={"dm_segment_calls":0,"backend_calls":0}
def bridge(source,opts):
    loc=opts["url"]
    if "seg.so" in loc:counters["dm_segment_calls"]+=1
    if "/api/classify" in loc:counters["backend_calls"]+=1
    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/145.0.0.0 Safari/537.36",
             "Referer":"https://www.bilibili.com/"}
    headers.update(opts.get("headers",{}))
    r=urllib.request.Request(loc,method=opts.get("method","GET"),headers=headers,
        data=(opts["data"].encode("utf8") if opts.get("data") else None))
    try:
        with urllib.request.urlopen(r,timeout=19) as response:
            buf=response.read()
            if opts.get("responseType")=="arraybuffer":
                return {"type":"bin","status":response.status,"bytes64":base64.b64encode(buf).decode()}
            return {"type":"json","status":response.status,"body":json.loads(buf)}
    except urllib.error.HTTPError as err:
        return {"type":"json","status":err.code,"body":json.loads(err.read())}
shim=r"""
window.GM_getValue=(key,fallback)=>({enabled:true,preset:'high_recall',disabled:[],preload:true});
window.GM_setValue=(key,val)=>{};
window.GM_registerMenuCommand=()=>{};
window.unsafeWindow=window;
window.GM_xmlhttpRequest=(req)=>{window.prefetch_bridge({
   url:req.url,method:req.method||'GET',headers:req.headers||{},data:req.data||null,
   responseType:req.responseType||'json'}).then((x)=>{
      if(x.type==='bin'){
         let raw=atob(x.bytes64),bytes=new Uint8Array(raw.length);
         for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
         req.onload({status:x.status,response:bytes.buffer});
      } else req.onload({status:x.status,response:x.body,responseText:JSON.stringify(x.body)});
    }).catch(e=>{console.error('BRIDGE',e);req.onerror?.(e)});
    return {abort(){}};
};
"""
log=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=__import__("os").environ.get("CHROME_BIN") or None,
        headless=True,args=["--disable-gpu","--no-sandbox","--autoplay-policy=no-user-gesture-required"])
    page=browser.new_page(viewport={"width":1280,"height":760})
    page.on("pageerror",lambda e:log.append(str(e)))
    page.on("console",lambda x:log.append(x.text[:220]) if x.type=="error" else None)
    page.expose_binding("prefetch_bridge",bridge)
    page.add_init_script(script=shim+"\n"+js)
    page.goto(url,wait_until="domcontentloaded",timeout=30000)
    page.wait_for_selector(".bpx-player-row-dm-wrap",timeout=25000)
    page.wait_for_function("document.documentElement.classList.contains('ai-dmk-active')",timeout=20000)
    print("INITIAL",counters,flush=True)
    page.wait_for_timeout(7000)
    state=page.evaluate("""() => ({
      visible:document.querySelectorAll('.bpx-player-row-dm-wrap .bili-danmaku-x-dm[data-ai-dmk-ok="1"]').length,
      blocked:document.querySelectorAll('.bpx-player-row-dm-wrap .bili-danmaku-x-dm[data-ai-dmk-ok="0"]').length,
      label:document.querySelector('#ai-dmk-stats')?.textContent,
      movie_time:document.querySelector('.bpx-player-container video')?.currentTime
    })""")
    print("PREFETCH_STATS",counters,"UI",state,"ERRORS",log[:10],flush=True)
    assert counters["dm_segment_calls"]>=1,"public protobuf segment not fetched"
    assert counters["backend_calls"]>=1,"batch classification did not occur"
    # Bilibili itself occasionally reports a COLS telemetry timeout unrelated
    # to the userscript. Report it, but do not treat third-party telemetry as a failure.
    errors_by_filter=[m for m in log if 'BRIDGE' in m or '[AI弹幕]' in m]
    assert not errors_by_filter,errors_by_filter
    out=ROOT/"browser_filter"/"test_output"
    (out/"native_prefetch_smoke.json").write_text(json.dumps({"counters":counters,"state":state,"errors":log},
        ensure_ascii=False,indent=2),encoding="utf8")
    browser.close()
print("PREFETCH_E2E_PASS",flush=True)
