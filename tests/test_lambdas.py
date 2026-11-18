"""Offline tests for LF1/LF2 with AWS + OpenSearch mocked. Run: python -m pytest backend/tests -q"""
import importlib.util
import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from unittest import mock

os.environ.update({"OS_HOST": "search-photos-x.us-east-1.es.amazonaws.com", "OS_USER": "u", "OS_PASS": "p",
                   "BOT_ID": "BOT123", "BOT_ALIAS_ID": "TSTALIASID", "AWS_REGION": "us-east-1",
                   "AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x"})

ROOT = pathlib.Path(__file__).resolve().parents[1] / "lambdas"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / name / "lambda_function.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResp:
    def __init__(self, status, body=None):
        self.status = status
        self.data = json.dumps(body).encode() if body is not None else b""


# ---------------- LF1 ----------------
def test_index_photos_merges_custom_and_rekognition_labels():
    lf1 = load("index-photos")
    calls = []

    def fake_request(method, url, body=None, headers=None):
        calls.append((method, url, json.loads(body) if body else None, headers))
        return FakeResp(404) if method == "HEAD" else FakeResp(201, {"result": "created"})

    lf1.http = mock.Mock(request=fake_request)
    lf1.rekognition = mock.Mock(detect_labels=mock.Mock(return_value={
        "Labels": [{"Name": "Dog"}, {"Name": "Animal"}, {"Name": "Park"}]}))
    lf1.s3 = mock.Mock(head_object=mock.Mock(return_value={
        "Metadata": {"customlabels": "Sam, Sally,dog"},
        "LastModified": datetime(2026, 11, 2, 12, 40, 2, tzinfo=timezone.utc)}))

    event = {"Records": [{"eventTime": "x", "s3": {"bucket": {"name": "b2"}, "object": {"key": "my+dog+photo.jpg"}}}]}
    out = lf1.lambda_handler(event, None)
    assert out["statusCode"] == 200

    # index created with english analyzer, then doc indexed
    assert calls[1][0] == "PUT" and calls[1][1].endswith("/photos")
    assert calls[1][2]["mappings"]["properties"]["labels"]["analyzer"] == "english"
    method, url, doc, headers = calls[2]
    assert method == "PUT" and "/photos/_doc/" in url
    assert doc == {"objectKey": "my dog photo.jpg", "bucket": "b2", "createdTimestamp": "2026-11-02T12:40:02",
                   "labels": ["Sam", "Sally", "dog", "Animal", "Park"]}  # "Dog" deduped against custom "dog"
    assert headers["authorization"].startswith("Basic ")


def test_parse_custom_labels_handles_missing_and_case():
    lf1 = load("index-photos")
    assert lf1.parse_custom_labels({}) == []
    assert lf1.parse_custom_labels({"CustomLabels": " a , ,b "}) == ["a", "b"]


# ---------------- LF2 ----------------
def lex_resp(intent, slots):
    def s(v):
        return {"value": {"originalValue": v, "interpretedValue": v}} if v else None
    return {"sessionState": {"intent": {"name": intent, "slots": {k: s(v) for k, v in slots.items()}}}}


def run_search(lf2, q, lex_response, hits=()):
    lf2.lex = mock.Mock(recognize_text=mock.Mock(return_value=lex_response))
    sent = {}

    def fake_request(method, url, body=None, headers=None):
        sent["query"] = json.loads(body)
        return FakeResp(200, {"hits": {"hits": [{"_source": h} for h in hits]}})

    lf2.http = mock.Mock(request=fake_request)
    out = lf2.lambda_handler({"queryStringParameters": {"q": q}}, None)
    return out, sent.get("query")


def test_search_two_keywords_or_query_and_presigned_urls():
    lf2 = load("search-photos")
    hits = [{"objectKey": "a.jpg", "bucket": "b2", "labels": ["Dog"]},
            {"objectKey": "a.jpg", "bucket": "b2", "labels": ["Dog"]},
            {"objectKey": "c.jpg", "bucket": "b2", "labels": ["Cat"]}]
    out, query = run_search(lf2, "show me cats and dogs",
                            lex_resp("SearchIntent", {"keyword1": "cats", "keyword2": "dogs"}), hits)
    body = json.loads(out["body"])
    assert out["statusCode"] == 200 and out["headers"]["Access-Control-Allow-Origin"] == "*"
    should = query["query"]["bool"]["should"]
    assert [c["match"]["labels"]["query"] for c in should] == ["cats", "dogs"]
    assert query["query"]["bool"]["minimum_should_match"] == 1
    assert len(body["results"]) == 2  # duplicate a.jpg removed
    assert body["results"][0]["labels"] == ["Dog"]
    assert "X-Amz-Signature" in body["results"][0]["url"]


def test_search_splits_compound_slot_and_strips_stopwords():
    lf2 = load("search-photos")
    _, query = run_search(lf2, "photos of trees and birds",
                          lex_resp("SearchIntent", {"keyword1": "trees and birds", "keyword2": None}))
    assert [c["match"]["labels"]["query"] for c in query["query"]["bool"]["should"]] == ["trees", "birds"]


def test_search_no_keywords_returns_empty():
    lf2 = load("search-photos")
    out, query = run_search(lf2, "hello there", lex_resp("FallbackIntent", {}))
    assert json.loads(out["body"]) == {"results": []} and query is None
    out, _ = run_search(lf2, "", lex_resp("SearchIntent", {}))
    assert json.loads(out["body"]) == {"results": []}


def test_search_error_returns_swagger_error_shape():
    lf2 = load("search-photos")
    lf2.lex = mock.Mock(recognize_text=mock.Mock(side_effect=RuntimeError("boom")))
    out = lf2.lambda_handler({"queryStringParameters": {"q": "dogs"}}, None)
    assert out["statusCode"] == 500 and json.loads(out["body"]) == {"code": 500, "message": "boom"}
