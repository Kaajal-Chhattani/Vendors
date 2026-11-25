function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'))
  return match ? decodeURIComponent(match[2]) : null
}

function csrfToken() {
  return document.getElementById('agents-ui-root')?.dataset.csrf || getCookie('csrftoken')
}

async function request(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken(),
      ...(options.headers || {}),
    },
    credentials: 'same-origin',
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Request failed (${res.status})`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  listAgents: () => request('/chat/api/agents/'),
  createAgent: (data) => request('/chat/api/agents/', { method: 'POST', body: JSON.stringify(data) }),
  updateAgent: (id, data) => request(`/chat/api/agents/${id}/`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteAgent: (id) => request(`/chat/api/agents/${id}/`, { method: 'DELETE' }),

  listTools: () => request('/chat/api/tools/'),
  createTool: (data) => request('/chat/api/tools/', { method: 'POST', body: JSON.stringify(data) }),
  updateTool: (id, data) => request(`/chat/api/tools/${id}/`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteTool: (id) => request(`/chat/api/tools/${id}/`, { method: 'DELETE' }),
}
