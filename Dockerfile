# Playwright-Image bringt Chromium für den Fallback mit (Version = playwright in pyproject.toml).
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

WORKDIR /app
COPY pyproject.toml constraints.txt ./
COPY src ./src
# feste Versionen aus constraints.txt – Builds bleiben reproduzierbar
RUN pip install --no-cache-dir -c constraints.txt .

COPY config ./config
ENV TZ=Europe/Berlin PYTHONUNBUFFERED=1
CMD ["python", "-m", "werkstudent.main"]
