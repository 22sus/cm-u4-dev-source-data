#!/bin/bash
cd /home/ubuntu
sudo apt-get update -y
# [추가] pip가 확실히 있는지 확인
sudo apt-get install -y python3-pip
pip3 install -r requirements.txt --break-system-packages --ignore-installed
