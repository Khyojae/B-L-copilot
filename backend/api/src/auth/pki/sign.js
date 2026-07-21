const crypto = require('crypto');

function signDocument(pdfBuffer, privateKeyPem) {
  const documentHash = crypto.createHash('sha256').update(pdfBuffer).digest('hex');
  const signature = crypto.sign('sha256', pdfBuffer, privateKeyPem).toString('base64');
  return { documentHash, signature };
}

module.exports = { signDocument };
