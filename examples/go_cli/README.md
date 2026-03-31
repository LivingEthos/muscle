# Go CLI Budget Manager

This example demonstrates building a CLI tool in Go for managing personal budgets with CSV import/export functionality.

## Features

- **CLI Interface**: Clean command-line interface using Cobra
- **Budget Management**: Create, list, update, delete budget entries
- **CSV Import**: Import transactions from CSV files
- **CSV Export**: Export budget data to CSV format
- **Data Storage**: SQLite database for persistence
- **Input Validation**: Comprehensive input validation

## Tech Stack

- Go - Programming language
- Cobra - CLI framework
- SQLite - Database
- Go CSV - CSV handling

## Commands

| Command | Description |
|---------|-------------|
| `budget add` | Add a new budget entry |
| `budget list` | List all budget entries |
| `budget update` | Update an existing entry |
| `budget delete` | Delete a budget entry |
| `budget import` | Import from CSV file |
| `budget export` | Export to CSV file |
| `budget summary` | Show budget summary |

## Usage

After SCLE generates the solution:

```bash
cd go_cli
go build -o budget ./cmd
./budget add --description "Groceries" --amount 150.00 --category "food"
./budget list
./budget import --file transactions.csv
./budget export --file budget.csv
```

Run `./budget --help` for more commands.
