## 공동개발

## Changelog
- 1.1.20 (2024.09.23)    
  tvdb 점검.   

- 1.1.19 (2024.09.03)    
  wavve 타임아웃 설정.

- 1.1.18 (2024.09.03)    
  tving 로그인 수정.   

- 1.1.17 (2024.09.01)    
  wavve redis 초기화를 use_celery=False 경우 하지 않도록 수정.   

- 1.1.16 (2024.08.28)    
  tmdb 등록된 한글 이름 사용하도록 수정.   

- 1.1.15 (2024.07.29)    
  tving drm request header 정리.   

- 1.1.14 (2024.07.27)
  alive와 연동을 위한 wavve 모듈 수정

- 1.1.13 (2024.06.30)   
  tving drm 변경 대응.      

- 1.1.11 (2024.06.24)   
  alive와 연동을 위한 tving 모듈 수정   

- 1.1.10 (2024.06.23)   
  최신 `requests_cache`과 호환되도록 패치한 `tvdb_api`를 내장   

- 1.1.9 (2024.06.22)   
  EPG 관련 수정.   

- 1.1.8 (2024.06.20)   
  wavve 방송일자 None 방지   

- 1.1.7 (2024.06.20)   
  wavve 방송일자 및 검색 최신 정렬   

- 1.1.6 (2024.06.13)   

- 1.1.5 (2024.06.11)   
  KTV 메타데이터 관련 연동 수정.   

- 1.1.4 (2024.06.05)   
  imgur 관련 기능 추가   

- 1.1.3 (2024.06.05)   
  daum 이미지 가져오는 부분 수정.   
  ```url = img_tag.attrib.get('data-original-src') or img_tag.attrib.get('src')```   

- 1.1.1 (2024.06.03)   
  wavve 관련 수정.   

- 1.1.0 (2024.06.02)   
  통합버전 START!!!   

- 1.0.6p (2024.06.01) by soju   
  daum extra title 이모지 제거, premiered 변경사항 대응   