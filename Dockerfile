# Playwright公式イメージ（ブラウザ実行に必要な依存が揃っている）
FROM mcr.microsoft.com/playwright:v1.58.2-jammy

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Python環境（Ubuntu 22.04ベースなのでpython3はあるが、pip等を確実にする）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# 依存関係
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r /app/requirements.txt

# アプリ本体はマウント運用でも良いが、ここでは一応COPYも可能にしておく
COPY . /app

# permission_mode="bypassPermissions" は root では使えないため、非 root で実行する
RUN chown -R 1000:1000 /app
USER 1000

# デフォルトはシェル（必要なら main.py にしてもOK）
CMD ["bash"]