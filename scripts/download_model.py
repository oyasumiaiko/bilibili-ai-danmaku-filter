"""Download Google EmbeddingGemma 2 weights (external Apache-2.0 dependency).

Downloads the original multimodal checkpoint before extract_text_only.py drops
the audio and vision towers. No checkpoint files belong in the Git repository.
"""
from __future__ import annotations
import argparse,pathlib

ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo-id",default="google/embeddinggemma-2")
    parser.add_argument("--destination",type=pathlib.Path,
        default=ROOT/"models"/"embeddinggemma-2-full")
    args=parser.parse_args()
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise SystemExit("Install requirements.txt first") from e
    args.destination.mkdir(parents=True,exist_ok=True)
    print("Downloading external Google model:",args.repo_id,flush=True)
    path=snapshot_download(repo_id=args.repo_id,local_dir=str(args.destination),
        allow_patterns=["*.json","*.jinja","*.model","*.safetensors",
                        "1_Pooling/*","2_Normalize/*","*.txt"])
    if not (args.destination/"model.safetensors").is_file():
        raise SystemExit("Expected a single model.safetensors in "+str(args.destination)+
                         "; check the upstream checkpoint format")
    print("Downloaded to",path,flush=True)
    print("Run: python scripts/extract_text_only.py",flush=True)

if __name__=="__main__":
    main()
