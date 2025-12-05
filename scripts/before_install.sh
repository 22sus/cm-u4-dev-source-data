#!/bin/bash
echo "[INFO] Cleaning up previous files..."
# 기존 소스 코드만 삭제
rm -f /home/ubuntu/api_server.py
rm -f /home/ubuntu/requirements.txt
# [삭제 금지] rm -rf /home/ubuntu/scripts  <-- 이 줄을 지우세요!
exit 0
