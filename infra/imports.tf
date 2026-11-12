# Adopt the two resources the scrapped la-ghost-bus repo created (owner's decision, 2026-11-11),
# instead of destroying and recreating them. `terraform plan` shows each as "will be imported";
# after the apply these blocks are no-ops and can be deleted in a later PR.
#
# Each S3 settings resource is imported too, so Terraform updates the live settings in place
# rather than trying to create them.

import {
  to = aws_s3_bucket.data
  id = local.data_bucket_name
}

import {
  to = aws_s3_bucket_versioning.data
  id = local.data_bucket_name
}

import {
  to = aws_s3_bucket_public_access_block.data
  id = local.data_bucket_name
}

import {
  to = aws_s3_bucket_ownership_controls.data
  id = local.data_bucket_name
}

import {
  to = aws_s3_bucket_server_side_encryption_configuration.data
  id = local.data_bucket_name
}

import {
  to = aws_s3_bucket_policy.data
  id = local.data_bucket_name
}

import {
  to = aws_s3_bucket_lifecycle_configuration.data
  id = local.data_bucket_name
}

import {
  to = aws_budgets_budget.monthly
  id = "${local.account_id}:la-ghost-bus-monthly"
}
