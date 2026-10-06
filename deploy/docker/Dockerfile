FROM node:24-bookworm-slim AS node
FROM python:3.13-slim-bookworm AS app
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY deploy/docker/requirements.txt /app/deploy/docker/requirements.txt
RUN pip install --no-cache-dir -r deploy/docker/requirements.txt
COPY receipt_renderer/package*.json /app/receipt_renderer/
RUN cd receipt_renderer && npm ci --omit=dev
COPY deploy/docker/package*.json /app/deploy/docker/
RUN cd deploy/docker && npm ci --omit=dev
COPY . /app
RUN useradd --uid 10001 --create-home app && mkdir -p /data /app/staticfiles && chown -R app:app /data /app/staticfiles
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DJANGO_SETTINGS_MODULE=config.docker_settings
USER app
EXPOSE 8000
CMD ["sh", "/app/deploy/docker/start.sh"]

# Feishu assistant: adds the Claude/Feishu SDKs and a headless Chromium for page screenshots.
FROM app AS bot
USER root
COPY requirements-bot.txt /app/requirements-bot.txt
RUN pip install --no-cache-dir -r /app/requirements-bot.txt     && PLAYWRIGHT_BROWSERS_PATH=/opt/playwright playwright install --with-deps chromium     && chmod -R a+rX /opt/playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
USER app
CMD ["python", "manage.py", "run_feishu_bot"]
