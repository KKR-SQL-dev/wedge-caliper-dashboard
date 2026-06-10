# L9 PVB Wedge Film Caliper Monitoring Dashboard

## 접속 주소

```
http://192.168.107.6:3021
```

## 실행

```bash
streamlit run app.py
```

## 방화벽 설정

포트 3021 인바운드 허용 (PowerShell 관리자):

```powershell
New-NetFirewallRule -DisplayName "Wedge Dashboard 3021" -Direction Inbound -LocalPort 3021 -Protocol TCP -Action Allow
```
