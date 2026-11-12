# Offline tests for the state bucket. `terraform test` runs them against a
# mock AWS provider: nothing is created and no credentials are needed.
# Run: terraform -chdir=infra/bootstrap test

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
}

run "bucket_name_includes_project_and_account" {
  command = apply

  assert {
    condition     = aws_s3_bucket.tfstate.bucket == "ghost-bus-la-tfstate-123456789012"
    error_message = "State bucket name must be ghost-bus-la-tfstate-<account_id>."
  }

  assert {
    condition     = aws_s3_bucket.tfstate.force_destroy == false
    error_message = "force_destroy must be false: deleting a bucket must never delete its objects."
  }
}

run "versioning_is_enabled" {
  command = apply

  assert {
    condition     = aws_s3_bucket_versioning.tfstate.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning must be on, so a corrupted state file can be rolled back."
  }
}

run "all_public_access_is_blocked" {
  command = apply

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.tfstate.block_public_acls,
      aws_s3_bucket_public_access_block.tfstate.block_public_policy,
      aws_s3_bucket_public_access_block.tfstate.ignore_public_acls,
      aws_s3_bucket_public_access_block.tfstate.restrict_public_buckets,
    ])
    error_message = "All four public access block settings must be true."
  }
}

run "encryption_and_ownership" {
  command = apply

  assert {
    condition = one([
      for rule in aws_s3_bucket_server_side_encryption_configuration.tfstate.rule :
      one(rule.apply_server_side_encryption_by_default).sse_algorithm
    ]) == "AES256"
    error_message = "State must be encrypted at rest with SSE-S3 (AES256)."
  }

  assert {
    condition     = aws_s3_bucket_ownership_controls.tfstate.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "ACLs must be disabled (BucketOwnerEnforced)."
  }
}

run "policy_denies_requests_without_tls" {
  command = apply

  assert {
    condition = anytrue([
      for s in jsondecode(aws_s3_bucket_policy.tfstate.policy).Statement :
      s.Effect == "Deny" && s.Condition.Bool["aws:SecureTransport"] == "false"
    ])
    error_message = "Bucket policy must deny any request not made over TLS."
  }
}

# Not tested here: default_tags. The mock provider doesn't merge provider default tags into
# tags_all, so the project tag is checked by reading the real `terraform plan` instead.
