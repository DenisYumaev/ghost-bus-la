# Offline tests for the data bucket and budget (ADR-004). A mock AWS provider answers every call:
# nothing is created and no credentials are needed. Run: make tf-test
#
# These encode the guardrails that make "bronze is sacred" (CLAUDE.md hard rule 1) true in AWS,
# so weakening one fails CI before any plan reaches a human.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
}


# Mock providers can't import (imports.tf), so each imported resource gets an override: the
# test supplies the "existing" object, and the configuration's values are still what's asserted.

override_resource {
  target = aws_s3_bucket.data
  values = {
    arn = "arn:aws:s3:::la-ghost-bus-bronze-123456789012"
  }
}

override_resource {
  target = aws_s3_bucket_versioning.data
  values = {}
}

override_resource {
  target = aws_s3_bucket_public_access_block.data
  values = {}
}

override_resource {
  target = aws_s3_bucket_ownership_controls.data
  values = {}
}

override_resource {
  target = aws_s3_bucket_server_side_encryption_configuration.data
  values = {}
}

override_resource {
  target = aws_s3_bucket_policy.data
  values = {}
}

override_resource {
  target = aws_s3_bucket_lifecycle_configuration.data
  values = {}
}

override_resource {
  target = aws_budgets_budget.monthly
  values = {}
}

variables {
  budget_alert_email = "alerts@example.com"
}

run "keeps_the_imported_bucket_name" {
  command = apply

  assert {
    condition     = aws_s3_bucket.data.bucket == "la-ghost-bus-bronze-123456789012"
    error_message = "The data bucket is the one imported from the scrapped repo; its name can't change."
  }

  assert {
    condition     = aws_s3_bucket.data.force_destroy == false
    error_message = "force_destroy must be false."
  }

  assert {
    condition     = aws_s3_bucket_versioning.data.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning must stay on."
  }

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.data.block_public_acls,
      aws_s3_bucket_public_access_block.data.block_public_policy,
      aws_s3_bucket_public_access_block.data.ignore_public_acls,
      aws_s3_bucket_public_access_block.data.restrict_public_buckets,
    ])
    error_message = "All four public access block settings must be true."
  }
}

run "policy_denies_deleting_bronze_for_everyone" {
  command = apply

  assert {
    condition = anytrue([
      for s in jsondecode(aws_s3_bucket_policy.data.policy).Statement :
      s.Effect == "Deny" && s.Principal == "*"
      && contains(s.Action, "s3:DeleteObject")
      && contains(s.Action, "s3:DeleteObjectVersion")
      && s.Resource == "${aws_s3_bucket.data.arn}/bronze/*"
      && try(s.Condition, null) == null
    ])
    error_message = "The policy must deny DeleteObject and DeleteObjectVersion on bronze/* for every principal, with no condition."
  }
}

run "policy_denies_unconditional_writes_to_bronze_and_selftest" {
  command = apply

  assert {
    condition = anytrue([
      for s in jsondecode(aws_s3_bucket_policy.data.policy).Statement :
      s.Effect == "Deny" && s.Principal == "*" && s.Action == "s3:PutObject"
      && toset(s.Resource) == toset([
        "${aws_s3_bucket.data.arn}/bronze/*",
        "${aws_s3_bucket.data.arn}/selftest/*",
      ])
      && s.Condition.Null["s3:if-none-match"] == "true"
    ])
    error_message = "The policy must deny PutObject on bronze/* and selftest/* when If-None-Match is absent."
  }
}

run "policy_denies_requests_without_tls" {
  command = apply

  assert {
    condition = anytrue([
      for s in jsondecode(aws_s3_bucket_policy.data.policy).Statement :
      s.Effect == "Deny" && try(s.Condition.Bool["aws:SecureTransport"], null) == "false"
    ])
    error_message = "The policy must deny any request not made over TLS."
  }
}

run "no_lifecycle_rule_touches_bronze" {
  command = apply

  # Every rule except the multipart cleanup must be scoped to a prefix outside bronze/.
  assert {
    condition = alltrue([
      for r in aws_s3_bucket_lifecycle_configuration.data.rule :
      length(r.abort_incomplete_multipart_upload) > 0
      || !startswith(one(r.filter).prefix, "bronze/")
    ])
    error_message = "No expiration or transition rule may apply to bronze/."
  }

  # The unscoped rule may only abort unfinished uploads; it must never expire or move objects.
  assert {
    condition = alltrue([
      for r in aws_s3_bucket_lifecycle_configuration.data.rule :
      length(r.expiration) == 0 && length(r.noncurrent_version_expiration) == 0 && length(r.transition) == 0
      if length(r.abort_incomplete_multipart_upload) > 0
    ])
    error_message = "The bucket-wide rule must only abort incomplete multipart uploads."
  }

  # No transitions anywhere: bronze never moves to a colder class (ADR-004).
  assert {
    condition     = alltrue([for r in aws_s3_bucket_lifecycle_configuration.data.rule : length(r.transition) == 0])
    error_message = "No storage-class transitions."
  }
}

run "derived_and_selftest_lifecycles" {
  command = apply

  assert {
    condition = anytrue([
      for r in aws_s3_bucket_lifecycle_configuration.data.rule :
      one(r.filter).prefix == "derived/" && one(r.noncurrent_version_expiration).noncurrent_days == 7
    ])
    error_message = "Old versions under derived/ must expire after 7 days."
  }

  assert {
    condition = anytrue([
      for r in aws_s3_bucket_lifecycle_configuration.data.rule :
      one(r.filter).prefix == "selftest/" && one(r.expiration).days == 1
    ])
    error_message = "selftest/ objects must expire after 1 day."
  }
}

run "budget_alerts_at_50_80_100_percent" {
  command = apply

  assert {
    condition     = aws_budgets_budget.monthly.limit_amount == "40" && aws_budgets_budget.monthly.time_unit == "MONTHLY"
    error_message = "Budget must be $40 a month (infra spec, section 2)."
  }

  assert {
    condition = toset([
      for n in aws_budgets_budget.monthly.notification : n.threshold if n.notification_type == "ACTUAL"
    ]) == toset([50, 80, 100])
    error_message = "Actual-spend alerts must fire at 50%, 80%, and 100%."
  }

  assert {
    condition = alltrue([
      for n in aws_budgets_budget.monthly.notification :
      n.subscriber_email_addresses == toset(["alerts@example.com"])
    ])
    error_message = "Every alert must go to budget_alert_email."
  }
}
