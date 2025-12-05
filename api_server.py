# [수정 필요 항목 리스트]
# 1. SECRET_KEY: 운영 환경에서는 강력한 난수 값으로 변경 필수
# 2. CORS: 개발용(*)과 운영용(특정 도메인) 설정을 상황에 맞춰 주석 해제/사용
# 3. MQTT_BROKER_PORT: 브로커 포트 변경 시 수정

from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from functools import wraps
import paho.mqtt.client as mqtt
import json
import time
import boto3
from boto3.dynamodb.conditions import Key, Attr
from collections import defaultdict
import os
import random

app = Flask(__name__)

# ==============================================================================
# 1. CORS (Cross-Origin Resource Sharing) 설정
# ==============================================================================
# 설명: 브라우저 보안 정책상 다른 도메인에서의 API 호출을 허용하기 위한 설정입니다.

# [개발용] 모든 도메인(*) 허용 - 현재 활성화됨
# CORS(app, resources={r"/api/*": {"origins": "*"}})

# [운영용] 특정 도메인만 허용 (보안 강화) - 필요 시 위 코드를 주석 처리하고 아래 주석 해제
CORS(app, resources={r"/api/*": {
    "origins": [
        "https://u4.bipa-g1-iot.click",
        "https://bipa-g1-iot.click"
    ]
}})

SECRET_KEY = "qc-line-jwt-secret-2025" # [수정 필요] JWT 서명용 비밀키

# 환경 변수에서 접속 정보 로드 (setup_app.sh에서 주입됨)
RDS_HOST = os.environ.get("RDS_HOST", "localhost")
RDS_USER = os.environ.get("RDS_USER", "admin")
RDS_PASSWORD = os.environ.get("RDS_PASSWORD", "12345678")
RDS_DB = "qc_line_db"
RDS_PORT = 3306

DYNAMODB_TABLE_NAME = os.environ.get("DDB_TABLE_NAME", "cm-u4-dev-dynamodb-table")
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-2')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = 1883
MQTT_USERNAME = None
MQTT_PASSWORD = None

DEVICE_LIST = ['device_01', 'device_02', 'device_03', 'device_04']

# ==============================================================================
# 2. 유틸리티 함수 (IP 식별 등)
# ==============================================================================

# [실제 클라이언트 IP 추출]
# 설명: CloudFront -> ALB -> App 구조에서는 request.remote_addr가 ALB의 IP로 보입니다.
#       실제 사용자 IP는 'X-Forwarded-For' 헤더의 첫 번째 값에 담겨 있습니다.
def get_real_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        # X-Forwarded-For: <Client IP>, <CloudFront IP>, ...
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

# [MQTT 클라이언트 설정]
# Flask 앱이 시작될 때 MQTT 브로커와 연결하여 '디바이스 제어' 명령을 발행할 준비를 합니다.
mqtt_client = mqtt.Client(client_id="flask_api_publisher", protocol=mqtt.MQTTv311)
if MQTT_USERNAME and MQTT_PASSWORD:
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

mqtt_connected = False

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print("🚀 MQTT Connected Successfully")
    else:
        mqtt_connected = False
        print(f"❌ MQTT Connection Failed with code {rc}")

def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print(f"⚠️ MQTT Disconnected (rc={rc}). Trying to reconnect...")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

def init_mqtt():
    try:
        if not mqtt_client.is_connected():
            print(f"🔌 Connecting to MQTT Broker: {MQTT_BROKER_HOST}")
            mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
            mqtt_client.loop_start() # 백그라운드 네트워크 루프 실행 (Non-blocking)
    except Exception as e:
        print(f"❌ MQTT Init Failed: {e}")

# 앱 구동 시 MQTT 연결 시도
init_mqtt()

# [DB 연결 헬퍼 함수]
def get_rds_conn():
    try:
        return pymysql.connect(
            host=RDS_HOST, user=RDS_USER, password=RDS_PASSWORD,
            database=RDS_DB, port=RDS_PORT,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=5
        )
    except Exception as e:
        print(f"❌ RDS Connection Failed: {e}")
        return None

def get_kst_time():
    return datetime.now(timezone(timedelta(hours=9))) # 한국 시간(KST)

