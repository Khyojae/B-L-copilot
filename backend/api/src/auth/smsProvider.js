// 실제 SMS 게이트웨이(NICE/PASS, Twilio 등) 연동은 학생 프로젝트 규모에서 비용/계약 부담이 커서
// 개발 단계에서는 콘솔에 코드만 남기는 스텁으로 대체한다. 나중에 실제 프로바이더로 바꿀 때는
// 이 send 함수 하나만 교체하면 된다 — 호출하는 쪽(phoneVerification.service.js)은 그대로 둔다.
async function send(phoneNumber, code) {
  console.log(`[dev-sms-stub] to=${phoneNumber} code=${code}`);
}

module.exports = { send };
