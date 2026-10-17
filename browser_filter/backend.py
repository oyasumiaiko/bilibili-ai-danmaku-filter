# -*- coding: utf-8 -*-
r"""Private localhost-only Bilibili AI danmaku filtering backend.

Windows scheduled task -> 127.0.0.1:39683 -> EmbeddingGemma2 270M CPU.
Authenticated settings/status, adjustable torch threads/cache/strong-hit behavior,
per-category sensitivity, custom always-block/allow phrases and one-line preview.
No listening on non-loopback interfaces, no cloud APIs, no arbitrary command exec.
"""
from __future__ import annotations
import argparse, contextlib, hmac, json, logging, logging.handlers, math, os
import pathlib, secrets, sys, threading, time
from collections import Counter, OrderedDict
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from preferences_realtime_filter import DanmakuFilter, resolve_model_dir

HERE=ROOT/"browser_filter"
STATE=HERE/"state"
LOGS=HERE/"logs"
STATE.mkdir(parents=True,exist_ok=True)
LOGS.mkdir(parents=True,exist_ok=True)
TOKEN_FILE=STATE/"local_auth.json"
SETTINGS_FILE=STATE/"backend_settings.json"
TASK_NAME="Bilibili AI Danmaku Filter (GitHub)"
DEFAULT_PORT=39683
DEFAULT_SETTINGS={"cpu_threads":4,"cache_size":16000,"early_block":True,"log_level":"INFO"}
LOG=logging.getLogger("ai_danmaku")
LOG.setLevel(logging.INFO)
LOG.addHandler(logging.handlers.RotatingFileHandler(LOGS/"backend.log",maxBytes=2_000_000,backupCount=2,encoding="utf8"))
if sys.stderr is not None:
    LOG.addHandler(logging.StreamHandler(sys.stderr))


