const express = require('express');
const fs = require('fs');
const app = express();

app.get('/search', (req, res) => {
  const query = req.query.q;
  res.send(`<h1>Results for: ${query}</h1>`);
});

app.get('/user/:id', (req, res) => {
  const userId = req.params.id;
  const query = `SELECT * FROM users WHERE id = '${userId}'`;
  db.query(query, (err, results) => {
    res.json(results);
  });
});

app.get('/file/:name', (req, res) => {
  const content = fs.readFileSync('/data/' + req.params.name);
  res.send(content);
});
