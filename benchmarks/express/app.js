const express = require('express');
const app = express();
app.use(express.json());
app.get('/', (req, res) => res.send('Hello, Express!'));
app.get('/hello/:name', (req, res) => res.send(`Hello, ${req.params.name}!`));
app.get('/user/:id', (req, res) => res.json({id: req.params.id, name: 'Ada'}));
app.post('/echo', (req, res) => res.json(req.body || {}));
app.get('/search', (req, res) => res.json({q: req.query.q || ''}));
app.get('/json', (req, res) => res.json({message: 'hello', items: Array.from({length:3000}, (_,i)=>i), nested:{a:'b', count:3000}}));
for(let i=0;i<500;i++){ app.get(`/dummy_${i}`, (req,res)=> res.send(`dummy ${i}`)); }
const port = process.env.PORT || 3000;
app.listen(port, '127.0.0.1', () => console.log(`Express on http://127.0.0.1:${port}/`));
