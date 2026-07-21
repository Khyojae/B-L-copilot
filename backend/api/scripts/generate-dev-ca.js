const fs = require('fs');
const path = require('path');
const forge = require('node-forge');

const CERTS_DIR = path.join(__dirname, '..', 'certs');

function issueCertificate({ publicKey, serialNumber, subjectAttrs, issuerAttrs, signingKey, validityYears, isCa }) {
  const cert = forge.pki.createCertificate();
  cert.publicKey = publicKey;
  cert.serialNumber = serialNumber;
  cert.validity.notBefore = new Date();
  cert.validity.notAfter = new Date();
  cert.validity.notAfter.setFullYear(cert.validity.notBefore.getFullYear() + validityYears);
  cert.setSubject(subjectAttrs);
  cert.setIssuer(issuerAttrs);
  cert.setExtensions([
    { name: 'basicConstraints', cA: isCa },
    isCa
      ? { name: 'keyUsage', keyCertSign: true, digitalSignature: true, cRLSign: true }
      : { name: 'keyUsage', digitalSignature: true, nonRepudiation: true },
  ]);
  cert.sign(signingKey, forge.md.sha256.create());
  return cert;
}

function writePem(filePath, pem) {
  fs.writeFileSync(filePath, pem);
}

function main() {
  fs.mkdirSync(CERTS_DIR, { recursive: true });

  const rootKeys = forge.pki.rsa.generateKeyPair(2048);
  const rootAttrs = [
    { name: 'commonName', value: 'Smart-eBL Dev Root CA' },
    { name: 'organizationName', value: 'Smart-eBL' },
  ];
  const rootCert = issueCertificate({
    publicKey: rootKeys.publicKey,
    serialNumber: '01',
    subjectAttrs: rootAttrs,
    issuerAttrs: rootAttrs,
    signingKey: rootKeys.privateKey,
    validityYears: 10,
    isCa: true,
  });

  writePem(path.join(CERTS_DIR, 'root-ca-cert.pem'), forge.pki.certificateToPem(rootCert));
  writePem(path.join(CERTS_DIR, 'root-ca-key.pem'), forge.pki.privateKeyToPem(rootKeys.privateKey));

  const carrierKeys = forge.pki.rsa.generateKeyPair(2048);
  const carrierCert = issueCertificate({
    publicKey: carrierKeys.publicKey,
    serialNumber: '1001',
    subjectAttrs: [
      { name: 'commonName', value: 'Dev Test Carrier' },
      { name: 'organizationName', value: 'Test Carrier Co' },
    ],
    issuerAttrs: rootAttrs,
    signingKey: rootKeys.privateKey,
    validityYears: 1,
    isCa: false,
  });

  writePem(path.join(CERTS_DIR, 'test-carrier-cert.pem'), forge.pki.certificateToPem(carrierCert));
  writePem(path.join(CERTS_DIR, 'test-carrier-key.pem'), forge.pki.privateKeyToPem(carrierKeys.privateKey));

  console.log('Generated dev root CA + test carrier certificate in', CERTS_DIR);
}

main();
