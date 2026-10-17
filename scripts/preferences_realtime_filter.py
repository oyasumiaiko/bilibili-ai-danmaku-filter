# -*- coding: utf-8 -*-
r"""Real-time Bilibili danmaku semantic filter, fully local and zero-shot.

One warm EmbeddingGemma2 Document-mode inference per eligible new sentence;
19 independent nuisance classes, configurable balanced/high_recall/aggressive.
Reference embeddings are precomputed, and deterministic regexes avoid most
unnecessary inference. Supports stdin, --input-file JSONL, or --text.
No model training, no Bilibili/player modification.

  python scripts/preferences_realtime_filter.py --text "感谢大体老师，逝者安息"
  python scripts/preferences_realtime_filter.py --preset high_recall --input-file input.jsonl --output-file output.jsonl
  echo "经费又不够了" | python scripts/preferences_realtime_filter.py
"""
from __future__ import annotations
import os,sys,json,re,pathlib,hashlib,collections,time,argparse
from collections import OrderedDict
from typing import Any
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CFG=ROOT/"config"/"filter_categories.json"
DEFAULT_TUNED=ROOT/"assets"/"tuned_profiles_v3.json"
DEFAULT_VECS=ROOT/"assets"/"reference_vectors_v3.npz"

def resolve_model_dir()->pathlib.Path:
    """Return the text-only checkpoint path; weights are not shipped in Git."""
    custom=os.environ.get("AI_DANMAKU_MODEL_DIR","").strip()
    return pathlib.Path(custom).expanduser().resolve() if custom else ROOT/"models"/"embeddinggemma-2-text"


def interpret(line:str)->tuple[dict[str,Any],str]:
    stripped=line.strip()
    if stripped.startswith("{"):
        try:
            obj=json.loads(stripped)
            if isinstance(obj,dict) and isinstance(obj.get("text"),str):
                return obj,obj["text"]
        except json.JSONDecodeError:
            pass
    return {"text":line.rstrip("\r\n")},line.rstrip("\r\n")

def pool(row:np.ndarray,kind:str)->float:
    if kind in ("top1","max"):return float(row.max())
    k=min(3,len(row))
    return float(np.partition(row,-k)[-k:].mean())

class DanmakuFilter:
    def __init__(self,preset="balanced",threads=4,
                 disabled=None,enable_only=None,cache_size=10000,
                 show_scores=False,skip_model=False,early_block=True,threshold_offsets=None,
                 config_path=DEFAULT_CFG,tuned_path=DEFAULT_TUNED,vectors_path=DEFAULT_VECS):
        self.cfg=json.loads(pathlib.Path(config_path).read_text(encoding="utf8"))
        self.tuned=json.loads(pathlib.Path(tuned_path).read_text(encoding="utf8"))
        if preset not in ("balanced","high_recall","aggressive","keywords_only"):
            raise ValueError("Unsupported preset: "+preset)
        self.preset=preset
        self.settings=self.tuned["presets"][preset if preset!="keywords_only" else "balanced"]
        self.delta=float(self.settings["global_threshold_delta"]) if preset!="keywords_only" else 0.
        self.disabled=set(disabled or ())
        self.enable_only=set(enable_only or ())
        self.threshold_offsets=dict(threshold_offsets or {})
        self.show_scores=show_scores
        self.skip_model=skip_model or preset=="keywords_only"
        self.early_block=early_block
        self.capacity=max(0,int(cache_size))
        self.cache=OrderedDict()
        self.categories=list(self.cfg["categories"])
        missing=(self.disabled|self.enable_only)-set(self.categories)
        if missing:raise ValueError("Unknown categories: "+",".join(sorted(missing)))
        self.compiled={}
        for cat,raw in self.cfg["categories"].items():
            self.compiled[cat]={
              "direct":[re.compile(s,re.I) for s in raw["strong_patterns"]],
              "except":[re.compile(s,re.I) for s in raw["exclude_patterns"]],
              "evidence":re.compile(raw["semantic_evidence_pattern"],re.I),
            }
        with np.load(vectors_path) as n:
            keys=[str(x) for x in n["category_keys"]]
            assert keys==self.categories,(keys,self.categories)
            pos=np.asarray(n["pos"],dtype=np.float32)
            neg=np.asarray(n["neg"],dtype=np.float32)
            pos_sizes=n["pos_sizes"]
            neg_sizes=n["neg_sizes"]
        self.vectors={}
        p_start=n_start=0
        for i,cat in enumerate(self.categories):
            psz=int(pos_sizes[i]);nsz=int(neg_sizes[i])
            self.vectors[cat]=(np.ascontiguousarray(pos[p_start:p_start+psz]),
                               np.ascontiguousarray(neg[n_start:n_start+nsz]))
            p_start+=psz;n_start+=nsz
        assert p_start==len(pos) and n_start==len(neg)
        self.model=None
        self.threads=int(threads)
        if not self.skip_model:
            import torch
            from sentence_transformers import SentenceTransformer
            torch.set_num_threads(self.threads)
            root=resolve_model_dir()
            if not (root/"model.safetensors").exists():
                raise FileNotFoundError(root/"model.safetensors")
            self.model=SentenceTransformer(str(root),device="cpu",
                config_kwargs={"vision_config":None,"audio_config":None},
                model_kwargs={"torch_dtype":torch.float32})
            self.model.max_seq_length=192
        self.metrics=collections.Counter()

    def _flags(self,txt:str):
        direct=[];fuzzy_candidates=[]
        excluded=[]
        for cat in self.categories:
            if cat in self.disabled or (self.enable_only and cat not in self.enable_only):
                continue
            pats=self.compiled[cat]
            if any(x.search(txt) for x in pats["except"]):
                excluded.append(cat)
                continue
            tuned=self.settings["categories"][cat]
            if tuned["use_strong_regex"] and any(x.search(txt) for x in pats["direct"]):
                direct.append(cat)
            elif not self.skip_model and (not tuned["semantic_gate"] or pats["evidence"].search(txt)):
                fuzzy_candidates.append(cat)
        return direct,fuzzy_candidates

    def classify(self,txt:str)->dict:
        now=time.perf_counter()
        self.metrics["seen"]+=1
        if self.capacity and txt in self.cache:
            data=self.cache[txt]
            self.cache.move_to_end(txt)
            self.metrics["cache_hits"]+=1
            out=dict(data)
            out["latency_ms"]=round((time.perf_counter()-now)*1000,3)
            out["cached"]=True
            return out
        direct,fuzzy=self._flags(txt)
        reasons={cat:"strong_pattern" for cat in direct}
        scored={}
        # A confident direct match is sufficient to hide, unless investigating
        # every class with --show-scores / --no-early-block.
        should_encode=(bool(fuzzy) and not self.skip_model
                       and (not direct or not self.early_block or self.show_scores))
        if should_encode:
            V=np.asarray(self.model.encode(
                [self.tuned["runtime_document_prefix"]+txt],
                prompt_name=self.tuned["runtime_document_task"],batch_size=1,
                normalize_embeddings=True,convert_to_numpy=True,
                show_progress_bar=False),dtype=np.float32)[0]
            for cat in fuzzy:
                if cat in reasons:continue
                c=self.settings["categories"][cat]
                P,N=self.vectors[cat]
                positive=pool(P@V,c["pool"])
                negative=pool(N@V,c["negative_pool"])
                score=float(positive-float(c["alpha"])*negative)
                cutoff=float(c["threshold"])+self.delta+float(self.threshold_offsets.get(cat,0))
                if score>=cutoff:
                    reasons[cat]="semantic_similarity"
                if self.show_scores or score>=cutoff:
                    scored[cat]={"score":round(score,5),"threshold":round(cutoff,5),
                                 "positive":round(positive,5),"hard_negative":round(negative,5)}
            self.metrics["model_encodes"]+=1
        elif fuzzy and not direct and not self.skip_model:
            raise AssertionError("Unreachable: eligible text was not processed")
        if direct:self.metrics["direct_hits"]+=1
        blocked=bool(reasons)
        if blocked:self.metrics["blocked"]+=1
        data={"blocked":blocked,"preset":self.preset,
              "matched_categories":list(reasons),
              "reasons":reasons,"used_embedding":bool(should_encode)}
        if scored:data["scores"]=scored
        if self.capacity:
            self.cache[txt]=data
            if len(self.cache)>self.capacity:self.cache.popitem(last=False)
        out=dict(data);out["cached"]=False
        out["latency_ms"]=round((time.perf_counter()-now)*1000,3)
        return out

