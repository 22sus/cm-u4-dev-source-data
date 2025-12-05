#!/bin/bash
echo "[INFO] Cleaning up previous files..."
# 기존 코드 파일 삭제 (디렉토리는 건드리지 않음)
rm -f /home/ubuntu/api_server.py
rm -f /home/ubuntu/requirements.txt
# scripts 폴더는 덮어씌워지므로 굳이 안 지워도 되지만 안전하게 삭제
rm -rf /home/ubuntu/scripts
exit 0
