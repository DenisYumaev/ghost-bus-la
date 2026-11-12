# Main configuration: the data bucket and the budget for now; the VM and its role arrive next.
# Credentials come from the standard AWS chain (AWS_PROFILE or the default profile).

provider "aws" {
  region = "us-west-2"

  default_tags {
    tags = {
      project    = "ghost-bus-la"
      managed_by = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Imported from the scrapped la-ghost-bus repo (owner's decision, 2026-11-11). Bucket names
  # can't be changed, so it keeps this name even though it holds derived/ and selftest/ too.
  data_bucket_name = "la-ghost-bus-bronze-${local.account_id}"
}

variable "budget_alert_email" {
  description = "Where budget alerts go. Set in terraform.tfvars (gitignored), never in code."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_alert_email))
    error_message = "budget_alert_email must be an email address."
  }
}

output "data_bucket_name" {
  description = "The bucket ingest writes to (BRONZE_BUCKET)."
  value       = aws_s3_bucket.data.bucket
}
