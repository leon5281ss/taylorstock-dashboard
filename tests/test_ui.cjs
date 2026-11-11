const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', addEventListener() {} });
  return elements.get(id);
};
const context = vm.createContext({
  document: { getElementById: element, querySelectorAll: () => [], body: { addEventListener() {} } },
  fetch: async () => ({ ok: false }),
});
const code = fs.readFileSync('docs/assets/app.js', 'utf8').replace(/init\(\);\s*$/, '');
vm.runInContext(code, context);
const payload = JSON.parse(fs.readFileSync('docs/data/stocks.json', 'utf8'));
payload.marketMonitor = { governmentBank: { label: '無權限' }, sources: [], items: [{ topics: ['國安基金', '政府護盤'], publishedDate: null, title: '<script>政策</script>', url: 'javascript:alert(1)' }] };
context.payload = payload;
vm.runInContext('state.data = payload; state.stocks = payload.stocks; render();', context);
const html = element('marketMonitor').innerHTML;
assert.ok(html.includes('無權限'));
assert.ok(html.includes('&lt;script&gt;'));
assert.ok(!html.includes('href="javascript:'));
assert.equal(html.split('&lt;script&gt;').length - 1, 1);
assert.equal((element('stockTableBody').innerHTML.match(/<tr>/g) || []).length, 22);
console.log('UI rendering: 22 symbols, market dedupe and escaping passed');
