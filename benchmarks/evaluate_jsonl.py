"""Model-agnostic paired binary benchmark for user-supplied JSONL predictions.

Rows:
  {"id":"unique","gold":true,
   "predictions":{"embedding":true,"d3":false},
   "latency_ms":{"embedding":63.2,"d3":2616.0}}

All rows MUST have all models. Sample IDs are required to detect overlap
between experiments. This script makes no model calls and requires no packages.
"""
from __future__ import annotations
import argparse,json,math,pathlib,statistics,sys

def percentile_ms(values,quantile):
    if not values:return None
    ordered=sorted(values)
    # nearest-rank percentile (one-indexed)
    return round(ordered[max(0,math.ceil(quantile*len(ordered))-1)],3)

def evaluate(rows):
    if not rows:raise ValueError("Empty benchmark")
    models=None;seen=set();stats={}
    positive=0
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict):raise ValueError(f"Line {i} must contain an object")
        identifier=row.get("id")
        if not isinstance(identifier,(str,int)) or str(identifier)=="":
            raise ValueError(f"Line {i}: 'id' must be a nonempty string or integer")
        if str(identifier) in seen:raise ValueError(f"Duplicate id: {identifier}")
        seen.add(str(identifier))
        y=row.get("gold")
        if type(y) not in (bool,int) or y not in (0,1):
            raise ValueError(f"Line {i}: gold must be boolean or 0/1")
        y=bool(y);positive+=y
        predictions=row.get("predictions")
        if not isinstance(predictions,dict) or not predictions:
            raise ValueError(f"Line {i}: nonempty predictions map required")
        if models is None:
            models=set(predictions)
            if not all(isinstance(x,str) and x.strip() for x in models):
                raise ValueError("Model names must be nonempty strings")
            stats={name:{"tp":0,"fp":0,"fn":0,"tn":0,"times":[]} for name in models}
        if set(predictions)!=models:
            raise ValueError(f"Line {i}: models differ; paired benchmark requires same model set")
        latencies=row.get("latency_ms",{})
        if not isinstance(latencies,dict):raise ValueError(f"Line {i}: latency_ms must be object")
        for name,pred in predictions.items():
            if type(pred) not in (bool,int) or pred not in (0,1):
                raise ValueError(f"Line {i}: prediction for {name} is not boolean")
            pred=bool(pred);s=stats[name]
            s["tp" if y and pred else "fn" if y else "fp" if pred else "tn"]+=1
            if name in latencies:
                val=latencies[name]
                if type(val) not in (int,float) or not math.isfinite(val) or val<0:
                    raise ValueError(f"Line {i}: invalid latency for {name}")
                s["times"].append(float(val))
    results={}
    for name in sorted(models):
        s=stats[name];tp,fp,fn,tn=(s[k] for k in ("tp","fp","fn","tn"))
        precision=tp/(tp+fp) if (tp+fp) else 0.0
        recall=tp/(tp+fn) if (tp+fn) else 0.0
        f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0
        times=s["times"]
        results[name]={"tp":tp,"fp":fp,"fn":fn,"tn":tn,
             "precision":round(precision,4),"recall":round(recall,4),"f1":round(f1,4),
             "accuracy":round((tp+tn)/len(rows),4),
             "latency_samples":len(times),
             "latency_p50_ms":round(statistics.median(times),3) if times else None,
             "latency_p95_ms":percentile_ms(times,.95)}
    return {"n":len(rows),"positive":positive,"negative":len(rows)-positive,
            "paired":True,"models":results}

def read_jsonl(path):
    rows=[]
    with pathlib.Path(path).open(encoding="utf-8-sig") as stream:
        for line_no,line in enumerate(stream,1):
            if not line.strip():continue
            try:rows.append(json.loads(line))
            except json.JSONDecodeError as e:raise ValueError(f"Invalid JSON on line {line_no}: {e}")
    return rows

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=pathlib.Path,required=True)
    p.add_argument("--output",type=pathlib.Path)
    args=p.parse_args(argv)
    result=evaluate(read_jsonl(args.input))
    text=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding="utf8")
        print("Wrote",args.output)
    else:sys.stdout.write(text)

if __name__=="__main__":main()
