#!/bin/bash
cd /home/ubuntu/flask-app
# nohup으로 백그라운드 실행 (로그 남기기)
nohup python3 api_server.py > app.log 2>&1 &
