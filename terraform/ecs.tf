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

    # ECS injects these before the container starts — no app-side secret fetching needed.
    # valueFrom syntax for JSON secret keys: <secret_arn>:<json_key>::
    # The trader roster lives in src/traders.json (baked into the image), not here.
    secrets = [
      # --- Required wallet credentials ---
      { name = "PRIVATE_KEY",                  valueFrom = "${aws_secretsmanager_secret.config.arn}:PRIVATE_KEY::" },
      { name = "POLY_ADDRESS",                 valueFrom = "${aws_secretsmanager_secret.config.arn}:POLY_ADDRESS::" },

      # --- Phase 1: copy trading ---
      { name = "COPY_RATIO",                   valueFrom = "${aws_secretsmanager_secret.config.arn}:COPY_RATIO::" },
      { name = "COPY_RATIO_SMALL",             valueFrom = "${aws_secretsmanager_secret.config.arn}:COPY_RATIO_SMALL::" },
      { name = "MAX_TRADE_USD",                valueFrom = "${aws_secretsmanager_secret.config.arn}:MAX_TRADE_USD::" },
      { name = "POLL_INTERVAL_SEC",            valueFrom = "${aws_secretsmanager_secret.config.arn}:POLL_INTERVAL_SEC::" },
      { name = "RECENT_TRADES_LIMIT",          valueFrom = "${aws_secretsmanager_secret.config.arn}:RECENT_TRADES_LIMIT::" },
      { name = "MIN_SHARES",                   valueFrom = "${aws_secretsmanager_secret.config.arn}:MIN_SHARES::" },
      { name = "MIN_POSITION_USD",             valueFrom = "${aws_secretsmanager_secret.config.arn}:MIN_POSITION_USD::" },
      { name = "MAX_EXPOSURE_PER_MARKET_USD",  valueFrom = "${aws_secretsmanager_secret.config.arn}:MAX_EXPOSURE_PER_MARKET_USD::" },
      { name = "MIRROR_SELLS",                 valueFrom = "${aws_secretsmanager_secret.config.arn}:MIRROR_SELLS::" },
      { name = "MARKET_KEYWORDS",              valueFrom = "${aws_secretsmanager_secret.config.arn}:MARKET_KEYWORDS::" },

      # --- Phase 2: multi-outcome arbitrage scanner ---
      { name = "ARB_ENABLED",                  valueFrom = "${aws_secretsmanager_secret.config.arn}:ARB_ENABLED::" },
      { name = "ARB_POLL_INTERVAL_SEC",        valueFrom = "${aws_secretsmanager_secret.config.arn}:ARB_POLL_INTERVAL_SEC::" },
      { name = "ARB_THRESHOLD",                valueFrom = "${aws_secretsmanager_secret.config.arn}:ARB_THRESHOLD::" },
      { name = "ARB_MIN_EDGE",                 valueFrom = "${aws_secretsmanager_secret.config.arn}:ARB_MIN_EDGE::" },
      { name = "ARB_MAX_BASKET_USD",           valueFrom = "${aws_secretsmanager_secret.config.arn}:ARB_MAX_BASKET_USD::" },
      { name = "ARB_MIN_OUTCOMES",             valueFrom = "${aws_secretsmanager_secret.config.arn}:ARB_MIN_OUTCOMES::" },
      { name = "ARB_MAX_OUTCOMES",             valueFrom = "${aws_secretsmanager_secret.config.arn}:ARB_MAX_OUTCOMES::" },

      # --- Phase 3: ultra-short crypto scanner ---
      { name = "CRYPTO_5M_ENABLED",            valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_ENABLED::" },
      { name = "CRYPTO_5M_POLL_INTERVAL_SEC",  valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_POLL_INTERVAL_SEC::" },
      { name = "CRYPTO_5M_ASSETS",             valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_ASSETS::" },
      { name = "CRYPTO_5M_MAX_TRADE_USD",      valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_MAX_TRADE_USD::" },
      { name = "CRYPTO_5M_IMPULSE_BPS",        valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_IMPULSE_BPS::" },
      { name = "CRYPTO_5M_IMPULSE_WINDOW_SEC", valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_IMPULSE_WINDOW_SEC::" },
      { name = "CRYPTO_5M_NEUTRAL_BAND",       valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_NEUTRAL_BAND::" },
      { name = "CRYPTO_5M_SPREAD_THRESHOLD",   valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_SPREAD_THRESHOLD::" },
      { name = "CRYPTO_5M_MIN_SECONDS_LEFT",   valueFrom = "${aws_secretsmanager_secret.config.arn}:CRYPTO_5M_MIN_SECONDS_LEFT::" },
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
