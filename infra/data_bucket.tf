# The data bucket: bronze (raw, permanent), derived (rebuildable), selftest (scratch). ADR-004.
#
# NEVER weaken prevent_destroy, versioning, or the deny statements below (CLAUDE.md hard rule 8).
# infra/tests/data_bucket.tftest.hcl fails if any of them is removed.

resource "aws_s3_bucket" "data" {
  bucket        = local.data_bucket_name
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

# A delete or overwrite keeps the old bytes as a noncurrent version.
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket = aws_s3_bucket.data.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        # Bronze is sacred (hard rule 1). Applies to every principal, administrators included;
        # removing it takes a reviewed Terraform change and an approved apply.
        Sid       = "DenyBronzeDeletes"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource  = "${aws_s3_bucket.data.arn}/bronze/*"
      },
      {
        # Every write must carry If-None-Match, so nothing can overwrite an existing object.
        # selftest/ is included so the M0 self-test can prove this statement works (ADR-004 VERIFY).
        Sid       = "DenyUnconditionalWrites"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = ["${aws_s3_bucket.data.arn}/bronze/*", "${aws_s3_bucket.data.arn}/selftest/*"]
        Condition = { Null = { "s3:if-none-match" = "true" } }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.data]
}

# No rule ever expires or moves anything under bronze/ (ADR-004, decision 4).
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # derived/ partitions are rewritten whole; without this, versioning keeps every rewrite forever.
  rule {
    id     = "derived-expire-old-versions"
    status = "Enabled"

    filter {
      prefix = "derived/"
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  rule {
    id     = "selftest-expire"
    status = "Enabled"

    filter {
      prefix = "selftest/"
    }

    expiration {
      days = 1
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.data]
}
