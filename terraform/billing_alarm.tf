# AWS billing metrics only exist in us-east-1 — all resources here use that provider alias

variable "billing_alarm_email" {
  description = "Email address to notify when the $20 billing threshold is breached"
  type        = string
  default     = "bfrick22@gmail.com"
}

variable "billing_alarm_threshold" {
  description = "USD amount that triggers the billing alarm"
  type        = number
  default     = 20
}

resource "aws_sns_topic" "billing_alarm" {
  provider = aws.us_east_1
  name     = "${var.app_name}-billing-alarm"
}

resource "aws_sns_topic_subscription" "billing_alarm_email" {
  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.billing_alarm.arn
  protocol  = "email"
  endpoint  = var.billing_alarm_email
}

resource "aws_cloudwatch_metric_alarm" "billing" {
  provider            = aws.us_east_1
  alarm_name          = "${var.app_name}-monthly-bill"
  alarm_description   = "Alert when estimated AWS charges exceed $${var.billing_alarm_threshold}"
  namespace           = "AWS/Billing"
  metric_name         = "EstimatedCharges"
  statistic           = "Maximum"
  period              = 86400  # 24 hours — billing metrics update ~3x/day
  evaluation_periods  = 1
  threshold           = var.billing_alarm_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Currency = "USD"
  }

  alarm_actions = [aws_sns_topic.billing_alarm.arn]
  ok_actions    = [aws_sns_topic.billing_alarm.arn]
}
