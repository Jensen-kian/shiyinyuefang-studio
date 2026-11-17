#!/bin/bash
# 专辑装帧工作台启动脚本
cd "$(dirname "$0")"
echo "启动中… 浏览器访问 http://127.0.0.1:8011"
python3.11 app.py