def local_token():
    if TOKEN_FILE.is_file():
        token=json.loads(TOKEN_FILE.read_text(encoding="utf8")).get("token","")
        if not isinstance(token,str) or len(token)<36:
            raise ValueError("Existing local authentication token invalid")
        return token
    token=secrets.token_urlsafe(48)
    with TOKEN_FILE.open("x",encoding="utf8") as f:
        json.dump({"token":token,"created":time.time()},f)
    if os.name=="nt":
        try:
            import subprocess
            name=os.environ.get("USERNAME")
            if name:
                subprocess.run(["icacls",str(TOKEN_FILE),"/inheritance:r", "/grant:r",name+":(R,W)"],
                               timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        except Exception:
            LOG.warning("Could not adjust private token ACL")
    return token


def validate_settings(changes,source=None):
    if not isinstance(changes,dict) or not changes:
        raise ValueError("settings must be a nonempty object")
    if set(changes)-set(DEFAULT_SETTINGS):
        raise ValueError("Unknown backend settings: "+",".join(sorted(set(changes)-set(DEFAULT_SETTINGS))))
    result=dict(DEFAULT_SETTINGS if source is None else source)
    for key,value in changes.items():
        if key=="cpu_threads":
            if type(value) is not int or value<1 or value>16:raise ValueError("cpu_threads range: 1..16")
        elif key=="cache_size":
            if type(value) is not int or value<100 or value>50000:raise ValueError("cache_size range: 100..50000")
        elif key=="early_block":
            if type(value) is not bool:raise ValueError("early_block must be true or false")
        elif key=="log_level":
            if value not in ("WARNING","INFO","DEBUG") or not isinstance(value,str):
                raise ValueError("log_level allowed: WARNING, INFO, DEBUG")
        result[key]=value
    return result


def read_settings():
    if not SETTINGS_FILE.exists():return dict(DEFAULT_SETTINGS)
    value=json.loads(SETTINGS_FILE.read_text(encoding="utf8"))
    if not isinstance(value,dict):raise ValueError("backend settings file is invalid")
    return validate_settings(value,source=dict(DEFAULT_SETTINGS))


def save_settings(value):
    tmp=SETTINGS_FILE.with_name(SETTINGS_FILE.name+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    os.replace(tmp,SETTINGS_FILE)


def positive_phrases(value,key):
    if value is None:return []
    if not isinstance(value,list) or len(value)>100:
        raise ValueError(key+" must be a list of at most 100 phrases")
    result=[]
    for x in value:
        if not isinstance(x,str) or not 1<=len(x.strip())<=80:
            raise ValueError(key+" entries must be nonempty strings of <=80 characters")
        t=x.strip().casefold()
        if t not in result:result.append(t)
    return result


def threshold_deltas(value,classes):
    if value is None:return {}
    if not isinstance(value,dict) or len(value)>30:
        raise ValueError("threshold_offsets must be a map of at most 30 categories")
    result={}
    for k,v in value.items():
        if k not in classes:raise ValueError("Unknown threshold category: "+str(k))
        if type(v) not in (int,float) or not math.isfinite(float(v)) or not -.10<=float(v)<=.10:
            raise ValueError("Category threshold delta must be -0.10 .. +0.10")
        if abs(float(v))>1e-8:result[k]=round(float(v),4)
    return result


class Hub:
    def __init__(self):
        self.started=time.time()
        self.started_load=time.perf_counter()
        self.lock=threading.RLock()
        self.state="loading"
        self.failure=""
        self.model=None
        self.pool=OrderedDict()
        self.categories={}
        self.stats=Counter()
        self.settings=read_settings()
        LOG.setLevel(getattr(logging,self.settings["log_level"]))

    def load(self):
        try:
            LOG.info("Loading EmbeddingGemma2 270M text, CPU threads %d",self.settings["cpu_threads"])
            baseline=DanmakuFilter(preset="high_recall",threads=self.settings["cpu_threads"],
                 cache_size=self.settings["cache_size"],early_block=self.settings["early_block"])
            with self.lock:
                self.model=baseline.model
                self.categories={cat:{"name":v["title"],"group":v["group"]}
                                  for cat,v in baseline.cfg["categories"].items()}
                self.pool[("high_recall",(),(),(),False)]=baseline
                self.state="ready"
            LOG.info("Model ready in %.2fs (%d classes)",time.perf_counter()-self.started_load,len(self.categories))
        except Exception as e:
            with self.lock:
                self.state="error"
                self.failure=type(e).__name__+": "+str(e)
            LOG.exception("Model loading error")

    def engine(self,preset,disabled,only,offsets,details=False):
        if preset not in ("balanced","high_recall","aggressive","keywords_only"):
            raise ValueError("Unknown preset")
        if (set(disabled)|set(only)|set(offsets))-set(self.categories):
            raise ValueError("Unknown filter category")
        key=(preset,tuple(sorted(disabled)),tuple(sorted(only)),tuple(sorted(offsets.items())),details)
        if key in self.pool:
            self.pool.move_to_end(key)
            return self.pool[key]
        result=DanmakuFilter(preset=preset,threads=self.settings["cpu_threads"],
               disabled=disabled,enable_only=only,threshold_offsets=offsets,
               cache_size=self.settings["cache_size"],early_block=self.settings["early_block"],
               show_scores=details,skip_model=True)
        if preset!="keywords_only":
            result.skip_model=False
            result.model=self.model
        self.pool[key]=result
        if len(self.pool)>15:self.pool.popitem(last=False)
        return result

    def classify(self,body,details=False):
        texts=body.get("texts")
        if not isinstance(texts,list) or not 1<=len(texts)<=96:
            raise ValueError("texts: array of 1..96 items required")
        if any(not isinstance(x,str) or len(x)>1200 for x in texts):
            raise ValueError("Each text must be a string of <=1200 characters")
        preset=body.get("preset","high_recall")
        disabled=body.get("disabled",[])
        only=body.get("enable_only",[])
        if not isinstance(disabled,list) or not isinstance(only,list) or len(disabled)>40 or len(only)>40:
            raise ValueError("disabled/enable_only must be arrays of <=40 category IDs")
        if any(not isinstance(k,str) for k in disabled+only):
            raise ValueError("Category IDs must be strings")
        forced_allow=positive_phrases(body.get("allow_phrases"),"allow_phrases")
        forced_block=positive_phrases(body.get("block_phrases"),"block_phrases")
        offsets=threshold_deltas(body.get("threshold_offsets"),self.categories)
        begin=time.perf_counter()
        out=[]
        with self.lock:
            if self.state!="ready":raise RuntimeError("Model is "+self.state)
            engine=self.engine(preset,disabled,only,offsets,details)
            cached={}
            for phrase in texts:
                text=phrase.casefold()
                if forced_allow and any(x in text for x in forced_allow):
                    result={"blocked":False,"matched_categories":[],"reasons":{"custom":"always_allow"},"cached":True,
                            "used_embedding":False}
                elif forced_block and any(x in text for x in forced_block):
                    result={"blocked":True,"matched_categories":["custom_block"],"reasons":{"custom":"always_block"},
                            "cached":True,"used_embedding":False}
                elif phrase in cached:
                    result=cached[phrase]
                else:
                    result=engine.classify(phrase)
                    cached[phrase]=result
                self.stats["received"]+=1
                self.stats["blocked"]+=bool(result["blocked"])
                self.stats["model_encodes"]+=bool(result.get("used_embedding")) and not bool(result.get("cached"))
                item={"blocked":bool(result["blocked"]),
                      "categories":list(result["matched_categories"]),
                      "reason":dict(result.get("reasons",{})),
                      "cached":bool(result.get("cached"))}
                if details:
                    item["scores"]=result.get("scores",{})
                    item["latency_ms"]=result.get("latency_ms",0)
                out.append(item)
            self.stats["requests"]+=1
        return {"results":out,"ms":round((time.perf_counter()-begin)*1000,2),
                "preset":preset,"input_count":len(texts)}

    def set_settings(self,body):
        with self.lock:
            new=validate_settings(body,self.settings)
            if self.state!="ready":raise RuntimeError("Model must be ready before changing CPU settings")
            if new["cpu_threads"]!=self.settings["cpu_threads"]:
                import torch
                torch.set_num_threads(new["cpu_threads"])
            if new!=self.settings:
                save_settings(new)
                self.settings=new
                for engine in self.pool.values():
                    engine.capacity=new["cache_size"]
                    engine.early_block=new["early_block"]
                    while len(engine.cache)>engine.capacity:engine.cache.popitem(last=False)
                LOG.setLevel(getattr(logging,new["log_level"]))
                self.stats["settings_updates"]+=1
                LOG.info("Backend settings updated: cpu=%s cache=%s early_block=%s log_level=%s",
                         new["cpu_threads"],new["cache_size"],new["early_block"],new["log_level"])
            return dict(self.settings)

    def clear_cache(self):
        with self.lock:
            num=sum(len(v.cache) for v in self.pool.values())
            for engine in self.pool.values():engine.cache.clear()
            self.stats["cache_clears"]+=1
            return {"cleared_entries":num,"active_profiles":len(self.pool)}

    def status(self):
        with self.lock:
            return {"service":"AI Danmaku Filter","status":self.state,"pid":os.getpid(),
                    "uptime_s":int(time.time()-self.started),
                    "category_count":len(self.categories),
                    "categories":self.categories if self.state=="ready" else {},
                    "profile_names":["balanced","high_recall","aggressive","keywords_only"],
                    "cpu_threads":self.settings["cpu_threads"],
                    "error":self.failure if self.state=="error" else "",
                    "requests":self.stats["requests"],"texts_processed":self.stats["received"],
                    "version":"1.1.0"}

    def settings_view(self,port):
        with self.lock:
            return {"settings":dict(self.settings),
                    "runtime":{"pid":os.getpid(),"status":self.state,
                               "uptime_s":int(time.time()-self.started),
                               "cache_entries":sum(len(e.cache) for e in self.pool.values()),
                               "active_profiles":len(self.pool),
                               "threads":self.settings["cpu_threads"],
                               "stats":dict(self.stats),
                               "model_path":str(resolve_model_dir()),
                               "port":port,"bind_address":"127.0.0.1",
                               "autostart_task":TASK_NAME,
                               "settings_path":str(SETTINGS_FILE),
                               "log_path":str(LOGS/"backend.log")},
                    "editable":["cpu_threads","cache_size","early_block","log_level"]}


class Handler(BaseHTTPRequestHandler):
    server_version="AiDanmakuLoopback/1.1"
    protocol_version="HTTP/1.1"
    def log_message(self,fmt,*args):
        if not self.path.startswith("/health"):LOG.debug("%s %s",self.address_string(),fmt%args)

    def respond(self,status,obj):
        binary=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(binary)))
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Access-Control-Allow-Private-Network","true")
        self.send_header("Vary","Origin")
        origin=self.headers.get("Origin","")
        if origin in ("https://www.bilibili.com","https://www.bilibili.tv"):
            self.send_header("Access-Control-Allow-Origin",origin)
        self.end_headers()
        with contextlib.suppress(BrokenPipeError,ConnectionResetError):
            self.wfile.write(binary)

    def error(self,code,message):
        self.respond(code,{"error":message,"status":"error"})

    def authorized(self):
        value=self.headers.get("X-AI-Danmaku-Token","")
        return bool(value) and hmac.compare_digest(value,self.server.token)

    def valid_host(self):
        return self.headers.get("Host","") in (
          f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}")

    def do_OPTIONS(self):
        if not self.valid_host():return self.error(403,"Invalid Host")
        origin=self.headers.get("Origin","")
        if origin not in ("https://www.bilibili.com","https://www.bilibili.tv"):
            return self.error(403,"Origin not allowed")
        self.send_response(204)
        self.send_header("Content-Length","0")
        self.send_header("Access-Control-Allow-Origin",origin)
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type,X-AI-Danmaku-Token")
        self.send_header("Access-Control-Allow-Private-Network","true")
        self.send_header("Access-Control-Max-Age","1200")
        self.end_headers()

    def do_GET(self):
        if not self.valid_host():return self.error(403,"Invalid Host")
        if self.path=="/health":return self.respond(200,self.server.hub.status())
        if not self.authorized():return self.error(401,"Unauthorized")
        if self.path=="/api/stats":return self.respond(200,self.server.hub.settings_view(self.server.server_port))
        if self.path=="/api/settings":return self.respond(200,self.server.hub.settings_view(self.server.server_port))
        return self.error(404,"Not found")

    def do_POST(self):
        if not self.valid_host():return self.error(403,"Invalid Host")
        if not self.authorized():return self.error(401,"Unauthorized")
        if self.path not in ("/api/classify","/api/preview","/api/settings","/api/cache/clear"):
            return self.error(404,"Not found")
        n=int(self.headers.get("Content-Length","0") or "0")
        if n<=0 or n>196_608:return self.error(413,"Body size must be 1..192KiB")
        try:
            body=json.loads(self.rfile.read(n))
            if not isinstance(body,dict):raise ValueError("Expected object")
            if self.path=="/api/settings":
                return self.respond(200,self.server.hub.set_settings(body))
            if self.path=="/api/cache/clear":
                return self.respond(200,self.server.hub.clear_cache())
            if self.path=="/api/preview":
                if not isinstance(body.get("texts"),list) or len(body["texts"])!=1:
                    raise ValueError("Preview requires exactly one text")
                return self.respond(200,self.server.hub.classify(body,details=True))
            return self.respond(200,self.server.hub.classify(body))
        except (ValueError,TypeError,json.JSONDecodeError) as ex:
            return self.error(400,str(ex))
        except RuntimeError as ex:
            return self.error(503,str(ex))
        except Exception:
            LOG.exception("API error in %s",self.path)
            return self.error(500,"Local filter failed")


class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    request_queue_size=64
    def __init__(self,address,handler,hub,token):
        self.hub,self.token=hub,token
        super().__init__(address,handler)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=DEFAULT_PORT)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error("Invalid port")
    token=local_token()
    hub=Hub()
    server=Server(("127.0.0.1",args.port),Handler,hub,token)
    LOG.info("Local AI Danmaku backend v1.1 started at http://127.0.0.1:%d pid=%d",args.port,os.getpid())
    threading.Thread(target=hub.load,name="embed-model-load",daemon=True).start()
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=="__main__":main()
