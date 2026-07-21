require('dotenv').config();

const { createApp } = require('./src/app');

const app = createApp();
const port = process.env.PORT || 4000;

app.listen(port, () => {
  console.log(`api listening on port ${port}`);
});
