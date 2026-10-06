ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NEWS_DB_PATH=/data/news.sqlite3
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -r requirements.txt \
    && groupadd -g 10001 app && useradd -u 10001 -g app app \
    && mkdir /data && chown app:app /data
COPY backend ./backend
COPY web ./web
COPY admin_web ./admin_web
COPY content ./content
COPY tools ./tools
USER 10001:10001
EXPOSE 8000
CMD ["python","-m","uvicorn","backend.app:app","--host","0.0.0.0","--port","8000","--workers","1"]
