const test = require('node:test');
const assert = require('node:assert/strict');
const forge = require('node-forge');
const { verifyChain } = require('../../src/auth/pki/ca');
const { signDocument } = require('../../src/auth/pki/sign');
const { verifyDocumentSignature } = require('../../src/auth/pki/verify');

function issueCert({ publicKey, serialNumber, subject, issuerCert, signingKey, notBefore, notAfter, isCa }) {
  const cert = forge.pki.createCertificate();
  cert.publicKey = publicKey;
  cert.serialNumber = serialNumber;
  cert.validity.notBefore = notBefore;
  cert.validity.notAfter = notAfter;
  cert.setSubject(subject);
  cert.setIssuer(issuerCert ? issuerCert.subject.attributes : subject);
  cert.setExtensions([
    { name: 'basicConstraints', cA: isCa },
    isCa
      ? { name: 'keyUsage', keyCertSign: true, digitalSignature: true, cRLSign: true }
      : { name: 'keyUsage', digitalSignature: true, nonRepudiation: true },
  ]);
  cert.sign(signingKey, forge.md.sha256.create());
  return cert;
}

function makeRootCa() {
  const keys = forge.pki.rsa.generateKeyPair(1024);
  const subject = [{ name: 'commonName', value: 'Test Root CA' }];
  const cert = issueCert({
    publicKey: keys.publicKey,
    serialNumber: '01',
    subject,
    issuerCert: null,
    signingKey: keys.privateKey,
    notBefore: new Date(Date.now() - 24 * 3600 * 1000),
    notAfter: new Date(Date.now() + 365 * 24 * 3600 * 1000),
    isCa: true,
  });
  return { cert, keys };
}

function makeCarrierCert(rootCa, { notBefore, notAfter } = {}) {
  const keys = forge.pki.rsa.generateKeyPair(1024);
  const cert = issueCert({
    publicKey: keys.publicKey,
    serialNumber: '1001',
    subject: [{ name: 'commonName', value: 'Test Carrier' }],
    issuerCert: rootCa.cert,
    signingKey: rootCa.keys.privateKey,
    notBefore: notBefore || new Date(Date.now() - 24 * 3600 * 1000),
    notAfter: notAfter || new Date(Date.now() + 365 * 24 * 3600 * 1000),
    isCa: false,
  });
  return { cert, keys };
}

const pdf = Buffer.from('fake e-B/L pdf bytes for testing');

test('valid document + valid certificate passes all 4 steps', async () => {
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);
  const { signature } = signDocument(pdf, forge.pki.privateKeyToPem(carrier.keys.privateKey));

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature,
    certificate: carrier.cert,
    rootCaCertificate: rootCa.cert,
  });

  assert.deepEqual(result, { valid: true });
});

test('tampered document fails at the signature step', async () => {
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);
  const { signature } = signDocument(pdf, forge.pki.privateKeyToPem(carrier.keys.privateKey));
  const tampered = Buffer.from('a DIFFERENT byte stream');

  const result = await verifyDocumentSignature({
    pdfBuffer: tampered,
    signature,
    certificate: carrier.cert,
    rootCaCertificate: rootCa.cert,
  });

  assert.equal(result.valid, false);
  assert.equal(result.step, 'signature');
});

test('revoked certificate fails at the revocation step', async () => {
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);
  const { signature } = signDocument(pdf, forge.pki.privateKeyToPem(carrier.keys.privateKey));

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature,
    certificate: carrier.cert,
    rootCaCertificate: rootCa.cert,
    isRevoked: async () => true,
  });

  assert.equal(result.valid, false);
  assert.equal(result.step, 'revocation');
});

test('expired certificate fails at the expiry step (not misreported as chain failure)', async () => {
  const rootCa = makeRootCa();
  const expiredCarrier = makeCarrierCert(rootCa, {
    notBefore: new Date('2020-01-01'),
    notAfter: new Date('2021-01-01'),
  });
  const { signature } = signDocument(pdf, forge.pki.privateKeyToPem(expiredCarrier.keys.privateKey));

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature,
    certificate: expiredCarrier.cert,
    rootCaCertificate: rootCa.cert,
  });

  assert.equal(result.valid, false);
  assert.equal(result.step, 'expiry');
});

test('certificate issued by a different (untrusted) root CA fails at the chain step', async () => {
  const realRoot = makeRootCa();
  const fakeRoot = makeRootCa();
  const impostorCarrier = makeCarrierCert(fakeRoot);
  const { signature } = signDocument(pdf, forge.pki.privateKeyToPem(impostorCarrier.keys.privateKey));

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature,
    certificate: impostorCarrier.cert,
    rootCaCertificate: realRoot.cert,
  });

  assert.equal(result.valid, false);
  assert.equal(result.step, 'chain');
});

test('verifyChain in isolation trusts a cert signed by the given root', () => {
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);
  assert.equal(verifyChain(carrier.cert, rootCa.cert).valid, true);
});

test('signDocument is deterministic and its documentHash matches an independent SHA-256 computation', () => {
  const crypto = require('node:crypto');
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);
  const privateKeyPem = forge.pki.privateKeyToPem(carrier.keys.privateKey);

  const first = signDocument(pdf, privateKeyPem);
  const second = signDocument(pdf, privateKeyPem);

  const expectedHash = crypto.createHash('sha256').update(pdf).digest('hex');
  assert.equal(first.documentHash, expectedHash);
  assert.equal(first.documentHash, second.documentHash);
  // RSA PKCS#1 v1.5 signatures are deterministic for a given key+message, unlike e.g. ECDSA.
  assert.equal(first.signature, second.signature);
});

test('an expired AND revoked certificate reports expiry first (checked before revocation)', async () => {
  const rootCa = makeRootCa();
  const expiredAndRevokedCarrier = makeCarrierCert(rootCa, {
    notBefore: new Date('2020-01-01'),
    notAfter: new Date('2021-01-01'),
  });
  const { signature } = signDocument(pdf, forge.pki.privateKeyToPem(expiredAndRevokedCarrier.keys.privateKey));

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature,
    certificate: expiredAndRevokedCarrier.cert,
    rootCaCertificate: rootCa.cert,
    isRevoked: async () => true,
  });

  assert.equal(result.step, 'expiry');
});

test('a garbage/malformed signature value fails cleanly at the signature step instead of throwing', async () => {
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature: 'not-valid-base64-or-a-real-signature!!',
    certificate: carrier.cert,
    rootCaCertificate: rootCa.cert,
  });

  assert.equal(result.valid, false);
  assert.equal(result.step, 'signature');
});

test('an empty-string signature also fails cleanly at the signature step', async () => {
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature: '',
    certificate: carrier.cert,
    rootCaCertificate: rootCa.cert,
  });

  assert.equal(result.valid, false);
  assert.equal(result.step, 'signature');
});

test('isRevoked defaulting to absent (not injected yet) skips the revocation step rather than throwing', async () => {
  const rootCa = makeRootCa();
  const carrier = makeCarrierCert(rootCa);
  const { signature } = signDocument(pdf, forge.pki.privateKeyToPem(carrier.keys.privateKey));

  const result = await verifyDocumentSignature({
    pdfBuffer: pdf,
    signature,
    certificate: carrier.cert,
    rootCaCertificate: rootCa.cert,
    // isRevoked intentionally omitted — simulates calling this before DB wiring exists
  });

  assert.deepEqual(result, { valid: true });
});
