// A API não é pública. A integração é manual e opt-in nesta fase.
const API = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '' : 'http://localhost:8000');
async function request(path, options={}) {
  const response = await fetch(`${API}${path}`, { ...options, headers: {'Content-Type':'application/json', ...options.headers}, signal: AbortSignal.timeout(12000) });
  let body;
  try { body = await response.json(); } catch { throw new Error(`Resposta inválida da API (${response.status})`); }
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Erro HTTP ${response.status}`);
  return body;
}
export const readSnapshot = () => request('/api/snapshot');
export const importSnapshot = data => request('/api/migration/import', {method:'POST', body:JSON.stringify(data)});
