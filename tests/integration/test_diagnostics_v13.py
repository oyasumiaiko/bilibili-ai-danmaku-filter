# -*- coding: utf-8 -*-
"""Bilibili-like sidebar + real local model tests, in an isolated Chrome process.
Tests on-screen filtering, prediction separation, sidebar behavior, search/export and SPA reset.
This neither touches the user's running Chrome nor restarts the existing Python backend.
"""
import base64,json,os,pathlib,urllib.request,urllib.error
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(pathlib.Path(__file__).resolve().parents[2]/"browser_filter")
SCRIPT=(ROOT/"bilibili_ai_filter.user.js").read_text(encoding="utf8").replace("http://127.0.0.1:39683",os.environ.get("AI_DANMAKU_TEST_BASE","http://127.0.0.1:39683"))
TOKEN=json.loads((ROOT/"state/local_auth.json").read_text(encoding="utf8"))["token"]
assert "// @version      1.3.0" in SCRIPT and TOKEN in SCRIPT
OUTPUT=ROOT/"test_output";OUTPUT.mkdir(exist_ok=True)
def varint(v):
    out=[]
    while v>=128:
        out.append((v&127)|128);v>>=7
    return bytes(out+[v])
def field(idx,wire,value):
    return varint(idx*8+wire)+(varint(len(value))+value if wire==2 else value)
def seg(items):
    return b''.join(field(1,2,field(2,0,varint(ms))+field(7,2,s.encode('utf8')))
        for ms,s in items)
SEG=base64.b64encode(seg([
    (1500,"经费又不够了"),(3000,"感谢大体老师，逝者安息"),
    (5000,"谢谢，我不吃"),(9000,"这是预判专用弹幕"),
    (18000,"前方高能")])).decode("ascii")
def gm_broker(source,req):
    if "/seg.so" in req["url"]:
        return {"type":"bin","status":200,"base64":SEG}
    url=req["url"];data=req.get("data")
    r=urllib.request.Request(url,method=req.get("method","GET"),
       headers=req.get("headers",{}),data=data.encode("utf8") if data else None)
    try:
        with urllib.request.urlopen(r,timeout=24) as response:
            return {"type":"json","status":response.status,"body":json.load(response)}
    except urllib.error.HTTPError as ex:
        return {"type":"json","status":ex.code,"body":json.loads(ex.read())}
