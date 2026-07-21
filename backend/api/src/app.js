const express = require('express');
const helmet = require('helmet');
const cookieParser = require('cookie-parser');

function createApp() {
  const app = express();

  app.use(helmet());
  app.use(express.json());
  app.use(cookieParser());

  app.get('/health', (req, res) => {
    res.json({ status: 'ok' });
  });

  app.use((err, req, res, next) => {
    const status = err.status || 500;
    res.status(status).json({ error: err.publicMessage || 'Internal Server Error' });
  });

  return app;
}

module.exports = { createApp };
