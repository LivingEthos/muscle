# Wiki Content Model

| Field | Value |
|---|---|
| Audience | Docs maintainers and future online-docs builders |
| Status | Repo-local source content |
| Source of truth | This `wiki/` folder plus runtime files linked from each page |

The wiki is organized as content-first documentation with small structured data
catalogs. Markdown pages are the canonical human-readable source. YAML files in
[`data/`](data/) are an index layer for future static-site generation,
search, navigation, command tables, or API imports.

## Directory Contract

```text
wiki/
  README.md
  _sidebar.md
  agent-reference.md
  content-model.md
  getting-started/
  concepts/
  reference/
  operations/
  data/
```

## Page Metadata

Each content page starts with a visible metadata table instead of hidden
frontmatter. This keeps pages readable on GitHub while still giving an online
docs migration a predictable pattern to parse.

Required fields:

- `Audience`
- `Status`
- `Source of truth`

Optional fields:

- `Primary commands`
- `Related pages`
- `Writes state`
- `Requires API key`

## Data Catalogs

| File | Purpose |
|---|---|
| [`data/pages.yml`](data/pages.yml) | Navigation and search index seed |
| [`data/commands.yml`](data/commands.yml) | Slash-command and CLI-command catalog |
| [`data/plugin-files.yml`](data/plugin-files.yml) | Bundle file inventory and validation ownership |

The YAML data should not drift from the markdown. When a slash command is added
or removed, update both [`reference/slash-commands.md`](reference/slash-commands.md)
and [`data/commands.yml`](data/commands.yml).

## Migration Notes For Online Docs

- Use this folder as the docs source root.
- Preserve page slugs; they are intentionally stable and lowercase.
- Convert metadata tables to frontmatter only if the target docs system needs it.
- Treat source links as repo-relative provenance links.
- Keep operational claims tied to validation pages and release notes.

