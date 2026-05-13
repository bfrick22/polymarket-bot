# Creates the secret shell — populate the value with the CLI command in outputs.tf
resource "aws_secretsmanager_secret" "config" {
  name                    = "${var.app_name}/config"
  description             = "All .env variables for the polymarket bot (JSON object)"
  recovery_window_in_days = 0
}
