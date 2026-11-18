"""
LF1: index-photos

Triggered by an S3 PUT (ObjectCreated:Put) on the photos bucket (B2).
1. Detect labels with Rekognition (detect_labels).
2. Read x-amz-meta-customLabels with head_object (S3 stores it lowercased as "customlabels").
3. Index {objectKey, bucket, createdTimestamp, labels} into the OpenSearch "photos" index.

No external dependencies: talks to OpenSearch with urllib3 (bundled with boto3 in the Lambda runtime)
using basic auth (OpenSearch fine-grained access control master user).

Environment variables:
  OS_HOST   e.g. search-photos-abc123.us-east-1.es.amazonaws.com   (no https://)
  OS_USER   master username
  OS_PASS   master password
  OS_INDEX  (optional) defaults to "photos"
"""
import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone

import boto3
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OS_HOST = os.environ.get("OS_HOST", "").replace("https://", "").rstrip("/")
OS_USER = os.environ.get("OS_USER", "")
OS_PASS = os.environ.get("OS_PASS", "")
OS_INDEX = os.environ.get("OS_INDEX", "photos")

s3 = boto3.client("s3")
rekognition = boto3.client("rekognition")
http = urllib3.PoolManager()

# "english" analyzer stems plurals, so a search for "dogs" matches the label "Dog".
INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "objectKey": {"type": "keyword"},
            "bucket": {"type": "keyword"},
            "createdTimestamp": {"type": "date", "format": "strict_date_hour_minute_second||strict_date_optional_time"},
            "labels": {"type": "text", "analyzer": "english", "fields": {"raw": {"type": "keyword"}}},
        }
    }
}


def os_request(method, path, body=None):
    headers = urllib3.make_headers(basic_auth=f"{OS_USER}:{OS_PASS}")
    headers["Content-Type"] = "application/json"
    resp = http.request(
        method,
        f"https://{OS_HOST}{path}",
        body=json.dumps(body) if body is not None else None,
        headers=headers,
    )
    text = resp.data.decode("utf-8") if resp.data else ""
    return resp.status, text


def ensure_index():
    status, _ = os_request("HEAD", f"/{OS_INDEX}")
    if status == 404:
        status, text = os_request("PUT", f"/{OS_INDEX}", INDEX_MAPPING)
        logger.info("Created index %s: %s %s", OS_INDEX, status, text)
    elif status >= 400:
        raise RuntimeError(f"OpenSearch HEAD /{OS_INDEX} returned {status}. Check OS_HOST/OS_USER/OS_PASS.")


def parse_custom_labels(metadata):
    # S3 lowercases user metadata keys: x-amz-meta-customLabels -> Metadata["customlabels"]
    raw = ""
    for key, value in (metadata or {}).items():
        if key.lower() == "customlabels":
            raw = value
            break
    return [label.strip() for label in raw.split(",") if label.strip()]


def dedupe(labels):
    seen, out = set(), []
    for label in labels:
        k = label.lower()
        if k not in seen:
            seen.add(k)
            out.append(label)
    return out


def index_object(bucket, key, event_time=None):
    # 1) Rekognition labels
    rek = rekognition.detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MaxLabels=50,
        MinConfidence=60,
    )
    rek_labels = [lbl["Name"] for lbl in rek.get("Labels", [])]

    # 2) Custom labels from S3 metadata (array A1)
    head = s3.head_object(Bucket=bucket, Key=key)
    custom_labels = parse_custom_labels(head.get("Metadata"))

    labels = dedupe(custom_labels + rek_labels)

    created = head.get("LastModified") or datetime.now(timezone.utc)
    doc = {
        "objectKey": key,
        "bucket": bucket,
        "createdTimestamp": created.strftime("%Y-%m-%dT%H:%M:%S"),
        "labels": labels,
    }

    # 3) Index into OpenSearch. Doc id = bucket/key so re-uploads overwrite instead of duplicating.
    doc_id = urllib.parse.quote(f"{bucket}/{key}", safe="")
    status, text = os_request("PUT", f"/{OS_INDEX}/_doc/{doc_id}", doc)
    if status >= 300:
        raise RuntimeError(f"Indexing failed ({status}): {text}")

    logger.info("Indexed %s/%s custom=%s rekognition=%s", bucket, key, custom_labels, rek_labels)
    return doc


def lambda_handler(event, context):
    logger.info("Event: %s", json.dumps(event))
    ensure_index()

    indexed = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        # Keys in S3 events are URL-encoded ("my+photo.jpg" -> "my photo.jpg")
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        indexed.append(index_object(bucket, key, record.get("eventTime")))

    return {"statusCode": 200, "body": json.dumps({"indexed": indexed})}
