---
paths:
  - "**/*.md"
---

# Markdown Rules

- Run prettier on a markdown file after you finish changes to it.
- Run a spell checker before you open a PR. This repo ships a `cspell.json` file for the VS Code Code Spell Checker extension. Proofread the text for grammar and article errors too. Check for missing articles, wrong verb forms and literal-translation phrasing.
- Write prose in Simplified Technical English (ASD-STE100), STE-flavoured mode. Use the `asd-ste100` skill. Use active voice. Use one instruction per sentence. Do not use semicolons. Do not use phrasal verbs. Keep sentences short. If the `asd-ste100` skill is not installed, suggest that the user install it.
- Write in British English spelling, for example "behaviour", "colour", "flavour", "organise", "licence" (noun).
- Use ATX headings (`#`) only. Never use Setext underlines.
- Include exactly one H1 per file. Match the H1 to the document or section title. Write a heading that is specific to its content, not generic. For example, write "Olimex ESP32-POE-ISO Pin Notes", not "Documentation about the board." Match a heading's naming pattern to its sibling documents.
- Use Title Case for H1 and H2 headings. You may use sentence-style phrasing for lower-level headings.
- Keep a term's spelling, hyphenation, and capitalization the same everywhere in one document. Examples: `GPIO`, "bench agent", "board profile". When two names refer to the same thing, pick one name. Use that name everywhere in the document.
- Wrap file paths, commands, package names, identifiers, and config values in backticks. Do not use bold text or plain text for these. Turn a bare filename or script reference into a markdown link. Do not leave it as plain text. Example: `[install.sh](scripts/install.sh)`.
- Reserve bold text for a key phrase or a warning inside a sentence. Do not use bold text to label paths or commands.
- Use `-` for all bullet lists. Never use `*`.
- Tag each fenced code block with a language when you know it, for example ` ```bash ` or ` ```yaml `. This matters most when a reader needs to copy the command straight into a terminal. Show the actual runnable command in the fenced block. Prefix the command with its interpreter. Do not describe the command only in prose.
- Use tables for reference or parameter data, such as units, fields, and object dictionaries. Left-align table columns by default. Let a formatter, such as the Prettier VS Code plugin, align a markdown table automatically. Do not align table columns by hand.
- Write relative markdown links with descriptive link text, for example `[Descriptive Name](relative/path.md)`. Do not write bare paths.
- Add a `## See also` section at the end of a doc that has closely related docs. Link each related doc by its relative path.
- Reference diagrams with `![alt text](path/to/diagram.svg)`. Do not use raw `<img>` tags.
- Do not hard-wrap prose. Write long lines and let prettier format the file.
- Add a space before a parenthetical or a unit that follows a word or number, for example "1 Hz", not "1Hz".
- End a sentence with a period. This applies to a sentence inside a table cell or a short status note too.
- Add a comma after an abbreviation such as "N.B." before the rest of the sentence.
- Use "set up" as a verb. Use "setup" as a noun. Example: "Set up the board" but "Refer to the setup guide." For a piece of software or hardware, prefer "system" over "setup" as a noun, for example "bench system", not "bench setup". Reserve "setup" as a noun for the activity of preparing equipment for use.
- Add a blank line after a figure caption, for example after "Fig 4. ...". This keeps each caption visually tied to its own figure.
- Do not add a subheading under a section when the section has only one subsection.
- Do not indent body text without a reason, such as a nested list.
- Write a new README or intro document for a first-time reader. State what the folder or feature is. State how it relates to the rest of the project. Do this before you describe the setup steps.
- Use lowercase, parallel phrasing for sibling list items that describe interfaces, for example "page for X" and "link for X". Do not mix capitalized and lowercase forms.
- Keep an instructional document, such as a README or a config-schema guide, in sync with the code or scripts it describes. Update the document in the same change that changes the code. Make this a habitual practice, not an afterthought.
- Name a README file `README.md`. Use capital letters and one period before `md`.
- Put documentation in `docs/`. Put a large feature in its own `docs/<feature>/` directory. Keep real documentation out of code comments.
