import numpy as np
from fastapi import FastAPI
import requests, json, os, time
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, Query, Request, HTTPException
import pandas as pd
from contextlib import asynccontextmanager
import psutil
import threading
from threading import Lock
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Dict, Any

df_lock = Lock()
data_dict_lock = Lock()

templates = Jinja2Templates(directory="templates") # HTML 템플릿 디렉토리 설정
# HTML 템플릿을 렌더링하기 위한 Jinja2 템플릿 객체 생성

# 기존 CSV 파일의 컬럼 순서를 가져오는 함수
def get_existing_columns(filename): # 기존 CSV 파일의 컬럼 순서를 가져오는 함수
    # 파일이 존재하는지 확인
    if os.path.exists(filename):
        try:
            return list(pd.read_csv(filename, nrows=1, skipinitialspace=True).columns) #존재하는 경우, 첫 번째 행을 읽어 컬럼 이름을 반환
        except (pd.errors.EmptyDataError, FileNotFoundError): # 파일이 비어있는 경우
            print("기존 CSV 파일이 비어있거나 존재하지 않습니다.") # 파일이 비어있는 경우 안내 메시지 출력
            return None  # 파일이 비어있는 경우 None 반환
    return None

def backup_data_csv():
    # 백업 함수. csv가 존재하면 backup으로 백업을 수행
    if os.path.exists("data.csv"):
        try:
            # data.csv 읽기
            df_backup = pd.read_csv("data.csv")
            if not df_backup.empty:
                # data_backup.csv에 추가
                existing_columns = get_existing_columns("data_backup.csv")
                if existing_columns is not None:
                    df_backup = df_backup[existing_columns]
                    df_backup.to_csv("data_backup.csv", mode='a', header=False, index=False)
                else:
                    df_backup.to_csv("data_backup.csv", mode='w', header=True, index=False)
                print("data.csv 내용을 data_backup.csv로 백업 완료")
            else:
                print("data.csv가 비어있어 백업하지 않습니다.")
        except Exception as e:
            print(f"백업 중 오류 발생: {e}")
    else:
        print("data.csv 파일이 존재하지 않아 백업하지 않습니다.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global data_dict # 전역 변수로 data_dict 선언
    print("FastAPI 서버가 시작되었습니다.") # 서버 시작 메시지 출력
    
    # 서버 시작 시 data.csv 초기화
    if os.path.exists("data.csv"):
        os.remove("data.csv") #device_id,time,acc_x,acc_y,acc_z,gyro_x,gyro_y,gyro_z,label

    df = pd.DataFrame(columns=['device_id','time', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z', 'label'])
    df.to_csv("data.csv", index=False)
    print("서버 시작 시 data.csv 파일을 초기화했습니다.")
    
    # 여기서 배터리 모니터링 스레드 실행
    threading.Thread(target=monitor_battery_and_save, daemon=True).start() # 배터리 모니터링 스레드를 시작
    print(" 배터리 모니터링 스레드 시작됨") # 배터리 모니터링 스레드 시작 메시지 출력

    yield  # 서버 실행 중

    # 서버 종료 시 처리
    global mindex
    print("서버가 종료됩니다. 백업을 수행합니다.")
    mindex = 2
    
    #  data.csv가 존재하면 data_backup.csv로 백업
    backup_data_csv()
    
    # 딕셔너리에 저장된 데이터도 data_backup.csv에 추가
    if data_dict:
        print(f"딕셔너리에 {len(data_dict)}개의 미저장 데이터가 있습니다. 백업 파일에 추가합니다.")
        try:
            all_rows = []
            for entry in data_dict:
                device_id = entry.get("device_id", "Unknown")
                time_val = entry.get("time", "")
                imu = entry.get("imu", [])
                if isinstance(imu, list):
                    for row in imu:
                        if len(row) == 6:
                            all_rows.append({
                                "device_id": device_id,
                                "time": time_val,
                                "acc_x": row[0],
                                "acc_y": row[1],
                                "acc_z": row[2],
                                "gyro_x": row[3],
                                "gyro_y": row[4],
                                "gyro_z": row[5],
                                "label": 1
                            })

            if all_rows:
                df_dict = pd.DataFrame(all_rows)
                existing_columns = get_existing_columns("data_backup.csv")
                if existing_columns is not None:
                    valid_columns = [c for c in existing_columns if c in df_dict.columns]
                    df_dict = df_dict[valid_columns]
                    df_dict.to_csv("data_backup.csv", mode='a', header=False, index=False)
                else:
                    df_dict.to_csv("data_backup.csv", mode='w', header=True, index=False)
                print("딕셔너리 데이터를 data_backup.csv에 추가 완료")
            else:
                print("imu 데이터가 없어서 백업하지 않았습니다.")
        except Exception as e:
            print(f"딕셔너리 데이터를 백업하는 중 오류 발생: {e}")

        else:
            print("딕셔너리에 저장된 데이터가 없습니다.")
    df.to_csv("data_backup.csv", mode='a', header=not os.path.exists("data_backup.csv"), index=False)
    print("서버 종료 시 모든 백업 완료")

mindex = 0 # 인덱스 초기화
data_dict = []  # 충전 중일 때 데이터를 저장할 딕셔너리 리스트

def monitor_battery_and_save():  # 배터리 모니터링 및 저장 함수
    global data_dict, mindex  # 전역 변수 data_dict와 mindex 사용
    was_charging = None  # 초기 충전 상태 (None으로 초기화)
    
    while True:
        battery = psutil.sensors_battery()  # 배터리 정보 가져오기
        if battery is not None:
            is_charging = battery.power_plugged
            current_percent = battery.percent
            print(f"[Battery] 충전 중: {is_charging}, 잔량: {current_percent}%, mindex: {mindex}")

            # 충전기 연결 해제 감지
            if was_charging is True and is_charging is False:
                print("충전기 연결 해제 감지. mindex를 1로 변경하고 data.csv에 저장합니다.")
                with data_dict_lock:
                    if mindex == 0 and data_dict:
                        mindex = 1

                        all_rows = []
                        for entry in data_dict:
                            device_id = entry.get("device_id", "Unknown")
                            time_val = entry.get("time", "")
                            imu = entry.get("imu", [])

                            if isinstance(imu, list):
                                for row in imu:
                                    if len(row) == 6:
                                        all_rows.append({
                                            "device_id": device_id,
                                            "time": time_val,
                                            "acc_x": row[0],
                                            "acc_y": row[1],
                                            "acc_z": row[2],
                                            "gyro_x": row[3],
                                            "gyro_y": row[4],
                                            "gyro_z": row[5],
                                            "label": 1
                                        })

                        # [2] DataFrame 변환 및 저장
                        if all_rows:
                            df_to_save = pd.DataFrame(all_rows)
                            filename = "data.csv"
                            existing_columns = get_existing_columns(filename)

                            if existing_columns is not None:
                                valid_columns = [c for c in existing_columns if c in df_to_save.columns]
                                df_to_save = df_to_save[valid_columns]
                                df_to_save.to_csv(filename, mode='a', header=False, index=False)
                            else:
                                df_to_save.to_csv(filename, mode='w', header=True, index=False)

                            print(f"data.csv에 {len(df_to_save)} rows 저장 완료")

                        else:
                            print("imu 데이터를 펼칠 수 없습니다. 저장 안됨")

                        # [3] 딕셔너리 초기화
                        data_dict = []
                        print(f"mindex가 {mindex}로 변경되고 딕셔너리가 초기화되었습니다.")

                        # 충전기 다시 연결 감지 (연결 해제 상태에서 다시 연결됨)
                    elif was_charging is False and is_charging is True:
                        print("충전기 재연결 감지! mindex를 0으로 변경합니다.")
                        with data_dict_lock:
                            if mindex == 1:
                                mindex = 0
                                print(f"mindex가 {mindex}로 변경되었습니다.")
                
            # 충전 상태 업데이트
            was_charging = is_charging

        else:
            print("배터리 정보 탐지 실패")
        
        time.sleep(10)

API_KEY = "test1" #임의의 키값
app = FastAPI( #FastAPI 서버
    title="User Matchstats API Server", # 서버 이름
    description="낙상감지 서버", # 서버 설명
    version="0.0.1", # 서버 버전
    lifespan=lifespan # 서버 시작, 종료 시 호출할 함수
    
)
BUILD_DIR = r"C:\Users\Administrator\Desktop\PEESERVER\frontend\fall_detection-main\build"
app.mount("/static", StaticFiles(directory=os.path.join(BUILD_DIR, "static")), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# React 정적 파일 경로 지정
from starlette.responses import FileResponse
from starlette.requests import Request

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse(os.path.join(BUILD_DIR, "index.html"))
# 3. JS, CSS가 아니라면 모두 index.html로 돌려주는 catch_all

## time,acc_x,acc_y,acc_z,gyro_x,gyro_y,gyro_z 컬럼이 존재함.
#api키도 확인해야하고, 데이터를 락 걸어서 추가해야 함.
#왜? 동시에 여러 사용자가 데이터를 추가하면 레이스 컨디션 발생할 수 있음.
@app.post("/add_data")
async def add_data(data: dict):
    global data_dict, mindex
    
    # API 키 검증
    if "api_key" not in data or data["api_key"] != API_KEY:
        return {"status": "error", "message": "유효하지 않은 API 키입니다."}

    # API 키 제거 (저장할 필요 없음)
    data_to_save = data.copy()
    del data_to_save["api_key"]
    
    with data_dict_lock:  # 동시 접근 방지
        if mindex == 0:
            # 충전 중: 딕셔너리에 데이터 누적
            data_dict.append(data_to_save)
            return {"status": "success", "message": "데이터가 딕셔너리에 저장되었습니다.", "mindex": mindex, "dict_size": len(data_dict)}
            
        elif mindex == 1:
            # 충전 해제 후: 새로운 딕셔너리에 데이터 누적 (다음 충전 해제 때까지)
            data_dict.append(data_to_save)
            return {"status": "success", "message": "데이터가 딕셔너리에 저장되었습니다.", "mindex": mindex, "dict_size": len(data_dict)}
            
        elif mindex == 2:
            # 서버 종료 상태: 데이터 받지 않음
            return {"status": "error", "message": "서버가 종료 중입니다. 데이터를 받을 수 없습니다.", "mindex": mindex}
            
        else:
            return {"status": "error", "message": f"알 수 없는 mindex 상태: {mindex}"}

@app.get("/show_data")
async def show_data():
    global data_dict
    with data_dict_lock:
        # 딕셔너리 데이터를 반환
        return {
            "data": data_dict,
            "mindex": mindex,
            "data_count": len(data_dict)
        }

@app.get("/show_csv_data")
async def show_csv_data():
    """data.csv 파일 내용을 반환"""
    try:
        if os.path.exists("data.csv"):
            df = pd.read_csv("data.csv")
            return {
                "status": "success",
                "data": df.to_dict(orient="records"),
                "data_count": len(df)
            }
        else:
            return {"status": "error", "message": "data.csv 파일이 존재하지 않습니다."}
    except Exception as e:
        return {"status": "error", "message": f"파일 읽기 오류: {str(e)}"}

@app.post("/force_backup")
async def force_backup():
    """수동으로 백업 수행"""
    try:
        backup_data_csv()
        return {"status": "success", "message": "백업이 완료되었습니다."}
    except Exception as e:
        return {"status": "error", "message": f"백업 중 오류 발생: {str(e)}"}

#디바이스 번호와 상태를 저장하는 리스트(0이면 비낙상, 1이면 낙상)
device_info = {}

class Device(BaseModel):
    device_id: str
    status: str

@app.post("/add_device")
async def add_device(device: Device):
    # 상태 업데이트 또는 추가
    device_info[device.device_id] = device.status # 추가함 디바이스
    
    # 상태별 카운트 계산
    status_0_count = sum(1 for s in device_info.values() if s == "0") # 0인 디바이스 개산
    status_1_count = sum(1 for s in device_info.values() if s == "1") # 1인 디바이스 개산
    status_diff = status_1_count - status_0_count # 1인거 수 뺴기 0인거 수
    
    return {
        "status": "updated" if device.device_id in device_info else "added",
        "device_id": device.device_id,
        "device_status": device.status,
        "all_devices": device_info,
        "alldevices_num": len(device_info),
        "status_0_count": status_0_count,
        "status_1_count": status_1_count,
        "status_diff": status_diff
    }

@app.get("/get_device_stats")
async def get_device_stats():
    """
    React 프론트엔드에서 호출하여:
    - status_0_count: 상태 0인 디바이스 개수 (비낙상)
    - total_devices: 전체 등록된 디바이스 개수
    """
    status_0_count = sum(1 for s in device_info.values() if s == "0")
    total_devices = len(device_info)
    return {
        "status_0_count": status_0_count,
        "total_devices": total_devices
    }

@app.get("/get_status")
async def get_status():
    """현재 시스템 상태 확인용 엔드포인트"""
    global mindex, data_dict
    battery_info = psutil.sensors_battery()
    with data_dict_lock:
        return {
            "mindex": mindex,
            "dict_data_count": len(data_dict),
            "battery_charging": battery_info.power_plugged if battery_info else None,
            "battery_percent": battery_info.percent if battery_info else None,
            "csv_exists": os.path.exists("data.csv"),
            "backup_csv_exists": os.path.exists("data_backup.csv")
        }

@app.post("/emergency_backup")
async def emergency_backup():
    """긴급 백업: 딕셔너리 데이터를 즉시 data_backup.csv에 저장"""
    global data_dict
    with data_dict_lock:
        if data_dict:
            try:
                df_dict = pd.DataFrame(data_dict)
                existing_columns = get_existing_columns("data_backup.csv")
                if existing_columns is not None:
                    df_dict = df_dict[existing_columns]
                    df_dict.to_csv("data_backup.csv", mode='a', header=True, index=False)
                else:
                    df_dict.to_csv("data_backup.csv", mode='w', header=True, index=False)
                
                data_count = len(data_dict)
                data_dict = []  # 딕셔너리 초기화
                
                return {
                    "status": "success", 
                    "message": f"긴급 백업 완료. {data_count}개 데이터를 data_backup.csv에 저장했습니다.",
                    "saved_count": data_count
                }
            except Exception as e:
                return {"status": "error", "message": f"긴급 백업 중 오류 발생: {str(e)}"}
        else:
            return {"status": "info", "message": "딕셔너리에 저장된 데이터가 없습니다."}

#time,acc_x,acc_y,acc_z,gyro_x,gyro_y,gyro_z,label
fall_df_cache = pd.DataFrame(columns=['device_id','time','acc_x','acc_y','acc_z','gyro_x','gyro_y','gyro_z','label'
])
@app.post("/fall-detection")
async def submit_fall_data(data: Dict[str, Any]):
    global data_dict, mindex, fall_df_cache

    # API 키 확인
    if data.get("api_key") != API_KEY:
        return {"status": "error", "message": "유효하지 않은 API 키입니다."}

    # 필드 정리 및 전처리
    device_id = data.get("mac_address", "Unknown")
    probability_str = data.get("probability", "0")
    time_str = data.get("timestamp", "")
    imu_data = data.get("imu_buffer", [])

    try:
        status_prob = float(probability_str)
    except ValueError:
        return {"status": "error", "message": "probability 값이 float이 아닙니다."}

    device_status = "1" if status_prob > 0.6 else "0"
    results = {}

    # 센서 데이터 저장
    with data_dict_lock:
        data_dict_obj = {
            "device_id": device_id,
            "probability": status_prob,
            "time": time_str,
            "imu": imu_data
        }

        if mindex in [0, 1]:
            if status_prob > 0.6:
                data_dict.append(data_dict_obj)
                print(f"낙상 저장 완료 (mindex={mindex}, 총 {len(data_dict)}개)")
            else:
                pass  # 낙상이 아닐 경우 저장하지 않음
            results["add_data"] = {
                "status": "success",
                "message": "낙상일 경우에만 data_dict에 저장되었습니다.",
                "mindex": mindex,
                "dict_size": len(data_dict)
            }
        elif mindex == 2:
            return {
                "status": "error",
                "message": "서버가 종료 중입니다. 데이터를 받을 수 없습니다.",
                "mindex": mindex
            }
        else:
            return {
                "status": "error",
                "message": f"알 수 없는 mindex 상태: {mindex}"
            }

        #  device_info 업데이트
        if device_id not in device_info:
            device_info[device_id] = {}

        # 중복 낙상 방지
        if device_info[device_id].get("status") == "1" and device_status == "1":
            return {
                "status": "info",
                "message": "이미 낙상 상태입니다. 중복 저장 안 함.",
                "device_id": device_id,
                "device_status": "1"
            }

        device_info[device_id]["status"] = device_status
        device_info[device_id].update(data_dict_obj)

        #  fall_df_cache 저장 (낙상일 때만)
        if status_prob > 0.6:
            if not imu_data or len(imu_data) != 100 or not all(len(row) == 6 for row in imu_data):
                return {"status": "error", "message": "imu_buffer는 100x6 형태여야 합니다."}
            try:
                all_rows = []
                for entry in data_dict:
                    time = entry["time"]
                    for i, row in enumerate(entry["imu"]):
                        if len(row) == 6:
                            all_rows.append({
                            "device_id": device_id,
                            "time": time,
                            "acc_x": row[0],
                            "acc_y": row[1],
                            "acc_z": row[2],
                            "gyro_x": row[3],
                            "gyro_y": row[4],
                            "gyro_z": row[5],
                            "label": 1
                        })
                    if all_rows:
                        df = df.append(pd.DataFrame(all_rows, columns=['device_id', 'time', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z', 'label']))
                        print(f"저장 완료.")
                    else:
                        print("백업할 데이터 없음.")
            except Exception as e:
                return {"a"}

    # 전체 상태 통계
    status_0_count = sum(1 for s in device_info.values() if s.get("status") == "0")
    status_1_count = sum(1 for s in device_info.values() if s.get("status") == "1")

    results["add_device"] = {
        "status": "updated" if device_id in device_info else "added",
        "device_id": device_id,
        "device_status": device_status,
        "alldevices_num": len(device_info),
        "status_0_count": status_0_count,
        "status_1_count": status_1_count,
        "status_diff": status_1_count - status_0_count
    }

    results["request_status"] = "OK"
    return results


# device_s 
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_spa(full_path: str):    
    file_path = os.path.join(BUILD_DIR, full_path)
    # 만약 실제 파일이 있으면 그걸 제공
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    # 없으면 index.html로 반환 (SPA 라우팅 지원)
    return FileResponse(os.path.join(BUILD_DIR, "index.html"))

#서버 열기
if __name__ == "__main__":
        import uvicorn
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8090,
            access_log=False
        )
