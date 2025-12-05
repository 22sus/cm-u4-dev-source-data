#!/bin/bash
# 기존 서비스 중지 (에러 무시)
sudo systemctl stop api-server || true
