/**
 * Sample Node.js server with realistic bugs for testing static analysis.
 */

const express = require('express');
const fs = require('fs');
const app = express();

// XSS vulnerability - unsanitized user input in response
app.get('/search', (req, res) => {
    const query = req.query.q;
    res.send(`<h1>Results for: ${query}</h1>`);
});

// SQL injection via string concatenation
app.get('/user/:id', (req, res) => {
    const userId = req.params.id;
    const query = `SELECT * FROM users WHERE id = '${userId}'`;
    db.query(query, (err, results) => {
        res.json(results);
    });
});

// Hardcoded secrets
const API_KEY = "sk-prod-abc123xyz456";
const DB_PASSWORD = "admin123";

// Prototype pollution vulnerability
app.post('/config', (req, res) => {
    const config = {};
    Object.assign(config, req.body);
    res.json(config);
});

// Missing error handling
app.get('/file/:name', (req, res) => {
    const content = fs.readFileSync('/data/' + req.params.name);
    res.send(content);
});

// Race condition - shared mutable state
let requestCount = 0;
app.get('/count', (req, res) => {
    requestCount++;
    setTimeout(() => {
        res.json({ count: requestCount });
    }, 100);
});

// Unused variable
const unusedConfig = { port: 3000, host: 'localhost' };

app.listen(3000);
