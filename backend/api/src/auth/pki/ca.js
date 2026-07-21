const fs = require('fs');
const forge = require('node-forge');

function loadCertificate(pemPath) {
  const pem = fs.readFileSync(pemPath, 'utf8');
  return forge.pki.certificateFromPem(pem);
}

function loadPrivateKeyPem(pemPath) {
  return fs.readFileSync(pemPath, 'utf8');
}

// forge의 체인 검증은 만료 여부도 함께 판단하는데, validityCheckDate로 이를 끄면
// (verify 콜백을 안 주는 한) 오히려 "신뢰 안 됨"으로 오판하는 버그성 동작이 있었음.
// 그래서 만료 확인은 verify.js에서 이 함수보다 먼저 별도로 수행하고, 여기서는
// (이미 만료되지 않은 것으로 확인된) 인증서의 신뢰 체인만 forge 기본 동작으로 검사한다.
function verifyChain(certificate, rootCaCertificate) {
  try {
    const caStore = forge.pki.createCaStore([rootCaCertificate]);
    forge.pki.verifyCertificateChain(caStore, [certificate]);
    return { valid: true };
  } catch (err) {
    return { valid: false, reason: (err && err.message) || 'chain verification failed' };
  }
}

module.exports = { loadCertificate, loadPrivateKeyPem, verifyChain };
