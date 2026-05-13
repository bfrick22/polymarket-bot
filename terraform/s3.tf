resource "aws_s3_bucket" "env" {
  bucket = "${var.app_name}-env-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "env" {
  bucket = aws_s3_bucket.env.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "env" {
  bucket                  = aws_s3_bucket.env.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "env" {
  bucket = aws_s3_bucket.env.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
