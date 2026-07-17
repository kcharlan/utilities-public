import express from 'express';
const app = express();

app.get('/api/node/hello', (req, res) => {
  res.json({ ok: true, from: 'node' });
});

app.listen(4000, '0.0.0.0', () => {
  console.log('Node API on 4000');
});
