import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import FallIcon from './assets/WarningFallingImage.svg';

// 환경변수 설정
const API_KEY = process.env.REACT_APP_API_KEY || '';
const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://seaon.iptime.org:8090';

// 날짜 처리 함수(24시 형식)
function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

type NoticeType = {
  id: number;
  text: string;
};

type SensorData = {
  device_id: string;
  time: string;
  acc_x: number;
  acc_y: number;
  acc_z: number;
  gyro_x: number;
  gyro_y: number;
  gyro_z: number;
};

export default function App() {
  const [now, setNow] = useState(formatDate(new Date()));
  const [notices, setNotices] = useState<NoticeType[]>([]);
  const [userStats, setUserStats] = useState<{ current: number; total: number }>({
    current: 0,
    total: 0,
  });
  const [sensorList, setSensorList] = useState<SensorData[]>([]);
  const nextNoticeId = useRef(1);

  // 1) 현재 시간 초 단위 업데이트
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(formatDate(new Date()));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // 2) /get_device_stats 폴링 (1초마다)
  useEffect(() => {
    async function fetchDeviceStats() {
      try {
        const res = await fetch(`${API_BASE_URL}/get_device_stats`);
        if (!res.ok) throw new Error('Network response was not ok');
        const json = await res.json();
        setUserStats({
          current: json.status_0_count,
          total: json.total_devices,
        });
      } catch (err) {
        console.error('디바이스 통계 조회 오류:', err);
      }
    }

    fetchDeviceStats();
    const intervalId = setInterval(fetchDeviceStats, 1000);
    return () => clearInterval(intervalId);
  }, []);

  // 3) /show_data 폴링 (1초마다) → 새로운 센서 데이터만 추출해서 Notice에 "{device_id} Fall detected" 추가
  useEffect(() => {
    async function fetchSensorData() {
      try {
        const res = await fetch(`${API_BASE_URL}/show_data`);
        if (!res.ok) throw new Error('Network response was not ok');
        const json = await res.json();
        const dataArr: SensorData[] = json.data;

        if (Array.isArray(dataArr)) {
          const prevCount = sensorList.length;
          const newCount = dataArr.length;

          if (newCount > prevCount) {
            const newlyAdded = dataArr.slice(prevCount);
            const newNotices: NoticeType[] = newlyAdded.map((item) => {
              return {
                id: nextNoticeId.current++,
                text: `${item.device_id} Fall detected`,
              };
            });
            setNotices((prev) => [...prev, ...newNotices]);
          }
          setSensorList(dataArr);
        }
      } catch (err) {
        console.error('센서 데이터 조회 오류:', err);
      } 
    }

    fetchSensorData();
    const intervalId = setInterval(fetchSensorData, 1000);
    return () => clearInterval(intervalId);
  }, [sensorList]);

  // 4) 낙상 감지 테스트 버튼 클릭 시 → /fall_detection 호출 -- 테스트용
  const handleDetectFall = async () => {
    const payload: SensorData & { api_key: string } = {
      device_id: 'test7',
      time: now,
      acc_x: 0.0,
      acc_y: 0.0,
      acc_z: 9.81,
      gyro_x: 0.0,
      gyro_y: 0.0,
      gyro_z: 0.0,
      api_key: API_KEY,
    };

    try {
      // 통합형 API 호출
      const response = await fetch(`${API_BASE_URL}/fall-detection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      console.log('fall_detection 응답:', result);

      alert(
        `${payload.device_id}의 낙상 정보가 서버에 전송되었습니다:\n` +
          JSON.stringify(result, null, 2),
      );
    } catch (error) {
      console.error('서버 전송 실패:', error);
      alert('서버 전송 중 오류가 발생했습니다.');
    }
  };

  return (
    <div className="main-bg">
      <div className="header">
        Real-time fall detection system
        <br />
        For administrator
      </div>

      <div className="top-info">
        <div className="user-box">
          Number of registered devices: {userStats.total}
        </div>
      </div>

      <div className="main-card">
        <div className="notice-area">
          <div className="notice-title">Notice</div>
          <div className="notice-list">
            {notices.map((item) => (
              <div className="notice-item" key={item.id}>
                <span className="notice-num">{item.id}</span> {item.text}
              </div>
            ))}
          </div>
        </div>

        <div className="fall-area">
          <div className="fall-icon">
            <img src={FallIcon} alt="Fall icon" width="447" height="300" />
          </div>
          <div className="fall-bar">Fall Detected</div>
          <div className="fall-number">{notices.length}</div>
        </div>
      </div>

      <div className="timestamp">TimeStamp: {now}</div>
    </div>
  );
}