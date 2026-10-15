# Logistria frontend rules
- Frontend is React + Vite in /frontend. Never change API/WebSocket contracts or backend code.
- UI is an operator tool (the "War Room"). No landing page, hero, marketing copy or onboarding.
- All colors, spacing, radii and durations come from CSS variables in one tokens file. No hardcoded hex values in components.
- Light theme only. No gradients, shadows, glow, glassmorphism, emoji, or purple/blue AI-gradient styling.
- Labels are 1-3 words, sentence case. No paragraphs or helper text. Details appear on click, never by default.
- Prefer hairline dividers over bordered boxes. Avoid boxes inside boxes.
- Animation uses CSS/SVG only (no new animation library), 150-400ms, and honors prefers-reduced-motion.
- Keep `npm test` and `npm run build` passing.