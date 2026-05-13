resource "aws_security_group" "bot" {
  name        = "${var.app_name}-sg"
  description = "Outbound-only for polymarket bot"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_cluster" "bot" {
  name = var.app_name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_ecs_task_definition" "bot" {
  family                   = var.app_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = var.app_name
    image     = "${aws_ecr_repository.bot.repository_url}:${var.image_tag}"
    essential = true

    environment = [
      { name = "ENV_BUCKET", value = aws_s3_bucket.env.bucket },
      { name = "ENV_KEY",    value = ".env" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.bot.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import sys; sys.exit(0)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 15
    }
  }])
}

resource "aws_ecs_service" "bot" {
  name            = var.app_name
  cluster         = aws_ecs_cluster.bot.id
  task_definition = aws_ecs_task_definition.bot.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # assign_public_ip avoids a NAT gateway (~$32/mo) since we're in public subnets
  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.bot.id]
    assign_public_ip = true
  }
}
