import ast
import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

import steam_scraper_support as support


def notebook_functions():
    nb = json.loads(Path(__file__).with_name("PLN_Scrapping_Dados.ipynb").read_text(encoding="utf-8"))
    code_cells = [cell for cell in nb["cells"] if cell["cell_type"] == "code"
                  and not "".join(cell["source"]).lstrip().startswith("%pip ")]
    ns = {"pasta_brutos": Path(__file__).resolve().parent.parent / "_DadosBrutos"}
    exec("".join(code_cells[1]["source"]), ns)
    for i in (2, 3, 4, 6):
        tree = ast.parse("".join(code_cells[i]["source"]))
        tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ImportFrom))]
        exec(compile(tree, "<notebook>", "exec"), ns)
    ns.update(urlJogos="https://api.example", urlLoja="https://store.example",
              token="test", steam_web_api_limiter=None)
    return ns


class ScraperTests(unittest.TestCase):
    def test_fast_collection_filters_games_and_limits_both_sentiments(self):
        ns = notebook_functions()
        def response(url, *, params, **kwargs):
            appid = int(url.rsplit("/", 1)[1])
            if params["review_type"] == "all":
                data = {"success": 1, "query_summary": {
                    "total_reviews": 99 if appid == 1 else 100}}
            else:
                self.assertEqual(appid, 2)
                self.assertEqual(params["num_per_page"], 10)
                data = {"success": 1, "reviews": [
                    {"review": str(i), "voted_up": params["review_type"] == "positive"}
                    for i in range(12)]}
            return Mock(json=Mock(return_value=data))
        ns["steam_get"] = Mock(side_effect=response)
        ns["load_review_checkpoint"] = Mock(return_value=([], set()))
        ns["save_review_checkpoint"] = Mock()
        games = pd.DataFrame([{"appid": 1, "name": "Small"},
                              {"appid": 2, "name": "Eligible"}])
        with patch.object(pd, "read_csv", return_value=games):
            result = ns["coletar_reviews_rapido"](workers=2)
        self.assertEqual(result.groupby(["appid", "review_type"]).size().to_dict(),
                         {(2, "positive"): 10, (2, "negative"): 10})
        self.assertFalse(ns["load_review_checkpoint"].call_args.args[2])

    def test_review_threshold_and_sentiment_limit(self):
        for total in (99, 100, 150):
            for sentiment in ("positive", "negative"):
                with self.subTest(total=total, sentiment=sentiment):
                    ns = notebook_functions()
                    sample = [{"review": str(i)} for i in range(12)]
                    ns["steam_get"] = Mock(side_effect=[
                        Mock(json=Mock(return_value={"success": 1,
                            "query_summary": {"total_reviews": total}})),
                        Mock(json=Mock(return_value={"success": 1, "reviews": sample})),
                    ])
                    result = ns["buscar_reviews_jogo"](10, sentiment)
                    self.assertEqual(result, sample[:10] if total >= 100 else [])
                    calls = ns["steam_get"].call_args_list
                    self.assertEqual(calls[0].kwargs["params"]["review_type"], "all")
                    self.assertEqual(calls[0].kwargs["params"]["language"], "all")
                    self.assertEqual(len(calls), 2 if total >= 100 else 1)
                    if total >= 100:
                        self.assertEqual(calls[1].kwargs["params"]["review_type"], sentiment)
                        self.assertEqual(calls[1].kwargs["params"]["num_per_page"], 10)

    def test_description_limit_and_resume(self):
        ns = notebook_functions()
        ns['buscar_informacoes_jogo'] = Mock(return_value={'description': 'New', 'genres': 'Action'})
        ns['atomic_csv'] = Mock()
        games = pd.DataFrame([
            {'appid': 1, 'name': 'Done', 'description': 'Existing'},
            {'appid': 2, 'name': 'Pending', 'description': ''},
            {'appid': 3, 'name': 'Later', 'description': ''},
        ])
        with patch.object(pd, 'read_csv', return_value=games):
            result = ns['atualizar_csv_com_informacoes_rapido'](max_jogos=1)
        self.assertEqual(result['description'].tolist(), ['Existing', 'New', ''])
        self.assertEqual(result.attrs['benchmark']['processed'], 1)
        self.assertEqual(result.attrs['benchmark']['with_description'], 1)
        ns['buscar_informacoes_jogo'].assert_called_once()

    def test_configure_preserves_cooldown(self):
        gate = support.RequestGate()
        gate.defer(60)
        deadline = gate.next_request
        gate.configure(0.75)
        self.assertEqual(gate.next_request, deadline)
        for invalid in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                gate.configure(invalid)

    def test_timeout_and_429_retry(self):
        client = Mock()
        limited = Mock(status_code=429, headers={"Retry-After": "42"})
        success = Mock(status_code=200)
        client.get.side_effect = [requests.Timeout(), limited, success]
        gate = Mock()
        with patch.object(support, "gate_for", return_value=gate):
            self.assertIs(support.steam_get("https://store.example", session=client), success)
        self.assertEqual(client.get.call_count, 3)
        self.assertEqual(gate.acquire.call_count, 3)
        gate.defer.assert_any_call(42.0)

    def test_last_429_still_sets_shared_cooldown(self):
        response = Mock(status_code=429, headers={"Retry-After": "60"})
        response.raise_for_status.side_effect = requests.HTTPError()
        gate = Mock()
        with patch.object(support, "gate_for", return_value=gate):
            with self.assertRaises(requests.HTTPError):
                support.steam_get("https://store.example", retries=1,
                                  session=Mock(get=Mock(return_value=response)))
        gate.defer.assert_called_once_with(60.0)
        self.assertIs(support.gate_for("https://same.example/a"),
                      support.gate_for("https://same.example/b"))

    def test_catalog_preserves_enrichment(self):
        ns = notebook_functions()
        ns["steam_get"] = Mock(return_value=Mock(json=Mock(return_value={
            "response": {"apps": [{"appid": 10, "name": "Updated"}]}})))
        existing = pd.DataFrame([{"appid": 10, "name": "Old", "user_tags": "Action"},
                                 {"appid": 20, "name": "Other", "user_tags": "Puzzle"}])
        ns["atomic_csv"] = Mock()
        with patch.object(Path, "exists", return_value=True), patch.object(pd, "read_csv", return_value=existing):
            result = ns["listar_jogos_steam"](quantidade=1)
        self.assertEqual(result.set_index("appid").at[10, "user_tags"], "Action")
        self.assertEqual(result.set_index("appid").at[10, "name"], "Updated")
        self.assertEqual(len(result), 2)

    def test_http_error_reaches_selenium(self):
        ns = notebook_functions()
        ns["buscar_tags_jogo_requests"] = Mock(side_effect=requests.HTTPError())
        ns["criar_driver_selenium"] = Mock()
        ns["buscar_tags_jogo_selenium"] = Mock(return_value=["Action"])
        ns["atomic_csv"] = Mock()
        games = pd.DataFrame([{"appid": 10, "name": "Test"}])
        with patch.object(pd, "read_csv", return_value=games), patch.object(support, "gate_for", return_value=Mock()):
            result = ns["atualizar_csv_com_tags_rapido"](workers=1)
        self.assertEqual(result.at[0, "user_tags"], "Action")
        ns["buscar_tags_jogo_selenium"].assert_called_once()

    def test_empty_reviews_have_headers_and_completion(self):
        ns = notebook_functions()
        ns["buscar_reviews_jogo"] = Mock(return_value=[])
        ns["load_review_checkpoint"] = Mock(return_value=([], set()))
        ns["save_review_checkpoint"] = Mock()
        games = pd.DataFrame([{"appid": 10, "name": "Test"}])
        with patch.object(pd, "read_csv", return_value=games):
            result = ns["coletar_reviews_rapido"](workers=1)
        self.assertEqual(list(pd.read_csv(io.StringIO(result.to_csv(index=False))).columns), support.REVIEW_COLUMNS)
        completed = ns["save_review_checkpoint"].call_args.args[1]
        self.assertEqual(completed, {(10, "positive"), (10, "negative")})
        ns["load_review_checkpoint"].return_value = ([], completed)
        ns["buscar_reviews_jogo"].reset_mock()
        with patch.object(pd, "read_csv", return_value=games):
            ns["coletar_reviews_rapido"](workers=1, pular_existentes=True)
        ns["buscar_reviews_jogo"].assert_not_called()

    def test_load_zero_result_ledger(self):
        with patch.object(Path, "exists", return_value=True), patch.object(pd, "read_csv", return_value=pd.DataFrame(columns=support.REVIEW_COLUMNS)), patch.object(Path, "read_text", return_value=json.dumps({"quantity": 10, "completed": [[10, "positive"]]})):
            rows, completed = support.load_review_checkpoint("reviews.csv", 10, True)
        self.assertEqual(rows, [])
        self.assertEqual(completed, {(10, "positive")})

    def test_failed_reviews_stay_pending(self):
        ns = notebook_functions()
        ns["buscar_reviews_jogo"] = Mock(side_effect=requests.Timeout())
        ns["load_review_checkpoint"] = Mock(return_value=([], set()))
        ns["save_review_checkpoint"] = Mock()
        with patch.object(pd, "read_csv", return_value=pd.DataFrame([{"appid": 10, "name": "Test"}])):
            ns["coletar_reviews_rapido"](workers=1)
        self.assertEqual(ns["save_review_checkpoint"].call_args.args[1], set())

    def test_checkpoint_does_not_advance_when_csv_write_fails(self):
        with patch.object(support, "atomic_csv", side_effect=OSError("disk full")), patch.object(Path, "write_text") as write:
            with self.assertRaises(OSError):
                support.save_review_checkpoint([], {(10, "positive")}, "reviews.csv", 10)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
