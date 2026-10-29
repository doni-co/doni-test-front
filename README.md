## 실행 방법

### 1. 필수 환경

실행 전에 다음 서비스가 실행 중이어야 합니다.

- **백엔드 서버**: `localhost:8000`
- **Celery Worker**: 백그라운드 작업 처리

### 2. 패키지 설치

```bash
pip install "streamlit>=1.37" requests streamlit-flow-component
```

### 3. 애플리케이션 실행

```bash
streamlit run app_ui.py
```

실행 후 터미널에 표시되는 로컬 URL로 접속합니다.
