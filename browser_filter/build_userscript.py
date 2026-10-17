"""Build local, private Tampermonkey files after dependencies are installed.

Never check the generated .user.js files into Git: one embeds a private token.
The checked-in files are only token-free templates and the diagnostics module.
"""
from __future__ import annotations
import argparse,pathlib,sys

HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))
from backend import local_token

def build(port:int=39683):
    if not 1024<=port<=65535:
        raise ValueError("Port must be 1024..65535")
    token=local_token()
    template=(HERE/"bilibili_ai_filter.template.user.js").read_text(encoding="utf8")
    marker="const BASE='http://127.0.0.1:39683';"
    if template.count(marker)!=1:raise RuntimeError("Missing unique loopback endpoint")
    diagnostics=(HERE/"diagnostics_module.js").read_text(encoding="utf8")
    if template.count("__AUTH_TOKEN__")!=1 or template.count("/* __DIAGNOSTICS_MODULE__ */")!=1:
        raise RuntimeError("Missing or duplicate local template placeholders")
    user_script=HERE/"bilibili_ai_filter.user.js"
    user_script.write_text(template.replace("/* __DIAGNOSTICS_MODULE__ */",diagnostics)
                     .replace("__AUTH_TOKEN__",token)
                     .replace(marker,f"const BASE='http://127.0.0.1:{port}';"),
                     encoding="utf8")
    loader_template=(HERE/"bilibili_ai_filter_loader.template.user.js").read_text(encoding="utf8")
    if loader_template.count("__REQUIRE_URI__")!=1:
        raise RuntimeError("Invalid @require placeholder")
    loader=HERE/"bilibili_ai_filter_loader.user.js"
    loader.write_text(loader_template.replace("__REQUIRE_URI__",user_script.resolve().as_uri()),
                      encoding="utf8")
    print("Built private Tampermonkey script and loader:")
    print("  "+str(user_script))
    print("  "+str(loader))
    print("Do not commit or share the generated files; they contain device-specific details.")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Build local private Tampermonkey files")
    parser.add_argument("--port",type=int,default=39683,
                        help="Loopback backend port; match backend.py --port (default 39683)")
    build(parser.parse_args().port)
