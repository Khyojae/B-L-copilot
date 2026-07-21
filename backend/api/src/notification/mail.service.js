const { getTransporter } = require('./mailer');

async function sendMail({ to, subject, text, html }) {
  const transporter = getTransporter();

  return transporter.sendMail({
    from: process.env.EMAIL_FROM,
    to,
    subject,
    text,
    html,
  });
}

module.exports = { sendMail };
