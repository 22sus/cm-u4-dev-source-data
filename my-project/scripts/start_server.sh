#!/bin/bash
cd /home/ec2-user/flask-app
# 백그라운드 실행, 로그는 app.log에 저장
nohup python3 api_server.py > app.log 2>&1 &
