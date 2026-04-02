# MUSCLE Settings API Key

Set or configure the MINIMAX/M2.7 API key for MUSCLE.

## Usage

```
/muscle:settings-api-key [--key <key>] [--source <source>]
```

## Options

- `--key` - API key to set (optional, prompts if not provided)
- `--source` - API key source: `env`, `opencode`, `ask` (optional)

## Examples

```
/muscle:settings-api-key --key sk-xxxxx
/muscle:settings-api-key --source opencode
/muscle:settings-api-key
```

## API Key Sources

- `env` - Use MINIMAX_API_KEY environment variable (default)
- `opencode` - Use OpenCode provider authentication
- `ask` - Prompt for API key when needed
- `manual` - Key set directly via --key flag
