locals {
  ecs_assume_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# Execution role — ECS agent uses this to pull ECR images and push logs
resource "aws_iam_role" "execution" {
  name               = "${var.app_name}-execution-role"
  assume_role_policy = local.ecs_assume_policy
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Task role — what the container process itself is permitted to call
resource "aws_iam_role" "task" {
  name               = "${var.app_name}-task-role"
  assume_role_policy = local.ecs_assume_policy
}

resource "aws_iam_role_policy" "task_s3_env" {
  name = "read-env-from-s3"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.env.arn,
        "${aws_s3_bucket.env.arn}/*"
      ]
    }]
  })
}
