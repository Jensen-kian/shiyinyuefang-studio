# 拾音乐坊 —— 生产镜像
# 注意：core/generator.py 与 core/barcode.py 依赖 /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf，
# python:3.11-slim 默认没有该字体，必须安装 fonts-dejavu-core，否则生成素材时会报字体缺失。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PORT=8011

RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用 Docker 层缓存
COPY deploy/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app
RUN mkdir -p /app/data /app/data/.trash

EXPOSE 8011

# 单 worker + 多线程：history.json 是无锁文件读写，多 worker 并发写会产生竞态；
# 生成素材为 CPU 密集任务，8 线程足够应对少量并发，超时放宽到 180s。
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "8", \
     "-b", "0.0.0.0:8011", "--timeout", "180", \
     "--access-logfile", "-", "--error-logfile", "-", "app:app"]
