# The VM's identity (ADR-004, decision 5). EC2 hands the instance short-lived credentials for
# this role through the metadata service; there are no access keys anywhere.

resource "aws_iam_role" "app" {
  name        = "ghost-bus-la-app"
  description = "Ghost Bus LA VM: archive to S3, SSM access. No delete on bronze."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "ghost-bus-la-app"
  role = aws_iam_role.app.name
}

# Session Manager: shell access and running commands, without SSH.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "app_s3" {
  name = "data-bucket-access"
  role = aws_iam_role.app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Write and read raw and derived data. Deliberately no delete on bronze/: the bucket
        # policy denies it anyway, and the role shouldn't even ask (least privilege).
        Sid    = "ReadWriteData"
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject"]
        Resource = [
          "${aws_s3_bucket.data.arn}/bronze/*",
          "${aws_s3_bucket.data.arn}/derived/*",
        ]
      },
      {
        # derived/ partitions are rewritten whole, which needs delete.
        Sid      = "RewriteDerived"
        Effect   = "Allow"
        Action   = ["s3:DeleteObject"]
        Resource = "${aws_s3_bucket.data.arn}/derived/*"
      },
      {
        # Scratch prefix for the conditional-write self-test (ADR-004 VERIFY).
        Sid      = "SelfTest"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.data.arn}/selftest/*"
      },
      {
        Sid      = "ListBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.data.arn
      },
      {
        # Runtime secrets (heartbeat URL, later database and email keys) live under one path.
        Sid      = "ReadOwnParameters"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:us-west-2:${local.account_id}:parameter/ghost-bus-la/*"
      },
    ]
  })
}
