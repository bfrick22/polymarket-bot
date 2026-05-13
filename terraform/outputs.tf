output "ecr_repository_url" {
  description = "ECR URL — use as your docker build/push target"
  value       = aws_ecr_repository.bot.repository_url
}

output "secrets_manager_arn" {
  description = "Secrets Manager ARN — populate this with your .env values"
  value       = aws_secretsmanager_secret.config.arn
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.bot.name
}

output "ecs_service_name" {
  value = aws_ecs_service.bot.name
}

output "deploy_commands" {
  description = "Steps to populate secrets, build image, and deploy after terraform apply"
  value       = <<-EOT

    # 1. Populate Secrets Manager from your .env file (run once, re-run to update)
    aws secretsmanager put-secret-value \
      --secret-id ${aws_secretsmanager_secret.config.arn} \
      --region ${var.aws_region} \
      --secret-string "$(python3 -c "
    import json, re
    vals = {}
    for line in open('.env'):
        line = line.strip()
        if not line or line.startswith('#'): continue
        k, _, v = line.partition('=')
        vals[k.strip()] = v.strip()
    print(json.dumps(vals))
    ")"

    # 2. Authenticate Docker to ECR
    aws ecr get-login-password --region ${var.aws_region} | \
      docker login --username AWS --password-stdin ${aws_ecr_repository.bot.repository_url}

    # 3. Build and push (--platform required on Apple Silicon)
    docker build --platform linux/amd64 -t ${aws_ecr_repository.bot.repository_url}:latest .
    docker push ${aws_ecr_repository.bot.repository_url}:latest

    # 4. Force a new deployment to pick up latest image/secrets
    aws ecs update-service --cluster ${aws_ecs_cluster.bot.name} \
      --service ${aws_ecs_service.bot.name} --force-new-deployment \
      --region ${var.aws_region}
  EOT
}
