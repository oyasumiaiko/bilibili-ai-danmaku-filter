# -*- coding: utf-8 -*-
"""Materialize a real full-precision text-only EmbeddingGemma 2 checkpoint.
Uses original safetensors payload bytes unchanged; excludes vision/audio towers.
No model quantization and no reduced embedding dimension.
"""
from __future__ import annotations
import hashlib, json, mmap, pathlib, shutil, struct, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/"models"/"embeddinggemma-2-full"
DEST=ROOT/"models"/"embeddinggemma-2-text"
DEST.mkdir(parents=True,exist_ok=True)
for f in SOURCE.iterdir():
    if f.is_file() and f.name != "model.safetensors":
        shutil.copy2(f, DEST/f.name)
for folder in ("1_Pooling","2_Normalize"):
    src=SOURCE/folder
    if src.exists():shutil.copytree(src,DEST/folder,dirs_exist_ok=True)
cfg=json.loads((SOURCE/"config.json").read_text(encoding="utf8"))
cfg["vision_config"]=None
cfg["audio_config"]=None
(DEST/"config.json").write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
src=SOURCE/"model.safetensors"
dst=DEST/"model.safetensors"
with src.open("rb") as f:
    meta_len=struct.unpack("<Q",f.read(8))[0]
    old=json.loads(f.read(meta_len))
    data_pos=8+meta_len
    kept={k:v for k,v in old.items() if k=="__metadata__" or k.startswith("language_model.") or k in ("embed_audio","embed_vision")}
    tensors=sorted((k,v) for k,v in kept.items() if k!="__metadata__")
    tensors.sort(key=lambda item:item[1]["data_offsets"][0])
    new_dict={"__metadata__":old.get("__metadata__",{"format":"pt"})}
    n=0
    for k,v in tensors:
        l=v["data_offsets"][1]-v["data_offsets"][0]
        new_dict[k]={"dtype":v["dtype"],"shape":v["shape"],"data_offsets":[n,n+l]}
        n+=l
    header=json.dumps(new_dict,separators=(",",":"),ensure_ascii=False).encode("utf8")
    header+=b" " *((-len(header)) %8)
    tmp=dst.with_suffix(".safetensors.pending")
    t0=time.monotonic()
    with tmp.open("wb") as out:
        out.write(struct.pack("<Q",len(header)))
        out.write(header)
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
            for k,v in tensors:
                a,b=v["data_offsets"]
                out.write(m[data_pos+a:data_pos+b])
    tmp.replace(dst)
    print("TEXT_ONLY_CREATED",dst,"BYTES",dst.stat().st_size,"TENSORS",len(tensors),
          "TEXT_WEIGHT_MB",round(n/1e6,2),
          "TIME_SEC",round(time.monotonic()-t0,2),flush=True)
    sample=[k for k in new_dict if k!="__metadata__"][:10]
    print("WEIGHT_SAMPLE",sample,flush=True)
    with dst.open("rb") as fr:
        length=struct.unpack("<Q",fr.read(8))[0]
        parsed=json.loads(fr.read(length))
        end=max(v["data_offsets"][1] for k,v in parsed.items() if k!="__metadata__")
        assert (8+length+end)==dst.stat().st_size
        assert not any(k.startswith("audio_tower.") or k.startswith("vision_tower.") for k in parsed)
    (DEST/"CHECKPOINT_DETAILS.json").write_text(json.dumps({
      "original_model":"google/embeddinggemma-2","original_full":str(src),
      "modified":"exclude audio_tower.* and vision_tower.*; change configs to null",
      "text_only":str(dst),"tensor_count":len(tensors),"tensor_bytes":n,
      "native_embedding_dim":768,"no_quantization":True,
    },ensure_ascii=False,indent=2),encoding="utf8")
