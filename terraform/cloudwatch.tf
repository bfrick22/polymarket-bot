resource "aws_cloudwatch_log_group" "bot" {
  name              = "/ecs/${var.app_name}"
  retention_in_days = 7
}
