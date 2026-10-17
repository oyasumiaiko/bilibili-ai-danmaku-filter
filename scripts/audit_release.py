"""Audit *staged* Git content before the first push or any later publication.

Only checks the Git index, not the ignored working files; no remote APIs.
Avoid printing any secret values in diagnostic output.
"""
from __future__ import annotations
import json,pathlib,re,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
TEXT_SUFFIXES={".py",".js",".json",".md",".txt",".yml",".yaml",".toml",".ps1"}
BANNED_FILENAMES={"bilibili_ai_filter.user.js",
                  "bilibili_ai_filter_loader.user.js",
                  "local_auth.json"}
BANNED_COMPONENTS={"state","models","data","logs","results",".venv"}
SECRET_PATTERNS=[
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"(?i)(?:bearer|api[_-]?key)[ \t]*[:=][ \t]*[A-Za-z0-9_.-]{32,}"),
    re.compile(rb"(?i)[a-z]:[\\/](?:users|ai)[\\/][^ \r\n\"']{3,}"),
]
def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT)
def main():
    paths=[x.decode("utf-8") for x in git("ls-files","-z").split(b"\0") if x]
    problems=[]
    state=ROOT/"browser_filter/state/local_auth.json"
    local_token=""
    if state.is_file():
        local_token=json.loads(state.read_text(encoding="utf8")).get("token","")
    for path in paths:
        p=pathlib.PurePosixPath(path)
        if p.name in BANNED_FILENAMES or any(x in BANNED_COMPONENTS for x in p.parts):
            problems.append((path,"private or generated file staged"))
            continue
        raw=git("show",":"+path)
        if len(raw)>2_000_000:
            problems.append((path,"file exceeds 2MB (check binary/model artifacts)"))
        if local_token and local_token.encode() in raw:
            problems.append((path,"local API secret in staged content"))
        if p.suffix.lower() in TEXT_SUFFIXES or p.name in {".gitignore",".gitattributes","LICENSE","NOTICE"}:
            for pattern in SECRET_PATTERNS:
                if pattern.search(raw):
                    problems.append((path,"secret-like string or absolute personal Windows path"))
                    break
    if problems:
        for path,explanation in problems:print("FAIL",path,explanation)
        raise SystemExit(1)
    print("RELEASE_AUDIT_PASS",len(paths),"staged files; no banned artifacts or token indicators")
if __name__=="__main__":main()
