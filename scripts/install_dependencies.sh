#!/bin/bash
cd /home/ubuntu

sudo apt-get update -y
# 의존성 설치
pip3 install -r requirements.txt --break-system-packages --ignore-installed
