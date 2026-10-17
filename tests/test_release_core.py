"""Lightweight offline checks: no model download, no browser or Bilibili access."""
from __future__ import annotations
import json,os,pathlib,subprocess,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from browser_filter import backend
from scripts.preferences_realtime_filter import DanmakuFilter,resolve_model_dir

class ConfigTests(unittest.TestCase):
    def test_categories_and_vectors(self):
        cfg=json.loads((ROOT/"config/filter_categories.json").read_text(encoding="utf8"))
        tuned=json.loads((ROOT/"assets/tuned_profiles_v3.json").read_text(encoding="utf8"))
        self.assertEqual(len(cfg["categories"]),19)
        self.assertEqual(len(tuned["presets"]["high_recall"]["categories"]),19)
        self.assertEqual(cfg["model"]["name"],"google/embeddinggemma-2")
        self.assertFalse(pathlib.Path(cfg["model"]["local_path"]).is_absolute())
        import numpy as np
        with np.load(ROOT/"assets/reference_vectors_v3.npz") as vectors:
            self.assertEqual([str(c) for c in vectors["category_keys"]],list(cfg["categories"]))
            self.assertEqual(vectors["pos"].shape[1],768)
            self.assertEqual(vectors["neg"].shape[1],768)

    def test_model_dir_is_configurable(self):
        original=os.environ.get("AI_DANMAKU_MODEL_DIR")
        try:
            os.environ["AI_DANMAKU_MODEL_DIR"]=str(ROOT/"models"/"override")
            self.assertEqual(resolve_model_dir(),(ROOT/"models"/"override").resolve())
        finally:
            if original is None:os.environ.pop("AI_DANMAKU_MODEL_DIR",None)
            else:os.environ["AI_DANMAKU_MODEL_DIR"]=original

    def test_keyword_only_classifier_needs_no_model(self):
        f=DanmakuFilter(preset="keywords_only",skip_model=True,threads=1)
        self.assertTrue(f.classify("经费又不够了")["blocked"])
        self.assertFalse(f.classify("谢谢，我不吃")["blocked"])
        self.assertFalse(f.classify("2020来考古")["blocked"])
        self.assertIsNone(f.model)

    def test_backend_validations(self):
        self.assertEqual(backend.validate_settings({"cpu_threads":2})["cpu_threads"],2)
        with self.assertRaises(ValueError):
            backend.validate_settings({"cpu_threads":99})
        with self.assertRaises(ValueError):
            backend.validate_settings({"log_level":"VERBOSE"})
        with self.assertRaises(ValueError):
            backend.validate_settings({"arbitrary_command":"rm -rf"})
        cats={"spoiler_direct":{}}
        self.assertEqual(backend.threshold_deltas({"spoiler_direct":-.05},cats),{"spoiler_direct":-.05})
        with self.assertRaises(ValueError):
            backend.threshold_deltas({"no_such_category":.01},cats)
        self.assertEqual(backend.positive_phrases(["  TEST  ","test"],"allow_phrases"),["test"])

    def test_private_local_build(self):
        from browser_filter.build_userscript import build
        build()
        folder=ROOT/"browser_filter"
        token=json.loads((folder/"state/local_auth.json").read_text(encoding="utf8"))["token"]
        source=(folder/"bilibili_ai_filter.template.user.js").read_text(encoding="utf8")
        diag=(folder/"diagnostics_module.js").read_text(encoding="utf8")
        emitted=(folder/"bilibili_ai_filter.user.js").read_text(encoding="utf8")
        loader=(folder/"bilibili_ai_filter_loader.user.js").read_text(encoding="utf8")
        self.assertNotIn(token,source)
        self.assertNotIn(token,diag)
        self.assertEqual(emitted,source.replace("/* __DIAGNOSTICS_MODULE__ */",diag).replace("__AUTH_TOKEN__",token))
        self.assertEqual(loader.count("@require"),1)
        self.assertIn((folder/"bilibili_ai_filter.user.js").resolve().as_uri(),loader)
        self.assertIn("// @version      1.3.0",loader)
        if (ROOT/".git").exists():
            targets=["browser_filter/state/local_auth.json",
              "browser_filter/bilibili_ai_filter.user.js",
              "browser_filter/bilibili_ai_filter_loader.user.js"]
            check=subprocess.run(["git","check-ignore",*targets],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(check.returncode,0,check.stderr)
            self.assertEqual(len(check.stdout.splitlines()),len(targets))

    def test_public_files_contain_no_private_installation_data(self):
        paths=[
          ROOT/"browser_filter/bilibili_ai_filter.template.user.js",
          ROOT/"browser_filter/bilibili_ai_filter_loader.template.user.js",
          ROOT/"config/filter_categories.json",
          ROOT/"scripts/preferences_realtime_filter.py",
          ROOT/"browser_filter/backend.py",
        ]
        for p in paths:
            s=p.read_text(encoding="utf8")
            self.assertNotRegex(s,r"(?i)[a-z]:\\\\Users\\\\[^\\\\]+",str(p))
            self.assertNotRegex(s,r"(?i)[a-z]:\\\\AI\\\\",str(p))
            self.assertNotIn("github_pat_",s,str(p))
        self.assertIn("__AUTH_TOKEN__",(ROOT/"browser_filter/bilibili_ai_filter.template.user.js").read_text(encoding="utf8"))
        self.assertIn("__REQUIRE_URI__",(ROOT/"browser_filter/bilibili_ai_filter_loader.template.user.js").read_text(encoding="utf8"))
        self.assertIn("ai-dmk-diag-entry",(ROOT/"browser_filter/diagnostics_module.js").read_text(encoding="utf8"))
        self.assertFalse((ROOT/"models/embeddinggemma-2-text/model.safetensors").exists())

if __name__=="__main__":
    unittest.main()
