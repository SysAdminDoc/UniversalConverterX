"""S3 / Backblaze B2 / MinIO upload adapter (F68).

Uses boto3 for multipart upload with progress tracking. Works with any
S3-compatible endpoint.

Config keys: endpoint_url, bucket, access_key, secret_key, prefix, region.
"""

import os

from .base import UploadDestination


class S3Destination(UploadDestination):
    NAME = "S3 / B2 / MinIO"

    def upload(self, file_path, metadata=None, progress_cb=None):
        cfg, err = self._validate_config(file_path=file_path)
        if err:
            return False, err
        try:
            import boto3
        except ImportError:
            return False, "boto3 not installed. Run: pip install boto3"

        try:
            s3 = boto3.client("s3", **self._client_kwargs(cfg))
            filename = os.path.basename(file_path)
            key = f"{cfg['prefix']}/{filename}" if cfg["prefix"] else filename
            file_size = os.path.getsize(file_path)

            cb = None
            if progress_cb and file_size > 0:
                sent = [0]
                def _track(bytes_amount):
                    sent[0] += bytes_amount
                    progress_cb(sent[0], file_size)
                cb = _track

            s3.upload_file(file_path, cfg["bucket"], key, Callback=cb)
            return True, f"Uploaded to s3://{cfg['bucket']}/{key}"
        except Exception as e:
            return False, f"S3 upload failed: {e}"

    def test_connection(self):
        cfg, err = self._validate_config()
        if err:
            return False, err
        try:
            import boto3
        except ImportError:
            return False, "boto3 not installed"

        try:
            s3 = boto3.client("s3", **self._client_kwargs(cfg))
            s3.head_bucket(Bucket=cfg["bucket"])
            return True, "Connection OK"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def _validate_config(self, file_path=None):
        cfg = self.config or {}
        bucket = str(cfg.get("bucket", "") or "").strip()
        access_key = str(cfg.get("access_key", "") or "").strip()
        secret_key = str(cfg.get("secret_key", "") or "").strip()
        region = str(cfg.get("region", "us-east-1") or "us-east-1").strip() or "us-east-1"
        endpoint = str(cfg.get("endpoint_url", "") or "").strip()
        prefix = str(cfg.get("prefix", "") or "").strip().strip("/")

        if not bucket:
            return None, "S3 bucket not configured"
        if not access_key:
            return None, "S3 access key not configured"
        if not secret_key:
            return None, "S3 secret key not configured"
        if file_path and not os.path.isfile(file_path):
            return None, "File not found"
        return {
            "bucket": bucket,
            "access_key": access_key,
            "secret_key": secret_key,
            "region": region,
            "endpoint_url": endpoint,
            "prefix": prefix,
        }, None

    @staticmethod
    def _client_kwargs(cfg):
        kwargs = {
            "aws_access_key_id": cfg["access_key"],
            "aws_secret_access_key": cfg["secret_key"],
            "region_name": cfg["region"],
        }
        if cfg.get("endpoint_url"):
            kwargs["endpoint_url"] = cfg["endpoint_url"]
        return kwargs
