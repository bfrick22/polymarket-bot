#!/usr/bin/env python3
"""
Loads .env from S3 into os.environ, then launches main.py.
Only runs the S3 fetch when ENV_BUCKET is set (i.e. on ECS).
Local runs still use the .env file via python-dotenv in config.py.
"""
import os
import sys
import runpy


def load_env_from_s3():
    bucket = os.environ.get("ENV_BUCKET")
    if not bucket:
        return

    key = os.environ.get("ENV_KEY", ".env")
    import boto3

    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        content = obj["Body"].read().decode("utf-8")
    except Exception as exc:
        print(f"[entrypoint] ERROR: could not load s3://{bucket}/{key}: {exc}", flush=True)
        sys.exit(1)

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if k:
            os.environ.setdefault(k, v)

    print(f"[entrypoint] loaded env from s3://{bucket}/{key}", flush=True)


if __name__ == "__main__":
    load_env_from_s3()
    sys.path.insert(0, "/app/src")
    runpy.run_path("/app/src/main.py", run_name="__main__")
