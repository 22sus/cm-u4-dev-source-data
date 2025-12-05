#!/bin/bash
# 기존에 실행 중인 api_server.py 찾아서 종료. 없어도 에러 안 나게 처리.
pkill -f "api_server.py" || true
