const crypto = require('crypto');
const forge = require('node-forge');
const { verifyChain } = require('./ca');

// isRevoked(serialNumber) -> Promise<boolean>는 DB(certificates.is_revoked) 조회가 필요해
// 호출하는 쪽에서 주입한다. 주입하지 않으면 폐기 확인 단계는 건너뛴다.
async function verifyDocumentSignature({ pdfBuffer, signature, certificate, rootCaCertificate, isRevoked }) {
  // 만료 확인을 체인 검증보다 먼저 한다 — forge의 체인 검증이 날짜 체크를 함께 수행해서
  // 순서를 바꾸면(ca.js verifyChain 주석 참고) "chain"/"expiry" 실패 원인이 뒤섞이기 때문.
  const now = new Date();
  if (now < certificate.validity.notBefore || now > certificate.validity.notAfter) {
    return { valid: false, step: 'expiry', reason: 'certificate is not within its validity period' };
  }

  const chainResult = verifyChain(certificate, rootCaCertificate);
  if (!chainResult.valid) {
    return { valid: false, step: 'chain', reason: chainResult.reason };
  }

  if (typeof isRevoked === 'function') {
    const revoked = await isRevoked(certificate.serialNumber);
    if (revoked) {
      return { valid: false, step: 'revocation', reason: 'certificate has been revoked' };
    }
  }

  const publicKeyPem = forge.pki.publicKeyToPem(certificate.publicKey);
  const signatureValid = crypto.verify('sha256', pdfBuffer, publicKeyPem, Buffer.from(signature, 'base64'));
  if (!signatureValid) {
    return { valid: false, step: 'signature', reason: 'signature does not match document' };
  }

  return { valid: true };
}

module.exports = { verifyDocumentSignature };
