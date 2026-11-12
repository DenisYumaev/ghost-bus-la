# If the VM's hardware or OS fails, AWS fixes it and emails the owner (infra spec, section 2).
# The external heartbeat (ingest PRs) covers failures these can't see, such as a crashed container.

resource "aws_sns_topic" "ops_alerts" {
  name = "ghost-bus-la-ops-alerts"
}

# AWS emails a confirmation link to this address after the first apply. Alerts are only
# delivered once the link is clicked.
resource "aws_sns_topic_subscription" "ops_email" {
  topic_arn = aws_sns_topic.ops_alerts.arn
  protocol  = "email"
  endpoint  = var.budget_alert_email
}

# System check: the AWS hardware or network under the VM. "Recover" moves the same instance,
# with its disk, IP, and ID, to healthy hardware.
resource "aws_cloudwatch_metric_alarm" "system_check" {
  alarm_name          = "ghost-bus-la-system-status-check"
  alarm_description   = "AWS-side failure under the VM; auto-recover. Runbook: docs/runbook.md#vm-status-check"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = aws_instance.app.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = ["arn:aws:automate:us-west-2:ec2:recover", aws_sns_topic.ops_alerts.arn]
  ok_actions          = [aws_sns_topic.ops_alerts.arn]
}

# Instance check: the VM's own OS (out of memory, kernel panic, full disk). Recover can't fix
# that, but a reboot often does.
resource "aws_cloudwatch_metric_alarm" "instance_check" {
  alarm_name          = "ghost-bus-la-instance-status-check"
  alarm_description   = "VM OS unresponsive; reboot. Runbook: docs/runbook.md#vm-status-check"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  dimensions          = { InstanceId = aws_instance.app.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = ["arn:aws:automate:us-west-2:ec2:reboot", aws_sns_topic.ops_alerts.arn]
  ok_actions          = [aws_sns_topic.ops_alerts.arn]
}
