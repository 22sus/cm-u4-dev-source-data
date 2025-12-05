#!/bin/bash
cd /home/ubuntu/flask-app
# 패키지 업데이트 및 설치
sudo apt-get update -y
sudo apt-get install -y python3-pip
# Python 의존성 설치
pip3 install -r requirements.txt --break-system-packages --ignore-installed
