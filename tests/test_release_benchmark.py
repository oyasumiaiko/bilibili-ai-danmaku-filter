"""Offline checks for benchmark arithmetic and paired-data validation."""
import json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"benchmarks"))
from evaluate_jsonl import evaluate,read_jsonl

class BenchmarkTests(unittest.TestCase):
    def test_demo_fixture(self):
        rows=read_jsonl(ROOT/"benchmarks/fixtures/synthetic_demo.jsonl")
        results=evaluate(rows)
        self.assertEqual(results["n"],6)
        self.assertEqual((results["positive"],results["negative"]),(3,3))
        models=results["models"]
        self.assertEqual(tuple(models["embedding"][x] for x in ("tp","fp","fn","tn")),(2,0,1,3))
        self.assertAlmostEqual(models["embedding"]["f1"],.8,places=4)
        self.assertEqual(tuple(models["d3"][x] for x in ("tp","fp","fn","tn")),(2,1,1,2))
        self.assertAlmostEqual(models["d3"]["f1"],.6667,places=4)
        self.assertEqual(tuple(models["gliner"][x] for x in ("tp","fp","fn","tn")),(1,1,2,2))
        self.assertAlmostEqual(models["gliner"]["f1"],.4,places=4)

    def test_duplicate_ids_are_rejected(self):
        row={"id":"a","gold":True,"predictions":{"a":True}}
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            evaluate([row,dict(row)])
    def test_unpaired_or_missing_predictions_are_rejected(self):
        rows=[
            {"id":"a","gold":True,"predictions":{"foo":True,"bar":False}},
            {"id":"b","gold":False,"predictions":{"foo":False}},
        ]
        with self.assertRaisesRegex(ValueError,"paired"):
            evaluate(rows)
    def test_bad_labels_and_latencies_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([{"id":"x","gold":"yes","predictions":{"a":True}}])
        with self.assertRaises(ValueError):
            evaluate([{"id":"x","gold":False,"predictions":{"a":False},"latency_ms":{"a":-1}}])

    def test_sanitized_historical_result_arithmetic(self):
        p=ROOT/"benchmarks/decision_models_2026-10-16.json"
        self.assertTrue(p.is_file(),"The sanitized benchmark snapshot must be committed")
        doc=json.loads(p.read_text(encoding="utf8"))
        self.assertEqual(doc["same_40"]["n"],40)
        self.assertEqual(doc["production_335"]["n"],335)
        self.assertEqual(doc["production_335"]["positive"],135)
        selected={m["id"]:m for m in doc["production_335"]["methods"]}
        self.assertEqual([selected["current_v13_high_recall"][k]
                          for k in ("tp","fp","fn","tn")],[105,4,30,196])
        self.assertEqual([selected["gliner_direct_chinese"][k]
                          for k in ("tp","fp","fn","tn")],[76,38,59,162])
        s40={m["id"]:m for m in doc["same_40"]["methods"]}
        self.assertEqual([s40["d3_lite_5_noul_or_055"][k]
                          for k in ("tp","fp","fn","tn")],[19,9,1,11])
        self.assertEqual([s40["current_v13_high_recall"][k]
                          for k in ("tp","fp","fn","tn")],[15,1,5,19])
        for set_name in ("same_40","production_335"):
            section=doc[set_name]
            n=section["n"];pos=section["positive"];neg=section["negative"]
            self.assertEqual(pos+neg,n)
            for model in section["methods"]:
                tp,fp,fn,tn=(int(model[k]) for k in ("tp","fp","fn","tn"))
                self.assertEqual(tp+fp+fn+tn,n,(set_name,model["id"]))
                self.assertEqual(tp+fn,pos,(set_name,model["id"]))
                self.assertEqual(fp+tn,neg,(set_name,model["id"]))
                precision=tp/(tp+fp) if tp+fp else 0
                recall=tp/(tp+fn) if tp+fn else 0
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0
                self.assertAlmostEqual(model["precision"],precision,places=4)
                self.assertAlmostEqual(model["recall"],recall,places=4)
                self.assertAlmostEqual(model["f1"],f1,places=4)
if __name__=="__main__":
    unittest.main()