# [인증 데코레이터] - JWT 토큰 검증
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'OPTIONS': return f(*args, **kwargs)
        token = request.headers.get('Authorization', '').split(' ')[1] if 'Authorization' in request.headers else None
        if not token: return jsonify({'message': 'Token missing'}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            request.user_id = data['user_id']
        except:
            return jsonify({'message': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated

# ==============================================================================
# 3. API 엔드포인트
# ==============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'version': 'v22.0 (Deployed via CodePipeline!)'}), 200


# [로그인 API] - RDS Users 테이블 조회 및 bcrypt 검증 로직으로 수정
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    user_ip = get_real_client_ip()
    print(f"🔐 Login Attempt - User: {username}, IP: {user_ip}")

    conn = get_rds_conn()
    if not conn:
        return jsonify({'success': False, 'message': 'DB Connection Failed'}), 500

    try:
        with conn.cursor() as cursor:
            # 1. DB에서 사용자 정보 조회
            sql = "SELECT id, username, password_hash FROM users WHERE username = %s"
            cursor.execute(sql, (username,))
            user = cursor.fetchone()

            if user:
                # 2. bcrypt 해시 비교
                # DB에 저장된 password_hash가 bytes 형식이어야 bcrypt.checkpw가 정상 동작
                stored_hash = user['password_hash'].encode('utf-8') 
                
                # 입력된 비밀번호(password)를 bytes로 인코딩하여 저장된 해시(stored_hash)와 비교
                if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
                    # 인증 성공
                    token = jwt.encode({
                        'user_id': user['username'],
                        'exp': datetime.utcnow() + timedelta(hours=24)
                    }, SECRET_KEY, algorithm="HS256")
                    
                    return jsonify({
                        'success': True,
                        'token': token,
                        'user': {'username': user['username']}
                    })

        # 인증 실패 (사용자가 없거나 비밀번호 불일치)
        return jsonify({'success': False, 'message': 'Invalid credentials (v2.0 - Updated!)'}), 401


    except Exception as e:
        print(f"❌ RDS Login Error: {e}")
        return jsonify({'success': False, 'message': 'Server error during login'}), 500
    finally:
        conn.close()

# [실시간 대시보드 API] - DynamoDB 조회 로직 수정 (GSI 대신 일반 PK/SK 쿼리 사용)
@app.route('/api/dashboard/realtime', methods=['GET'])
@token_required
def get_realtime_dashboard():
    target_device = request.args.get('device_id', 'all')
    
    # KST 기준 '오늘' 날짜 키 생성
    now_kst = get_kst_time()
    today_str = now_kst.strftime("%Y-%m-%d")

    # DynamoDB Query 시간 범위 설정 (오늘 00:00:00 KST 부터 현재 UTC까지)
    # DynamoDB Timestamp는 UTC 기준 (ISO 8601)
    start_of_today_kst = datetime(now_kst.year, now_kst.month, now_kst.day, 0, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    start_of_today_utc = start_of_today_kst.astimezone(timezone.utc).isoformat()
    # 현재 시점 UTC
    now_utc_iso = datetime.now(timezone.utc).isoformat()

    try:
        total_normal = 0
        total_defect = 0
        
        # 1. 전체 라인 조회 ('all') 로직 수정
        if target_device == 'all':
            graph_data = defaultdict(lambda: {'line_trends': {}})
            
            for dev_id in DEVICE_LIST:
                # PK(Device_id)로 쿼리하고 Sort Key(Timestamp)로 범위 설정
                response = table.query(
                    KeyConditionExpression=Key('Device_id').eq(dev_id) & Key('Timestamp').between(start_of_today_utc, now_utc_iso)
                )
                items = response.get('Items', [])
                
                # 라인별 통계 집계
                for item in items:
                    # day_key로 한 번 더 필터링 (Timestamp 범위가 넘어갈 수 있기 때문)
                    if item.get('day_key') != today_str: continue 
                    
                    ts = item.get('Timestamp', '')
                    if not ts: continue
                    
                    # 5분 단위로 그룹화 (HH:MM) - 초 단위 절사
                    time_key = ts[11:16] # 2023-10-25T14:30:00 -> 14:30
                    
                    is_defect = (item.get('color_check') == 'DEFECT' or 
                                 item.get('weight_check') == 'DEFECT' or 
                                 item.get('iron_check') == 'DEFECT')
                    
                    if is_defect:
                        total_defect += 1
                        # 시간대별 불량 카운트 (누적)
                        if dev_id not in graph_data[time_key]['line_trends']:
                            graph_data[time_key]['line_trends'][dev_id] = 0
                        graph_data[time_key]['line_trends'][dev_id] += 1
                    else:
                        total_normal += 1

            # 그래프 데이터 포맷팅
            sorted_times = sorted(graph_data.keys())
            formatted_graph = []
            for t in sorted_times:
                formatted_graph.append({
                    'time': t,
                    'line_trends': graph_data[t]['line_trends']
                })
                
            total_prod = total_normal + total_defect
            defect_rate = round((total_defect / total_prod * 100), 2) if total_prod > 0 else 0
            
            return jsonify({
                'success': True,
                'summary': {
                    'total_production': total_prod,
                    'total_normal': total_normal,
                    'total_defect': total_defect,
                    'defect_rate': defect_rate
                },
                'graph_data': formatted_graph[-20:] # 최근 20개 포인트만
            })

        # 2. 특정 라인 상세 조회
        else:
            # PK(Device_id)로 쿼리하고 Sort Key(Timestamp)로 범위 설정
            response = table.query(
                KeyConditionExpression=Key('Device_id').eq(target_device) & Key('Timestamp').between(start_of_today_utc, now_utc_iso)
            )
            
            # 오늘 날짜 데이터만 필터링 (Timestamp 범위가 넘어갈 수 있기 때문)
            items = [i for i in response.get('Items', []) if i.get('day_key') == today_str]
            
            sensor_stats = {
                'color': {'defect': 0},
                'weight': {'defect': 0},
                'iron': {'defect': 0}
            }
            
            graph_data = defaultdict(lambda: {'color': 0, 'weight': 0, 'iron': 0})

            for item in items:
                ts = item.get('Timestamp', '')
                time_key = ts[11:16]
                
                c_def = item.get('color_check') == 'DEFECT'
                w_def = item.get('weight_check') == 'DEFECT'
                i_def = item.get('iron_check') == 'DEFECT'
                
                if c_def: sensor_stats['color']['defect'] += 1; graph_data[time_key]['color'] += 1
                if w_def: sensor_stats['weight']['defect'] += 1; graph_data[time_key]['weight'] += 1
                if i_def: sensor_stats['iron']['defect'] += 1; graph_data[time_key]['iron'] += 1
                
                if c_def or w_def or i_def:
                    total_defect += 1
                else:
                    total_normal += 1
            
            total_prod = total_normal + total_defect
            
            # 센서별 불량률 계산
            def calc_rate(cnt): return round((cnt/total_prod*100), 1) if total_prod > 0 else 0
            
            summary_detail = {
                'color': {'defect_count': sensor_stats['color']['defect'], 'defect_rate': calc_rate(sensor_stats['color']['defect'])},
                'weight': {'defect_count': sensor_stats['weight']['defect'], 'defect_rate': calc_rate(sensor_stats['weight']['defect'])},
                'iron': {'defect_count': sensor_stats['iron']['defect'], 'defect_rate': calc_rate(sensor_stats['iron']['defect'])}
            }
            
            sorted_times = sorted(graph_data.keys())
            formatted_graph = []
            for t in sorted_times:
                formatted_graph.append({
                    'time': t,
                    'sensor_trends': graph_data[t]
                })

            return jsonify({
                'success': True,
                'summary': {
                    'total_production': total_prod,
                    'total_normal': total_normal,
                    'total_defect': total_defect,
                    'defect_rate': round((total_defect/total_prod*100), 2) if total_prod > 0 else 0,
                    'sensor_details': summary_detail
                },
                'graph_data': formatted_graph[-20:]
            })

    except Exception as e:
        print(f"DynamoDB Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# [히스토리 대시보드 API] - RDS 조회
@app.route('/api/dashboard/history', methods=['GET'])
@token_required
def get_history_stats():
    device_id = request.args.get('device_id')
    start_dt = request.args.get('start_dt') # YYYY-MM-DD HH:MM:SS
    end_dt = request.args.get('end_dt')
    
    conn = get_rds_conn()
    if not conn:
        return jsonify({'success': False, 'message': 'DB Connection Failed'}), 500
    
    try:
        with conn.cursor() as cursor:
            # 1. 전체 라인 조회
            if device_id == 'all':
                sql = """
                    SELECT device_id, 
                           SUM(normal_count) as total_normal, 
                           SUM(defect_count) as total_defect
                    FROM production_stats_5min
                    WHERE start_time >= %s AND end_time <= %s
                    GROUP BY device_id
                """
                cursor.execute(sql, (start_dt, end_dt))
                rows = cursor.fetchall()
                
                lines_breakdown = {}
                grand_normal = 0
                grand_defect = 0
                
                for r in rows:
                    lines_breakdown[r['device_id']] = {
                        'normal': int(r['total_normal']),
                        'defect': int(r['total_defect'])
                    }
                    grand_normal += int(r['total_normal'])
                    grand_defect += int(r['total_defect'])
                
                return jsonify({
                    'success': True,
                    'type': 'all',
                    'data': {
                        'total_normal': grand_normal,
                        'total_defect': grand_defect,
                        'lines_breakdown': lines_breakdown
                    }
                })
            
            # 2. 특정 라인 조회
            else:
                sql = """
                    SELECT SUM(normal_count) as total_normal, 
                           SUM(defect_count) as total_defect,
                           SUM(color_defect) as color_defect,
                           SUM(weight_defect) as weight_defect,
                           SUM(iron_defect) as iron_defect
                    FROM production_stats_5min
                    WHERE device_id = %s AND start_time >= %s AND end_time <= %s
                """
                cursor.execute(sql, (device_id, start_dt, end_dt))
                result = cursor.fetchone()
                
                if not result or result['total_normal'] is None:
                    return jsonify({'success': True, 'data': {'total_normal':0, 'total_defect':0, 'sensor_breakdown':{'color':0,'weight':0,'iron':0}}})
                
                return jsonify({
                    'success': True,
                    'type': 'device',
                    'data': {
                        'total_normal': int(result['total_normal']),
                        'total_defect': int(result['total_defect']),
                        'sensor_breakdown': {
                            'color': int(result['color_defect']),
                            'weight': int(result['weight_defect']),
                            'iron': int(result['iron_defect'])
                        }
                    }
                })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

# [디바이스 제어 API] - MQTT 발행 및 RDS 제어 이력 로깅 추가
@app.route('/api/device/control', methods=['POST', 'OPTIONS'])
@token_required
def control_device():
    # CORS Preflight 요청 처리
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    data = request.get_json()
    target_device = data.get('device_id')
    command = data.get('command') # 'ON' or 'OFF'
    password = data.get('password') # 보안 확인용 (여기선 로깅 및 사용자 확인용)
    
    # 실제 IP 로깅
    user_ip = get_real_client_ip()
    print(f"🎮 Control Request from IP: {user_ip} - Device: {target_device}, Cmd: {command}")
    
    if not target_device or command not in ['ON', 'OFF']:
        return jsonify({'success': False, 'message': 'Invalid parameters'}), 400

    conn = get_rds_conn()
    if not conn:
        return jsonify({'success': False, 'message': 'DB Connection Failed'}), 503

    try:
        # 1. 비밀번호 확인 로직 (제어 전 필수)
        with conn.cursor() as cursor:
            sql = "SELECT id, username, password_hash FROM users WHERE username = %s"
            cursor.execute(sql, (request.user_id,))
            user = cursor.fetchone()
            
            # 저장된 해시와 입력된 비밀번호 비교
            if not user or not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                return jsonify({'success': False, 'message': 'Invalid control password'}), 403

        # 2. MQTT 발행 로직
        topic = "device/control"
        payload = {
            "set": command,
            "device_id": target_device,
            "sender_ip": user_ip # 감사 로그용
        }
        message_json = json.dumps(payload)
        
        if not mqtt_client.is_connected():
            print("⚠️ MQTT Disconnected. Attempting to reconnect...")
            mqtt_client.reconnect()
            time.sleep(0.1)

        if mqtt_client.is_connected():
            result = mqtt_client.publish(topic, message_json, qos=1) 
            result.wait_for_publish(timeout=2.0)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                # 3. 제어 이력 로깅 (RDS)
                with conn.cursor() as cursor:
                    sql_log = """
                        INSERT INTO device_control_history 
                        (device_id, command, sender_user, sender_ip) 
                        VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(sql_log, (target_device, command, request.user_id, user_ip))
                conn.commit()
                
                return jsonify({'success': True, 'message': f'명령 전송 성공: {command}'}), 200
            else:
                return jsonify({'success': False, 'message': 'MQTT 발행 실패'}), 500
        else:
            return jsonify({'success': False, 'message': '브로커 연결 끊김'}), 503

    except Exception as e:
        print(f"❌ Control API Error: {e}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    # Flask 앱 실행 (0.0.0.0으로 외부 접속 허용)
    app.run(host='0.0.0.0', port=5000)