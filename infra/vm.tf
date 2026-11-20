# The one VM (ADR-011, to be written): runs ingest now, the whole Docker Compose stack from M2.
# Shell access only through SSM Session Manager: no SSH key, never port 22. From M2, inbound 80
# and 443 reach Caddy, which fronts the API (infra spec, section 2).

variable "instance_type" {
  description = "t4g.small through M1, t4g.medium from M2 (SPEC section 3.4)."
  type        = string
  default     = "t4g.medium"

  # Hard rule 8: one instance, nothing above t4g.medium.
  validation {
    condition     = contains(["t4g.small", "t4g.medium"], var.instance_type)
    error_message = "instance_type must be t4g.small or t4g.medium (CLAUDE.md hard rule 8)."
  }
}

variable "availability_zone" {
  description = "Pinned so the VM and its disk never move zones between plans."
  type        = string
  default     = "us-west-2a"
}

# Canonical publishes the current Ubuntu image ID here; no hard-coded AMI IDs.
data "aws_ssm_parameter" "ubuntu_arm64" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
}

# The account's default VPC. Its subnets give instances a public IP for outbound traffic,
# so no NAT gateway is needed (hard rule 8: no NAT gateways).
data "aws_subnet" "app" {
  availability_zone = var.availability_zone
  default_for_az    = true
}

resource "aws_security_group" "app" {
  name        = "ghost-bus-la-app"
  description = "Ghost Bus LA VM: no inbound; all outbound (Metro, S3, SSM)."
  vpc_id      = data.aws_subnet.app.vpc_id

  # Only Caddy's ports. Never 22: shell access is through SSM.
  ingress {
    description = "HTTP: ACME certificate challenges and redirect to HTTPS"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS: the public API through Caddy"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Outbound HTTPS and DNS to Metro, GitLab, S3, SSM, and package mirrors"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "ghost-bus-la-app" }
}

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.ubuntu_arm64.insecure_value
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnet.app.id
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  associate_public_ip_address = true
  disable_api_termination     = true
  user_data                   = file("${path.module}/cloud-init.yaml")

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # lets containers reach the role credentials
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true
  }

  tags = { Name = "ghost-bus-la" }

  lifecycle {
    # Canonical publishes a new image every few weeks, and cloud-init only runs on first boot.
    # Without this, either change would make every later plan replace the VM and its spool.
    # Upgrading the OS is a deliberate, planned rebuild instead.
    ignore_changes = [ami, user_data]
  }
}

# A fixed address for the API's DNS record (infra spec, section 2): the auto-assigned public IP
# changes on every stop and start. Associating it replaces that IP, so outbound traffic (ingest,
# S3) uses this address too.
resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id
  tags     = { Name = "ghost-bus-la" }
}

output "public_ip" {
  description = "Point the api.<domain> A record here."
  value       = aws_eip.app.public_ip
}

output "instance_id" {
  description = "For SSM: aws ssm start-session --target <instance_id>"
  value       = aws_instance.app.id
}
