# AI Workmate — frontend

Next.js 16 (App Router) + TypeScript + Tailwind v4 + shadcn/ui (Base UI) + Recharts.
See the [project README](../README.md) for setup. Scripts:

```bash
npm run dev          # http://localhost:3000, proxies /api to API_URL (default http://localhost:8000)
npm run lint && npm run typecheck && npm test
npx playwright test  # e2e; needs API + web running and a seeded DB
```
