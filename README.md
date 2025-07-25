## 공동개발

## Changelog
- 1.2.3 (2025.07.11) by soju6jan
  - jav censored 준비
<br><br>  
- 1.1.46 (2025.06.29)
    - Flaskfarm 로그 보안 적용 수정
<br><br>
- 1.1.45 (2025.06.20)
    - 네이버 로그인 API 지원, 카페 글쓰기 API 추가
<br><br>
- 1.1.44 (2025.06.10)
    - Wavve: 썸네일 url 정규화
<br><br>
- 1.1.43 (2025.06.03)
    - Wavve
        - API 버전 호환성 보완
        - 파일명의 제목 및 회차 번호 정규식 설정 추가
<br><br>
- 1.1.42 (2025.05.25)
    - Wavve: 스트리밍 주소 만료 확인 방식 추가
    - Tving: 프록시 Off시 프록시 주소 초기화
<br><br>
- 1.1.41 (2025.05.02)
    - Wavve: live streaming 데이터를 받아올 때 abr 여부를 강제하지 않음
<br><br>
- 1.1.40 (2025.04.29)
    - Wavve 업데이트 
<br><br>
- 1.1.39 (2025.04.21)
    - Wavve 버그 수정
<br><br>
- 1.1.38 (2025.04.20)
    - 사이트 설정 변경시 session 초기화
    - Daum 회차 방송일 예외 처리
    - Wavve API 요청 실패 처리 수정
<br><br>
- 1.1.37 (2025.04.11)
    - Daum 캡챠 escape 처리
<br><br>
- 1.1.36 (2025.03.27)
    - TV 쇼 plot 정보 출처 추가
<br><br>
- 1.1.35 (2025.03.25)
    - Daum TV 방송사 예외 처리
    - 웨이브 자동 로그인 예외 처리
<br><br>
- 1.1.34 (2025.03.20)
    - 웨이브 예외 처리
<br><br>
- 1.1.33 (2025.03.19)
    - 웨이브 Credential 만료시 재로그인
    - 기타 수정
<br><br>
- 1.1.32 (2025.03.13)
    - 왓챠 스틸컷 오류 수정
    - 기타 예외 처리
<br><br>
- 1.1.31 (2025.02.16)
    - Daum TV 장르 오류 수정
<br><br>
- 1.1.30 (2025.02.14)
    - 오류 수정
<br><br>
- 1.1.29 (2025.02.10)
    - Tving v3 대응
<br><br>
- 1.1.28 (2025.02.01)
    - redis 오류 수정
<br><br>
- 1.1.27 (2025.01.31)
    - 애플 오리지널 제목 검색 재시도
    - Daum 영화 수정
<br><br>
- 1.1.26 (2025.01.28)
    - Daum 영화 일부 복구
    - 왓챠 일부 타이틀 버그 수정
<br><br>
- 1.1.25 (2025.01.27)
    - 왓챠 프록시 적용
    - 왓챠 API 수정
<br><br>
- 1.1.24p19 (2025.01.26)
    - 다음 TV 정보 변경 대응 업데이트
    - 웨이브 전체 채널 수 제한 버그 수정
    - Daum 사용자 쿠키 수정
    - 에피소드 방영일에 redis 적용
    - 다음 에피소드 목록 수집 방식 변경
    - 왓챠 API URL 수정
    - 버그 수정 및 코드 정리
<br><br>
- 1.1.23 (2025.01.11)
    - 다음 TV 정보 변경 대응 업데이트
<br><br>
- 1.1.22 (2025.01.10)
    - 다음 TV 정보 수집 방식 수정
<br><br>
- 1.1.21 (2024.12.04)
    - wavve API 클래스 분리
<br><br>
- 1.1.20 (2024.09.23)
    - tvdb 점검.
<br><br>
- 1.1.19 (2024.09.03)
    - wavve 타임아웃 설정.
<br><br>
- 1.1.18 (2024.09.03)
    - tving 로그인 수정.
<br><br>
- 1.1.17 (2024.09.01)
    - wavve redis 초기화를 use_celery=False 경우 하지 않도록 수정.
<br><br>
- 1.1.16 (2024.08.28)
    - tmdb 등록된 한글 이름 사용하도록 수정.
<br><br>
- 1.1.15 (2024.07.29)
    - tving drm request header 정리.
<br><br>
- 1.1.14 (2024.07.27)
    - alive와 연동을 위한 wavve 모듈 수정
<br><br>
- 1.1.13 (2024.06.30)
    - tving drm 변경 대응.
<br><br>
- 1.1.11 (2024.06.24)
    - alive와 연동을 위한 tving 모듈 수정
<br><br>
- 1.1.10 (2024.06.23)
    - 최신 `requests_cache`과 호환되도록 패치한 `tvdb_api`를 내장
<br><br>
- 1.1.9 (2024.06.22)
    - EPG 관련 수정.
<br><br>
- 1.1.8 (2024.06.20)
    - wavve 방송일자 None 방지
<br><br>
- 1.1.7 (2024.06.20)
    - wavve 방송일자 및 검색 최신 정렬
<br><br>
- 1.1.6 (2024.06.13)
<br><br>
- 1.1.5 (2024.06.11)
    - KTV 메타데이터 관련 연동 수정.
<br><br>
- 1.1.4 (2024.06.05)
    - imgur 관련 기능 추가
<br><br>
- 1.1.3 (2024.06.05)
    - daum 이미지 가져오는 부분 수정.<br>
    ```url = img_tag.attrib.get('data-original-src') or img_tag.attrib.get('src')```
<br><br>
- 1.1.1 (2024.06.03)
    - wavve 관련 수정.
<br><br>
- 1.1.0 (2024.06.02)
    - 통합버전 START!!!
<br><br>
- 1.0.6p (2024.06.01) by soju
    - daum extra title 이모지 제거, premiered 변경사항 대응