SHIM=r"""
(() => {
  window.__gmMenus={};
  window.__prefs={enabled:true,preset:'high_recall',disabled:[],preload:true,
                  batchSize:8,lookahead:22,requestTimeout:16000};
  window.GM_getValue=(k,v)=>window.__prefs;
  window.GM_setValue=(k,v)=>{window.__prefs=v;};
  window.GM_registerMenuCommand=(name,callback)=>window.__gmMenus[name]=callback;
  window.unsafeWindow=window;
  window.__INITIAL_STATE__={cid:314159265};
  window.GM_xmlhttpRequest=(o)=>{
    window.gm_broker({url:o.url,method:o.method||'GET',headers:o.headers||{},
      data:o.data||null,responseType:o.responseType||'json'})
    .then(data=>setTimeout(()=>{
      if(data.type==='bin'){
        const raw=atob(data.base64);
        const b=Uint8Array.from(raw,c=>c.charCodeAt(0));
        o.onload({status:data.status,response:b.buffer});
      }else o.onload({status:data.status,response:data.body,responseText:JSON.stringify(data.body)});
    },300)).catch(e=>{console.error('GM_ERR',e);o.onerror?.(e);});
    return {abort(){}};
  };
})();
"""
HTML="""<!doctype html><html><head><meta charset='utf-8'>
<style>
body{margin:0;background:#fafafa;font:14px system-ui}
#main{width:1390px;margin:100px auto;display:flex;gap:30px}
.bpx-player-container{position:relative;width:900px;height:510px;background:#242424;color:#fff}
.bpx-player-container video{display:block;width:900px;height:480px}
.bpx-player-row-dm-wrap{position:absolute;top:0;left:0;width:900px;height:480px;pointer-events:none}
.bili-danmaku-x-dm{font-size:14px;line-height:20px;width:max-content;background:#fff;color:#222}
#danmukuBox{width:350px}
.bui-collapse-header{position:relative;display:flex;width:350px;height:44px;align-items:center;
  background:#fff;box-sizing:border-box;border-bottom:1px solid #ddd}
.bpx-player-filter{padding-left:16px}
.bui-collapse-arrow{position:absolute;right:16px;width:16px;height:16px;background:#ddd}
</style></head><body>
<div id="main"><div class="bpx-player-container"><video></video>
<div class="bpx-player-row-dm-wrap"></div></div>
<div id="danmukuBox" class="danmaku-box">
 <div class="danmaku-wrap"><div class="bpx-player-collapse">
   <div class="bui-area"><div class="bui-collapse-wrap bui-collapse-wrap-folded">
     <div class="bui-collapse-header">
       <div class="bui-collapse-arrow"></div><div class="bpx-player-filter">弹幕列表</div>
     </div><div class="bui-collapse-body"></div>
   </div></div>
 </div></div>
</div></div>
<script>
 document.querySelector('.bui-collapse-header').addEventListener('click',()=>{
   document.querySelector('.bui-collapse-wrap').classList.toggle('bui-collapse-wrap-folded')
 });
</script></body></html>"""
URL="https://www.bilibili.com/video/BV1DIAGTEST/"
errors=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=__import__("os").environ.get("CHROME_BIN") or None,
        headless=True,args=["--no-sandbox","--disable-gpu"])
    context=browser.new_context(viewport={"width":1500,"height":900},accept_downloads=True)
    page=context.new_page()
    page.route(URL,lambda route:route.fulfill(status=200,content_type="text/html; charset=UTF-8",body=HTML))
    page.expose_binding("gm_broker",gm_broker)
    page.add_init_script(script=SHIM+"\n"+SCRIPT)
    page.on("pageerror",lambda exc:errors.append(str(exc)))
    page.goto(URL,wait_until="domcontentloaded",timeout=18000)
    page.wait_for_function("document.documentElement.classList.contains('ai-dmk-active')",timeout=11000)
    page.wait_for_selector("#ai-dmk-diag-entry",timeout=7000)
    assert page.locator("#ai-dmk-toggle").count()==0
    assert page.locator("#ai-dmk-diag-panel").count()==0
    assert page.evaluate("typeof window.__gmMenus['AI 弹幕过滤：诊断']==='function'")
    geometry=page.evaluate("""() => {
      const panel=document.querySelector('#danmukuBox').getBoundingClientRect(),
            video=document.querySelector('.bpx-player-container').getBoundingClientRect(),
            btn=document.querySelector('#ai-dmk-diag-entry').getBoundingClientRect(),
            arrow=document.querySelector('.bui-collapse-arrow').getBoundingClientRect();
      return {videoRight:video.right,sidebarLeft:panel.left,
        btnX:btn.x,btnRight:btn.right,arrowX:arrow.x};
    }""")
    assert geometry["sidebarLeft"]>geometry["videoRight"],geometry
    assert geometry["btnX"]>geometry["sidebarLeft"] and geometry["btnRight"]<geometry["arrowX"],geometry
    print("SIDEBAR_BUTTON_GEOMETRY",geometry,flush=True)

    # Introduce multiple real text nodes. Some will match prefetch cache and some live inference.
    initial=page.evaluate("""() => {
      const root=document.querySelector('.bpx-player-row-dm-wrap');
      const texts=['经费又不够了','感谢大体老师，逝者安息',
        '谢谢，我不吃','这集太有意思了','谢谢，我不吃'];
      return texts.map((text,i)=>{
        const node=document.createElement('div');node.className='bili-danmaku-x-dm';
        node.id='case-'+i;node.textContent=text;root.appendChild(node);
        return getComputedStyle(node).visibility;
      });
    }""")
    assert all(x=="visible" for x in initial),initial
    page.wait_for_function("""() => ['0','0','1','1','1'].every((want,i)=>
      document.getElementById('case-'+i)?.dataset.aiDmkOk===want)""",timeout=25000)
    print("REAL_DECISIONS_COLLECTED",flush=True)

    # The click must not activate Bilibili's original fold/unfold event.
    before=page.evaluate("document.querySelector('.bui-collapse-wrap').classList.contains('bui-collapse-wrap-folded')")
    page.locator("#ai-dmk-diag-entry").click()
    after=page.evaluate("document.querySelector('.bui-collapse-wrap').classList.contains('bui-collapse-wrap-folded')")
    assert before==after,"diagnostic button must not open Bilibili native list"
    page.wait_for_selector("#ai-dmk-diag-panel.ai-open",timeout=1500)
    assert page.locator("#ai-dmk-diag-panel.ai-dmk-diag-fallback").count()==0
    assert page.locator("#ai-dmk-diag-list [role=listitem]").count()==5
    summary=page.locator("#ai-dmk-diag-summary").inner_text()
    assert "屏蔽 2" in summary and "保留 3" in summary,summary
    blocked=page.locator("#ai-dmk-diag-list .ai-dmk-diag-row[data-status=blocked]").count()
    allowed=page.locator("#ai-dmk-diag-list .ai-dmk-diag-row[data-status=allowed]").count()
    assert blocked==2 and allowed==3,(blocked,allowed)
    print("DIAGNOSTIC_LIST",summary,flush=True)

    page.locator("#ai-dmk-diag-status").select_option("blocked")
    assert page.locator("#ai-dmk-diag-list [role=listitem]").count()==2
    page.locator("#ai-dmk-diag-category").select_option("ritual_gratitude")
    assert page.locator("#ai-dmk-diag-list [role=listitem]").count()==1
    assert "感谢大体老师" in page.locator("#ai-dmk-diag-list").inner_text()
    page.locator("#ai-dmk-diag-category").select_option("all")
    page.locator("#ai-dmk-diag-status").select_option("allowed")
    page.locator("#ai-dmk-diag-query").fill("谢谢")
    assert page.locator("#ai-dmk-diag-list [role=listitem]").count()==2
    page.locator("#ai-dmk-diag-query").fill("")
    page.locator("#ai-dmk-diag-status").select_option("all")

    # Confirm the prefetch list is separate; not counted among rendered comments.
    page.locator("#ai-dmk-diag-scope").select_option("forecast")
    page.wait_for_function("document.querySelector('#ai-dmk-diag-summary').textContent.includes('预判去重文本')",timeout=3500)
    forecast_count=page.locator("#ai-dmk-diag-list [role=listitem]").count()
    assert forecast_count>=3,forecast_count
    assert "预判专用弹幕" in page.locator("#ai-dmk-diag-list").inner_text()
    print("PREFETCH_DIAGNOSTICS",page.locator("#ai-dmk-diag-summary").inner_text(),flush=True)
    page.locator("#ai-dmk-diag-scope").select_option("screen")

    # Export should include all entries, not only the displayed filtered subset.
    with page.expect_download(timeout=6000) as download_future:
        page.locator("#ai-dmk-diag-export").click()
    download=download_future.value
    filename=OUTPUT/"diagnostics_v13_export_smoke.json"
    download.save_as(str(filename))
    exported=json.loads(filename.read_text(encoding="utf8"))
    assert len(exported["screen"])==5
    assert len(exported["forecast"])>=3
    assert sum(x["status"]=="blocked" for x in exported["screen"])==2
    assert exported["video"]["cid"]==314159265
    assert "TOKEN" not in json.dumps(exported)
    print("DIAGNOSTIC_JSON_EXPORT_PASS",download.suggested_filename,flush=True)
    page.screenshot(path=str(OUTPUT/"diagnostics_v13_sidebar_smoke.png"),timeout=8000)

    # Test reused DOM node, no separate unsupported overlay in the player.
    page.evaluate("document.querySelector('#case-0').textContent='经费又不够了'"
                  " + '！！！'")
    page.wait_for_function("document.querySelector('#case-0')?.dataset.aiDmkOk==='0'",timeout=12000)
    page.wait_for_function("document.querySelector('#ai-dmk-diag-summary')?.textContent.includes('6 条')",timeout=5000)
    assert page.locator(".bpx-player-container #ai-dmk-diag-panel").count()==0

    # A time-only query parameter is not a new video.
    page.evaluate("history.replaceState({},'', '/video/BV1DIAGTEST/?t=26')")
    page.wait_for_timeout(3200)
    assert "6 条" in page.locator("#ai-dmk-diag-summary").inner_text()
    # A different BV identity is a new video, even within a single Chrome tab.
    page.evaluate("history.pushState({},'', '/video/BV1DIAGNEW/')")
    page.wait_for_function("document.querySelector('#ai-dmk-diag-summary')?.textContent.includes('0 条')",timeout=8000)
    page.locator("#ai-dmk-diag-close").click()
    assert page.locator("#ai-dmk-diag-panel.ai-open").count()==0
    assert page.locator("#ai-dmk-diag-entry").count()==1
    assert not errors,errors
    browser.close()
print("DIAGNOSTICS_V13_FULL_PASS",flush=True)
