output "ecr_repository_url" {
  description = "ECR URL — use as your docker build/push target"
  value       = aws_ecr_repository.bot.repository_url
}

output "s3_env_bucket" {
  description = "S3 bucket name — upload your .env file here"
  value       = aws_s3_bucket.env.bucket
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.bot.name
}

output "ecs_service_name" {
  value = aws_ecs_service.bot.name
}

output "deploy_commands" {
  description = "Steps to build, push, and upload env after terraform apply"
  value       = <<-EOT

    # 1. Authenticate Docker to ECR
    aws ecr get-login-password --region ${var.aws_region} | \
      docker login --username AWS --password-stdin ${aws_ecr_repository.bot.repository_url}

    # 2. Build and push (use --platform for Apple Silicon)
    docker build --platform linux/amd64 -t ${aws_ecr_repository.bot.repository_url}:latest .
    docker push ${aws_ecr_repository.bot.repository_url}:latest

    # 3. Upload your .env to S3
    aws s3 cp .env s3://${aws_s3_bucket.env.bucket}/.env

    # 4. Force a new deployment to pick up the latest image/env
    aws ecs update-service --cluster ${aws_ecs_cluster.bot.name} \
      --service ${aws_ecs_service.bot.name} --force-new-deployment \
      --region ${var.aws_region}
  EOT
}
