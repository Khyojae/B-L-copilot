const crypto = require('crypto');

// email_verification_tokens / phone_verifications / password_reset_tokens 세 곳 모두
// "무작위 값 생성 -> 원문은 사용자에게, 해시만 DB에 저장 -> 만료시각 계산" 패턴이 동일해서
// 공통 유틸로 뺐다. 저장(DB)은 각 서비스가 맡는다.

function generateToken(bytes = 32) {
  const token = crypto.randomBytes(bytes).toString('hex');
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
  return { token, tokenHash };
}

function generateNumericCode(digits = 6) {
  const max = 10 ** digits;
  const code = crypto.randomInt(0, max).toString().padStart(digits, '0');
  const codeHash = crypto.createHash('sha256').update(code).digest('hex');
  return { code, codeHash };
}

function expiresInMinutes(minutes) {
  return new Date(Date.now() + minutes * 60 * 1000);
}

module.exports = { generateToken, generateNumericCode, expiresInMinutes };
