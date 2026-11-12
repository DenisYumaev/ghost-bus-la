# Bootstrap: the S3 bucket that holds the main configuration's Terraform state (ADR-004, decision 6).
#
# This configuration keeps its own state LOCALLY (infra/bootstrap/terraform.tfstate, gitignored),
# because a bucket can't hold the state of the code that creates it. It is applied once and rarely
# touched again. If the local state is lost, nothing breaks: re-import the bucket with
#   terraform import aws_s3_bucket.tfstate ghost-bus-la-tfstate-<account_id>
# and prevent_destroy protects the bucket in the meantime.
#
# Credentials come from the standard AWS chain (AWS_PROFILE or the default profile). Nothing about
# credentials is written here (CLAUDE.md hard rule 9).

provider "aws" {
  region = "us-west-2"

  default_tags {
    tags = {
      project    = "ghost-bus-la"
      managed_by = "terraform/bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tfstate" {
  # Bucket names are global across every AWS account; the account ID makes this one unique
  # without committing it to the repo.
  bucket = "ghost-bus-la-tfstate-${data.aws_caller_identity.current.account_id}"

  # Never delete objects as a side effect of deleting the bucket.
  force_destroy = false

  lifecycle {
    # Any plan that would destroy this bucket fails. Losing it means losing track of every
    # resource the main configuration manages.
    prevent_destroy = true
  }
}

# Every state write keeps the previous version, so a corrupted or wrong state can be rolled back.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

# State files hold resource details in plain text; nothing about this bucket is ever public.
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Disable ACLs: access is controlled only by IAM and the bucket policy.
resource "aws_s3_bucket_ownership_controls" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3 is the AWS default; stating it makes it reviewable and testable.
# SSE-KMS would add a key to manage and a charge per request, for no gain at this scale.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Old state versions are kept 90 days: long enough to roll back, short enough not to pile up.
resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # A lifecycle rule on noncurrent versions needs versioning to exist first.
  depends_on = [aws_s3_bucket_versioning.tfstate]
}

# Written with jsonencode rather than an aws_iam_policy_document data source, so the offline
# tests can read the policy (a mocked data source would return placeholder text).
resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.tfstate.arn, "${aws_s3_bucket.tfstate.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })

  # The public access block must exist before any bucket policy is attached.
  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}

output "tfstate_bucket_name" {
  description = "Goes in infra/backend.hcl (gitignored) as `bucket`."
  value       = aws_s3_bucket.tfstate.bucket
}
