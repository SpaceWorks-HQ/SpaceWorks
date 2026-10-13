#!/usr/bin/env bash
# Compose dotenv single quotes suppress interpolation of operator-provided secrets.
env_setting() {
  local value="$2"
  value="${value//\\/\\\\}"
  value="${value//\'/\\\'}"
  printf "%s='%s'\n" "$1" "$value" >> .env
}

write_setup_environment() {
  [[ "${ANSWERS_CONFIRMED:-}" == yes ]] || die 'Confirm the deployment questions first.'
  (umask 077; set -o noclobber; : > .env)
  chmod 600 .env
  local scheme=http app_url origins proxy_count=1 layer=none
  [[ "$HTTPS_MODE" == 1 ]] || scheme=https
  app_url="$scheme://$WEBHOST"
  [[ "$HOSTING_MODEL" != 3 ]] || app_url="https://$MS_SUBDOMAIN.$PLATFORM_DOMAIN"
  origins="${SITE_ORIGINS:-$app_url}"
  [[ -z "$SITE_ORIGINS" ]] || app_url="${SITE_ORIGINS%%,*}"
  [[ "$HTTPS_MODE" != 2 ]] || layer=tls
  [[ "$HOSTING_MODEL" != 3 ]] || layer=saas
  [[ "$SHAPE" != 2 ]] || layer=single
  printf '%s\n' "$layer" > "$ROOT/.spaceworks-layer"
  export SPACEWORKS_COMPOSE_LAYER="$layer"
  # The database-pointer reader accepts literal assignments; generated alphanumerics
  # need no dotenv quotes and must match the passwords Compose gives PostgreSQL.
  printf 'POSTGRES_PASSWORD=%s\nPOSTGRES_APP_PASSWORD=%s\n' "$(rand_key 32)" "$(rand_key 32)" >> .env
  env_setting MINIO_ROOT_USER "$(rand_key 24)"
  env_setting MINIO_ROOT_PASSWORD "$(rand_key 40)"
  env_setting SECRET_KEY "$(rand_key 50)"
  env_setting API_CLIENT_ENC_KEY "$(fernet_key)"
  env_setting AUDIT_MAC_MASTER_KEY "$(fernet_key)"
  env_setting SPACEWORKS_HOSTING_MODEL "$HOSTING_MODEL"
  env_setting SPACEWORKS_RUN_FRONTEND "$([[ "$RUN_FRONTEND" == 1 ]] && echo yes || echo no)"
  env_setting SPACEWORKS_STORAGE "$([[ "$STORAGE" == 1 ]] && echo bundled || echo external)"
  env_setting SPACEWORKS_EDITION "$SPACEWORKS_EDITION"
  # Scheduler mode is unquoted: the topology authority reads this key literally.
  echo 'SPACEWORKS_SCHEDULER_MODE=image' >> .env
  env_setting ALLOWED_HOSTS "$WEBHOST,localhost,127.0.0.1,backend"
  env_setting CORS_ALLOWED_ORIGINS "$origins"
  env_setting CSRF_TRUSTED_ORIGINS "$origins"
  env_setting PUBLIC_APP_BASE_URL "$app_url"
  env_setting HTTP_PORT "$([[ "$HTTPS_MODE" == 3 ]] && echo 8080 || echo 80)"
  env_setting ENABLE_HTTPS "$([[ "$HTTPS_MODE" == 1 ]] && echo false || echo true)"
  env_setting TRUST_X_FORWARDED_PROTO "$([[ "$HTTPS_MODE" == 1 ]] && echo false || echo true)"
  if [[ "$HTTPS_MODE" == 3 ]]; then
    env_setting HTTP_PORT_BIND 127.0.0.1
    env_setting API_BIND 127.0.0.1
    env_setting API_PORT 8080
    proxy_count=2
  fi
  env_setting TRUSTED_PROXY_COUNT "$proxy_count"
  env_setting PUBLIC_DOMAIN "$PUBLIC_DOMAIN"
  env_setting TLS_EMAIL "$TLS_EMAIL"
  if [[ "$HOSTING_MODEL" == 3 ]]; then
    env_setting CADDY_SAAS_CONFIG ./deploy/Caddyfile.saas-install
    env_setting PLATFORM_DOMAIN "$PLATFORM_DOMAIN"
    env_setting PLATFORM_FIRST_HOST "$MS_SUBDOMAIN.$PLATFORM_DOMAIN"
    env_setting PLATFORM_DOMAIN_SUFFIX ".$PLATFORM_DOMAIN"
    env_setting PLATFORM_SUBDOMAIN_AUTO_TLS true
    env_setting PLATFORM_ORIGIN_HOST "origin.$PLATFORM_DOMAIN"
    env_setting BEHIND_TRUSTED_PROXY true
    env_setting PLATFORM_STAFF_ORIGINS "https://$PLATFORM_DOMAIN${SITE_ORIGINS:+,${SITE_ORIGINS%%,*}}"
    env_setting INFRA_HOSTS "localhost,127.0.0.1,backend,origin.$PLATFORM_DOMAIN,files.$PLATFORM_DOMAIN,$MS_SUBDOMAIN.$PLATFORM_DOMAIN,$PLATFORM_DOMAIN"
  fi
  if [[ "$HOSTING_MODEL" == 2 && -n "$SITE_ORIGINS" ]]; then
    env_setting PLATFORM_STAFF_ORIGINS "${SITE_ORIGINS%%,*}"
  fi
  env_setting SPACEWORKS_WEB_UPSTREAM "$([[ "$RUN_FRONTEND" == 1 ]] && echo frontend:80 || echo api-edge:80)"
  if [[ "$STORAGE" == 2 ]]; then
    env_setting AWS_S3_ENDPOINT_URL "$S3_ENDPOINT"
    env_setting AWS_S3_PUBLIC_ENDPOINT_URL "$S3_ENDPOINT"
    env_setting AWS_S3_REGION_NAME "$S3_REGION"
    env_setting AWS_ACCESS_KEY_ID "$S3_ACCESS_KEY"
    env_setting AWS_SECRET_ACCESS_KEY "$S3_SECRET_KEY"
    env_setting AWS_STORAGE_BUCKET_NAME "$PRIVATE_BUCKET"
    env_setting PUBLIC_IMAGE_BUCKET "$IMAGE_BUCKET"
    env_setting PUBLIC_IMAGE_BASE_URL "$IMAGE_BASE_URL"
    env_setting STORAGE_PRESIGN_METHOD "$PRESIGN_METHOD"
  elif [[ "$HTTPS_MODE" != 1 ]]; then
    local storage_host="files.${PLATFORM_DOMAIN:-$WEBHOST}"
    env_setting STORAGE_DOMAIN "$storage_host"
    env_setting STORAGE_CADDY_CONFIG /etc/caddy/storage.caddy
    env_setting AWS_S3_PUBLIC_ENDPOINT_URL "https://$storage_host"
    env_setting PUBLIC_IMAGE_BASE_URL "https://$storage_host/public-images"
    env_setting MINIO_CORS_ALLOWED_ORIGINS "$origins"
    env_setting MINIO_API_BIND 127.0.0.1
  else
    env_setting AWS_S3_PUBLIC_ENDPOINT_URL "http://$WEBHOST:9000"
    env_setting PUBLIC_IMAGE_BASE_URL "http://$WEBHOST:9000/public-images"
    env_setting MINIO_CORS_ALLOWED_ORIGINS "$origins"
  fi
}
