#!/bin/bash
# 기존에 실행 중인 api_server 프로세스 종료 (Systemd 서비스가 아니라면 pkill 사용)
pkill -f "api_server.py" || echo "Process not running"
