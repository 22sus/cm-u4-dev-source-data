#!/bin/bash
# 기존 배포 파일 정리
echo "[INFO] Cleaning up previous files..."
# 경로 주의: appspec.yml의 destination과 맞춰야 함
rm -rf /home/ubuntu/flask-app
mkdir -p /home/ubuntu/flask-app
exit 0
