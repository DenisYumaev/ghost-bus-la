# Offline tests for the VM, its role, and its recovery alarms (infra spec, sections 2 and 3).
# Mock provider: nothing is created. Run: make tf-test

mock_provider "aws" {

  # The provider validates ARNs, so the mock must return a real-looking one.
  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:us-west-2:123456789012:ghost-bus-la-ops-alerts"
    }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_ssm_parameter" {
    defaults = {
      value          = "ami-0123456789abcdef0"
      insecure_value = "ami-0123456789abcdef0"
    }
  }

  mock_data "aws_subnet" {
    defaults = {
      id     = "subnet-0123456789abcdef0"
      vpc_id = "vpc-0123456789abcdef0"
    }
  }
}

# The imported data-bucket resources need overrides here too (see data_bucket.tftest.hcl).
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

run "instance_size_is_capped" {
  command = plan

  variables {
    instance_type = "t4g.large"
  }

  # Hard rule 8: nothing above t4g.medium.
  expect_failures = [var.instance_type]
}

run "instance_is_small_arm_with_no_ssh_key" {
  command = apply

  assert {
    condition     = aws_instance.app.instance_type == "t4g.small"
    error_message = "Start on t4g.small through M1 (SPEC section 3.4)."
  }

  # key_name is computed, so the mock invents a value; check the source instead.
  # The real instance is also checked after apply (describe-instances shows no KeyName).
  assert {
    condition = alltrue([
      for f in fileset(path.module, "*.tf") : !strcontains(file("${path.module}/${f}"), "key_name")
    ])
    error_message = "No SSH key pair: no configuration file may set key_name. Shell access is through SSM only."
  }

  assert {
    condition     = aws_instance.app.disable_api_termination == true
    error_message = "Termination protection must be on."
  }
}

run "metadata_requires_imdsv2" {
  command = apply

  assert {
    condition     = aws_instance.app.metadata_options[0].http_tokens == "required"
    error_message = "IMDSv2 must be required, so stolen-URL tricks can't read the role's credentials."
  }

  assert {
    condition     = aws_instance.app.metadata_options[0].http_put_response_hop_limit == 2
    error_message = "Hop limit 2, so containers (one network hop further) can reach the role credentials."
  }
}

run "root_volume_is_encrypted_gp3_30gb" {
  command = apply

  assert {
    condition = (
      aws_instance.app.root_block_device[0].encrypted == true
      && aws_instance.app.root_block_device[0].volume_type == "gp3"
      && aws_instance.app.root_block_device[0].volume_size == 30
    )
    error_message = "Root volume must be 30 GB gp3, encrypted (infra spec, section 2)."
  }
}

run "security_group_has_no_inbound_rules" {
  command = apply

  assert {
    condition     = length(aws_security_group.app.ingress) == 0
    error_message = "No inbound rules through M1. Never port 22."
  }

  assert {
    condition     = contains(aws_instance.app.vpc_security_group_ids, aws_security_group.app.id)
    error_message = "The instance must use the app security group."
  }
}

run "role_can_write_bronze_but_never_delete_it" {
  command = apply

  # No statement in the role's policy grants a delete on bronze/.
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.app_s3.policy).Statement :
      !(
        anytrue([for a in flatten([s.Action]) : startswith(a, "s3:Delete") || a == "s3:*"])
        && anytrue([
          for r in flatten([s.Resource]) :
          contains(["${aws_s3_bucket.data.arn}/bronze/*", "${aws_s3_bucket.data.arn}/*"], r)
        ])
      )
    ])
    error_message = "The instance role must never be able to delete under bronze/ (or the whole bucket)."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_role_policy.app_s3.policy).Statement :
      contains(flatten([s.Action]), "s3:PutObject")
      && contains(flatten([s.Resource]), "${aws_s3_bucket.data.arn}/bronze/*")
    ])
    error_message = "The instance role must be able to put objects under bronze/."
  }
}

run "role_is_attached_and_ssm_managed" {
  command = apply

  assert {
    condition     = aws_instance.app.iam_instance_profile == aws_iam_instance_profile.app.name
    error_message = "The instance must run with the app instance profile."
  }

  assert {
    condition     = aws_iam_role_policy_attachment.ssm_core.policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    error_message = "The role needs AmazonSSMManagedInstanceCore for Session Manager."
  }

  assert {
    condition     = strcontains(aws_iam_role.app.assume_role_policy, "ec2.amazonaws.com")
    error_message = "Only EC2 may assume the instance role."
  }
}

run "failed_status_checks_trigger_recovery" {
  command = apply

  assert {
    condition = anytrue([
      for a in aws_cloudwatch_metric_alarm.system_check.alarm_actions : endswith(a, ":ec2:recover")
    ])
    error_message = "A failed system status check must trigger automatic recovery."
  }

  assert {
    condition = anytrue([
      for a in aws_cloudwatch_metric_alarm.instance_check.alarm_actions : endswith(a, ":ec2:reboot")
    ])
    error_message = "A failed instance status check must trigger a reboot."
  }

  assert {
    condition = alltrue([
      contains(aws_cloudwatch_metric_alarm.system_check.alarm_actions, aws_sns_topic.ops_alerts.arn),
      contains(aws_cloudwatch_metric_alarm.instance_check.alarm_actions, aws_sns_topic.ops_alerts.arn),
    ])
    error_message = "Both alarms must also email the owner through the ops SNS topic."
  }
}
