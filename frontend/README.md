# Agents & Tools UI

React app for managing `chat.Agent` and `chat.ToolDefinition` and the (many-to-many)
connections between them. Served by Django at `/chat/agents-ui/`.

## Build

```
npm install
npm run build
```

This writes `main.js` / `main.css` into `/home/auriga/vendors/static/agents-ui/`,
which Django serves via `STATICFILES_DIRS`. Rebuild after any change under `src/`
— there is no dev server wired up against the Django API (same-origin session
auth + CSRF make that simplest).