def main():
    p=argparse.ArgumentParser(description="Bilibili local preference classifier, independent 19 category predicates")
    p.add_argument("--preset",choices=["balanced","high_recall","aggressive","keywords_only"],default="balanced")
    p.add_argument("--threads",type=int,default=4)
    p.add_argument("--text",help="Filter a single text comment")
    p.add_argument("--input-file",help="JSONL of Bilibili comments or UTF-8 text file, one per line")
    p.add_argument("--output-file",help="Write decision JSONL to this new path")
    p.add_argument("--disable-category",action="append",default=[])
    p.add_argument("--enable-only",action="append",default=[])
    p.add_argument("--show-scores",action="store_true")
    p.add_argument("--no-early-block",action="store_true")
    p.add_argument("--cache-size",type=int,default=10000)
    p.add_argument("--limit",type=int,default=0)
    args=p.parse_args()
    if args.threads<1 or args.limit<0:p.error("threads must be >=1 and limit must be >=0")
    start=time.perf_counter()
    engine=DanmakuFilter(preset=args.preset,threads=args.threads,disabled=args.disable_category,
                         enable_only=args.enable_only,show_scores=args.show_scores,
                         early_block=not args.no_early_block,cache_size=args.cache_size)
    print("PREFERENCES_FILTER_READY",args.preset,
          "classes",len(engine.enable_only) if engine.enable_only else len(engine.categories)-len(engine.disabled),
          "start_seconds",round(time.perf_counter()-start,2),file=sys.stderr,flush=True)
    output=pathlib.Path(args.output_file) if args.output_file else None
    if output: output.parent.mkdir(parents=True,exist_ok=True)
    fileout=output.open("w",encoding="utf8") if output else sys.stdout
    inp=pathlib.Path(args.input_file).open(encoding="utf-8-sig") if args.input_file else sys.stdin
    try:
        for i,line in enumerate([args.text] if args.text is not None else inp,1):
            if not line.strip():continue
            record,text=interpret(line)
            result=engine.classify(text)
            item={**record,"preferences_filter":result}
            print(json.dumps(item,ensure_ascii=False),file=fileout,flush=output is None)
            if args.limit and i>=args.limit:break
    finally:
        if args.input_file:inp.close()
        if output:fileout.close()
    print("PREFERENCES_FILTER_COUNTS",dict(engine.metrics),file=sys.stderr,flush=True)
if __name__=="__main__":main()
