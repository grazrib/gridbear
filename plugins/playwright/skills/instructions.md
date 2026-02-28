## Browser Automation (Playwright)

Hai accesso a tool Playwright per navigare e interagire con pagine web.

### Tool Disponibili

**Navigazione:**
- `browser_navigate` - Naviga a un URL
- `browser_navigate_back` - Torna alla pagina precedente
- `browser_tabs` - Gestisci tab del browser

**Interazione:**
- `browser_click` - Clicca su un elemento
- `browser_type` - Digita testo in un campo
- `browser_hover` - Passa il mouse su un elemento
- `browser_select_option` - Seleziona opzione in un dropdown
- `browser_press_key` - Premi un tasto
- `browser_drag` - Trascina un elemento

**Cattura:**
- `browser_snapshot` - Cattura lo stato della pagina (accessibilita)
- `browser_take_screenshot` - Cattura screenshot come immagine

**Form:**
- `browser_fill_form` - Compila piu campi di un form
- `browser_file_upload` - Carica file

**Attesa:**
- `browser_wait_for` - Attendi testo, scomparsa testo, o tempo

**Debug:**
- `browser_console_messages` - Leggi messaggi console
- `browser_network_requests` - Vedi richieste di rete
- `browser_evaluate` - Esegui JavaScript

### Workflow Tipico

1. Naviga alla pagina: `browser_navigate`
2. Cattura stato per vedere elementi: `browser_snapshot`
3. Interagisci (click, type, etc.)
4. Screenshot finale: `browser_take_screenshot`

### Esempi

**Cerca su Google:**
1. browser_navigate url="https://google.com"
2. browser_snapshot (per vedere i ref degli elementi)
3. browser_type ref="<ref>" text="query di ricerca" submit=true

**Screenshot di una pagina e invio all'utente:**
1. browser_navigate url="https://example.com"
2. browser_wait_for time=2 (attendi caricamento)
3. browser_take_screenshot -> saves to /app/data/playwright/<filename>.png
4. send_file_to_chat(file_path="/app/data/playwright/<filename>.png", chat_id=..., platform=...)

**Compila un form:**
1. browser_navigate url="https://example.com/form"
2. browser_snapshot
3. browser_fill_form con i campi trovati

### Importante: Invio Screenshot
Gli screenshot vengono salvati nella directory `/app/data/playwright/`.
Quando il tool browser_take_screenshot ritorna un filename (es. `page-123.png`),
il path completo e `/app/data/playwright/page-123.png`.
Per inviare lo screenshot all'utente, usa il tool `send_file_to_chat` con il path completo.
NON usare tag [SEND_FILE:], usa sempre il tool MCP send_file_to_chat.
