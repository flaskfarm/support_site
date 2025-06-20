## 네이버 로그인 & 카페 글쓰기

<br><br>

### 네이버 로그인 설정   
  [네이버 개발자 센터](https://developers.naver.com/apps/#/list) 에서 Application 등록.
  - 적당한 이름을 넣고, 사용 API에 카페 선택  
    <img src="https://i.imgur.com/XGAWjTF.png" width="50%" height="50%" />
  - 로그인 오픈 API 서비스 환경 PC웹 선택  
  - 서비스 URL에 본인 FF 주소
  - 네이버 로그인 Callback URL에 본인 FF주소/support_site/site/naverlogin  
    <img src="https://i.imgur.com/tMwOeqL.png" width="60%" height="60%" />
  - 애플리케이션 정보 Client ID, Secret 설정 창에 입력 후 로그인 버튼 클릭.
  - 팝업창이 나오고 동의 후 설정에 Token 값 입력되는지 확인.  
    <img src="https://i.imgur.com/PPZIwQx.png" width="30%" height="30%" />

----

### 네이버 카페 글쓰기 API
  참고: [https://developers.naver.com/docs/login/cafe-api/cafe-api.md](https://developers.naver.com/docs/login/cafe-api/cafe-api.md)

  ```
  from support_site import ToolNaverCafe
  cafe_id = "30871085"  # 네이버 카페 ID
  menu_id = "9"  # 네이버 카페 메뉴 ID     
  subject = "테스트"
  content = "네이버 카페 테스트입니다."
  ret = ToolNaverCafe.write_post(cafe_id, menu_id, subject, content)
  ```

  특이사항
    - 카페 API 문제로 인해 content에 " 를 사용할 수 없음.  
    - 말머리 사용 불가.  

----
## imgur 설정

<br><br>

### Token 설정   
  1. [https://imgur.com](https://imgur.com) 회원가입 후 [https://api.imgur.com/oauth2/addclient](https://api.imgur.com/oauth2/addclient) Application 등록   
  2. Application type with a callback URL 선택.   
     callback URL에 **FF주소/support_site/site/imgur**  입력 후 submit 제출하여 앱 등록   
    <img src="https://i.imgur.com/0Ub50ZC.png" width="400" height="300" />
  3. 설정에서 Client ID, Client Secret 입력 후 사용 동의 클릭.   
  4. 팝업창 imgur 로그인 후 allow 클릭   
  5. FF 새로 고침하여 Token 확인   

<br>

### imgur 업로드

  참고 사이트 : [https://github.com/layerssss/paste.js](https://github.com/layerssss/paste.js)

  이미지를 클립보드에 복사한 후 붙여넣기 하면 imgur에 업로드 후 링크를 알려준다.   
  본인 계정의 "cdn" 앨범에 저장.   
  <img src="https://i.imgur.com/1jwkUnX.png" width="50%" height="50%" />
