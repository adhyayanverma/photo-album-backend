"""
LF2: search-photos

Behind API Gateway GET /search?q=... (Lambda proxy integration).
1. Send q to the Lex V2 bot (SearchIntent) to pull out keywords from its slots.
2. If keywords were found, search the OpenSearch "photos" index (OR across keywords).
3. Return {"results": [{"url": ..., "labels": [...]}, ...]} per the swagger spec;
   empty results if Lex found no keywords.

Environment variables:
  OS_HOST, OS_USER, OS_PASS, OS_INDEX (optional, default "photos")
  BOT_ID          Lex V2 bot id (e.g. ABCDE12345)
  BOT_ALIAS_ID    Lex V2 alias id (TSTALIASID works for the draft/test alias)
  BOT_LOCALE_ID   (optional) default en_US
  URL_EXPIRY      (optional) presigned URL lifetime in seconds, default 3600
"""
import json
import logging
import os
import re
import uuid

import boto3
import urllib3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OS_HOST = os.environ.get("OS_HOST", "").replace("https://", "").rstrip("/")
OS_USER = os.environ.get("OS_USER", "")
OS_PASS = os.environ.get("OS_PASS", "")
OS_INDEX = os.environ.get("OS_INDEX", "photos")
BOT_ID = os.environ.get("BOT_ID", "")
BOT_ALIAS_ID = os.environ.get("BOT_ALIAS_ID", "TSTALIASID")
BOT_LOCALE_ID = os.environ.get("BOT_LOCALE_ID", "en_US")
URL_EXPIRY = int(os.environ.get("URL_EXPIRY", "3600"))

REGION = os.environ.get("AWS_REGION", "us-east-1")
lex = boto3.client("lexv2-runtime")
s3 = boto3.client("s3", region_name=REGION, config=Config(signature_version="s3v4"))
http = urllib3.PoolManager()

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key,x-amz-meta-customLabels",
    "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
    "Content-Type": "application/json",
}

STOPWORDS = {
    "show", "me", "photos", "photo", "pictures", "picture", "pics", "images", "image",
    "of", "with", "in", "them", "it", "the", "a", "an", "some", "find", "search", "for",
    "and", "or", "i", "want", "to", "see", "please", "get", "display",
}


def respond(status, body):
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body)}


def slot_value(slot):
    if not slot or not slot.get("value"):
        return None
    value = slot["value"]
    # originalValue = what the user typed; interpretedValue = Lex's resolution
    return value.get("originalValue") or value.get("interpretedValue")


def split_keywords(text):
    """'cats and dogs' -> ['cats', 'dogs']; keeps multi-word labels like 'golden retriever'."""
    parts = re.split(r",|&|\band\b|\bor\b", text.lower())
    out = []
    for part in parts:
        words = [w for w in re.findall(r"[a-z0-9\-']+", part) if w not in STOPWORDS]
        if words:
            out.append(" ".join(words))
    return out


def get_keywords_from_lex(query):
    resp = lex.recognize_text(
        botId=BOT_ID,
        botAliasId=BOT_ALIAS_ID,
        localeId=BOT_LOCALE_ID,
        sessionId=str(uuid.uuid4()),  # fresh session per search so no state carries over
        text=query,
    )
    intent = resp.get("sessionState", {}).get("intent", {}) or {}
    logger.info("Lex intent=%s slots=%s", intent.get("name"), json.dumps(intent.get("slots")))
    if intent.get("name") != "SearchIntent":
        return []

    keywords = []
    for _, slot in sorted((intent.get("slots") or {}).items()):
        value = slot_value(slot)
        if value:
            keywords.extend(split_keywords(value))

    # dedupe, keep order
    seen, unique = set(), []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


def search_opensearch(keywords):
    query = {
        "size": 100,
        "query": {
            "bool": {
                "should": [{"match": {"labels": {"query": k, "operator": "and"}}} for k in keywords],
                "minimum_should_match": 1,
            }
        },
    }
    headers = urllib3.make_headers(basic_auth=f"{OS_USER}:{OS_PASS}")
    headers["Content-Type"] = "application/json"
    resp = http.request(
        "POST",
        f"https://{OS_HOST}/{OS_INDEX}/_search",
        body=json.dumps(query),
        headers=headers,
    )
    data = json.loads(resp.data.decode("utf-8") or "{}")
    if resp.status >= 300:
        raise RuntimeError(f"OpenSearch search failed ({resp.status}): {data}")
    return [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]


def to_photo(doc):
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": doc["bucket"], "Key": doc["objectKey"]},
        ExpiresIn=URL_EXPIRY,
    )
    return {"url": url, "labels": doc.get("labels", [])}


def lambda_handler(event, context):
    logger.info("Event: %s", json.dumps(event))
    try:
        params = event.get("queryStringParameters") or {}
        q = (params.get("q") or event.get("q") or "").strip()
        if not q:
            return respond(200, {"results": []})

        keywords = get_keywords_from_lex(q)
        logger.info("Query %r -> keywords %s", q, keywords)
        if not keywords:
            return respond(200, {"results": []})

        docs = search_opensearch(keywords)
        seen, results = set(), []
        for doc in docs:
            key = (doc.get("bucket"), doc.get("objectKey"))
            if key not in seen:
                seen.add(key)
                results.append(to_photo(doc))
        return respond(200, {"results": results})
    except Exception as exc:  # return the swagger Error shape
        logger.exception("Search failed")
        return respond(500, {"code": 500, "message": str(exc)})
