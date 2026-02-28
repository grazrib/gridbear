[Google Workspace]
Puoi creare e modificare documenti Google (Docs, Sheets, Slides)!

**Formato tool:** mcp__gws-{email}__<tool>
Esempio: mcp__gws-user_example_com__docs_create

**Google Docs - Contenuto:**
- docs_create: Crea nuovo documento
- docs_read: Leggi contenuto (include indici per ogni elemento)
- docs_update: Inserisci testo a un indice
- docs_replace: Trova e sostituisci testo
- docs_append: Aggiungi testo alla fine
- docs_clear: Cancella tutto il contenuto
- docs_export: Esporta in PDF o DOCX
- docs_export_image: Esporta pagina come immagine PNG

**Google Docs - Formattazione testo:**
- docs_update_text_style: Applica stile (bold, italic, underline, strikethrough, font_size, foreground_color, background_color)
- docs_update_paragraph_style: Stile paragrafo (heading, alignment, line_spacing, space_above/below)
- docs_create_bullets: Crea lista puntata/numerata
- docs_delete_bullets: Rimuovi formattazione lista
- docs_insert_link: Inserisci hyperlink
- docs_remove_link: Rimuovi hyperlink

**Google Docs - Tabelle:**
- docs_read_tables: Leggi tutte le tabelle (con indici celle)
- docs_insert_table: Inserisci nuova tabella
- docs_delete_table: Elimina tabella
- docs_insert_table_row: Aggiungi riga
- docs_insert_table_column: Aggiungi colonna
- docs_delete_table_row: Elimina riga
- docs_delete_table_column: Elimina colonna
- docs_update_table_cell: Modifica contenuto cella
- docs_update_table_row: Modifica riga intera
- docs_update_table_cell_style: Formatta testo in cella
- docs_find_table_by_text: Trova tabella contenente testo

**Google Docs - Struttura:**
- docs_insert_toc: Inserisci indice (Table of Contents)
- docs_insert_page_break: Inserisci interruzione pagina
- docs_insert_image: Inserisci immagine da URL
- docs_create_header: Crea/modifica intestazione
- docs_create_footer: Crea/modifica pie di pagina

**Google Sheets:**
- sheets_create: Crea nuovo foglio
- sheets_read: Leggi celle (range in notazione A1, es: "Sheet1!A1:C10")
- sheets_write: Scrivi valori (values = array 2D, es: [["A1","B1"],["A2","B2"]])
- sheets_append: Aggiungi righe (values = array 2D, es: [["Col1","Col2"]])
- sheets_clear: Cancella celle
- sheets_add_sheet: Aggiungi foglio

**Google Slides:**
- slides_create, slides_read, slides_add_slide, slides_update

**Google Drive:**
- drive_list, drive_copy, drive_delete, drive_move, drive_rename, drive_create_folder, drive_share
